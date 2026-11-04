"""profiles.social_graph — whom a person follows, and whom a feed must hide.

Load-bearing properties:

* ``blocked`` is undirected and complete: a block placed by either side
  hides the other, the list names no blocker, and it is never cut;
* ``following`` never carries a blocked id and is cut at the ceiling with
  ``truncated: true`` — a short following list only narrows a feed;
* an id that cannot name a user raises (the caller's 503), never an empty
  graph that would read as "follows nobody, blocks nobody".
"""
import uuid

import pytest
from django.test import override_settings

from stapel_core.comm import call, function_registry
from stapel_profiles import functions, relationships
from stapel_profiles.models import RelationshipStatus, UserRelationship


@pytest.fixture(autouse=True)
def registered():
    function_registry.clear()
    functions.register()
    yield
    function_registry.clear()


def _relate(a, b, status):
    UserRelationship.objects.create(follower_id=a, following_id=b, status=status)


def _graph(user_id, **extra):
    return call(functions.SOCIAL_GRAPH, {"user_id": str(user_id), **extra})


@pytest.mark.django_db
class TestSocialGraph:
    def test_a_stranger_has_an_empty_graph(self):
        assert _graph(uuid.uuid4()) == {"following": [], "blocked": [], "truncated": False}

    def test_following_lists_followed_ids_newest_first(self):
        me, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        _relate(me, b, RelationshipStatus.FOLLOWING)
        _relate(me, c, RelationshipStatus.FOLLOWING)
        assert _graph(me)["following"] == [str(c), str(b)]

    def test_a_follower_is_not_followed(self):
        me, fan = uuid.uuid4(), uuid.uuid4()
        _relate(fan, me, RelationshipStatus.FOLLOWING)
        assert _graph(me)["following"] == []

    def test_neutral_rows_are_not_follows(self):
        me, b = uuid.uuid4(), uuid.uuid4()
        _relate(me, b, RelationshipStatus.NEUTRAL)
        assert _graph(me) == {"following": [], "blocked": [], "truncated": False}

    @pytest.mark.parametrize("direction", ["mine", "theirs"])
    def test_a_block_in_either_direction_is_listed(self, direction):
        me, other = uuid.uuid4(), uuid.uuid4()
        if direction == "mine":
            _relate(me, other, RelationshipStatus.BLOCKED)
        else:
            _relate(other, me, RelationshipStatus.BLOCKED)
        assert _graph(me)["blocked"] == [str(other)]

    def test_a_blocked_id_never_rides_in_following(self):
        """They follow me and I block them; I follow them and they block me."""
        me, blocker = uuid.uuid4(), uuid.uuid4()
        _relate(me, blocker, RelationshipStatus.FOLLOWING)
        _relate(blocker, me, RelationshipStatus.BLOCKED)
        graph = _graph(me)
        assert graph["following"] == []
        assert graph["blocked"] == [str(blocker)]

    def test_the_answer_names_no_blocker(self):
        """Identical whichever side placed the block."""
        me, other = uuid.uuid4(), uuid.uuid4()
        _relate(me, other, RelationshipStatus.BLOCKED)
        mine = _graph(me)
        UserRelationship.objects.all().delete()
        _relate(other, me, RelationshipStatus.BLOCKED)
        assert _graph(me) == mine
        assert set(mine) == {"following", "blocked", "truncated"}

    @override_settings(STAPEL_PROFILES={"PROFILES_FOLLOWING_MAX": 2})
    def test_following_is_cut_at_the_ceiling_and_says_so(self):
        me = uuid.uuid4()
        for _ in range(3):
            _relate(me, uuid.uuid4(), RelationshipStatus.FOLLOWING)
        graph = _graph(me)
        assert len(graph["following"]) == 2
        assert graph["truncated"] is True

    @override_settings(STAPEL_PROFILES={"PROFILES_FOLLOWING_MAX": 3})
    def test_exactly_the_ceiling_is_not_truncated(self):
        me = uuid.uuid4()
        for _ in range(3):
            _relate(me, uuid.uuid4(), RelationshipStatus.FOLLOWING)
        graph = _graph(me)
        assert len(graph["following"]) == 3
        assert graph["truncated"] is False

    def test_the_caller_limit_narrows_below_the_ceiling(self):
        me = uuid.uuid4()
        for _ in range(3):
            _relate(me, uuid.uuid4(), RelationshipStatus.FOLLOWING)
        graph = _graph(me, limit=1)
        assert len(graph["following"]) == 1
        assert graph["truncated"] is True

    @override_settings(STAPEL_PROFILES={"PROFILES_FOLLOWING_MAX": 1})
    def test_the_caller_limit_cannot_widen_the_ceiling(self):
        me = uuid.uuid4()
        for _ in range(2):
            _relate(me, uuid.uuid4(), RelationshipStatus.FOLLOWING)
        graph = _graph(me, limit=100)
        assert len(graph["following"]) == 1
        assert graph["truncated"] is True

    @override_settings(STAPEL_PROFILES={"PROFILES_FOLLOWING_MAX": 1})
    def test_blocked_is_never_cut(self):
        me = uuid.uuid4()
        others = [uuid.uuid4() for _ in range(3)]
        for other in others:
            _relate(other, me, RelationshipStatus.BLOCKED)
        assert sorted(_graph(me)["blocked"]) == sorted(str(o) for o in others)

    def test_a_malformed_id_raises_rather_than_answering_empty(self):
        with pytest.raises(relationships.MalformedUserId):
            relationships.social_graph("not-a-user")

    def test_the_payload_schema_refuses_extra_keys(self):
        with pytest.raises(Exception):
            call(functions.SOCIAL_GRAPH, {"user_id": str(uuid.uuid4()), "extra": 1})
