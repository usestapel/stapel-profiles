"""The public profile card — what a stranger may know about somebody.

``profiles.public_cards`` (``functions.public_cards``) answers, for a page of
user ids at once, the card every marketplace surface draws next to a person:
their display name, their avatar with the render metadata a UI needs to
reserve the box before the bytes land, when they joined, and — where a
deployment's profile carries one — what kind of seller they are.

The projection rule
-------------------
**A card may never carry more than the public projection.** The caller here
is a server (stapel-classified's seller card, stapel-chat's conversation
header), and a server is not an exemption: the person rendered on the other
end is a stranger to the person reading. So every field of a profile that
appears in a card is gated by ``PROFILES_PUBLIC_FIELDS`` — the same setting
that decides what ``GET .../<user_id>`` and ``POST .../batch`` expose — and a
host that hides the display name from public lookups hides it here too,
without knowing this function exists. Nothing that is not in the card's own
fixed key set can appear in a card at all: the shape is built key by key from
a frozen tuple (:data:`CARD_KEYS`), never by serializing a model, so a field
added to ``Profile`` tomorrow cannot leak through this path.

Two facts in the card have no counterpart in the HTTP public projection and
are therefore card-only, stated here rather than inherited:

* ``member_since`` — a **date**, not a timestamp. "Joined March 2024" is what
  a marketplace shows to establish that an account is not brand new; the
  exact second of registration is a behavioural fingerprint nobody needs, so
  it is coarsened here rather than at every consumer.
* ``seller_type`` — present only when this deployment's profile model
  actually carries the field (§66 made the profile a manifest), ``""``
  otherwise. It is a self-declared, publicly displayed trading capacity
  ("private"/"business"), which in most jurisdictions the buyer is entitled
  to see before contacting.

Degradation is data
-------------------
The avatar's render metadata comes from ``cdn.describe_many`` — the same
call, the same snapshot keys and the same ``meta_status``/``meta_reason``
vocabulary stapel-chat's attachments and stapel-classified's listing cards
use, so one picture has one answer everywhere in the fleet. That call may
fail, and when it does the card still answers: the ref is kept, the numbers
are ``null`` and ``meta_reason`` names what is missing. A conversation must
never fail to open because the CDN blinked.
"""
from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)

META_OK = "ok"
META_PARTIAL = "partial"
META_MISSING = "missing"

#: Every key a card carries, always present. A client never tests for a
#: field's existence (the stapel-chat attachment rule), and — read the other
#: way round — nothing outside this tuple can ever appear in a card.
CARD_KEYS = (
    "user_id",
    "display_name",
    "avatar",
    "member_since",
    "seller_type",
)

#: Every key an avatar object carries. Identical to the shape a chat
#: attachment and a classified listing image carry, because it is the same
#: CDN answering about the same kind of thing.
IMAGE_KEYS = (
    "mime",
    "ext",
    "bytes",
    "width",
    "height",
    "aspect",
    "square",
    "animated",
    "preview_b64",
    "preview_kind",
    "variants",
)

#: Why an avatar carries no render metadata, when it carries none.
REASON_CDN_UNAVAILABLE = "cdn_unavailable"
REASON_UNKNOWN_REF = "unknown_ref"
REASON_NOT_DESCRIBED = "not_described"
REASON_EXTERNAL_AVATAR = "external_avatar"
REASON_NOT_CDN_REF = "not_cdn_ref"


def existing_users(user_ids) -> set:
    """Of these ids, the ones that name a user this deployment knows about.

    The seam that makes "no profile row" tellable from "no such person".
    This module stores ``user_id`` as a bare UUID and keeps **no FK across
    modules** (MODULE.md) — that stays true: this is a READ of
    ``get_user_model()``, the reference every feature module is told to use
    (``stapel_core.django.users.models.AbstractStapelUser``), not a
    relation, not a migration, and not a second copy of anything.

    Deployment shapes and how this degrades:

    * Monolith — the auth user table itself. Exact answer.
    * Microservice — the shadow user table, filled by
      ``JWT_CREATE_USERS_FROM_TOKEN`` and by auth's ``user.created`` /
      ``user.updated`` projection (``stapel_auth.projection``). A user the
      shadow table has not heard of yet reads as unknown and gets the
      historical 404 — never worse than the pre-0.15.0 behaviour.

    A host whose user pk is not UUID-shaped (a swapped ``AUTH_USER_MODEL``
    over an integer pk) makes the lookup unanswerable rather than wrong: the
    empty set means "cannot vouch for anyone", i.e. the old 404.
    """
    if not user_ids:
        return set()
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError

    try:
        return set(
            get_user_model()
            ._default_manager.filter(pk__in=list(user_ids))
            .values_list("pk", flat=True)
        )
    except (ValueError, TypeError, ValidationError):
        return set()


def _is_user_id(value) -> bool:
    """Whether this string can name a user here (the pk is a UUID)."""
    import uuid

    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _visible_public_fields() -> set:
    from .conf import profiles_settings

    return set(profiles_settings.PROFILES_PUBLIC_FIELDS or [])


def _member_since(profile):
    """The join date as ``YYYY-MM-DD``, or ``None`` for a row never written."""
    created = getattr(profile, "created_at", None)
    if not created:
        return None
    return created.date().isoformat()


def _avatar_ref(profile):
    """``(ref, describe_it)`` for this profile's avatar, or ``(None, False)``.

    Applies the module's READ boundary (audit PROFILE-01) exactly as
    ``serializers.avatar_image`` does: a stored external URL that today's
    policy would refuse, and a "gravatar" value that is not an email hash,
    degrade to *no avatar* rather than being handed to a consumer. An old
    row is not evidence that today's policy allows it.
    """
    from .models import AvatarSource
    from .validators import is_gravatar_hash, is_safe_avatar_url

    value = getattr(profile, "avatar", None)
    if not value:
        return None, False
    source = getattr(profile, "avatar_source", None)
    if source == AvatarSource.CDN:
        return str(value), True
    if source == AvatarSource.URL:
        if not is_safe_avatar_url(value):
            logger.warning(
                "profiles: suppressed unsafe stored avatar URL for %s",
                getattr(profile, "user_id", None),
            )
            return None, False
        return str(value), False
    if source == AvatarSource.GRAVATAR:
        if not is_gravatar_hash(value):
            logger.warning(
                "profiles: suppressed non-hash gravatar avatar for %s",
                getattr(profile, "user_id", None),
            )
            return None, False
        return f"https://www.gravatar.com/avatar/{value}", False
    return str(value), False


def _image(ref: str, snapshot: dict | None, *, reason: str | None = None) -> dict:
    """One avatar object: the ref, plus whatever the CDN could tell us."""
    image = {"ref": str(ref), **{key: None for key in IMAGE_KEYS}}
    image["variants"] = []
    if not snapshot:
        image["meta_status"] = (
            META_MISSING if reason == REASON_UNKNOWN_REF else META_PARTIAL
        )
        image["meta_reason"] = reason
        return image
    for key in IMAGE_KEYS:
        if key in snapshot:
            image[key] = snapshot[key]
    image["variants"] = list(snapshot.get("variants") or [])
    image["meta_status"] = str(snapshot.get("meta_status") or META_OK)
    image["meta_reason"] = snapshot.get("meta_reason")
    return image


def _describe(refs: list[str]) -> tuple[dict, set, str | None]:
    """``cdn.describe_many`` over every CDN ref on the page, in one call.

    Returns ``(snapshots, missing, failure_reason)``. A failure is logged and
    reported as a reason, never raised: the card is what the caller is
    opening a conversation with.
    """
    from .conf import profiles_settings

    name = str(profiles_settings.PROFILES_CARD_MEDIA_FUNCTION or "")
    if not name or not refs:
        return {}, set(), REASON_CDN_UNAVAILABLE if refs else None

    from stapel_core.comm import call

    try:
        answer = call(name, {"refs": refs})
    except Exception:  # noqa: BLE001 — degradation is data, see the docstring
        logger.info("profiles: %r unavailable for avatar metadata", name, exc_info=True)
        return {}, set(), REASON_CDN_UNAVAILABLE
    if not isinstance(answer, dict):
        return {}, set(), REASON_CDN_UNAVAILABLE
    return (
        answer.get("items") or {},
        set(answer.get("missing") or []),
        None,
    )


def public_cards(user_ids: Iterable) -> dict:
    """``{"profiles": {user_id: card}, "missing": [user_id, ...]}``.

    Same three-way reading as ``POST .../batch``, for the same reason: a
    registered person who has never opened their profile is a **person**, and
    answering their card as absent is what left a live marketplace with no
    names anywhere. So an id resolves to one of

    * a card built from their row;
    * a card built from an unwritten profile (registered, typed nothing) —
      empty ``display_name``, no avatar, no ``member_since``;
    * ``missing`` — the id names nobody. Never an error.
    """
    from .models import get_profile_model

    wanted = list(dict.fromkeys(str(uid) for uid in user_ids if str(uid or "").strip()))
    if not wanted:
        return {"profiles": {}, "missing": []}

    Profile = get_profile_model()
    # An id that is not UUID-shaped cannot name anybody here, and asking the
    # database about it would fail the whole page over one malformed entry.
    # It is reported `missing`, which is exactly what it is.
    lookupable = [uid for uid in wanted if _is_user_id(uid)]
    rows = {
        str(p.user_id): p for p in Profile.objects.filter(user_id__in=lookupable)
    }

    unwritten = existing_users([uid for uid in lookupable if uid not in rows])
    unwritten = {str(uid) for uid in unwritten}

    profiles = {}
    missing = []
    to_describe: list[str] = []
    for uid in wanted:
        row = rows.get(uid)
        if row is None:
            if uid not in unwritten:
                missing.append(uid)
                continue
            row = Profile(user_id=uid)
        card, ref, describe_it = _card(uid, row)
        if describe_it and ref:
            to_describe.append(ref)
        profiles[uid] = card

    _attach_avatars(profiles, to_describe)
    return {"profiles": profiles, "missing": missing}


def _card(user_id: str, profile):
    """One card, built key by key from :data:`CARD_KEYS` — never serialized."""
    visible = _visible_public_fields()
    ref, describe_it = _avatar_ref(profile)
    if "avatar" not in visible:
        # The host hid avatars from public lookups; a card is a public
        # lookup wearing a different transport.
        ref, describe_it = None, False

    values = {
        "user_id": user_id,
        "display_name": (
            str(getattr(profile, "display_name", "") or "")
            if "display_name" in visible
            else ""
        ),
        # Carries the ref until _attach_avatars swaps in the full object; a
        # card with no avatar keeps `None`.
        "avatar": ref,
        "member_since": _member_since(profile),
        "seller_type": str(getattr(profile, "seller_type", "") or ""),
    }
    # Built key by key FROM the frozen tuple, not from the model and not from
    # whatever `values` happens to hold: a field added to Profile tomorrow
    # cannot reach a caller through this path.
    card = {key: values[key] for key in CARD_KEYS}
    return card, ref, describe_it


def _attach_avatars(profiles: dict, refs: list[str]) -> None:
    """Turn every card's avatar ref into the full render-metadata object."""
    cdn_refs = list(dict.fromkeys(refs))
    snapshots, unknown, failure = _describe(cdn_refs)

    for card in profiles.values():
        ref = card.get("avatar")
        if not ref:
            card["avatar"] = None
            continue
        if ref not in cdn_refs:
            # Not a CDN reference at all (an external URL, a gravatar link,
            # a storage key): the ref is renderable, the numbers are not
            # ours to know.
            card["avatar"] = _image(
                ref,
                None,
                reason=(
                    REASON_EXTERNAL_AVATAR
                    if str(ref).startswith("http")
                    else REASON_NOT_CDN_REF
                ),
            )
            continue
        if ref in snapshots:
            card["avatar"] = _image(ref, snapshots[ref])
        elif ref in unknown:
            card["avatar"] = _image(ref, None, reason=REASON_UNKNOWN_REF)
        else:
            card["avatar"] = _image(
                ref, None, reason=failure or REASON_NOT_DESCRIBED
            )


__all__ = [
    "CARD_KEYS",
    "IMAGE_KEYS",
    "META_MISSING",
    "META_OK",
    "META_PARTIAL",
    "existing_users",
    "public_cards",
]
