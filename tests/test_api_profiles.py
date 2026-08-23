"""API tests for profile endpoints (/me, /{user_id}) and languages."""

import uuid

import pytest
from stapel_core.core.language import COOKIE_APP_LANGUAGE, COOKIE_USE_DEVICE_LANGUAGE

from stapel_profiles.errors import ERR_404_PROFILE_NOT_FOUND
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
        assert data["avatar_source"] == "file"
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
        resp = api_client.patch("/me", {"avatar_source": "url"}, format="json")
        assert resp.status_code in (401, 403)

    def test_patch_updates_fields(self, authed_client, user):
        from django.test import override_settings

        # The avatar here is incidental payload; the URL boundary itself is
        # pinned in test_avatar_url_boundary.py.
        with override_settings(
            STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["example.com"]}
        ):
            resp = authed_client.patch(
                "/me",
                {"avatar_source": "url", "avatar": "https://example.com/me.png"},
                format="json",
            )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["avatar_source"] == "url"
        assert data["avatar"] == "https://example.com/me.png"
        profile = Profile.objects.get(user_id=user.id)
        assert profile.avatar_source == "url"
        assert profile.avatar == "https://example.com/me.png"

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

    def test_patch_app_language_declared_but_never_seeded(self, authed_client, user):
        """A language the deployment DECLARES is choosable even if nobody ran
        `sync_languages`.

        This is the state the meettoday sandbox was in: LANGUAGES declared ru
        and en, the Language table held zero rows, so the picker was empty and
        every write 400'd — app_language stayed NULL for all 66 profiles and
        every notification had to guess at the recipient's language.
        """
        from django.test import override_settings

        assert not Language.objects.filter(code="fi").exists()
        with override_settings(LANGUAGES=[("fi", "Suomi")]):
            resp = authed_client.patch(
                "/me",
                {"app_language": "fi", "use_device_language": False},
                format="json",
            )
        assert resp.status_code == 200, resp.content
        assert Profile.objects.get(user_id=user.id).app_language_id == "fi"
        # Materialised with the name the deployment declared, so the picker
        # and the profile agree about what "fi" is called.
        assert Language.objects.get(code="fi").name == "Suomi"

    def test_language_list_offers_declared_languages_without_seeding(
        self, authed_client
    ):
        """The picker is not empty just because nobody ran `sync_languages`.

        Half the defect was here: the write could be widened all it liked,
        but a settings screen with nothing to pick still leaves every user
        without a stated language.
        """
        from django.test import override_settings

        Language.objects.all().delete()
        with override_settings(LANGUAGES=[("fi", "Suomi"), ("sv", "Svenska")]):
            resp = authed_client.get("/languages/")
        assert resp.status_code == 200, resp.content
        assert {row["code"] for row in resp.json()} == {"fi", "sv"}

    def test_patch_undeclared_language_is_still_rejected(self, authed_client):
        """Widened, not opened: a code nobody declared is still not a language."""
        from django.test import override_settings

        with override_settings(LANGUAGES=[("fi", "Suomi")]):
            resp = authed_client.patch("/me", {"app_language": "zz"}, format="json")
        assert resp.status_code == 400
        assert not Language.objects.filter(code="zz").exists()

    def test_patch_understands_accepts_declared_codes(self, authed_client, user):
        from django.test import override_settings

        with override_settings(LANGUAGES=[("fi", "Suomi"), ("sv", "Svenska")]):
            resp = authed_client.patch(
                "/me", {"understands": ["fi", "sv"]}, format="json"
            )
        assert resp.status_code == 200, resp.content
        assert set(
            Profile.objects.get(user_id=user.id).understands.values_list(
                "code", flat=True
            )
        ) == {"fi", "sv"}

    def test_patch_invalid_avatar_source_rejected(self, authed_client):
        resp = authed_client.patch("/me", {"avatar_source": "dropbox"}, format="json")
        assert resp.status_code == 400

    def test_patch_display_name_and_theme_persist(self, authed_client, user):
        """Regression: ProfileCreateUpdateSerializer silently dropped
        display_name/theme (missing from its `fields`) after they moved back
        into ProfileCore hard-core (0.7.0) — the write side never got the
        read side's fields, so a PATCH accepted the request but never wrote
        the columns."""
        resp = authed_client.patch(
            "/me",
            {"display_name": "Ada Lovelace", "theme": "dark"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["display_name"] == "Ada Lovelace"
        assert data["theme"] == "dark"
        profile = Profile.objects.get(user_id=user.id)
        assert profile.display_name == "Ada Lovelace"
        assert profile.theme == "dark"


@pytest.mark.django_db
class TestProfileDetail:
    def test_get_public_profile_anonymous(self, api_client, user):
        Profile.objects.create(user_id=user.id, avatar_source="url", avatar="https://example.com/me.png")
        resp = api_client.get(f"/{user.id}")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["avatar"] == "https://example.com/me.png"
        # relationship_status is not in the anonymous field policy — it has
        # no meaning without a viewer (PROFILES_PUBLIC_FIELDS_ANONYMOUS).
        assert "relationship_status" not in data
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
class TestProfileOfSomebodyWhoNeverLoggedIn:
    """The class defect (0.15.0): a marketplace with no names on it.

    A user registers and goes straight to browsing. They never open their
    own profile, so before 0.15.0 no row existed — and every place that
    renders them TO SOMEBODY ELSE (seller block, chat, review author) reads
    this endpoint and got a 404. The account existed; the product had
    nowhere to read it from.
    """

    def test_registered_but_never_logged_in_reads_200(self, api_client, user):
        assert not Profile.objects.filter(user_id=user.id).exists()
        resp = api_client.get(f"/{user.id}")
        assert resp.status_code == 200, resp.content
        assert resp.json()["user_id"] == str(user.id)

    def test_the_wire_stays_honest_about_an_empty_name(self, api_client, user):
        """No `fallback_label`, no invented placeholder: empty is empty and
        the client renders its own fallback (which the pairs already do)."""
        data = api_client.get(f"/{user.id}").json()
        assert data["display_name"] == ""
        assert "fallback_label" not in data

    def test_a_read_never_writes_a_row(self, api_client, user):
        """These endpoints are AllowAny over every user id. Answering must
        not be a way for unauthenticated traffic to grow this database."""
        api_client.get(f"/{user.id}")
        assert not Profile.objects.filter(user_id=user.id).exists()

    def test_unknown_uuid_still_404s(self, api_client, db):
        """404 keeps exactly one meaning: this id names nobody."""
        resp = api_client.get(f"/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["localizable_error"] == ERR_404_PROFILE_NOT_FOUND

    def test_the_shape_matches_a_real_row(self, api_client, user, other_user):
        """One wire contract, not two: the synthesised answer is the same
        serializer over the model's own defaults."""
        Profile.objects.create(user_id=other_user.id)
        real = api_client.get(f"/{other_user.id}").json()
        synthesised = api_client.get(f"/{user.id}").json()
        assert set(real) == set(synthesised)

    def test_batch_agrees_with_the_single_lookup(self, api_client, user):
        """The two public endpoints may never disagree about a person."""
        unknown = uuid.uuid4()
        resp = api_client.post(
            "/batch", {"user_ids": [str(user.id), str(unknown)]}, format="json"
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert [p["user_id"] for p in data["profiles"]] == [str(user.id)]
        assert data["missing"] == [str(unknown)]


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


@pytest.mark.django_db
def test_unconfigured_languages_are_not_a_declaration():
    """Django's 100-entry default is not a claim this project made.

    Materialising it would fill the picker with languages nobody chose to
    support, so an unconfigured project keeps the old behaviour: only rows
    somebody seeded.
    """
    from django.conf import global_settings
    from django.test import override_settings

    from stapel_profiles.models import Language, ensure_declared_languages

    Language.objects.all().delete()
    with override_settings(LANGUAGES=global_settings.LANGUAGES):
        ensure_declared_languages()
    assert Language.objects.count() == 0
