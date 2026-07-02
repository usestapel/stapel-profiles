"""API tests for profile endpoints (/me, /{user_id}) and languages."""

import uuid

import pytest
from stapel_core.core.language import COOKIE_APP_LANGUAGE, COOKIE_USE_DEVICE_LANGUAGE

from stapel_profiles.errors import (
    ERR_400_DISPLAY_NAME_EMOJI,
    ERR_400_DISPLAY_NAME_TOO_SHORT,
    ERR_404_PROFILE_NOT_FOUND,
)
from stapel_profiles.models import Language, Profile


@pytest.mark.django_db
class TestMyProfileGet:
    def test_requires_auth(self, api_client):
        resp = api_client.get("/me")
        assert resp.status_code in (401, 403)

    def test_get_creates_profile_with_defaults(self, authed_client, user):
        assert not Profile.objects.filter(user_id=user.id).exists()
        resp = authed_client.get("/me")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["user_id"] == str(user.id)
        assert data["currency_code"] == "EUR"
        assert data["followers_count"] == 0
        assert data["following_count"] == 0
        assert Profile.objects.filter(user_id=user.id).exists()

    def test_get_sets_language_cookies(self, authed_client):
        resp = authed_client.get("/me")
        # use_device_language defaults to True -> cookie "1"
        assert resp.cookies[COOKIE_USE_DEVICE_LANGUAGE].value == "1"
        # No app_language set -> cookie deleted (empty value)
        assert resp.cookies[COOKIE_APP_LANGUAGE].value == ""

    def test_get_updates_auto_detected_language(self, authed_client, user):
        resp = authed_client.get("/me", HTTP_ACCEPT_LANGUAGE="de-DE,de;q=0.9")
        assert resp.status_code == 200
        profile = Profile.objects.get(user_id=user.id)
        assert profile.auto_detected_language == "de"


@pytest.mark.django_db
class TestMyProfilePatch:
    def test_requires_auth(self, api_client):
        resp = api_client.patch("/me", {"display_name": "Nope"}, format="json")
        assert resp.status_code in (401, 403)

    def test_patch_updates_fields(self, authed_client, user):
        resp = authed_client.patch(
            "/me",
            {"display_name": "  New Name  ", "theme": "dark"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["display_name"] == "New Name"
        assert data["theme"] == "dark"
        profile = Profile.objects.get(user_id=user.id)
        assert profile.display_name == "New Name"
        assert profile.theme == "dark"

    def test_patch_app_language_sets_cookie(self, authed_client, user):
        Language.objects.create(code="de", name="German")
        resp = authed_client.patch(
            "/me",
            {"app_language": "de", "use_device_language": False},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["app_language"]["code"] == "de"
        assert resp.cookies[COOKIE_APP_LANGUAGE].value == "de"
        assert resp.cookies[COOKIE_USE_DEVICE_LANGUAGE].value == "0"
        assert Profile.objects.get(user_id=user.id).app_language_id == "de"

    def test_patch_display_name_too_short_rejected(self, authed_client, user):
        resp = authed_client.patch("/me", {"display_name": "x"}, format="json")
        assert resp.status_code == 400
        assert ERR_400_DISPLAY_NAME_TOO_SHORT in str(resp.json())
        assert Profile.objects.get(user_id=user.id).display_name == ""

    def test_patch_display_name_emoji_rejected(self, authed_client):
        resp = authed_client.patch("/me", {"display_name": "Hi 😀"}, format="json")
        assert resp.status_code == 400
        assert ERR_400_DISPLAY_NAME_EMOJI in str(resp.json())

    def test_patch_invalid_theme_rejected(self, authed_client):
        resp = authed_client.patch("/me", {"theme": "neon"}, format="json")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestProfileDetail:
    def test_get_public_profile_anonymous(self, api_client, user):
        Profile.objects.create(user_id=user.id, display_name="Someone")
        resp = api_client.get(f"/{user.id}")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["display_name"] == "Someone"
        assert data["relationship_status"] is None
        # Private fields must not leak through the public serializer
        assert "email_messages" not in data
        assert "essential_cookies_accepted" not in data

    def test_get_own_profile_shows_self_status(self, authed_client, user):
        Profile.objects.create(user_id=user.id)
        resp = authed_client.get(f"/{user.id}")
        assert resp.status_code == 200
        assert resp.json()["relationship_status"] == "self"

    def test_get_other_profile_shows_neutral(self, authed_client, other_user):
        Profile.objects.create(user_id=other_user.id)
        resp = authed_client.get(f"/{other_user.id}")
        assert resp.status_code == 200
        assert resp.json()["relationship_status"] == "neutral"

    def test_unknown_profile_404(self, api_client):
        resp = api_client.get(f"/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["localizable_error"] == ERR_404_PROFILE_NOT_FOUND


@pytest.mark.django_db
class TestLanguages:
    def test_list_returns_only_active(self, api_client):
        Language.objects.create(code="en", name="English")
        Language.objects.create(code="xx", name="Hidden", is_active=False)
        resp = api_client.get("/languages")
        assert resp.status_code == 200
        codes = [lang["code"] for lang in resp.json()]
        assert codes == ["en"]

    def test_retrieve_by_code(self, api_client):
        Language.objects.create(code="en", name="English")
        resp = api_client.get("/languages/en")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "English"
        assert data["flag"] is None

    def test_retrieve_unknown_404(self, api_client, db):
        resp = api_client.get("/languages/zz")
        assert resp.status_code == 404
