"""Tests for serializer branches: flag URLs, CDN ref sync,
and the create() path of ProfileCreateUpdateSerializer."""

import uuid

import pytest
from django.test import override_settings

from stapel_profiles.models import Language, Profile
from stapel_profiles.serializers import (
    LanguageSerializer,
    ProfileCreateUpdateSerializer,
)

VALID_REF = "avatar/" + "a" * 64


@pytest.mark.django_db
class TestLanguageFlagUrl:
    @override_settings(MEDIA_URL="/media/")
    def test_flag_url_is_relative(self):
        lang = Language.objects.create(code="fr", name="French", flag="flags/fr.svg")
        data = LanguageSerializer(lang).data
        assert data["flag"] == "/media/flags/fr.svg"

    def test_no_flag_returns_none(self):
        lang = Language.objects.create(code="eo", name="Esperanto")
        assert LanguageSerializer(lang).data["flag"] is None



@pytest.mark.django_db
class TestAvatarRefSync:
    @override_settings(PROFILES_AVATAR_CHECK="off")
    def test_update_with_avatar_change_syncs_refs(self, monkeypatch):
        import stapel_core.django.cdn.ref_sync as ref_sync

        calls = []

        def fake_sync(service, kind, pk, old_refs, new_refs):
            calls.append((old_refs, new_refs))

        monkeypatch.setattr(ref_sync, "sync_cdn_refs", fake_sync)
        profile = Profile.objects.create(user_id=uuid.uuid4())
        ser = ProfileCreateUpdateSerializer(
            profile, data={"avatar": VALID_REF}, partial=True
        )
        assert ser.is_valid(), ser.errors
        ser.save()

        profile.refresh_from_db()
        assert profile.avatar == VALID_REF
        assert calls == [([], [VALID_REF])]

    @override_settings(PROFILES_AVATAR_CHECK="off")
    def test_ref_sync_failure_does_not_break_update(self, monkeypatch):
        import stapel_core.django.cdn.ref_sync as ref_sync

        def boom(*args, **kwargs):
            raise RuntimeError("sync down")

        monkeypatch.setattr(ref_sync, "sync_cdn_refs", boom)
        profile = Profile.objects.create(user_id=uuid.uuid4())
        ser = ProfileCreateUpdateSerializer(
            profile, data={"avatar": VALID_REF}, partial=True
        )
        assert ser.is_valid(), ser.errors
        ser.save()
        profile.refresh_from_db()
        assert profile.avatar == VALID_REF


@pytest.mark.django_db
class TestCreatePath:
    def test_create_publishes_event_and_signal(self):
        from stapel_core.signals import profile_updated

        received = []

        def receiver(sender, profile, fields_changed=None, **kwargs):
            received.append(fields_changed)

        profile_updated.connect(receiver)
        try:
            ser = ProfileCreateUpdateSerializer(data={"display_name": "Fresh"})
            assert ser.is_valid(), ser.errors
            created = ser.save(user_id=uuid.uuid4())
        finally:
            profile_updated.disconnect(receiver)

        assert Profile.objects.filter(user_id=created.user_id).exists()
        # save(user_id=...) merges the kwarg into validated_data
        assert received == [["display_name", "user_id"]]
