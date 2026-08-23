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

from stapel_core.comm import subscribe_action
from stapel_profiles.actions import (
    handle_erasure_requested,
    handle_owner_probe,
    handle_user_deleted,
)
from stapel_profiles.erasure import GDPR_OWNER, GDPR_SUBJECT_TYPES, erase_account
from stapel_profiles.models import Profile, RelationshipStatus, UserRelationship

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"


def _validate(payload: dict, name: str) -> None:
    jsonschema.validate(
        payload,
        json.loads((SCHEMAS / "emits" / f"{name}.json").read_text()),
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
            "relationships_outgoing": 1,
            "relationships_incoming": 1,
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

        handle_erasure_requested(_request("account", user_id, correlation))

        assert len(receipts) == 1
        payload = receipts[0].payload
        assert payload["correlation_id"] == str(correlation)
        assert payload["owner"] == GDPR_OWNER
        assert payload["subject_type"] == "account"
        assert payload["subject_key"] == str(user_id)
        assert payload["counts"] == {
            "profiles": 1,
            "relationships_outgoing": 1,
            "relationships_incoming": 1,
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

        handle_erasure_requested(event)
        handle_erasure_requested(event)

        assert len(receipts) == 2
        assert receipts[1].payload["counts"] == {
            "profiles": 0,
            "relationships_outgoing": 0,
            "relationships_incoming": 0,
        }

    def test_a_subject_type_we_do_not_claim_gets_no_receipt(self, receipts):
        """A profile is not partitioned by workspace. A receipt from an
        owner that erased nothing is worse than silence — the orchestrator
        counts it and finalizes."""
        handle_erasure_requested(_request("workspace", uuid.uuid4()))

        assert receipts == []

    def test_an_unusable_key_gets_no_receipt(self, receipts, caplog):
        handle_erasure_requested(_request("account", "not-a-uuid"))

        assert receipts == []
        assert "unusable" in caplog.text

    def test_a_malformed_request_gets_no_receipt(self, receipts):
        handle_erasure_requested(
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

        handle_user_deleted(
            types.SimpleNamespace(payload={"user_id": str(user_id)}, event_id="e1")
        )

        assert not Profile.objects.filter(user_id=user_id).exists()

    def test_it_receipts_when_the_event_carries_a_correlation(self, receipts):
        """The silent-owner finding: this handler erased and said nothing,
        so a host still on the account-only protocol timed out."""
        user_id = uuid.uuid4()
        _populate(user_id)
        correlation = uuid.uuid4()

        handle_user_deleted(
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

        handle_user_deleted(
            types.SimpleNamespace(payload={"user_id": str(user_id)}, event_id="e1")
        )

        assert receipts == []


@pytest.mark.django_db
class TestTheProbe:
    def test_it_answers_with_owner_and_subject_types(self, alive):
        handle_owner_probe(
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
        rather than about a consumed erasure path."""
        assert (
            handle_owner_probe.__module__
            == handle_erasure_requested.__module__
            == "stapel_profiles.actions"
        )

    def test_the_owner_name_is_the_providers_section(self):
        from stapel_profiles.gdpr import ProfilesGDPRProvider

        assert ProfilesGDPRProvider.section == GDPR_OWNER
