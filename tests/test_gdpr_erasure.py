"""The erasure receipt, and the probe that proves the path is consumed.

This module has always erased on ``user.deleted`` and always said nothing
about it — the "silent owner" finding. stapel-gdpr's orchestrator does not
self-certify: an ``ErasurePart`` with no receipt keeps the request in
``erasing`` until it times out thirty days later, which is
indistinguishable from an owner whose consumer was never deployed. The pins
here are, in order:

* every erasure answers ``gdpr.section.erased`` with **counts** — "it ran"
  and "it removed a profile and two relationships" are different claims,
  and only the second can be audited;
* a redelivery erases nothing and still receipts (at-least-once delivery
  means the second copy must not leave the request unconfirmed);
* the probe is answered **from this same module**, which is the only reason
  ``gdpr.owner.alive`` is evidence about the erasure path rather than about
  a running container;
* the claimed subject types are exactly the ones the eraser handles.
"""

import json
import types
import uuid
from pathlib import Path

import jsonschema
import pytest

from django.core.checks import run_checks

from stapel_core.comm import action_registry, subscribe_action
from stapel_core.comm.actions import deliver_to_subscribers
from stapel_core.gdpr import register_gdpr_owner, registered_gdpr_owners
from stapel_profiles.erasure import (
    GDPR_OWNER,
    GDPR_SUBJECT_TYPES,
    erase_account,
    erase_subject,
)
from stapel_profiles.models import Profile, RelationshipStatus, UserRelationship

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"

#: `gdpr.section.erased` and `gdpr.owner.alive` are core's facts, and since
#: core 0.81.0 core ships their schemas. This module used to vendor copies that
#: pinned `owner` to `{"const": "profile"}`, which made a local test pass while
#: the deployed contract refused every other owner's receipt. Validating
#: against the OWNER's schema is the point: it is the one a service loads.
import stapel_core  # noqa: E402

CORE_SCHEMAS = Path(stapel_core.__file__).resolve().parent / "gdpr" / "schemas"

#: The registration `apps.ready()` made. Same terms means the helper hands the
#: existing registration back rather than subscribing a second time, so this is
#: both how the tests reach the protocol handlers and an assertion that
#: `ready()` performed the registration with exactly these terms.
PROFILE_OWNER = register_gdpr_owner(GDPR_OWNER, GDPR_SUBJECT_TYPES, erase_subject)


def _schema_path(name: str) -> Path:
    local = SCHEMAS / "emits" / f"{name}.json"
    return local if local.exists() else CORE_SCHEMAS / "emits" / f"{name}.json"


def _validate(payload: dict, name: str) -> None:
    jsonschema.validate(
        payload,
        json.loads(_schema_path(name).read_text()),
        format_checker=jsonschema.FormatChecker(),
    )


def _request(subject_type, subject_key, correlation_id=None):
    return types.SimpleNamespace(
        payload={
            "correlation_id": str(correlation_id or uuid.uuid4()),
            "subject_type": subject_type,
            "subject_key": str(subject_key),
        },
        event_id="evt-1",
        service="gdpr",
    )


@pytest.fixture
def receipts():
    events = []
    subscribe_action("gdpr.section.erased", events.append)
    return events


@pytest.fixture
def alive():
    events = []
    subscribe_action("gdpr.owner.alive", events.append)
    return events


def _populate(user_id):
    """One of everything this module holds about a person."""
    other = uuid.uuid4()
    Profile.objects.create(user_id=user_id)
    UserRelationship.objects.create(
        follower_id=user_id, following_id=other,
        status=RelationshipStatus.FOLLOWING,
    )
    UserRelationship.objects.create(
        follower_id=other, following_id=user_id,
        status=RelationshipStatus.BLOCKED,
    )
    return other


@pytest.mark.django_db
class TestErasure:
    def test_it_removes_the_profile_and_both_relationship_directions(self):
        user_id = uuid.uuid4()
        _populate(user_id)

        counts = erase_account(user_id)

        assert not Profile.objects.filter(user_id=user_id).exists()
        assert UserRelationship.objects.count() == 0
        assert counts == {
            "profiles": 1,
            "profiles_merged_in": 0,
            "relationships_outgoing": 1,
            "relationships_incoming": 1,
            "contacts": 0,
            "contact_reveals": 0,
        }

    def test_somebody_elses_rows_are_untouched(self):
        doomed = uuid.uuid4()
        kept = uuid.uuid4()
        _populate(doomed)
        Profile.objects.create(user_id=kept)

        erase_account(doomed)

        assert Profile.objects.filter(user_id=kept).exists()


@pytest.mark.django_db
class TestTheReceipt:
    def test_it_receipts_with_counts(self, receipts):
        user_id = uuid.uuid4()
        _populate(user_id)
        correlation = uuid.uuid4()

        PROFILE_OWNER.handle_erasure_requested(_request("account", user_id, correlation))

        assert len(receipts) == 1
        payload = receipts[0].payload
        assert payload["correlation_id"] == str(correlation)
        assert payload["owner"] == GDPR_OWNER
        assert payload["subject_type"] == "account"
        assert payload["subject_key"] == str(user_id)
        assert payload["counts"] == {
            "profiles": 1,
            "profiles_merged_in": 0,
            "relationships_outgoing": 1,
            "relationships_incoming": 1,
            "contacts": 0,
            "contact_reveals": 0,
        }
        _validate(payload, "gdpr.section.erased")
        assert not Profile.objects.filter(user_id=user_id).exists()

    def test_a_redelivery_erases_nothing_and_still_receipts(self, receipts):
        """At-least-once delivery: the second copy must not leave the
        orchestrator's part unconfirmed, and must not claim a second
        erasure either."""
        user_id = uuid.uuid4()
        _populate(user_id)
        event = _request("account", user_id)

        PROFILE_OWNER.handle_erasure_requested(event)
        PROFILE_OWNER.handle_erasure_requested(event)

        assert len(receipts) == 2
        assert receipts[1].payload["counts"] == {
            "profiles": 0,
            "profiles_merged_in": 0,
            "relationships_outgoing": 0,
            "relationships_incoming": 0,
            "contacts": 0,
            "contact_reveals": 0,
        }

    def test_a_subject_type_we_do_not_claim_gets_no_receipt(self, receipts):
        """A profile is not partitioned by workspace. A receipt from an
        owner that erased nothing is worse than silence — the orchestrator
        counts it and finalizes."""
        PROFILE_OWNER.handle_erasure_requested(_request("workspace", uuid.uuid4()))

        assert receipts == []

    def test_an_unusable_key_gets_no_receipt(self, receipts, caplog):
        PROFILE_OWNER.handle_erasure_requested(_request("account", "not-a-uuid"))

        assert receipts == []
        assert "unusable" in caplog.text

    def test_a_malformed_request_gets_no_receipt(self, receipts):
        PROFILE_OWNER.handle_erasure_requested(
            types.SimpleNamespace(
                payload={"subject_type": "account"}, event_id="e9", service="gdpr"
            )
        )

        assert receipts == []


@pytest.mark.django_db
class TestDeprecatedUserDeletedPath:
    """``user.deleted`` fires alongside the new event until gdpr 0.6.0."""

    def test_it_erases_through_the_same_code(self):
        user_id = uuid.uuid4()
        _populate(user_id)

        PROFILE_OWNER.handle_user_deleted(
            types.SimpleNamespace(payload={"user_id": str(user_id)}, event_id="e1")
        )

        assert not Profile.objects.filter(user_id=user_id).exists()

    def test_it_receipts_when_the_event_carries_a_correlation(self, receipts):
        """The silent-owner finding: this handler erased and said nothing,
        so a host still on the account-only protocol timed out."""
        user_id = uuid.uuid4()
        _populate(user_id)
        correlation = uuid.uuid4()

        PROFILE_OWNER.handle_user_deleted(
            types.SimpleNamespace(
                payload={
                    "user_id": str(user_id),
                    "correlation_id": str(correlation),
                },
                event_id="e1",
            )
        )

        assert len(receipts) == 1
        assert receipts[0].payload["correlation_id"] == str(correlation)
        assert receipts[0].payload["subject_type"] == "account"
        assert receipts[0].payload["counts"]["profiles"] == 1
        _validate(receipts[0].payload, "gdpr.section.erased")

    def test_without_a_correlation_it_erases_and_stays_quiet(self, receipts):
        user_id = uuid.uuid4()
        _populate(user_id)

        PROFILE_OWNER.handle_user_deleted(
            types.SimpleNamespace(payload={"user_id": str(user_id)}, event_id="e1")
        )

        assert receipts == []


@pytest.mark.django_db
class TestTheProbe:
    def test_it_answers_with_owner_and_subject_types(self, alive):
        PROFILE_OWNER.handle_owner_probe(
            types.SimpleNamespace(
                payload={"correlation_id": str(uuid.uuid4())},
                event_id="p1",
                service="gdpr",
            )
        )

        assert len(alive) == 1
        payload = alive[0].payload
        assert payload["owner"] == GDPR_OWNER
        assert payload["subject_types"] == list(GDPR_SUBJECT_TYPES)
        _validate(payload, "gdpr.owner.alive")

    def test_the_claimed_types_are_the_ones_the_eraser_handles(self):
        from stapel_profiles.erasure import ERASERS

        assert set(GDPR_SUBJECT_TYPES) == set(ERASERS)

    def test_it_is_answered_from_the_erasure_subscriber(self):
        """Co-location IS the contract: answering the probe from anywhere
        else would make ``alive`` a statement about a deployed container
        rather than about a consumed erasure path. One registration builds
        both handlers over one ``erase``, which is what keeps them together."""
        assert PROFILE_OWNER.handle_owner_probe.stapel_gdpr_owner == GDPR_OWNER
        assert PROFILE_OWNER.handle_erasure_requested.stapel_gdpr_owner == GDPR_OWNER
        assert PROFILE_OWNER.erase is erase_subject

    def test_the_owner_name_is_the_providers_section(self):
        from stapel_profiles.gdpr import ProfilesGDPRProvider

        assert ProfilesGDPRProvider.section == GDPR_OWNER


@pytest.mark.django_db
class TestTheRegistration:
    """What ``apps.ready()`` put on the bus, and what one fan-out produces."""

    def test_the_owner_claims_the_account_and_nothing_else(self):
        assert registered_gdpr_owners()[GDPR_OWNER] == tuple(GDPR_SUBJECT_TYPES)

    def test_the_three_protocol_actions_are_subscribed(self):
        assert action_registry.handlers("gdpr.erasure.requested")
        assert action_registry.handlers("gdpr.owner.probe")
        # The deprecated account signal, until stapel-gdpr 0.6.0 drops it.
        assert action_registry.handlers("user.deleted")

    def test_boot_reports_no_second_answerer_and_no_stranded_section(self):
        """``manage.py check`` on this module's settings.

        ``gdpr.W012`` is core's bridge naming a library that answers the
        protocol by hand beside it; ``gdpr.E011`` is a registered provider
        nothing in the process answers for. This module must raise neither:
        one registration, one answerer, one receipt per part.
        """
        ids = {message.id for message in run_checks()}

        assert "stapel_core.gdpr.W012" not in ids
        assert "stapel_core.gdpr.E011" not in ids

    def test_one_fan_out_writes_exactly_one_receipt(self, receipts):
        """Every subscriber of the action, delivered as the bus delivers it.

        Core's provider bridge is subscribed too and would answer for a
        section nothing else claims — one part, two receipts, two deletions
        asserted where one happened.
        """
        user_id = uuid.uuid4()
        _populate(user_id)
        handlers = action_registry.handlers("gdpr.erasure.requested")

        failures = deliver_to_subscribers(_request("account", user_id), handlers)

        assert failures == []
        assert len(receipts) == 1
        assert receipts[0].payload["owner"] == GDPR_OWNER
        assert receipts[0].payload["counts"]["profiles"] == 1

    def test_a_second_fan_out_removes_nothing_and_still_receipts(self, receipts):
        user_id = uuid.uuid4()
        _populate(user_id)
        handlers = action_registry.handlers("gdpr.erasure.requested")
        event = _request("account", user_id)

        deliver_to_subscribers(event, handlers)
        deliver_to_subscribers(event, handlers)

        assert len(receipts) == 2
        assert receipts[1].payload["counts"]["profiles"] == 0
        assert receipts[1].payload["receipt_id"] == receipts[0].payload["receipt_id"]


class TestTheReceiptContractIsNotThisModulesSubset:
    """This module vendored a copy of `gdpr.section.erased` until 0.21.1.

    `stapel_core.comm` registers ONE schema per action name for the whole
    process, so whichever copy a service loaded became the contract for every
    emitter in it. This module's copy pinned `owner` to `{"const": "profile"}`
    and required four fields core leaves optional — so in any service that
    loaded it, a receipt from a different owner was rejected. The receipt is
    emitted inside the erasure's own transaction, so the rejection rolled the
    erasure back while the orchestrator counted a success.

    Core owns the fact and ships the schema. These assert the contract stays
    the action's, not this emitter's subset.
    """

    def test_another_owners_receipt_validates(self):
        """The one the vendored copy refused."""
        _validate(
            {
                "correlation_id": "c1",
                "owner": "identity_mirror:svc-profiles",
                "subject_type": "account",
                "subject_key": "u1",
                "receipt_id": "identity_mirror:account:u1:c1",
                "counts": {"identity_mirror": 1},
            },
            "gdpr.section.erased",
        )

    def test_the_legacy_account_only_form_validates(self):
        """Owners still on {user_id, service} must not be refused either."""
        _validate(
            {"correlation_id": "c1", "user_id": "u1", "service": "profiles"},
            "gdpr.section.erased",
        )

    def test_this_module_ships_no_copy_of_cores_facts(self):
        for action in ("gdpr.section.erased", "gdpr.owner.alive"):
            assert not (SCHEMAS / "emits" / f"{action}.json").exists(), (
                f"{action} is emitted by stapel_core, which ships its schema. "
                f"A copy here becomes the contract for every emitter in any "
                f"service that loads it."
            )
