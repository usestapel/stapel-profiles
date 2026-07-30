"""API tests for POST /batch — many public profiles in one request (#111).

The endpoint exists to kill two things at once: the per-tile fan-out (16
contacts = 16 requests) and the 404-per-missing-profile console noise. The
second is the load-bearing one, and most of the tests below are about it:
"this person never opened settings" is a normal state, and the answer has
to say so plainly without dressing it as a failure and without inventing a
placeholder profile for someone who never chose one.
"""

import uuid

import pytest
from django.test import override_settings

from stapel_profiles.errors import ERR_400_TOO_MANY_IDS
from stapel_profiles.models import Profile, RelationshipStatus, UserRelationship


def _post(client, ids):
    return client.post(
        "/batch", {"user_ids": [str(i) for i in ids]}, format="json"
    )


@pytest.mark.django_db
class TestBatchHappyPath:
    def test_resolves_many_profiles_in_one_call(self, api_client):
        ids = [uuid.uuid4() for _ in range(3)]
        for i, uid in enumerate(ids):
            Profile.objects.create(user_id=uid, display_name=f"User {i}")

        resp = _post(api_client, ids)

        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert [p["user_id"] for p in data["profiles"]] == [str(i) for i in ids]
        assert [p["display_name"] for p in data["profiles"]] == [
            "User 0",
            "User 1",
            "User 2",
        ]
        assert data["missing"] == []

    def test_response_order_follows_the_request(self, api_client):
        """A grid zips the answer back onto its tiles by position."""
        ids = [uuid.uuid4() for _ in range(4)]
        for i, uid in enumerate(ids):
            Profile.objects.create(user_id=uid, display_name=f"User {i}")
        asked = [ids[2], ids[0], ids[3], ids[1]]

        data = _post(api_client, asked).json()

        assert [p["user_id"] for p in data["profiles"]] == [str(i) for i in asked]

    def test_duplicate_ids_are_collapsed(self, api_client):
        uid = uuid.uuid4()
        Profile.objects.create(user_id=uid, display_name="Ada")

        data = _post(api_client, [uid, uid, uid]).json()

        assert len(data["profiles"]) == 1
        assert data["missing"] == []

    def test_empty_request_is_an_empty_answer_not_an_error(self, api_client):
        resp = _post(api_client, [])
        assert resp.status_code == 200, resp.content
        assert resp.json() == {"profiles": [], "missing": []}

    def test_payload_matches_the_single_profile_endpoint(self, api_client):
        """The batch must not be a second, subtly different profile shape."""
        uid = uuid.uuid4()
        Profile.objects.create(user_id=uid, display_name="Ada")

        single = api_client.get(f"/{uid}").json()
        batched = _post(api_client, [uid]).json()["profiles"][0]

        assert batched == single


@pytest.mark.django_db
class TestMissingIsNotAnError:
    """The whole point: a person with no profile row is not a failure."""

    def test_missing_profile_is_reported_not_raised(self, api_client):
        present, absent = uuid.uuid4(), uuid.uuid4()
        Profile.objects.create(user_id=present, display_name="Ada")

        resp = _post(api_client, [present, absent])

        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert [p["user_id"] for p in data["profiles"]] == [str(present)]
        assert data["missing"] == [str(absent)]

    def test_all_missing_is_still_a_200(self, api_client):
        ids = [uuid.uuid4() for _ in range(3)]

        resp = _post(api_client, ids)

        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["profiles"] == []
        assert data["missing"] == [str(i) for i in ids]

    def test_missing_carries_no_invented_profile(self, api_client):
        """A filled-in placeholder would be this service asserting a name
        for a person who never chose one. `missing` is bare ids only."""
        absent = uuid.uuid4()

        data = _post(api_client, [absent]).json()

        assert data["missing"] == [str(absent)]
        assert data["profiles"] == []

    def test_asked_and_not_asked_are_distinguishable(self, api_client):
        """`profiles` + `missing` cover exactly the requested set, so an id
        in neither list provably was not part of this request."""
        present, absent, never_asked = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        Profile.objects.create(user_id=present, display_name="Ada")

        data = _post(api_client, [present, absent]).json()

        answered = {p["user_id"] for p in data["profiles"]} | set(data["missing"])
        assert answered == {str(present), str(absent)}
        assert str(never_asked) not in answered


@pytest.mark.django_db
class TestBatchLimit:
    """Over the ceiling the request is refused — never silently truncated."""

    @override_settings(STAPEL_PROFILES={"PROFILES_BATCH_MAX_IDS": 2})
    def test_over_the_limit_is_refused(self, api_client):
        ids = [uuid.uuid4() for _ in range(3)]
        for uid in ids:
            Profile.objects.create(user_id=uid, display_name="x")

        resp = _post(api_client, ids)

        assert resp.status_code == 400, resp.content
        body = resp.json()
        assert body["localizable_error"] == ERR_400_TOO_MANY_IDS
        # Both numbers, so the caller can chunk without bisecting the limit.
        assert body["params"]["requested"] == 3
        assert body["params"]["limit"] == 2

    @override_settings(STAPEL_PROFILES={"PROFILES_BATCH_MAX_IDS": 2})
    def test_over_the_limit_returns_no_partial_answer(self, api_client):
        """Silent truncation would render the overflow as people who "have
        no profile" — a wrong answer delivered as a successful one."""
        ids = [uuid.uuid4() for _ in range(3)]
        for uid in ids:
            Profile.objects.create(user_id=uid, display_name="x")

        body = _post(api_client, ids).json()

        assert "profiles" not in body
        assert "missing" not in body

    @override_settings(STAPEL_PROFILES={"PROFILES_BATCH_MAX_IDS": 2})
    def test_exactly_the_limit_is_allowed(self, api_client):
        ids = [uuid.uuid4() for _ in range(2)]
        for uid in ids:
            Profile.objects.create(user_id=uid, display_name="x")

        resp = _post(api_client, ids)

        assert resp.status_code == 200, resp.content
        assert len(resp.json()["profiles"]) == 2

    @override_settings(STAPEL_PROFILES={"PROFILES_BATCH_MAX_IDS": 2})
    def test_limit_counts_the_list_as_submitted(self, api_client):
        """The ceiling bounds what the caller sends; it must not depend on
        how much of the payload happens to be redundant."""
        uid = uuid.uuid4()
        Profile.objects.create(user_id=uid, display_name="x")

        resp = _post(api_client, [uid, uid, uid])

        assert resp.status_code == 400, resp.content
        assert resp.json()["params"]["requested"] == 3


@pytest.mark.django_db
class TestBatchSocialFields:
    """Batched social fields must agree with the per-row ones, and must not
    cost a query per row."""

    def test_counts_match_the_single_endpoint(self, api_client):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        for uid in (a, b, c):
            Profile.objects.create(user_id=uid, display_name="x")
        UserRelationship.objects.create(
            follower_id=b, following_id=a, status=RelationshipStatus.FOLLOWING
        )
        UserRelationship.objects.create(
            follower_id=c, following_id=a, status=RelationshipStatus.FOLLOWING
        )
        UserRelationship.objects.create(
            follower_id=a, following_id=b, status=RelationshipStatus.FOLLOWING
        )

        batched = {
            p["user_id"]: p for p in _post(api_client, [a, b, c]).json()["profiles"]
        }

        assert batched[str(a)]["followers_count"] == 2
        assert batched[str(a)]["following_count"] == 1
        assert batched[str(b)]["followers_count"] == 1
        assert batched[str(c)]["followers_count"] == 0
        for uid in (a, b, c):
            assert batched[str(uid)] == api_client.get(f"/{uid}").json()

    def test_relationship_status_matches_the_single_endpoint(
        self, authed_client, user
    ):
        followed, neutral = uuid.uuid4(), uuid.uuid4()
        for uid in (followed, neutral):
            Profile.objects.create(user_id=uid, display_name="x")
        Profile.objects.create(user_id=user.id, display_name="me")
        UserRelationship.objects.create(
            follower_id=user.id,
            following_id=followed,
            status=RelationshipStatus.FOLLOWING,
        )

        batched = {
            p["user_id"]: p
            for p in _post(
                authed_client, [followed, neutral, user.id]
            ).json()["profiles"]
        }

        assert batched[str(followed)]["relationship_status"] == "following"
        assert batched[str(neutral)]["relationship_status"] == "neutral"
        assert batched[str(user.id)]["relationship_status"] == "self"

    def test_query_count_does_not_grow_with_the_page(
        self, api_client, django_assert_num_queries
    ):
        """The per-row social queries would make a 50-tile batch cost 150
        SQL round-trips — trading an HTTP fan-out for a database one."""
        few = [uuid.uuid4() for _ in range(2)]
        many = [uuid.uuid4() for _ in range(12)]
        for uid in few + many:
            Profile.objects.create(user_id=uid, display_name="x")

        _post(api_client, few)  # warm any lazy import/connection setup

        # Three grouped queries (profiles + two follow counts) for two
        # rows and for twelve alike; anonymous, so no relationship lookup.
        with django_assert_num_queries(3):
            _post(api_client, few)
        with django_assert_num_queries(3):
            _post(api_client, many)
