"""A profile is keyed on the IDENTITY, not on the signup flow.

Auth emits two different facts and means to:

* ``user.registered`` — a person completed a signup FLOW, carrying hints auth
  does not store (avatar_url, display_name, language);
* ``user.created``    — the identity row itself, from a ``post_save`` observer,
  so it fires for every account born by ANY route (org provisioning, an admin
  action, a login grant, a JWT shadow row).

Until 0.20.5 this module provisioned on the milestone only, which stranded
every account born the other way. Measured on a live fleet 2026-09-15: 33 of
265 accounts (12.5%) had no profile row; 24 of those had a ``user.created``
event and no ``user.registered``, and 16 of them had signed up that same
month — accruing, not historical.
"""
import types
import uuid

import pytest

from stapel_profiles.actions import handle_user_created, handle_user_registered
from stapel_profiles.models import Profile


def _event(payload):
    return types.SimpleNamespace(payload=payload, event_id="evt-created-1")


@pytest.mark.django_db
class TestIdentityProvisioning:
    def test_an_account_born_without_a_signup_flow_gets_a_row(self):
        """The 24-user case: user.created arrives, user.registered never does."""
        user_id = uuid.uuid4()
        handle_user_created(_event({"user_id": str(user_id), "username": "x"}))
        assert Profile.objects.filter(user_id=user_id).exists()

    def test_the_row_is_empty(self):
        """An empty row is the honest state of someone who has typed nothing.

        It must not invent a name from the projection payload — the identity
        event carries a username, which is not a display name.
        """
        user_id = uuid.uuid4()
        handle_user_created(
            _event({"user_id": str(user_id), "username": "kdoe", "email": "k@d.io"})
        )
        profile = Profile.objects.get(user_id=user_id)
        assert profile.display_name == ""
        assert not profile.avatar

    def test_redelivery_is_a_no_op(self):
        """Delivery is at-least-once."""
        user_id = uuid.uuid4()
        for _ in range(3):
            handle_user_created(_event({"user_id": str(user_id)}))
        assert Profile.objects.filter(user_id=user_id).count() == 1

    def test_a_payload_without_user_id_is_refused_not_crashed(self):
        handle_user_created(_event({"username": "nobody"}))
        assert Profile.objects.count() == 0


@pytest.mark.django_db
class TestTheTwoEventsTogether:
    """Both subscriptions coexist; neither makes the other redundant."""

    def test_either_order_yields_exactly_one_row(self, monkeypatch):
        import stapel_core.comm as comm

        monkeypatch.setattr(comm, "call", lambda *a, **k: {"ref": "avatar/" + "a" * 64})

        first = uuid.uuid4()
        handle_user_created(_event({"user_id": str(first)}))
        handle_user_registered(_event({"user_id": str(first), "auth_type": "email"}))

        second = uuid.uuid4()
        handle_user_registered(_event({"user_id": str(second), "auth_type": "email"}))
        handle_user_created(_event({"user_id": str(second)}))

        assert Profile.objects.filter(user_id=first).count() == 1
        assert Profile.objects.filter(user_id=second).count() == 1

    def test_the_identity_event_does_not_clobber_a_seeded_name(self, monkeypatch):
        """user.registered seeds the hints; a later user.created must not undo it.

        The two are separate outbox rows with no ordering guarantee, so this
        is a real sequence and not a contrived one.
        """
        import stapel_core.comm as comm

        monkeypatch.setattr(comm, "call", lambda *a, **k: {"ref": "avatar/" + "a" * 64})

        user_id = uuid.uuid4()
        handle_user_registered(
            _event({
                "user_id": str(user_id),
                "auth_type": "oauth",
                "display_name": "Kim Doe",
            })
        )
        assert Profile.objects.get(user_id=user_id).display_name == "Kim Doe"

        handle_user_created(_event({"user_id": str(user_id), "username": "kdoe"}))
        assert Profile.objects.get(user_id=user_id).display_name == "Kim Doe"
