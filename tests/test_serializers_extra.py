"""Tests for serializer branches: flag URLs, CDN ref sync,
and the create() path of ProfileCreateUpdateSerializer."""

import uuid

import pytest
from django.test import override_settings

from stapel_profiles.models import Language, Profile
from stapel_profiles.serializers import (
    LanguageSerializer,
    ProfileCreateUpdateSerializer,
    ProfileSerializer,
)

VALID_REF = "avatar/" + "a" * 64


class TestReadWriteSerializerParity:
    """Regression guard (0.7.2): `ProfileCreateUpdateSerializer` (the write
    side of `PATCH /me`) silently missed `display_name`/`theme` after 0.7.0
    moved them back into `ProfileCore` — only `ProfileSerializer` (the read
    side) picked them up. DRF drops unknown request keys with no error, so
    the PATCH validated and returned 200 while never writing the columns;
    caught only by manually checking the DB.

    This asserts the structural invariant that let that happen at all:
    every WRITABLE field on the read serializer (i.e. not in its
    `read_only_fields`, and not a computed/method field with no column of
    its own) must also be accepted by the write serializer. It is
    field-name-agnostic on purpose — it exists so the NEXT field anyone
    moves into the hard core fails this test immediately, rather than
    silently repeating this exact bug for whatever field comes next.
    """

    #: Read-side fields with no backing model column to PATCH — never
    #: expected on the write serializer.
    COMPUTED_ONLY_FIELDS = frozenset({
        "user_id",
        "avatar_image",
        "followers_count",
        "following_count",
        "created_at",
        "updated_at",
    })

    def test_every_writable_read_field_is_accepted_for_write(self):
        read_fields = set(ProfileSerializer.Meta.fields)
        read_only = set(ProfileSerializer.Meta.read_only_fields)
        writable_on_read = read_fields - read_only - self.COMPUTED_ONLY_FIELDS

        write_fields = set(ProfileCreateUpdateSerializer.Meta.fields)

        missing = writable_on_read - write_fields
        assert not missing, (
            f"{sorted(missing)} are writable on ProfileSerializer (the "
            "read side of /me) but missing from ProfileCreateUpdateSerializer "
            "(the write side) — PATCH /me will silently accept and drop "
            "these fields. Add them to ProfileCreateUpdateSerializer.Meta.fields."
        )


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
            profile, data={"avatar_source": "cdn", "avatar": VALID_REF}, partial=True
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
            profile, data={"avatar_source": "cdn", "avatar": VALID_REF}, partial=True
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
            ser = ProfileCreateUpdateSerializer(data={"avatar_source": "url"})
            assert ser.is_valid(), ser.errors
            created = ser.save(user_id=uuid.uuid4())
        finally:
            profile_updated.disconnect(receiver)

        assert Profile.objects.filter(user_id=created.user_id).exists()
        # save(user_id=...) merges the kwarg into validated_data
        assert received == [["avatar_source", "user_id"]]
