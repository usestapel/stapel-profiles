"""Public-profile visibility and enumeration limits (audit PROFILE-01).

`GET /<user_id>` and `POST /batch` answer for any user id, to anyone. Two
questions therefore have to have written-down answers: WHAT they expose
(a declared field policy, identical on both endpoints) and HOW MUCH of the
user base one caller may walk (per-caller rate limits over the batching cap
that was already there).
"""
import uuid

import pytest
from django.test import override_settings

from stapel_profiles.models import Profile

pytestmark = pytest.mark.django_db

FULL_PUBLIC_FIELDS = {
    "user_id",
    "display_name",
    "avatar_source",
    "avatar",
    "avatar_image",
    "location_id",
    "location_display_name_narrow",
    "location_display_name_broad",
    "followers_count",
    "following_count",
    "relationship_status",
    "seller_type",
    "created_at",
    "contacts",
}


@pytest.fixture
def profile(db):
    return Profile.objects.create(user_id=uuid.uuid4(), display_name="Ada")


@pytest.fixture
def anon_client():
    """A second, definitely unauthenticated client.

    The shared `api_client` fixture is the very object `authed_client`
    force-authenticates, so a test that wants both callers must build its
    own — otherwise "anonymous" and "member" are the same session.
    """
    from rest_framework.test import APIClient

    return APIClient()


def _batch(client, ids):
    return client.post("/batch", {"user_ids": [str(i) for i in ids]}, format="json")


# ── Visibility ───────────────────────────────────────────────────────


NARROW_ANONYMOUS_FIELDS = {
    "user_id",
    "display_name",
    "avatar_source",
    "avatar",
    "avatar_image",
    "seller_type",
    "created_at",
    "contacts",
}


def test_members_see_the_full_public_field_set(api_client, authed_client, profile):
    """The member-facing default is unchanged: the full public set."""
    del api_client  # the anonymous half is pinned by the tests below
    body = authed_client.get(f"/{profile.user_id}").json()
    assert set(body) == FULL_PUBLIC_FIELDS


def test_anonymous_default_is_narrower_than_the_member_view(anon_client, profile):
    """Closed by default (audit 2026-08-11).

    `GET /<user_id>` and `POST /batch` are AllowAny and answer for any user
    id, so THIS is what an unauthenticated scraper gets out of the box. It
    must not include whereabouts or the social graph.
    """
    body = anon_client.get(f"/{profile.user_id}").json()

    assert set(body) == NARROW_ANONYMOUS_FIELDS
    assert not {f for f in body if f.startswith("location_")}
    assert "followers_count" not in body
    assert "following_count" not in body


def test_the_batch_endpoint_has_the_same_anonymous_default(anon_client, profile):
    """The bulk door is the one worth scraping — it must not be wider."""
    body = _batch(anon_client, [profile.user_id]).json()
    assert set(body["profiles"][0]) == NARROW_ANONYMOUS_FIELDS


def test_the_member_view_for_anonymous_is_an_explicit_opt_out(anon_client, profile):
    """The pre-0.12.6 answer stays reachable — as a stated decision."""
    for value in (None, ["*"]):
        with override_settings(
            STAPEL_PROFILES={"PROFILES_PUBLIC_FIELDS_ANONYMOUS": value}
        ):
            body = anon_client.get(f"/{profile.user_id}").json()
        assert set(body) == FULL_PUBLIC_FIELDS, value


def test_host_can_narrow_what_a_public_lookup_exposes(api_client, profile):
    with override_settings(
        STAPEL_PROFILES={"PROFILES_PUBLIC_FIELDS": ["user_id", "display_name"]}
    ):
        body = api_client.get(f"/{profile.user_id}").json()
    assert set(body) == {"user_id", "display_name"}


def test_the_batch_endpoint_obeys_the_same_policy(api_client, profile):
    """Two doors onto the same data must not disagree about privacy."""
    with override_settings(
        STAPEL_PROFILES={"PROFILES_PUBLIC_FIELDS": ["user_id", "display_name"]}
    ):
        body = _batch(api_client, [profile.user_id]).json()
    assert set(body["profiles"][0]) == {"user_id", "display_name"}


def test_anonymous_callers_can_be_given_a_narrower_view(anon_client, authed_client, profile):
    policy = {
        "PROFILES_PUBLIC_FIELDS_ANONYMOUS": ["user_id", "display_name", "avatar_image"],
    }
    with override_settings(STAPEL_PROFILES=policy):
        anonymous = anon_client.get(f"/{profile.user_id}").json()
        member = authed_client.get(f"/{profile.user_id}").json()

    assert set(anonymous) == {"user_id", "display_name", "avatar_image"}
    assert set(member) == FULL_PUBLIC_FIELDS


@pytest.fixture
def guest_client(api_client):
    """A guest session — what `POST /auth/api/v1/anonymous/` mints.

    Not a second anonymous client: this one IS `is_authenticated`, which is
    the whole point of the class of caller and the reason the defect below
    was invisible to a permission check.
    """
    from stapel_core.django.users.models import User

    api_client.force_authenticate(user=User.create_anonymous_user())
    return api_client


def test_a_guest_session_reads_the_anonymous_view_not_the_member_one(
    guest_client, profile
):
    """The stand defect (2026-09-04): a storefront mints a guest from the
    first tap on "message the seller", and that one POST used to buy the
    member view of every user id — whereabouts and the social graph, at
    scrape rate, from a session nobody registered."""
    body = guest_client.get(f"/{profile.user_id}").json()

    assert set(body) == NARROW_ANONYMOUS_FIELDS
    assert not {f for f in body if f.startswith("location_")}
    assert "followers_count" not in body
    assert "relationship_status" not in body


def test_the_batch_door_answers_a_guest_the_same_way(guest_client, profile):
    body = _batch(guest_client, [profile.user_id]).json()
    assert set(body["profiles"][0]) == NARROW_ANONYMOUS_FIELDS


def test_a_member_still_reads_the_member_view(authed_client, profile):
    """The narrowing is about accounts, not about sessions: a registered
    caller is unchanged."""
    body = authed_client.get(f"/{profile.user_id}").json()
    assert set(body) == FULL_PUBLIC_FIELDS


def test_a_deployment_that_opens_the_anonymous_view_opens_it_for_guests_too(
    guest_client, profile
):
    """One policy, one answer: the opt-out is stated once and covers every
    caller without an account."""
    with override_settings(STAPEL_PROFILES={"PROFILES_PUBLIC_FIELDS_ANONYMOUS": None}):
        body = guest_client.get(f"/{profile.user_id}").json()
    assert set(body) == FULL_PUBLIC_FIELDS


def test_the_anonymous_policy_can_only_narrow(api_client, profile):
    """A field hidden from members must not reappear for the internet."""
    with override_settings(
        STAPEL_PROFILES={
            "PROFILES_PUBLIC_FIELDS": ["user_id"],
            "PROFILES_PUBLIC_FIELDS_ANONYMOUS": ["user_id", "avatar"],
        }
    ):
        body = api_client.get(f"/{profile.user_id}").json()
    assert set(body) == {"user_id"}


# ── Tenure (`created_at`) ────────────────────────────────────────────
#
# A seller page renders "on the site since <month year>". The fact lived on
# /me only, so a storefront could not draw it for anybody but the viewer
# themselves. It is tenure — it names nobody, and nothing about signing in
# moves it — so it is in BOTH default policy lists, and removable from
# either like every other field.


def _parsed(value):
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(value)
    assert parsed is not None, f"{value!r} is not an ISO 8601 datetime"
    return parsed


def test_a_member_reads_the_join_date(authed_client, profile):
    body = authed_client.get(f"/{profile.user_id}").json()

    assert "created_at" in body
    assert _parsed(body["created_at"]) == profile.created_at


def test_an_anonymous_caller_reads_the_join_date_too(anon_client, profile):
    """The storefront's visitor is usually signed out — a join date they
    cannot see is a join date the seller page cannot draw."""
    body = anon_client.get(f"/{profile.user_id}").json()

    assert "created_at" in body
    assert _parsed(body["created_at"]) == profile.created_at


def test_the_batch_door_carries_the_join_date(anon_client, profile):
    body = _batch(anon_client, [profile.user_id]).json()

    assert _parsed(body["profiles"][0]["created_at"]) == profile.created_at


def test_the_join_date_is_the_profiles_creation_not_a_sign_in(
    authed_client, profile
):
    """`created_at` answers "since when", never "when were they last here".

    Signing in touches nothing on this row, and a later WRITE moves
    `updated_at` — not this. A client that read tenure off something that
    moves would be publishing an activity signal.
    """
    profile.display_name = "Ada Lovelace"
    profile.save()
    profile.refresh_from_db()
    assert profile.updated_at > profile.created_at

    body = authed_client.get(f"/{profile.user_id}").json()

    assert _parsed(body["created_at"]) == profile.created_at
    assert _parsed(body["created_at"]) != profile.updated_at
    assert "updated_at" not in body


def test_a_host_that_drops_the_join_date_from_the_policy_hides_it(
    authed_client, anon_client, profile
):
    """Removable by policy like every other field — for members and for the
    internet, through the two lists that already exist."""
    members_only = [f for f in FULL_PUBLIC_FIELDS if f != "created_at"]
    with override_settings(
        STAPEL_PROFILES={"PROFILES_PUBLIC_FIELDS": sorted(members_only)}
    ):
        member = authed_client.get(f"/{profile.user_id}").json()
        # Hidden from members means hidden from the internet: the anonymous
        # list may only ever narrow.
        anonymous = anon_client.get(f"/{profile.user_id}").json()
        batched = _batch(authed_client, [profile.user_id]).json()

    assert "created_at" not in member
    assert "created_at" not in anonymous
    assert "created_at" not in batched["profiles"][0]


def test_the_join_date_can_be_hidden_from_the_internet_alone(
    authed_client, anon_client, profile
):
    with override_settings(
        STAPEL_PROFILES={
            "PROFILES_PUBLIC_FIELDS_ANONYMOUS": sorted(
                NARROW_ANONYMOUS_FIELDS - {"created_at"}
            )
        }
    ):
        anonymous = anon_client.get(f"/{profile.user_id}").json()
        member = authed_client.get(f"/{profile.user_id}").json()

    assert "created_at" not in anonymous
    assert "created_at" in member


# ── Enumeration limits ───────────────────────────────────────────────


def test_public_lookups_are_rate_limited_per_caller(api_client, profile):
    with override_settings(STAPEL_PROFILES={"PROFILES_LOOKUP_RATE": "2/min"}):
        assert api_client.get(f"/{profile.user_id}").status_code == 200
        assert api_client.get(f"/{profile.user_id}").status_code == 200
        assert api_client.get(f"/{profile.user_id}").status_code == 429


def test_the_batch_endpoint_has_its_own_tighter_budget(api_client, profile):
    """One batch request is a much bigger read than one lookup."""
    with override_settings(
        STAPEL_PROFILES={"PROFILES_BATCH_RATE": "1/min", "PROFILES_LOOKUP_RATE": "100/min"}
    ):
        assert _batch(api_client, [profile.user_id]).status_code == 200
        assert _batch(api_client, [profile.user_id]).status_code == 429
        # The single-lookup budget is untouched by the batch one.
        assert api_client.get(f"/{profile.user_id}").status_code == 200


def test_one_callers_budget_is_not_anothers(anon_client, authed_client, profile):
    with override_settings(STAPEL_PROFILES={"PROFILES_LOOKUP_RATE": "1/min"}):
        assert anon_client.get(f"/{profile.user_id}").status_code == 200
        assert anon_client.get(f"/{profile.user_id}").status_code == 429
        # A different (authenticated) caller still gets their own budget.
        assert authed_client.get(f"/{profile.user_id}").status_code == 200


def test_a_host_may_switch_the_limit_off(api_client, profile):
    with override_settings(STAPEL_PROFILES={"PROFILES_LOOKUP_RATE": None}):
        for _ in range(5):
            assert api_client.get(f"/{profile.user_id}").status_code == 200


# ── Referrer policy ──────────────────────────────────────────────────


def test_profile_responses_declare_a_restrictive_referrer_policy(api_client, profile):
    resp = api_client.get(f"/{profile.user_id}")
    assert resp["Referrer-Policy"] == "no-referrer"
    assert _batch(api_client, [profile.user_id])["Referrer-Policy"] == "no-referrer"


def test_referrer_policy_is_configuration(api_client, profile):
    with override_settings(STAPEL_PROFILES={"PROFILES_REFERRER_POLICY": "same-origin"}):
        assert api_client.get(f"/{profile.user_id}")["Referrer-Policy"] == "same-origin"
    with override_settings(STAPEL_PROFILES={"PROFILES_REFERRER_POLICY": ""}):
        assert "Referrer-Policy" not in api_client.get(f"/{profile.user_id}")
