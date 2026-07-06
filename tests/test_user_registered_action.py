"""Tests for the ``user.registered`` → avatar-import handler.

Covers the no-op cases (no avatar_url, no user_id, already-set avatar),
the happy path (mocked ``cdn.import_from_url`` comm call), idempotency
under at-least-once redelivery, and the swallow-not-retry failure mode.
"""
import types
import uuid

import pytest

from stapel_profiles.actions import handle_user_registered
from stapel_profiles.models import Profile


def _event(payload):
    return types.SimpleNamespace(payload=payload, event_id="evt-reg-1")


@pytest.fixture
def mock_import(monkeypatch):
    """Patch stapel_core.comm.call and record invocations."""
    import stapel_core.comm as comm

    calls = []

    def fake_call(name, payload=None, **kwargs):
        calls.append((name, payload))
        return {"ref": "avatar/" + "a" * 64}

    monkeypatch.setattr(comm, "call", fake_call)
    return calls


@pytest.mark.django_db
class TestNoOpCases:
    def test_no_avatar_url_is_noop(self, mock_import):
        user_id = uuid.uuid4()
        handle_user_registered(
            _event({"user_id": str(user_id), "auth_type": "email"})
        )
        assert mock_import == []
        assert not Profile.objects.filter(user_id=user_id).exists()

    def test_null_avatar_url_is_noop(self, mock_import):
        user_id = uuid.uuid4()
        handle_user_registered(
            _event({"user_id": str(user_id), "auth_type": "oauth", "avatar_url": None})
        )
        assert mock_import == []

    def test_empty_avatar_url_is_noop(self, mock_import):
        handle_user_registered(
            _event({"user_id": str(uuid.uuid4()), "avatar_url": ""})
        )
        assert mock_import == []

    def test_missing_user_id_logs_and_skips(self, mock_import, caplog):
        handle_user_registered(_event({"avatar_url": "https://x/a.png"}))
        assert mock_import == []
        assert "without user_id" in caplog.text


@pytest.mark.django_db
class TestHappyPath:
    def test_imports_and_stores_ref(self, mock_import):
        user_id = uuid.uuid4()
        ref = "avatar/" + "a" * 64
        handle_user_registered(
            _event(
                {
                    "user_id": str(user_id),
                    "auth_type": "oauth",
                    "avatar_url": "https://provider.example/pic.png",
                }
            )
        )
        # comm call made with the avatar type and the user as rate-limit caller
        assert len(mock_import) == 1
        name, payload = mock_import[0]
        assert name == "cdn.import_from_url"
        assert payload["image_type"] == "avatar"
        assert payload["url"] == "https://provider.example/pic.png"
        assert payload["caller"] == str(user_id)

        profile = Profile.objects.get(user_id=user_id)
        assert profile.avatar == ref

    def test_updates_existing_profile_without_avatar(self, mock_import):
        user_id = uuid.uuid4()
        Profile.objects.create(user_id=user_id, display_name="Newbie")
        handle_user_registered(
            _event({"user_id": str(user_id), "avatar_url": "https://p/a.png"})
        )
        profile = Profile.objects.get(user_id=user_id)
        assert profile.avatar == "avatar/" + "a" * 64
        assert profile.display_name == "Newbie"  # untouched


@pytest.mark.django_db
class TestRespectUserChoice:
    def test_existing_avatar_not_overwritten(self, mock_import):
        user_id = uuid.uuid4()
        Profile.objects.create(
            user_id=user_id, avatar="avatar/" + "b" * 64
        )
        handle_user_registered(
            _event({"user_id": str(user_id), "avatar_url": "https://p/a.png"})
        )
        # No fetch attempted, manual avatar preserved.
        assert mock_import == []
        assert Profile.objects.get(user_id=user_id).avatar == "avatar/" + "b" * 64


@pytest.mark.django_db
class TestIdempotency:
    def test_redelivery_does_not_refetch(self, mock_import):
        user_id = uuid.uuid4()
        payload = {"user_id": str(user_id), "avatar_url": "https://p/a.png"}
        handle_user_registered(_event(payload))
        handle_user_registered(_event(payload))  # at-least-once redelivery
        # Fetched exactly once; second delivery sees the stored avatar.
        assert len(mock_import) == 1
        assert Profile.objects.filter(user_id=user_id).count() == 1


@pytest.mark.django_db
class TestBestEffortFailure:
    def test_import_failure_is_swallowed(self, monkeypatch, caplog):
        import stapel_core.comm as comm

        def boom(*args, **kwargs):
            raise RuntimeError("cdn down / blocked_ip")

        monkeypatch.setattr(comm, "call", boom)
        user_id = uuid.uuid4()

        # Must not raise — registration event delivery must not be retried
        # for a cosmetic avatar failure.
        handle_user_registered(
            _event({"user_id": str(user_id), "avatar_url": "https://p/a.png"})
        )
        assert "failed to import provider avatar" in caplog.text
        # Profile left without an avatar (not created just to be empty).
        profile = Profile.objects.filter(user_id=user_id).first()
        assert profile is None or not profile.avatar

    def test_missing_ref_in_result_is_swallowed(self, monkeypatch, caplog):
        import stapel_core.comm as comm

        monkeypatch.setattr(comm, "call", lambda *a, **k: {"unexpected": 1})
        user_id = uuid.uuid4()
        handle_user_registered(
            _event({"user_id": str(user_id), "avatar_url": "https://p/a.png"})
        )
        assert "no ref" in caplog.text
        assert not Profile.objects.filter(user_id=user_id).exists()
