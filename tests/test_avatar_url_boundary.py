"""The avatar URL boundary (security audit PROFILE-01).

`avatar` under `avatar_source=url` (or `gravatar`) is a string ONE user
controls and EVERY consumer renders. These pin both directions of the
boundary: what may be written, and what may be handed back out.
"""
import uuid

import pytest
from django.test import override_settings

from stapel_profiles.errors import (
    ERR_400_AVATAR_GRAVATAR_HASH,
    ERR_400_AVATAR_URL_HOST,
    ERR_400_AVATAR_URL_SCHEME,
)
from stapel_profiles.models import AvatarSource, Profile
from stapel_profiles.serializers import ProfileCreateUpdateSerializer, avatar_image


def _validate(avatar, source):
    serializer = ProfileCreateUpdateSerializer(
        data={"avatar": avatar, "avatar_source": source}
    )
    serializer.is_valid()
    return [str(err) for err in serializer.errors.get("avatar", [])]


# ── Import side ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        "data:image/svg+xml;base64,PHN2Zz48c2NyaXB0Pg==",
        "vbscript:msgbox(1)",
    ],
)
def test_active_scheme_avatar_is_refused(value):
    """An active scheme is not a picture reference, it is code."""
    assert ERR_400_AVATAR_URL_SCHEME in _validate(value, AvatarSource.URL)


def test_plain_http_avatar_is_refused():
    """http downgrades the page and leaks the referrer in clear text."""
    assert ERR_400_AVATAR_URL_SCHEME in _validate(
        "http://example.com/me.png", AvatarSource.URL
    )


def test_https_avatar_is_accepted():
    """...from a host this deployment named. The allowlist is not optional."""
    with override_settings(
        STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["example.com"]}
    ):
        assert _validate("https://example.com/me.png", AvatarSource.URL) == []


def test_external_avatar_is_refused_when_no_host_is_allowlisted():
    """The host allowlist is CLOSED by default (audit 2026-08-11).

    An empty allowlist names no host this deployment trusts, so there is
    nothing to accept: an unlisted external avatar is fetched by every
    viewer of the profile, which makes it a beacon the profile's owner
    chose and the viewer never agreed to.
    """
    assert ERR_400_AVATAR_URL_HOST in _validate(
        "https://tracker.example.net/a.png", AvatarSource.URL
    )
    assert ERR_400_AVATAR_URL_HOST in _validate(
        "https://example.com/me.png", AvatarSource.URL
    )


def test_any_host_is_reachable_only_as_an_explicit_opt_out():
    """["*"] restores the pre-0.12.6 "any host" behaviour — as a stated act."""
    with override_settings(
        STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["*"]}
    ):
        assert _validate("https://tracker.example.net/a.png", AvatarSource.URL) == []
        # Opening the host policy never opens the scheme policy.
        assert ERR_400_AVATAR_URL_SCHEME in _validate(
            "javascript:alert(1)", AvatarSource.URL
        )


def test_schemeless_and_hostless_values_are_refused():
    assert ERR_400_AVATAR_URL_SCHEME in _validate("//example.com/me.png", AvatarSource.URL)
    assert ERR_400_AVATAR_URL_SCHEME in _validate("me.png", AvatarSource.URL)
    assert ERR_400_AVATAR_URL_HOST in _validate("https:///me.png", AvatarSource.URL)


def test_host_allowlist_is_enforced():
    with override_settings(
        STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["cdn.example.com", ".corp.example"]}
    ):
        assert _validate("https://cdn.example.com/a.png", AvatarSource.URL) == []
        assert _validate("https://team.corp.example/a.png", AvatarSource.URL) == []
        assert ERR_400_AVATAR_URL_HOST in _validate(
            "https://tracker.example.net/a.png", AvatarSource.URL
        )
        # Suffix matching is on the host boundary, not on the string.
        assert ERR_400_AVATAR_URL_HOST in _validate(
            "https://evilcorp.example/a.png", AvatarSource.URL
        )


def test_scheme_policy_is_configuration():
    """A deployment may widen the schemes — deliberately, and visibly."""
    with override_settings(
        STAPEL_PROFILES={
            "PROFILES_AVATAR_URL_ALLOWED_SCHEMES": ["https", "http"],
            "PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["example.com"],
        }
    ):
        assert _validate("http://example.com/me.png", AvatarSource.URL) == []
    # Widening never reaches active schemes unless a host names them.
    with override_settings(
        STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_SCHEMES": ["https", "http"]}
    ):
        assert ERR_400_AVATAR_URL_SCHEME in _validate(
            "javascript:alert(1)", AvatarSource.URL
        )


@pytest.mark.parametrize(
    "value",
    [
        "../../etc/passwd",
        "abc?d=https://evil.example/x.png",
        "https://evil.example/x.png",
        "not-a-hash",
    ],
)
def test_gravatar_value_must_be_an_email_hash(value):
    assert ERR_400_AVATAR_GRAVATAR_HASH in _validate(value, AvatarSource.GRAVATAR)


def test_gravatar_hash_is_accepted():
    assert _validate("a" * 32, AvatarSource.GRAVATAR) == []
    assert _validate("b" * 64, AvatarSource.GRAVATAR) == []


# ── Read side ────────────────────────────────────────────────────────
#
# Rows written before the rule (or by a writer that bypassed the API) must
# not be handed to clients either: no consumer should have to defend itself
# against this field.


@pytest.mark.django_db
def test_stored_active_scheme_avatar_is_not_emitted():
    profile = Profile.objects.create(
        user_id=uuid.uuid4(),
        avatar_source=AvatarSource.URL,
        avatar="javascript:alert(1)",
    )
    assert avatar_image(profile) is None


@pytest.mark.django_db
def test_stored_disallowed_host_avatar_is_not_emitted():
    profile = Profile.objects.create(
        user_id=uuid.uuid4(),
        avatar_source=AvatarSource.URL,
        avatar="https://tracker.example.net/a.png",
    )
    with override_settings(
        STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["cdn.example.com"]}
    ):
        assert avatar_image(profile) is None
    # Same row, no host policy at all: still not emitted — an empty
    # allowlist is "no host is trusted", not "every host is".
    assert avatar_image(profile) is None
    # Same row under the explicit opt-out: emitted.
    with override_settings(
        STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["*"]}
    ):
        assert avatar_image(profile) is not None


@pytest.mark.django_db
def test_stored_non_hash_gravatar_is_not_emitted():
    profile = Profile.objects.create(
        user_id=uuid.uuid4(),
        avatar_source=AvatarSource.GRAVATAR,
        avatar="../../evil",
    )
    assert avatar_image(profile) is None


@pytest.mark.django_db
def test_public_profile_response_never_carries_an_unsafe_avatar(api_client):
    user_id = uuid.uuid4()
    Profile.objects.create(
        user_id=user_id,
        display_name="Mallory",
        avatar_source=AvatarSource.URL,
        avatar="javascript:alert(1)",
    )

    body = api_client.get(f"/{user_id}").json()

    assert body["avatar_image"] is None
