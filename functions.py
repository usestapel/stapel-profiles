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
