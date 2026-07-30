"""The guest (anonymous session) surface of stapel-profiles.

With ``AUTH_ANONYMOUS`` on, a guest session is ``is_authenticated`` — so a
bare ``IsAuthenticated`` gate lets it through, and until this module the
source said nothing about whether that was wanted. ``views.py`` now states
the rule; these tests are what makes the statement load-bearing:

    a guest may **see** the social graph (own rows only, so: empty), and may
    **not write** to it.

The read half is the half that matters most. ``MyProfileView`` is on the live
guest path of a real consumer (meettoday: a guest types a display name at
``PATCH /me`` *before* joining a call), so a regression that closes it would
break a product in production, mid-call — not in review.
"""

import pytest

from stapel_core.django.api.permissions import (
    ANONYMOUS_ALLOWED,
    IsNotAnonymousUser,
)
from stapel_profiles import views
from stapel_profiles.models import Profile, RelationshipStatus, UserRelationship


@pytest.fixture
def guest(db):
    """A guest session's user — exactly what ``POST /auth/api/v1/anonymous/``
    mints: authenticated, with ``is_anonymous=True`` on the row."""
    from stapel_core.django.users.models import User

    return User.create_anonymous_user()


@pytest.fixture
def guest_client(api_client, guest):
    api_client.force_authenticate(user=guest)
    return api_client


@pytest.fixture
def other_profile(other_user):
    return Profile.objects.create(user_id=other_user.id)


# ---------------------------------------------------------------------------
# The guest path: a guest names themselves before joining a call
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGuestMayOwnAProfile:
    def test_guest_can_read_own_profile(self, guest_client, guest):
        resp = guest_client.get("/me")
        assert resp.status_code == 200, resp.content
        assert Profile.objects.filter(user_id=guest.id).exists()

    def test_guest_can_set_own_display_name(self, guest_client, guest):
        """The meettoday guest-name gate, verbatim."""
        resp = guest_client.patch("/me", {"display_name": "Гость Вася"}, format="json")
        assert resp.status_code == 200, resp.content
        assert Profile.objects.get(user_id=guest.id).display_name == "Гость Вася"

    def test_declared_allowed_in_the_source(self):
        assert views.MyProfileView.stapel_anonymous_access == ANONYMOUS_ALLOWED


# ---------------------------------------------------------------------------
# A guest may read the (necessarily empty) graph
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, expected",
    [
        ("/me/followers", {"followers": [], "count": 0}),
        ("/me/following", {"following": [], "count": 0}),
        ("/me/blocked", []),
    ],
)
def test_guest_reads_own_empty_graph(guest_client, path, expected):
    resp = guest_client.get(path)
    assert resp.status_code == 200, resp.content
    assert resp.json() == expected


@pytest.mark.django_db
def test_guest_reads_relationship_status_as_neutral(guest_client, other_user):
    resp = guest_client.get(f"/{other_user.id}/relationship")
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == RelationshipStatus.NEUTRAL


@pytest.mark.django_db
def test_guest_read_sees_only_own_rows(guest_client, user, other_user):
    """Someone else's follow must not show up in the guest's empty answer."""
    UserRelationship.objects.create(
        follower_id=user.id,
        following_id=other_user.id,
        status=RelationshipStatus.FOLLOWING,
    )
    assert guest_client.get("/me/following").json() == {"following": [], "count": 0}
    assert guest_client.get("/me/followers").json() == {"followers": [], "count": 0}


# ---------------------------------------------------------------------------
# A guest may not write to it
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["follow", "unfollow", "block", "unblock"])
def test_guest_cannot_write_the_graph(guest_client, other_profile, other_user, action):
    resp = guest_client.post(f"/{other_user.id}/{action}")
    assert resp.status_code == 403, resp.content
    assert not UserRelationship.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["follow", "unfollow", "block", "unblock"])
def test_registered_user_still_writes_the_graph(
    authed_client, other_profile, other_user, action
):
    """The gate is about *anonymous*, not about *authenticated* — the ordinary
    user must be unaffected by it."""
    resp = authed_client.post(f"/{other_user.id}/{action}")
    assert resp.status_code == 200, resp.content


def test_write_views_carry_the_permission_class():
    for view in (
        views.FollowView,
        views.UnfollowView,
        views.BlockView,
        views.UnblockView,
    ):
        assert IsNotAnonymousUser in view.permission_classes, view.__name__


def test_no_view_is_left_silent():
    """Every ``IsAuthenticated``-only view in this module has taken a position.

    The same question ``stapel_core.adoption`` E001/W002 asks a consumer's
    deployment, asked here, where it can be answered.
    """
    from rest_framework.permissions import IsAuthenticated
    from rest_framework.views import APIView

    from stapel_core.django.api.permissions import ANONYMOUS_DECLARATIONS

    silent = [
        name
        for name, obj in vars(views).items()
        if isinstance(obj, type)
        and issubclass(obj, APIView)
        and set(getattr(obj, "permission_classes", ()) or ()) == {IsAuthenticated}
        and getattr(obj, "stapel_anonymous_access", None) not in ANONYMOUS_DECLARATIONS
    ]
    assert silent == []
