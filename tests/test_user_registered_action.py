"""Tests for the ``user.registered`` handler (display-name pre-fill + avatar).

Avatar half: the no-op cases (no avatar_url, no user_id, already-set
avatar), the happy path (mocked ``cdn.import_from_url`` comm call),
idempotency under at-least-once redelivery, and the swallow-not-retry
failure mode.

Display-name half (#149): the hint an admin/provider typed for this person
is a PRE-FILL, never an assignment — the tests below pin the guard that
makes that true (a set name is never clobbered, a name cleared after
onboarding is never resurrected by a redelivery) plus the input canon the
untrusted hint is held to.
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
        assert profile.avatar_source == "cdn"

    def test_updates_existing_profile_without_avatar(self, mock_import):
        user_id = uuid.uuid4()
        Profile.objects.create(user_id=user_id)
        handle_user_registered(
            _event({"user_id": str(user_id), "avatar_url": "https://p/a.png"})
        )
        profile = Profile.objects.get(user_id=user_id)
        assert profile.avatar == "avatar/" + "a" * 64
        assert profile.avatar_source == "cdn"


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
class TestDisplayNamePrefill:
    """#149 — the ``display_name`` hint must actually land on the profile."""

    def test_hint_prefills_a_new_profile(self, mock_import):
        user_id = uuid.uuid4()
        handle_user_registered(
            _event(
                {
                    "user_id": str(user_id),
                    "auth_type": "login",
                    "display_name": "Ada Lovelace",
                }
            )
        )
        assert Profile.objects.get(user_id=user_id).display_name == "Ada Lovelace"

    def test_hint_prefills_an_empty_existing_profile(self, mock_import):
        # GET /me creates an empty row on first render; a hint arriving
        # after that must still land.
        user_id = uuid.uuid4()
        Profile.objects.create(user_id=user_id)
        handle_user_registered(
            _event({"user_id": str(user_id), "display_name": "Ada Lovelace"})
        )
        assert Profile.objects.get(user_id=user_id).display_name == "Ada Lovelace"

    def test_hint_is_stripped(self, mock_import):
        user_id = uuid.uuid4()
        handle_user_registered(
            _event({"user_id": str(user_id), "display_name": "  Ada  "})
        )
        assert Profile.objects.get(user_id=user_id).display_name == "Ada"

    def test_no_hint_creates_no_profile(self, mock_import):
        user_id = uuid.uuid4()
        handle_user_registered(_event({"user_id": str(user_id), "auth_type": "email"}))
        assert not Profile.objects.filter(user_id=user_id).exists()

    def test_null_hint_is_a_noop(self, mock_import):
        user_id = uuid.uuid4()
        Profile.objects.create(user_id=user_id, display_name="Ada")
        handle_user_registered(
            _event({"user_id": str(user_id), "display_name": None})
        )
        assert Profile.objects.get(user_id=user_id).display_name == "Ada"

    def test_whitespace_only_hint_creates_no_row(self, mock_import):
        """A blank hint is not a name — and must not conjure a profile row
        for a user who has not touched the product yet."""
        user_id = uuid.uuid4()
        handle_user_registered(
            _event({"user_id": str(user_id), "display_name": "   "})
        )
        assert not Profile.objects.filter(user_id=user_id).exists()


@pytest.mark.django_db
class TestDisplayNameBelongsToItsOwner:
    """A pre-fill is not an assignment: the person named owns the name."""

    def test_user_set_name_is_never_clobbered(self, mock_import):
        user_id = uuid.uuid4()
        Profile.objects.create(user_id=user_id, display_name="Ada")
        handle_user_registered(
            _event({"user_id": str(user_id), "display_name": "A. Lovelace (admin)"})
        )
        assert Profile.objects.get(user_id=user_id).display_name == "Ada"

    def test_redelivery_does_not_overwrite_a_renamed_profile(self, mock_import):
        """At-least-once delivery must not undo the user's own rename."""
        user_id = uuid.uuid4()
        payload = {"user_id": str(user_id), "display_name": "A. Lovelace (admin)"}
        handle_user_registered(_event(payload))
        # The user renames themselves during onboarding.
        Profile.objects.filter(user_id=user_id).update(display_name="Ada")
        handle_user_registered(_event(payload))  # redelivery
        assert Profile.objects.get(user_id=user_id).display_name == "Ada"

    def test_redelivery_does_not_resurrect_a_cleared_name(self, mock_import):
        """The hole an emptiness-only guard leaves: a user who deliberately
        clears their name after onboarding must not get the admin's version
        back on the next redelivery."""
        user_id = uuid.uuid4()
        payload = {"user_id": str(user_id), "display_name": "A. Lovelace (admin)"}
        handle_user_registered(_event(payload))
        # The user finishes onboarding and empties the field on purpose.
        Profile.objects.filter(user_id=user_id).update(
            display_name="", initial_setup_passed=True
        )
        handle_user_registered(_event(payload))  # redelivery
        assert Profile.objects.get(user_id=user_id).display_name == ""


@pytest.mark.django_db
class TestDisplayNameHintIsUntrusted:
    """The hint comes from another service: held to this module's canon."""

    def test_too_long_hint_is_declined_not_truncated(self, mock_import, caplog):
        user_id = uuid.uuid4()
        long_name = "x" * 200
        handle_user_registered(
            _event({"user_id": str(user_id), "display_name": long_name})
        )
        # Declined outright: no truncated "xxx…x" name, and no row at all.
        assert not Profile.objects.filter(user_id=user_id).exists()
        assert "declined" in caplog.text

    def test_hint_violating_the_name_canon_is_declined(self, mock_import, caplog):
        user_id = uuid.uuid4()
        handle_user_registered(
            _event({"user_id": str(user_id), "display_name": "<script>"})
        )
        # Declined outright — never sanitized into something nobody typed.
        assert not Profile.objects.filter(user_id=user_id).exists()
        assert "declined" in caplog.text

    def test_prefill_failure_never_costs_the_avatar(self, mock_import):
        """The two halves of the handler are independent."""
        user_id = uuid.uuid4()
        handle_user_registered(
            _event(
                {
                    "user_id": str(user_id),
                    "display_name": "<script>",
                    "avatar_url": "https://p/a.png",
                }
            )
        )
        assert len(mock_import) == 1
        assert Profile.objects.get(user_id=user_id).avatar == "avatar/" + "a" * 64


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
