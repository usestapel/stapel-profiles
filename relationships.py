"""The block store, and the one question a server needs to ask it.

Until 0.16.0 this module owned every block in the fleet (``UserRelationship``
with a ``blocked`` status, ``POST .../<user_id>/block``, ``me/blocked``) and
published no way for a *server* to consult one. Every block in every product
was therefore enforced by a client hiding a button: the blocked party's own
app declined to show the "message" control, and anything that spoke to the
API directly — another client, a script, a curl — was not blocked at all.
:func:`blocked_pairs` is the missing half, and ``profiles.relationships``
(``functions.relationships``) is its comm form.

Directionality — what is stored, what is answered
-------------------------------------------------
A block is **asymmetric as an intent** and **symmetric as an effect**, and
this module keeps both facts in the one place each belongs:

* **Stored: the intent.** ``UserRelationship(follower_id=blocker,
  following_id=blocked, status="blocked")`` — one row, one direction, one
  author. The write side needs it (my unblock may only remove *my* block;
  if A unblocks B while B still blocks A, the pair stays blocked), the
  owner's own screen needs it (``me/blocked`` is a list of people *I* chose),
  and GDPR needs it (the row names two people, and the receipt counts each
  direction separately).
* **Answered: the effect.** A caller asking "may these two reach each other"
  gets one boolean per pair with **no direction in it**. Enforcement is
  symmetric because a block that only stopped one arrow would be a block in
  name only: if A blocks B, B must not receive A's messages either, or B's
  inbox becomes a channel A can still use — and A's own act would have
  handed B a reason to notice.

Answering the effect is also what makes non-disclosure *structural* rather
than a rule every caller has to remember. There is no field in this answer
that could name a blocker, so no consumer can accidentally render one, and
no consumer needs a policy about which half of the pair may be told what.
The one place direction remains readable is the blocker's own authenticated
surface (``GET me/blocked``), which is their own data.

What a block does NOT do
------------------------
It does not delete anything belonging to the other party, and it never
deletes history: no message, no thread, no listing, no review, and not the
counterparty's own follow row. This module deletes exactly one thing on
unblock — the caller's own block edge — and nothing at all on block. A
product that wants a blocked conversation to disappear from a list filters
its own view with :func:`blocked_pairs`; it does not ask this module to
erase the past (stapel-classified's rule, and the same one stapel-chat is
building against).
"""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

#: The relationship status a block is stored as.
BLOCKED = "blocked"


class MalformedUserId(ValueError):
    """A pair carried something that cannot name a user.

    Raised rather than answered "not blocked": this module cannot check an
    id it cannot parse, and *unknown* must not read as *allowed* on a path
    whose whole purpose is enforcement. The caller (stapel-classified's
    ``BLOCK_ENFORCEMENT``) turns a raised check into a 503, which is the
    fail-closed outcome.
    """


class TooManyPairs(ValueError):
    """More pairs than :setting:`PROFILES_PAIRS_MAX` in one call.

    Refused, never truncated — the same rule ``POST .../batch`` follows. A
    silently short answer would report the dropped pairs as *allowed*, which
    is precisely the wrong direction to be wrong in.
    """


def _as_user_id(value) -> str:
    """Normalise one id, or raise :class:`MalformedUserId`."""
    text = str(value or "").strip()
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError, TypeError) as exc:
        raise MalformedUserId(f"not a user id: {value!r}") from exc


def normalise_pairs(pairs) -> list[tuple[str, str]]:
    """The caller's pairs, de-duplicated, in the order they were asked.

    A pair of one person with themselves is dropped: nobody can block
    themselves (``error.400.cannot_block_self``, and a DB check constraint
    behind it), so the question has one answer and it costs no query.
    """
    wanted: list[tuple[str, str]] = []
    seen: set[frozenset] = set()
    for pair in pairs or []:
        try:
            first, second = pair
        except (TypeError, ValueError) as exc:
            raise MalformedUserId(f"not a pair: {pair!r}") from exc
        left, right = _as_user_id(first), _as_user_id(second)
        if left == right:
            continue
        key = frozenset((left, right))
        if key in seen:
            continue
        seen.add(key)
        wanted.append((left, right))
    return wanted


def blocked_pairs(pairs) -> list[tuple[str, str]]:
    """Which of ``pairs`` have a block between them, in EITHER direction.

    Returns the blocked pairs **in the order and orientation the caller
    asked them**, so a caller can match its own page back onto the answer
    without knowing anything about how the block is stored. Direction is not
    reported (see the module docstring): a pair is in the answer or it is
    not.

    One query, whatever the page size: every block row among the people in
    the request is read at once (the ``following_id, status`` /
    ``follower_id, status`` indexes on ``UserRelationship`` serve it), and
    the pairing happens in memory. The alternative — an OR of N pair
    predicates — grows a query per conversation on the screen.
    """
    from .conf import profiles_settings
    from .models import UserRelationship

    wanted = normalise_pairs(pairs)
    if not wanted:
        return []

    limit = int(profiles_settings.PROFILES_PAIRS_MAX)
    if len(wanted) > limit:
        raise TooManyPairs(
            f"profiles.relationships: {len(wanted)} pairs exceeds the "
            f"PROFILES_PAIRS_MAX ceiling of {limit}"
        )

    people = {person for pair in wanted for person in pair}
    rows = UserRelationship.objects.filter(
        status=BLOCKED, follower_id__in=people, following_id__in=people
    ).values_list("follower_id", "following_id")
    edges = {frozenset((str(a), str(b))) for a, b in rows}
    return [pair for pair in wanted if frozenset(pair) in edges]


def is_blocked(user_a, user_b) -> bool:
    """Whether a block stands between two people, in either direction."""
    return bool(blocked_pairs([(user_a, user_b)]))


# ── The write side ───────────────────────────────────────────────────
#
# Deliberately NOT published as comm Functions. ``profiles.set_display_name``
# exists because another module legitimately holds *authority* over a name
# (a workspace owner correcting a member on the roster) while profiles holds
# the data. A block has no such authority anywhere: it is the subject's own
# act about their own safety, and nothing in the fleet may place one on
# somebody's behalf. The write therefore stays on the authenticated HTTP
# edge, where the actor is the person themselves; siblings get the read.


def block(blocker_id, blocked_id) -> str:
    """Record that ``blocker_id`` no longer wants contact with ``blocked_id``.

    Idempotent, and destructive of nothing: it writes ONE row (the caller's
    own edge) and touches no data belonging to the other party — not their
    follow of the blocker, not any thread, not any listing.
    """
    from .models import RelationshipStatus, UserRelationship

    if str(blocker_id) == str(blocked_id):
        raise ValueError("a user cannot block themselves")
    relationship, _created = UserRelationship.objects.update_or_create(
        follower_id=blocker_id,
        following_id=blocked_id,
        defaults={"status": RelationshipStatus.BLOCKED},
    )
    return str(relationship.status)


def unblock(blocker_id, blocked_id) -> str:
    """Withdraw the caller's OWN block, and only that.

    Deletes the caller's block edge if there is one and returns whatever
    relationship remains between the two from the caller's side. A block the
    other person placed is theirs and survives — which is why the read is
    symmetric and this write is not.
    """
    from .models import RelationshipStatus, UserRelationship

    UserRelationship.objects.filter(
        follower_id=blocker_id,
        following_id=blocked_id,
        status=RelationshipStatus.BLOCKED,
    ).delete()
    remaining = (
        UserRelationship.objects.filter(
            follower_id=blocker_id, following_id=blocked_id
        )
        .values_list("status", flat=True)
        .first()
    )
    return str(remaining or RelationshipStatus.NEUTRAL)


def blocks_of(user_id) -> list:
    """The ids this user has blocked — their own list, their own data.

    The INCOMING direction has no accessor here on purpose: "who blocked me"
    is the one question this module must never answer to the person asking
    it about themselves.
    """
    from .models import RelationshipStatus, UserRelationship

    return list(
        UserRelationship.objects.filter(
            follower_id=user_id, status=RelationshipStatus.BLOCKED
        ).values_list("following_id", flat=True)
    )


__all__ = [
    "BLOCKED",
    "MalformedUserId",
    "TooManyPairs",
    "block",
    "blocked_pairs",
    "blocks_of",
    "is_blocked",
    "normalise_pairs",
    "unblock",
]
