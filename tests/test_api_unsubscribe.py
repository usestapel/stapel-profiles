"""API tests for the one-click unsubscribe endpoint (HMAC token, RFC 8058)."""

import uuid

import pytest
from stapel_core.notifications.tokens import generate_unsubscribe_token

from stapel_profiles.models import Profile

URL = "/notifications/unsubscribe"


def _token(user_id, group="messages", channel="email"):
    return generate_unsubscribe_token(str(user_id), group, channel)


@pytest.mark.django_db
class TestUnsubscribe:
    def test_valid_token_unsubscribes(self, api_client, user):
        profile = Profile.objects.create(user_id=user.id)
        assert profile.email_messages is True

        resp = api_client.post(f"{URL}?token={_token(user.id)}")
        assert resp.status_code == 200, resp.content
        assert resp.json() == {"success": True, "unsubscribed": "email_messages"}
        profile.refresh_from_db()
        assert profile.email_messages is False

    def test_push_system_channel_group(self, api_client, user):
        profile = Profile.objects.create(user_id=user.id)
        token = _token(user.id, group="system", channel="push")
        resp = api_client.post(f"{URL}?token={token}")
        assert resp.status_code == 200
        assert resp.json()["unsubscribed"] == "push_system"
        profile.refresh_from_db()
        assert profile.push_system is False

    def test_repeat_is_idempotent(self, api_client, user):
        profile = Profile.objects.create(user_id=user.id, email_messages=False)
        resp = api_client.post(f"{URL}?token={_token(user.id)}")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "unsubscribed": "email_messages"}
        profile.refresh_from_db()
        assert profile.email_messages is False

    def test_token_in_body_also_accepted(self, api_client, user):
        profile = Profile.objects.create(user_id=user.id)
        resp = api_client.post(URL, {"token": _token(user.id)}, format="json")
        assert resp.status_code == 200
        profile.refresh_from_db()
        assert profile.email_messages is False

    def test_tampered_token_rejected(self, api_client, user):
        Profile.objects.create(user_id=user.id)
        token = _token(user.id)[:-4] + "beef"
        resp = api_client.post(f"{URL}?token={token}")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Invalid or expired token"

    def test_missing_token_rejected(self, api_client, db):
        resp = api_client.post(URL)
        assert resp.status_code == 400

    def test_unknown_preference_rejected(self, api_client, user):
        profile = Profile.objects.create(user_id=user.id)
        token = _token(user.id, group="marketing", channel="email")
        resp = api_client.post(f"{URL}?token={token}")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Invalid preference"
        profile.refresh_from_db()
        assert profile.email_messages is True

    def test_missing_profile_rejected(self, api_client, db):
        resp = api_client.post(f"{URL}?token={_token(uuid.uuid4())}")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Profile not found"
