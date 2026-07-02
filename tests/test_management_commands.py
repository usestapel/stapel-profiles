"""Tests for the profiles management commands."""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from stapel_profiles.models import Language, Profile


@pytest.mark.django_db
class TestSyncLanguages:
    def _run(self, tmp_path):
        out = StringIO()
        with override_settings(MEDIA_ROOT=str(tmp_path)):
            call_command("sync_languages", stdout=out)
        return out.getvalue()

    def test_creates_languages_from_fixture(self, tmp_path):
        output = self._run(tmp_path)
        assert Language.objects.filter(code="en").exists()
        assert Language.objects.count() > 0
        assert "created" in output
        # Flag files are copied into MEDIA_ROOT
        assert (tmp_path / "flags").exists()

    def test_second_run_skips_existing(self, tmp_path):
        self._run(tmp_path)
        total = Language.objects.count()
        output = self._run(tmp_path)
        assert Language.objects.count() == total
        assert "0 created" in output

    def test_fills_empty_name_without_overwriting(self, tmp_path):
        Language.objects.create(code="en", name="")
        output = self._run(tmp_path)
        assert Language.objects.get(code="en").name == "English"
        assert "Updated en" in output


@pytest.mark.django_db
class TestPublishAllProfiles:
    def test_publishes_event_per_profile(self):
        Profile.objects.create(user_id=uuid.uuid4(), display_name="A")
        Profile.objects.create(user_id=uuid.uuid4(), display_name="B")

        out = StringIO()
        call_command("publish_all_profiles", stdout=out)

        assert "Publishing events for 2 profiles" in out.getvalue()
        assert "2 published, 0 errors" in out.getvalue()

    def test_counts_publish_errors(self, monkeypatch):
        import stapel_profiles.management.commands.publish_all_profiles as cmd_mod

        Profile.objects.create(user_id=uuid.uuid4())

        def boom(*args, **kwargs):
            raise RuntimeError("kafka down")

        monkeypatch.setattr(cmd_mod, "publish", boom)
        out = StringIO()
        call_command("publish_all_profiles", stdout=out)
        assert "0 published, 1 errors" in out.getvalue()
