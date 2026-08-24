"""The block check — the answer, and the silence around it.

``profiles.relationships`` is the first thing in the fleet that lets a
*server* enforce a block. Two properties are load-bearing and neither is
obvious from the happy path:

* **symmetry** — a block stops both arrows. The stored row has a direction
  (who blocked whom); the answer does not, and the tests below pin that the
  answer is IDENTICAL whichever way round the block was placed and whichever
  way round the pair is asked;
* **non-disclosure** — the blocked party must never learn they are blocked.
  Not from a field, not from an error, not from a behavioural difference.
  The tests pin all three: the answer's shape carries no blocker, the public
  read a blocked person gets is byte-identical to the one they got before,
  and their own GDPR export says nothing about the block placed on them.

Plus the rule that makes this safe to depend on: an uncheckable block
RAISES. A caller turns that into a 503 (stapel-classified's
``BLOCK_ENFORCEMENT``); a short or optimistic answer would turn it into
contact.
"""

import json
import types
import uuid

import pytest
from django.test import override_settings

from stapel_core.comm import call, function_registry, subscribe_action
from stapel_profiles import functions, relationships
from stapel_profiles.erasure import erase_account
from stapel_profiles.models import Profile, RelationshipStatus, UserRelationship


@pytest.fixture(autouse=True)
def clean_function_registry():
    function_registry.clear()
    yield
    function_registry.clear()


@pytest.fixture
def registered():
    """The providers, registered exactly as ``apps.ready()`` registers them."""
    functions.register()


def _ask(pairs):
    return call(functions.RELATIONSHIPS, {"pairs": [[str(a), str(b)] for a, b in pairs]})


def _block(blocker, blocked):
    UserRelationship.objects.create(
        follower_id=blocker, following_id=blocked,
        status=RelationshipStatus.BLOCKED,
    )


@pytest.mark.django_db
class TestTheAnswer:
    def test_strangers_are_not_blocked(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        assert _ask([(a, b)]) == {"blocked": []}

    def test_a_block_answers_for_the_pair(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        _block(a, b)
        assert _ask([(a, b)]) == {"blocked": [[str(a), str(b)]]}

    def test_the_pair_is_echoed_in_the_orientation_it_was_asked(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        _block(a, b)
        # Asked the other way round: the caller gets its own orientation back
        # so it can match the answer onto its page without knowing anything
        # about how the block is stored.
        assert _ask([(b, a)]) == {"blocked": [[str(b), str(a)]]}

    def test_a_follow_is_not_a_block(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        UserRelationship.objects.create(
            follower_id=a, following_id=b, status=RelationshipStatus.FOLLOWING,
        )
        assert _ask([(a, b)]) == {"blocked": []}

    def test_a_page_answers_only_the_blocked_pairs_in_ask_order(self, registered):
        a, b, c, d = (uuid.uuid4() for _ in range(4))
        _block(a, b)
        _block(d, c)
        answer = _ask([(a, c), (a, b), (c, d)])
        assert answer == {"blocked": [[str(a), str(b)], [str(c), str(d)]]}

    def test_self_pairs_are_dropped_and_duplicates_collapse(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        _block(a, b)
        answer = _ask([(a, a), (a, b), (b, a)])
        # Nobody can block themselves; a pair asked twice, in either
        # orientation, is one question.
        assert answer == {"blocked": [[str(a), str(b)]]}

    def test_a_page_costs_one_query(self, registered, django_assert_num_queries):
        people = [uuid.uuid4() for _ in range(20)]
        pairs = list(zip(people[::2], people[1::2]))
        _block(*pairs[0])
        with django_assert_num_queries(1):
            _ask(pairs)


@pytest.mark.django_db
class TestSymmetry:
    def test_the_block_stops_both_arrows(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        _block(a, b)
        # B never blocked anybody, and still must not reach A.
        assert relationships.is_blocked(b, a) is True

    def test_the_answer_does_not_say_who_blocked_whom(self, registered):
        """The core non-disclosure pin: two worlds, opposite blockers, one answer.

        If anything in the answer varied with the direction of the stored
        row, a consumer could tell the blocked party who blocked them — from
        a field, or just from noticing the difference. Comparing the whole
        serialized answer is the test that cannot be satisfied by a
        carefully-worded field.
        """
        a, b = uuid.uuid4(), uuid.uuid4()
        _block(a, b)
        forward = json.dumps(_ask([(a, b)]), sort_keys=True)

        UserRelationship.objects.all().delete()
        _block(b, a)
        backward = json.dumps(_ask([(a, b)]), sort_keys=True)

        assert forward == backward

    def test_both_directions_blocked_answers_once(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        _block(a, b)
        _block(b, a)
        assert _ask([(a, b)]) == {"blocked": [[str(a), str(b)]]}

    def test_the_answer_carries_nothing_but_pairs(self, registered):
        a, b = uuid.uuid4(), uuid.uuid4()
        _block(a, b)
        answer = _ask([(a, b)])
        # No blocker, no timestamp, no reason, no status — there is no field
        # here that COULD disclose, which is what makes the property
        # structural rather than a rule every caller must remember.
        assert set(answer) == {"blocked"}
        assert all(len(pair) == 2 for pair in answer["blocked"])


@pytest.mark.django_db
class TestFailsClosed:
    def test_more_pairs_than_the_ceiling_is_refused(self, registered):
        pairs = [(uuid.uuid4(), uuid.uuid4()) for _ in range(6)]
        with override_settings(STAPEL_PROFILES={"PROFILES_PAIRS_MAX": 5}):
            with pytest.raises(Exception):  # noqa: B017 — comm wraps the raise
                _ask(pairs)

    def test_an_id_that_names_nobody_is_refused_not_allowed(self, registered):
        with pytest.raises(Exception):  # noqa: B017 — comm wraps the raise
            call(functions.RELATIONSHIPS, {"pairs": [["not-a-uuid", str(uuid.uuid4())]]})

    def test_the_service_raises_its_own_types(self, db):
        with pytest.raises(relationships.MalformedUserId):
            relationships.blocked_pairs([("", str(uuid.uuid4()))])
        with override_settings(STAPEL_PROFILES={"PROFILES_PAIRS_MAX": 1}):
            with pytest.raises(relationships.TooManyPairs):
                relationships.blocked_pairs(
                    [(uuid.uuid4(), uuid.uuid4()), (uuid.uuid4(), uuid.uuid4())]
                )


@pytest.mark.django_db
class TestTheWriteSide:
    def test_block_is_idempotent_and_writes_one_row(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        assert relationships.block(a, b) == RelationshipStatus.BLOCKED
        relationships.block(a, b)
        assert UserRelationship.objects.count() == 1

    def test_blocking_deletes_nothing_of_the_other_party(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        Profile.objects.create(user_id=b)
        UserRelationship.objects.create(
            follower_id=b, following_id=a, status=RelationshipStatus.FOLLOWING,
        )

        relationships.block(a, b)

        # A block is not a deletion: the other person's row, their profile
        # and every thread the two ever had (owned by other modules) survive.
        assert UserRelationship.objects.filter(
            follower_id=b, following_id=a, status=RelationshipStatus.FOLLOWING,
        ).exists()
        assert Profile.objects.filter(user_id=b).exists()

    def test_unblock_removes_only_my_own_edge(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        relationships.block(a, b)
        relationships.block(b, a)

        relationships.unblock(a, b)

        # B's block is B's decision and stands — so the pair is still
        # blocked, which is exactly why the read is symmetric.
        assert not UserRelationship.objects.filter(
            follower_id=a, following_id=b
        ).exists()
        assert relationships.is_blocked(a, b) is True

    def test_unblock_leaves_an_unrelated_pair_alone(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        relationships.block(a, b)
        relationships.block(a, c)

        relationships.unblock(a, b)

        assert relationships.blocks_of(a) == [c]

    def test_blocks_of_lists_only_my_own(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        relationships.block(a, b)
        relationships.block(c, a)
        # "Who blocked me" has no accessor: it is the one question this
        # module must never answer to the person asking about themselves.
        assert relationships.blocks_of(a) == [b]

    def test_nobody_can_block_themselves(self):
        a = uuid.uuid4()
        with pytest.raises(ValueError):
            relationships.block(a, a)


@pytest.mark.django_db
class TestNonDisclosureOnTheHttpSurface:
    """A blocked person's own view of the world must not change."""

    def test_the_public_profile_reads_identically_before_and_after(
        self, api_client, user, other_user
    ):
        Profile.objects.create(user_id=user.id)
        Profile.objects.create(user_id=other_user.id)
        api_client.force_authenticate(user=other_user)

        before = api_client.get(f"/{user.id}").json()
        relationships.block(user.id, other_user.id)
        after = api_client.get(f"/{user.id}").json()

        # Byte-identical: not a status, not a count, not a 403, not a 404.
        assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)

    def test_the_relationship_endpoint_says_neutral_to_the_blocked_party(
        self, api_client, user, other_user
    ):
        Profile.objects.create(user_id=user.id)
        Profile.objects.create(user_id=other_user.id)
        relationships.block(user.id, other_user.id)

        api_client.force_authenticate(user=other_user)
        answer = api_client.get(f"/{user.id}/relationship").json()

        # The endpoint reports the CALLER's own edge. The blocked party has
        # none, and "neutral" is the truth about their own row.
        assert answer["status"] == "neutral"

    def test_my_blocked_list_is_the_blockers_own(self, api_client, user, other_user):
        Profile.objects.create(user_id=user.id)
        Profile.objects.create(user_id=other_user.id)
        relationships.block(user.id, other_user.id)

        api_client.force_authenticate(user=other_user)
        assert api_client.get("/me/blocked").json() == []

        api_client.force_authenticate(user=user)
        listed = api_client.get("/me/blocked").json()
        assert [row["user_id"] for row in listed] == [str(other_user.id)]

    def test_the_gdpr_export_does_not_disclose_an_incoming_block(self):
        from stapel_profiles.gdpr import ProfilesGDPRProvider

        blocker, blocked = uuid.uuid4(), uuid.uuid4()
        Profile.objects.create(user_id=blocked)
        relationships.block(blocker, blocked)

        export = ProfilesGDPRProvider().export(blocked)

        # The subject's export carries THEIR decisions. A protective measure
        # somebody else took is erased with them (below) but never disclosed
        # to them: an export that listed it would be the disclosure this
        # whole design exists to prevent, and it would identify the person
        # who took it.
        assert export["blocked"] == []
        assert json.dumps(export, default=str).find(str(blocker)) == -1


@pytest.mark.django_db
class TestErasure:
    """A block names two people, and either of them may erase it."""

    def test_the_blocker_erasing_removes_the_block(self):
        blocker, blocked = uuid.uuid4(), uuid.uuid4()
        Profile.objects.create(user_id=blocker)
        relationships.block(blocker, blocked)

        counts = erase_account(blocker)

        assert counts["relationships_outgoing"] == 1
        assert UserRelationship.objects.count() == 0

    def test_the_blocked_party_erasing_removes_the_block(self):
        blocker, blocked = uuid.uuid4(), uuid.uuid4()
        Profile.objects.create(user_id=blocked)
        relationships.block(blocker, blocked)

        counts = erase_account(blocked)

        # Somebody else's row ABOUT this person is just as much their data —
        # a block list that still names an erased account is not erased.
        assert counts["relationships_incoming"] == 1
        assert UserRelationship.objects.count() == 0

    def test_the_receipt_and_the_probe_answer_for_the_block_store(self):
        from stapel_profiles.actions import handle_erasure_requested, handle_owner_probe

        receipts, alive = [], []
        subscribe_action("gdpr.section.erased", receipts.append)
        subscribe_action("gdpr.owner.alive", alive.append)

        blocker, blocked = uuid.uuid4(), uuid.uuid4()
        Profile.objects.create(user_id=blocker)
        relationships.block(blocker, blocked)

        correlation_id = str(uuid.uuid4())
        handle_erasure_requested(types.SimpleNamespace(
            payload={
                "correlation_id": correlation_id,
                "subject_type": "account",
                "subject_key": str(blocker),
            },
            event_id="evt-1",
            service="gdpr",
        ))
        handle_owner_probe(types.SimpleNamespace(
            payload={"correlation_id": correlation_id}, event_id="evt-2",
            service="gdpr",
        ))

        assert receipts and receipts[0].payload["counts"]["relationships_outgoing"] == 1
        assert alive and alive[0].payload["owner"] == "profile"
