"""API tests for relationship endpoints (follow/unfollow/block/unblock/lists)."""

import uuid

import pytest

from stapel_profiles.errors import (
    ERR_400_CANNOT_BLOCK_SELF,
    ERR_400_CANNOT_FOLLOW_SELF,
    ERR_404_PROFILE_NOT_FOUND,
)
from stapel_profiles.models import Profile, RelationshipStatus, UserRelationship


@pytest.fixture
def other_profile(other_user):
    return Profile.objects.create(user_id=other_user.id, avatar_source="url", avatar="https://example.com/other.png")


@pytest.mark.django_db
class TestFollow:
    def test_requires_auth(self, api_client, other_user):
        resp = api_client.post(f"/{other_user.id}/follow")
        assert resp.status_code in (401, 403)

    def test_follow_creates_relationship(self, authed_client, user, other_profile, other_user):
        resp = authed_client.post(f"/{other_user.id}/follow")
        assert resp.status_code == 200, resp.content
        assert resp.json() == {"success": True, "status": "following"}
        rel = UserRelationship.objects.get(
            follower_id=user.id, following_id=other_user.id
        )
        assert rel.status == RelationshipStatus.FOLLOWING

    def test_follow_is_idempotent(self, authed_client, user, other_profile, other_user):
        authed_client.post(f"/{other_user.id}/follow")
        resp = authed_client.post(f"/{other_user.id}/follow")
        assert resp.status_code == 200
        assert UserRelationship.objects.filter(follower_id=user.id).count() == 1

    def test_cannot_follow_self(self, authed_client, user):
        Profile.objects.create(user_id=user.id)
        resp = authed_client.post(f"/{user.id}/follow")
        assert resp.status_code == 400
        assert resp.json()["localizable_error"] == ERR_400_CANNOT_FOLLOW_SELF

    def test_follow_unknown_profile_404(self, authed_client):
        resp = authed_client.post(f"/{uuid.uuid4()}/follow")
        assert resp.status_code == 404
        assert resp.json()["localizable_error"] == ERR_404_PROFILE_NOT_FOUND


@pytest.mark.django_db
class TestUnfollow:
    def test_requires_auth(self, api_client, other_user):
        resp = api_client.post(f"/{other_user.id}/unfollow")
        assert resp.status_code in (401, 403)

    def test_unfollow_removes_relationship(self, authed_client, user, other_profile, other_user):
        authed_client.post(f"/{other_user.id}/follow")
        resp = authed_client.post(f"/{other_user.id}/unfollow")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "status": "neutral"}
        assert not UserRelationship.objects.filter(
            follower_id=user.id, following_id=other_user.id
        ).exists()

    def test_unfollow_does_not_unblock(self, authed_client, user, other_profile, other_user):
        authed_client.post(f"/{other_user.id}/block")
        resp = authed_client.post(f"/{other_user.id}/unfollow")
        assert resp.status_code == 200
        assert resp.json()["status"] == "blocked"
        rel = UserRelationship.objects.get(
            follower_id=user.id, following_id=other_user.id
        )
        assert rel.status == RelationshipStatus.BLOCKED

    def test_unfollow_never_followed_is_noop(self, authed_client, other_user):
        resp = authed_client.post(f"/{other_user.id}/unfollow")
        assert resp.status_code == 200
        assert resp.json()["status"] == "neutral"
        assert UserRelationship.objects.count() == 0


@pytest.mark.django_db
class TestBlockUnblock:
    def test_block_requires_auth(self, api_client, other_user):
        resp = api_client.post(f"/{other_user.id}/block")
        assert resp.status_code in (401, 403)

    def test_block_creates_relationship(self, authed_client, user, other_user):
        resp = authed_client.post(f"/{other_user.id}/block")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "status": "blocked"}
        rel = UserRelationship.objects.get(
            follower_id=user.id, following_id=other_user.id
        )
        assert rel.status == RelationshipStatus.BLOCKED

    def test_block_overrides_follow(self, authed_client, user, other_profile, other_user):
        authed_client.post(f"/{other_user.id}/follow")
        resp = authed_client.post(f"/{other_user.id}/block")
        assert resp.status_code == 200
        rel = UserRelationship.objects.get(
            follower_id=user.id, following_id=other_user.id
        )
        assert rel.status == RelationshipStatus.BLOCKED

    def test_cannot_block_self(self, authed_client, user):
        resp = authed_client.post(f"/{user.id}/block")
        assert resp.status_code == 400
        assert resp.json()["localizable_error"] == ERR_400_CANNOT_BLOCK_SELF

    def test_unblock_removes_block(self, authed_client, user, other_user):
        authed_client.post(f"/{other_user.id}/block")
        resp = authed_client.post(f"/{other_user.id}/unblock")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "status": "neutral"}
        assert UserRelationship.objects.count() == 0

    def test_unblock_does_not_touch_follow(self, authed_client, user, other_profile, other_user):
        authed_client.post(f"/{other_user.id}/follow")
        resp = authed_client.post(f"/{other_user.id}/unblock")
        assert resp.status_code == 200
        assert resp.json()["status"] == "following"


@pytest.mark.django_db
class TestRelationshipStatus:
    def test_requires_auth(self, api_client, other_user):
        resp = api_client.get(f"/{other_user.id}/relationship")
        assert resp.status_code in (401, 403)

    def test_neutral_when_no_relationship(self, authed_client, other_user):
        resp = authed_client.get(f"/{other_user.id}/relationship")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(other_user.id)
        assert data["status"] == "neutral"

    def test_following_status(self, authed_client, other_profile, other_user):
        authed_client.post(f"/{other_user.id}/follow")
        resp = authed_client.get(f"/{other_user.id}/relationship")
        assert resp.status_code == 200
        assert resp.json()["status"] == "following"


@pytest.mark.django_db
class TestRelationshipLists:
    def test_followers_requires_auth(self, api_client):
        assert api_client.get("/me/followers").status_code in (401, 403)

    def test_following_requires_auth(self, api_client):
        assert api_client.get("/me/following").status_code in (401, 403)

    def test_blocked_requires_auth(self, api_client):
        assert api_client.get("/me/blocked").status_code in (401, 403)

    def test_followers_list(self, authed_client, user, other_user):
        UserRelationship.objects.create(
            follower_id=other_user.id,
            following_id=user.id,
            status=RelationshipStatus.FOLLOWING,
        )
        resp = authed_client.get("/me/followers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["followers"] == [str(other_user.id)]

    def test_following_list(self, authed_client, user, other_profile, other_user):
        authed_client.post(f"/{other_user.id}/follow")
        resp = authed_client.get("/me/following")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["following"] == [str(other_user.id)]

    def test_blocked_list_returns_public_profiles(
        self, authed_client, user, other_profile, other_user
    ):
        authed_client.post(f"/{other_user.id}/block")
        resp = authed_client.get("/me/blocked")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["user_id"] == str(other_user.id)
        assert data[0]["avatar"] == "https://example.com/other.png"
        # Public serializer: no private settings in the payload.
        assert "email_messages" not in data[0]

    def test_empty_lists(self, authed_client):
        assert authed_client.get("/me/followers").json()["count"] == 0
        assert authed_client.get("/me/following").json()["count"] == 0
        assert authed_client.get("/me/blocked").json() == []
