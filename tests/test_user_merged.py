"""A merge keeps the survivor's profile and archives the guest's.

The gap these tests close (stapel-core 0.52.1, ``stapel_core.lifecycle.E001``):
this module subscribed ``user.deleted`` and nothing else, so a guest whose
account was folded into an existing one left a profile row — and every
follow and block naming it — pointing at an id that can no longer sign in.
Nothing raised and nothing retried; the rows were simply orphaned.

A profile is keyed by the user id, which is also its primary key, so two
profiles cannot become one row and something has to lose. These tests pin
which: the survivor's row is never read, written or created, and the merged
row is archived rather than deleted.
"""
import types
import uuid

import pytest

from stapel_profiles.actions import handle_user_merged
from stapel_profiles.erasure import erase_account
from stapel_profiles.models import (
    Profile,
    RelationshipStatus,
    UserRelationship,
)


def _event(**payload):
    return types.SimpleNamespace(payload=payload, event_id="evt-1")


@pytest.fixture
def guest():
    return uuid.uuid4()


@pytest.fixture
def survivor():
    return uuid.uuid4()


@pytest.mark.django_db
class TestProfileArchival:
    def test_survivor_wins_and_guest_is_archived(self, guest, survivor):
        Profile.objects.create(user_id=guest, display_name="Anonymous Otter")
        Profile.objects.create(user_id=survivor, display_name="Real Name")

        handle_user_merged(
            _event(from_user_id=str(guest), into_user_id=str(survivor))
        )

        archived = Profile.objects.get(user_id=guest)
        kept = Profile.objects.get(user_id=survivor)
        assert archived.merged_into == survivor
        assert archived.display_name == "Anonymous Otter"  # archived, not blanked
        assert kept.merged_into is None
        assert kept.display_name == "Real Name"

    def test_nothing_is_copied_onto_the_survivor(self, guest, survivor):
        """A guest's name must never land on an established account."""
        Profile.objects.create(
            user_id=guest, display_name="Anonymous Otter",
            avatar_source="url", avatar="https://example.com/guest.png",
        )
        Profile.objects.create(user_id=survivor)

        handle_user_merged(
            _event(from_user_id=str(guest), into_user_id=str(survivor))
        )

        kept = Profile.objects.get(user_id=survivor)
        assert kept.display_name == ""
        assert not kept.avatar

    def test_survivor_without_a_row_does_not_get_one(self, guest, survivor):
        """A merge is not a registration — `user.registered` provisions rows."""
        Profile.objects.create(user_id=guest, display_name="Anonymous Otter")

        handle_user_merged(
            _event(from_user_id=str(guest), into_user_id=str(survivor))
        )

        assert not Profile.objects.filter(user_id=survivor).exists()
        assert Profile.objects.get(user_id=guest).merged_into == survivor


@pytest.mark.django_db
class TestRelationshipsMove:
    def test_follows_and_blocks_move_to_the_survivor(self, guest, survivor):
        followed = uuid.uuid4()
        blocked = uuid.uuid4()
        fan = uuid.uuid4()
        UserRelationship.objects.create(
            follower_id=guest, following_id=followed,
            status=RelationshipStatus.FOLLOWING,
        )
        UserRelationship.objects.create(
            follower_id=guest, following_id=blocked,
            status=RelationshipStatus.BLOCKED,
        )
        UserRelationship.objects.create(
            follower_id=fan, following_id=guest,
            status=RelationshipStatus.FOLLOWING,
        )

        handle_user_merged(
            _event(from_user_id=str(guest), into_user_id=str(survivor))
        )

        assert not UserRelationship.objects.filter(follower_id=guest).exists()
        assert not UserRelationship.objects.filter(following_id=guest).exists()
        assert UserRelationship.objects.get(
            follower_id=survivor, following_id=blocked
        ).status == RelationshipStatus.BLOCKED
        assert UserRelationship.objects.filter(
            follower_id=survivor, following_id=followed
        ).exists()
        assert UserRelationship.objects.filter(
            follower_id=fan, following_id=survivor
        ).exists()

    def test_duplicate_and_self_edges_are_dropped_not_raised(self, guest, survivor):
        """The survivor's own row wins; a self-edge is not a storable state."""
        shared = uuid.uuid4()
        UserRelationship.objects.create(
            follower_id=guest, following_id=shared,
            status=RelationshipStatus.FOLLOWING,
        )
        UserRelationship.objects.create(
            follower_id=survivor, following_id=shared,
            status=RelationshipStatus.BLOCKED,
        )
        # The guest followed the account they are about to become.
        UserRelationship.objects.create(
            follower_id=guest, following_id=survivor,
            status=RelationshipStatus.FOLLOWING,
        )

        handle_user_merged(
            _event(from_user_id=str(guest), into_user_id=str(survivor))
        )

        assert UserRelationship.objects.filter(
            follower_id=survivor, following_id=shared
        ).count() == 1
        assert UserRelationship.objects.get(
            follower_id=survivor, following_id=shared
        ).status == RelationshipStatus.BLOCKED
        assert not UserRelationship.objects.filter(
            follower_id=survivor, following_id=survivor
        ).exists()
        assert UserRelationship.objects.count() == 1


@pytest.mark.django_db
class TestIdempotenceAndBadInput:
    def test_redelivery_changes_nothing(self, guest, survivor):
        Profile.objects.create(user_id=guest, display_name="Anonymous Otter")
        Profile.objects.create(user_id=survivor, display_name="Real Name")
        followed = uuid.uuid4()
        UserRelationship.objects.create(
            follower_id=guest, following_id=followed,
            status=RelationshipStatus.FOLLOWING,
        )
        event = _event(from_user_id=str(guest), into_user_id=str(survivor))

        handle_user_merged(event)
        handle_user_merged(event)

        assert Profile.objects.get(user_id=guest).merged_into == survivor
        assert Profile.objects.get(user_id=survivor).display_name == "Real Name"
        assert UserRelationship.objects.count() == 1
        assert UserRelationship.objects.filter(
            follower_id=survivor, following_id=followed
        ).exists()

    def test_unknown_users_do_nothing(self, guest, survivor):
        stranger = Profile.objects.create(user_id=uuid.uuid4(), display_name="Nobody")

        handle_user_merged(
            _event(from_user_id=str(guest), into_user_id=str(survivor))
        )

        stranger.refresh_from_db()
        assert stranger.merged_into is None
        assert Profile.objects.count() == 1

    @pytest.mark.parametrize(
        "payload",
        [
            {"from_user_id": "not-a-uuid", "into_user_id": "also-not-a-uuid"},
            {"from_user_id": "not-a-uuid", "into_user_id": str(uuid.uuid4())},
            {"from_user_id": str(uuid.uuid4())},
            {"into_user_id": str(uuid.uuid4())},
            {},
            {"from_user_id": "", "into_user_id": str(uuid.uuid4())},
        ],
    )
    def test_malformed_payload_does_not_raise(self, payload):
        """A raise here means the bus redelivers a poison message forever."""
        row = Profile.objects.create(user_id=uuid.uuid4(), display_name="Untouched")

        handle_user_merged(_event(**payload))

        row.refresh_from_db()
        assert row.merged_into is None

    def test_one_account_named_twice_is_dropped(self, guest):
        Profile.objects.create(user_id=guest)

        handle_user_merged(
            _event(from_user_id=str(guest), into_user_id=str(guest))
        )

        assert Profile.objects.get(user_id=guest).merged_into is None


@pytest.mark.django_db
def test_erasing_the_survivor_takes_the_archived_row_with_it(guest, survivor):
    """An archived row names the survivor — erasing them must take it too."""
    Profile.objects.create(user_id=guest, display_name="Anonymous Otter")
    Profile.objects.create(user_id=survivor, display_name="Real Name")
    handle_user_merged(_event(from_user_id=str(guest), into_user_id=str(survivor)))

    counts = erase_account(survivor)

    assert counts["profiles"] == 1
    assert counts["profiles_merged_in"] == 1
    assert Profile.objects.count() == 0


def test_lifecycle_pair_check_is_green():
    """The regression gate: this app answers both halves of the life cycle.

    ``stapel_core.lifecycle.E001`` reports an app that handles
    ``user.deleted`` and registers no ``user.merged`` handler. It is what
    would have caught the silence in the first place, so it stays wired to
    the suite rather than to a one-time audit.
    """
    from stapel_core.comm.lifecycle_checks import check_lifecycle_pairs
    from stapel_core.comm.registry import action_registry

    # Asserted first, because the check reads the registry: a process with
    # no subscribers at all would report [] too, and a green gate that is
    # blind to the thing it gates proves nothing.
    subscribed = {
        getattr(h, "__module__", "") for h in action_registry.handlers("user.merged")
    }
    assert "stapel_profiles.actions" in subscribed
    assert check_lifecycle_pairs() == []
