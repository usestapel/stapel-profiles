"""comm Function providers of the profiles module.

Registered from ``ProfilesConfig.ready()`` (``functions.register()`` is
idempotent). Other modules reach a name — read it, check it, write it —
without importing this package and without HTTP client code; the transport
is deployment configuration (``STAPEL_COMM``), so the same call works in a
monolith and in a split deployment where profiles is its own container::

    from stapel_core.comm import call

    call("profiles.set_display_name",
         {"user_id": str(user_id), "display_name": "Ada Lovelace"})
    # -> {"ok": True, "display_name": "Ada Lovelace", "reason": None}

    call("profiles.validate_display_name", {"display_name": "Ada"})
    # -> {"ok": True, "reason": None}

    call("profiles.display_names", {"user_ids": [str(a), str(b)]})
    # -> {"display_names": {"<a>": "Ada Lovelace"}}

    call("profiles.language", {"user_id": str(user_id)})
    # -> {"app_language": "en", "auto_detected_language": "ru"}

**Why a write is published at all.** The module that owns the *authority*
question owns the endpoint; the module that owns the *data* owns the write
and publishes it by name (`tasks/who-owns-the-name-write.md`). A workspace
owner correcting a member's name on the roster is workspaces' operation to
authorize — rank semantics ("only an owner renames an owner") live nowhere
else — and profiles' name to write. Same shape as ``billing.debit``, which
lets workspaces move credits in billing's ledger on workspaces' authority:
the comm plane is the trusted internal surface, the caller's edge already
did the authorization, and the owner enforces its own invariants. What
does NOT happen is a sibling resolving ``stapel_profiles.*`` symbols by
dotted path — that seam (stapel-workspaces 0.19.0) worked only where
profiles was co-mounted and answered a permanent 503 everywhere else.

**What the owner keeps.** Every invariant of a name stays here and runs on
every path into it: the canon (:func:`~stapel_profiles.validators.validate_display_name`),
the swap-aware model resolution (:func:`~stapel_profiles.models.get_profile_model`,
SWAP001 — a host that assembled its own extended Profile keeps its names
there), get-or-create semantics, and the ``profile.changed`` emission that
every downstream projection depends on.

**Failure style follows billing's:** refusals are *structural*
(``{"ok": False, "reason": ...}``), never exceptions — an invalid name is
an expected outcome of a user typing, not an error. ``reason`` is the
trailing name of this module's own error keys (``display_name_emoji`` →
``error.400.display_name_emoji``) so a caller re-declaring those keys maps
one to one and no second, differently-strict name vocabulary is invented.
Delivery is at-least-once and the write is last-write-wins on one field, so
no idempotency key is required (unlike ``billing.debit``, where a repeat is
a second debit).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from stapel_core.comm import register_function

logger = logging.getLogger(__name__)

SET_DISPLAY_NAME = "profiles.set_display_name"
VALIDATE_DISPLAY_NAME = "profiles.validate_display_name"
DISPLAY_NAMES = "profiles.display_names"
LANGUAGE = "profiles.language"
RELATIONSHIPS = "profiles.relationships"
PUBLIC_CARDS = "profiles.public_cards"

#: Structural refusal reasons that are NOT a bad name: the deployment's
#: active profile model carries no ``display_name`` at all (§66 moved it out
#: of the hard core, so a project without the identity preset has none).
#: There is no canonical name to correct in such a deployment; a caller
#: answers the same "profiles cannot serve this" it answers for an absent
#: module, never a 200 over a write that did not happen.
REASON_NO_DISPLAY_NAME_FIELD = "no_display_name_field"

# Single source of truth for the payload contracts: the committed schema
# files (the schemas/ autoloader registers them too; passing them at
# register_function() time makes validation work even without it).
_SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas" / "functions"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMAS_DIR / f"{name}.json").read_text())


SET_DISPLAY_NAME_SCHEMA = _load_schema(SET_DISPLAY_NAME)
VALIDATE_DISPLAY_NAME_SCHEMA = _load_schema(VALIDATE_DISPLAY_NAME)
DISPLAY_NAMES_SCHEMA = _load_schema(DISPLAY_NAMES)
LANGUAGE_SCHEMA = _load_schema(LANGUAGE)
RELATIONSHIPS_SCHEMA = _load_schema(RELATIONSHIPS)
PUBLIC_CARDS_SCHEMA = _load_schema(PUBLIC_CARDS)


def _reason_of(error_key: str) -> str:
    """``error.400.display_name_emoji`` -> ``display_name_emoji``.

    The wire reason is the key's trailing name rather than the whole key so
    the result stays a *structural* verdict (billing's shape) while still
    round-tripping losslessly: a caller that re-declares these keys rebuilds
    ``error.400.{reason}`` and refuses in this module's own vocabulary.
    """
    return ".".join(error_key.split(".")[2:])


def _check(display_name: str) -> str | None:
    """The canon's verdict on *display_name*: a reason, or ``None`` if fine."""
    from stapel_core.django.api.errors import StapelValidationError

    from .validators import validate_display_name

    try:
        validate_display_name(display_name)
    except StapelValidationError as exc:
        return _reason_of(exc.error_key)
    return None


def validate_display_name_fn(payload: dict) -> dict:
    """Provider for ``profiles.validate_display_name``.

    Payload: ``{"display_name": str}``
    Returns: ``{"ok": bool, "reason": str | None}``

    The canon on its own, with no write and no side effect — for a caller
    that stores a name of its own that will be *displayed* next to the ones
    kept here (stapel-workspaces' ``WorkspaceInvitation.display_name_hint``
    is the first: the invitee has no profile row yet, so there is nothing
    here to write, but the two must not disagree about what a name may
    contain). Publishing the check by name is what stops that caller from
    growing a second, weaker regex — the drift this module's llms.txt names
    as the mistake.

    The empty string is valid: clearing a name is not a name violation, and
    the canon short-circuits on it before the two-character minimum.
    """
    reason = _check((payload.get("display_name") or "").strip())
    return {"ok": reason is None, "reason": reason}


def set_display_name(payload: dict) -> dict:
    """Provider for ``profiles.set_display_name``.

    Payload: ``{"user_id": str, "display_name": str}``
    Returns: ``{"ok": bool, "display_name": str | None, "reason": str | None}``

    Creates the profile row when there is none: the caller knows the account
    exists (it holds an authority relation to it), and "has not opened the
    profile screen yet" must not make an admin's correction unwritable.

    Publishes ``profile.changed`` afterwards, as this module's llms.txt
    demands of ANY write that does not go through its serializers — every
    consumer of that event (search projections, chat rosters, a host's
    ``User.first_name`` mirror) desyncs silently otherwise. The publisher is
    best-effort and savepoint-isolated; the name is saved either way.
    """
    from django.core.exceptions import FieldDoesNotExist

    from .events import publish_profile_changed
    from .models import get_profile_model

    display_name = (payload.get("display_name") or "").strip()
    reason = _check(display_name)
    if reason is not None:
        return {"ok": False, "display_name": None, "reason": reason}

    Profile = get_profile_model()
    try:
        Profile._meta.get_field("display_name")
    except FieldDoesNotExist:
        logger.warning(
            "%s: the active profile model %s has no display_name field — this "
            "deployment holds no canonical name to write",
            SET_DISPLAY_NAME,
            Profile.__name__,
        )
        return {
            "ok": False,
            "display_name": None,
            "reason": REASON_NO_DISPLAY_NAME_FIELD,
        }

    profile, _created = Profile.objects.get_or_create(user_id=payload["user_id"])
    profile.display_name = display_name
    profile.save(update_fields=["display_name", "updated_at"])
    publish_profile_changed(profile)
    return {"ok": True, "display_name": display_name, "reason": None}


def display_names(payload: dict) -> dict:
    """Provider for ``profiles.display_names``.

    Payload: ``{"user_ids": [str, ...]}``
    Returns: ``{"display_names": {user_id: display_name}}``

    The comm form of the ``POST /profiles/api/v1/batch`` read, narrowed to
    the one field a roster needs. Same "missing is not invented" contract as
    ``ProfileBatchResponse``: an id with no profile row, or with an empty
    ``display_name``, is simply ABSENT from the map — never a placeholder,
    so the caller can tell "no name here" from "a name that is the empty
    string" and fall back to whatever it holds locally.

    Swap-aware for the same reason the write is: a host that put its names
    on its own extended Profile would otherwise be told nobody has a name.
    """
    ids = list(dict.fromkeys(str(uid) for uid in payload.get("user_ids") or []))
    if not ids:
        return {"display_names": {}}

    from .models import get_profile_model

    Profile = get_profile_model()
    try:
        Profile._meta.get_field("display_name")
    except Exception:
        return {"display_names": {}}

    rows = Profile.objects.filter(user_id__in=ids).values_list(
        "user_id", "display_name"
    )
    return {
        "display_names": {
            str(uid): name for uid, name in rows if (name or "").strip()
        }
    }


def language(payload: dict) -> dict:
    """Provider for ``profiles.language``.

    Payload: ``{"user_id": str}``
    Returns: ``{"app_language": str | None, "auto_detected_language": str | None}``

    The recipient's own answer to "which language do you read in", asked at
    the moment somebody is about to write to them. Two different facts, and
    a caller ranks them differently: ``app_language`` is a language the user
    CHOSE (the picker in profiles' language settings), ``auto_detected_language``
    is one merely OBSERVED from an Accept-Language header. Both are ``None``
    when absent — including for a user_id with no profile row at all, which
    is the normal state of an invitee who has not accepted yet.

    Published because the alternative — every sibling keeping a mirror of
    this field, fed by an event — is the shape that failed: stapel-notifications
    mirrored ``app_language`` into ``UserNotificationSettings`` and the table
    stood empty for the mirror's whole lifetime (meettoday sandbox, 2026-08:
    0 rows for 66 profiles), so every recipient silently got the SENDER's
    language. A mirror cannot tell "the user chose nothing" from "the sync
    never ran"; a call can — it either answers or raises.

    Swap-aware like the rest of this module's surface: a host that assembled
    its own extended profile keeps the language there. A profile model
    carrying neither field answers null/null rather than raising — "this
    deployment holds no language for anybody" is a legitimate answer, and
    the caller's fallback chain handles it.
    """
    from .models import get_profile_model

    Profile = get_profile_model()
    fields = {f.name for f in Profile._meta.get_fields()}
    wanted = [f for f in ("app_language", "auto_detected_language") if f in fields]
    if not wanted:
        logger.warning(
            "%s: the active profile model %s carries no language field — "
            "this deployment holds no stated language for anybody",
            LANGUAGE, Profile.__name__,
        )
        return {"app_language": None, "auto_detected_language": None}

    row = (
        Profile.objects.filter(user_id=payload["user_id"])
        .values(*wanted)
        .first()
    ) or {}
    # app_language is a FK to Language, whose PK *is* the code — .values()
    # yields the code itself, which is what the wire carries (same shape as
    # the profile.changed payload).
    return {
        "app_language": (row.get("app_language") or None),
        "auto_detected_language": ((row.get("auto_detected_language") or "").strip() or None),
    }


def relationships(payload: dict) -> dict:
    """Provider for ``profiles.relationships`` — the fleet's block check.

    Payload: ``{"pairs": [[user_a, user_b], ...]}``
    Returns: ``{"blocked": [[user_a, user_b], ...]}``

    Which of the asked pairs have a block between them **in either
    direction**, echoed in the order and orientation they were asked. Batch,
    because the caller is checking a page of conversations, and one query
    serves the whole page.

    **Direction is not in the answer, and cannot be.** A block is stored as
    an intent (who blocked whom) and answered as an effect (these two must
    not reach each other) — see :mod:`stapel_profiles.relationships`. The
    blocked party must never learn they are blocked, and the way to hold that
    property is to make it structural: there is no field here that could name
    a blocker, so no consumer can render one and no consumer needs a policy
    about who may be told what.

    **Raises rather than lies.** Over ``PROFILES_PAIRS_MAX`` pairs, or an id
    that cannot name a user, this raises — the caller (stapel-classified's
    ``BLOCK_ENFORCEMENT``, stapel-chat's send path) turns a failed check into
    a 503 rather than into contact. Refusals here are NOT structural, unlike
    the display-name providers: an invalid name is a user typing, but an
    uncheckable block is an outage, and an outage is not consent.
    """
    from .relationships import blocked_pairs

    return {"blocked": [list(pair) for pair in blocked_pairs(payload.get("pairs"))]}


def public_cards(payload: dict) -> dict:
    """Provider for ``profiles.public_cards`` — the person, as a stranger sees them.

    Payload: ``{"user_ids": [str, ...]}``
    Returns: ``{"profiles": {user_id: card}, "missing": [user_id, ...]}``

    where a card is exactly ``{user_id, display_name, avatar, member_since,
    seller_type}`` — the marketplace's PUBLIC projection and never more,
    gated by the same ``PROFILES_PUBLIC_FIELDS`` policy the public HTTP
    lookups obey (:mod:`stapel_profiles.cards`). ``avatar`` is ``null`` or the
    fleet's one image object: the ref plus ``cdn.describe_many`` render
    metadata, with ``meta_status``/``meta_reason`` naming any gap.

    Same three-way reading as ``POST .../batch``: a card for a person with a
    row, a card for a registered person who has typed nothing, and
    ``missing`` for an id that names nobody. Never an error, never a
    placeholder name.
    """
    from .cards import public_cards as build_cards

    return build_cards(payload.get("user_ids") or [])


def register() -> None:
    """Register this module's Function providers.

    Idempotent: re-registering the *same* handler object is a no-op, so
    AppConfig.ready() may run more than once without raising.
    """
    register_function(
        SET_DISPLAY_NAME, set_display_name, schema=SET_DISPLAY_NAME_SCHEMA
    )
    register_function(
        VALIDATE_DISPLAY_NAME,
        validate_display_name_fn,
        schema=VALIDATE_DISPLAY_NAME_SCHEMA,
    )
    register_function(DISPLAY_NAMES, display_names, schema=DISPLAY_NAMES_SCHEMA)
    register_function(LANGUAGE, language, schema=LANGUAGE_SCHEMA)
    register_function(RELATIONSHIPS, relationships, schema=RELATIONSHIPS_SCHEMA)
    register_function(PUBLIC_CARDS, public_cards, schema=PUBLIC_CARDS_SCHEMA)
