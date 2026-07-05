"""
Tests for the profile.changed comm event and the profile_updated signal.
"""
import json
import uuid
from pathlib import Path

import jsonschema
import pytest
from django.db import transaction
from django.test import override_settings
from stapel_core.comm import action_registry, subscribe_action
from stapel_core.signals import profile_updated

import stapel_profiles
from stapel_profiles.events import publish_profile_changed
from stapel_profiles.models import Profile
from stapel_profiles.serializers import ProfileCreateUpdateSerializer

SCHEMA_PATH = (
    Path(stapel_profiles.__file__).parent / "schemas" / "emits" / "profile.changed.json"
)


@pytest.fixture
def captured_events():
    """Subscribe to profile.changed in-process; unsubscribe afterwards."""
    events = []

    def handler(event):
        events.append(event)

    subscribe_action("profile.changed", handler)
    yield events
    action_registry._subscribers.get("profile.changed", []).remove(handler)


def _update_profile(**data):
    profile = Profile.objects.create(user_id=uuid.uuid4())
    serializer = ProfileCreateUpdateSerializer(
        instance=profile, data=data, partial=True
    )
    assert serializer.is_valid(), serializer.errors
    serializer.save()
    return profile


@pytest.mark.django_db
class TestProfileChangedEvent:
    def test_emitted_on_update(self, captured_events):
        profile = _update_profile(display_name="New Name")

        assert len(captured_events) == 1
        event = captured_events[0]
        assert event.event_type == "profile.changed"
        assert event.payload["user_id"] == str(profile.user_id)
        assert event.payload["display_name"] == "New Name"

    def test_payload_matches_schema(self, captured_events):
        _update_profile(display_name="Schema Guy", theme="dark")

        schema = json.loads(SCHEMA_PATH.read_text())
        # additionalProperties is false and all fields are required —
        # this asserts the payload shape exactly.
        jsonschema.validate(captured_events[0].payload, schema)

    def test_schema_rejects_foreign_payload(self):
        """Guard: the schema is exact-match, not permissive."""
        schema = json.loads(SCHEMA_PATH.read_text())
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"user_id": 42}, schema)


def _explode(event):
    raise RuntimeError("outbox write failed")


@pytest.mark.django_db(transaction=True)
class TestProfileChangedBestEffort:
    """publish_profile_changed is a best-effort fan-out: an emit failure must
    never fail the surrounding profile mutation, in EITHER request mode. The
    outbox path (OUTBOX_ENABLED=True) is the one that marks a transaction
    rollback-only on emit failure, so these tests force that path."""

    def test_emit_failure_does_not_poison_atomic_request(self, monkeypatch):
        # ATOMIC_REQUESTS=True regression: on the pre-fix code the failing emit
        # marks the request transaction rollback-only, so the assert below
        # (any DB query after it) raises TransactionManagementError and the
        # created profile is rolled back with a 500. The nested atomic isolates
        # the failure to a savepoint, keeping the request transaction healthy.
        from stapel_core.comm import actions

        monkeypatch.setattr(actions, "_emit_via_outbox", _explode)

        with override_settings(STAPEL_COMM={"OUTBOX_ENABLED": True}):
            with transaction.atomic():  # simulate ATOMIC_REQUESTS wrapping
                profile = Profile.objects.create(user_id=uuid.uuid4())
                publish_profile_changed(profile)  # emit fails, swallowed
                # Would raise TransactionManagementError if the outer tx were
                # poisoned by the swallowed emit failure:
                assert Profile.objects.filter(pk=profile.pk).exists()

        assert Profile.objects.filter(pk=profile.pk).exists()

    def test_emit_failure_does_not_break_autocommit(self, monkeypatch):
        # Autocommit mode: the helper's atomic is the outermost block; the
        # failing emit rolls only itself back and is swallowed, the profile
        # (saved by the caller) is untouched.
        from stapel_core.comm import actions

        monkeypatch.setattr(actions, "_emit_via_outbox", _explode)

        profile = Profile.objects.create(user_id=uuid.uuid4())
        with override_settings(STAPEL_COMM={"OUTBOX_ENABLED": True}):
            publish_profile_changed(profile)  # no active tx -> outermost atomic

        assert Profile.objects.filter(pk=profile.pk).exists()


@pytest.mark.django_db
class TestProfileUpdatedSignal:
    def test_signal_fired_on_update(self):
        received = []

        def receiver(sender, profile, fields_changed=None, **kwargs):
            received.append((sender, profile, fields_changed))

        profile_updated.connect(receiver)
        try:
            profile = _update_profile(display_name="Signal Guy", theme="dark")
        finally:
            profile_updated.disconnect(receiver)

        assert len(received) == 1
        sender, received_profile, fields_changed = received[0]
        assert sender is Profile
        assert received_profile.user_id == profile.user_id
        assert fields_changed == ["display_name", "theme"]
