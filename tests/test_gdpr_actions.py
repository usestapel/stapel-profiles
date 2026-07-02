"""Tests for the GDPR provider, action subscriptions and error registry."""

import types
import uuid

import pytest

from stapel_profiles.actions import handle_user_deleted
from stapel_profiles.errors import PROFILES_ERRORS, ProfilesErrorKeysView
from stapel_profiles.gdpr import ProfilesGDPRProvider
from stapel_profiles.models import (
    Language,
    Profile,
    RelationshipStatus,
    UserRelationship,
)


def _event(payload):
    return types.SimpleNamespace(payload=payload, event_id="evt-1")


@pytest.mark.django_db
class TestGDPRExport:
    def test_export_full_profile(self):
        user_id = uuid.uuid4()
        lang = Language.objects.create(code="de", name="German")
        Profile.objects.create(
            user_id=user_id, display_name="Exportee", app_language=lang
        )
        followed = uuid.uuid4()
        blocked = uuid.uuid4()
        UserRelationship.objects.create(
            follower_id=user_id,
            following_id=followed,
            status=RelationshipStatus.FOLLOWING,
        )
        UserRelationship.objects.create(
            follower_id=user_id,
            following_id=blocked,
            status=RelationshipStatus.BLOCKED,
        )

        data = ProfilesGDPRProvider().export(user_id)

        assert data["profile"]["display_name"] == "Exportee"
        assert data["profile"]["app_language"] == "de"
        assert data["following"] == [followed]
        assert data["blocked"] == [blocked]

    def test_export_missing_profile_is_empty(self):
        data = ProfilesGDPRProvider().export(uuid.uuid4())
        assert data["profile"] == {}
        assert data["following"] == []
        assert data["blocked"] == []


@pytest.mark.django_db
class TestGDPRDelete:
    def test_delete_removes_profile_and_relationships(self):
        user_id = uuid.uuid4()
        other = uuid.uuid4()
        Profile.objects.create(user_id=user_id)
        UserRelationship.objects.create(
            follower_id=user_id, following_id=other,
            status=RelationshipStatus.FOLLOWING,
        )
        UserRelationship.objects.create(
            follower_id=other, following_id=user_id,
            status=RelationshipStatus.FOLLOWING,
        )

        provider = ProfilesGDPRProvider()
        provider.delete(user_id)
        provider.anonymize(user_id)  # no-op, must not raise

        assert not Profile.objects.filter(user_id=user_id).exists()
        assert UserRelationship.objects.count() == 0


@pytest.mark.django_db
class TestUserDeletedAction:
    def test_handler_erases_profile(self):
        user_id = uuid.uuid4()
        Profile.objects.create(user_id=user_id)

        handle_user_deleted(_event({"user_id": str(user_id)}))

        assert not Profile.objects.filter(user_id=user_id).exists()

    def test_handler_without_user_id_logs_and_skips(self, caplog):
        Profile.objects.create(user_id=uuid.uuid4())

        handle_user_deleted(_event({}))

        assert Profile.objects.count() == 1
        assert "without user_id" in caplog.text


class TestErrorRegistry:
    def test_error_keys_view_returns_service_errors(self):
        assert ProfilesErrorKeysView().get_service_errors() is PROFILES_ERRORS


@pytest.mark.django_db
class TestPublishProfileChangedFailure:
    def test_emit_failure_is_swallowed(self, monkeypatch, caplog):
        import stapel_core.comm as comm

        from stapel_profiles.events import publish_profile_changed

        def boom(*args, **kwargs):
            raise RuntimeError("bus down")

        monkeypatch.setattr(comm, "emit", boom)
        profile = Profile.objects.create(user_id=uuid.uuid4())

        publish_profile_changed(profile)  # must not raise

        assert "Failed to publish profile-changed event" in caplog.text


class TestDisplayNameValidator:
    def test_empty_value_passes_through(self):
        from stapel_profiles.validators import validate_display_name

        assert validate_display_name("") == ""

    def test_forbidden_chars_rejected(self):
        from stapel_core.django.api.errors import StapelValidationError

        from stapel_profiles.validators import validate_display_name

        with pytest.raises(StapelValidationError):
            validate_display_name("a<script>b")

    def test_invisible_chars_rejected(self):
        from stapel_core.django.api.errors import StapelValidationError

        from stapel_profiles.validators import validate_display_name

        with pytest.raises(StapelValidationError):
            validate_display_name("ab\u200bcd")  # zero-width space


def test_admin_registrations():
    from django.contrib import admin as django_admin

    from stapel_profiles import admin as profiles_admin  # noqa: F401
    from stapel_profiles.models import Language, Profile, UserRelationship

    for model in (Language, Profile, UserRelationship):
        assert model in django_admin.site._registry
