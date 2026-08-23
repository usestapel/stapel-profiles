"""Action subscriptions of the profiles module.

Handlers must be idempotent: delivery is at-least-once (outbox retries,
broker redelivery).

The GDPR pair below — ``gdpr.erasure.requested`` and ``gdpr.owner.probe`` —
lives in this one file on purpose. The probe is answered from the same
subscriber that erases, so ``gdpr.owner.alive`` is evidence that the
erasure path is *consumed*, not merely that a container is deployed
(stapel-gdpr MODULE.md, "Erasure parts", option 2).
"""
import logging

from django.core.exceptions import ValidationError

from stapel_core.comm import on_action

from .erasure import GDPR_OWNER, GDPR_SUBJECT_TYPES

logger = logging.getLogger(__name__)

ERASURE_REQUESTED_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "gdpr.erasure.requested",
    "type": "object",
    "required": ["correlation_id", "subject_type", "subject_key"],
    "properties": {
        "request_id": {"type": "integer"},
        "correlation_id": {"type": "string"},
        "subject_type": {"type": "string"},
        "subject_key": {"type": "string"},
        "workspace_id": {"type": "string"},
        "requested_by": {"type": "string"},
        "origin": {"type": "string"},
        "due_at": {"type": "string"},
    },
    "additionalProperties": False,
}

OWNER_PROBE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "gdpr.owner.probe",
    "type": "object",
    "required": ["correlation_id"],
    "properties": {"correlation_id": {"type": "string"}},
    "additionalProperties": False,
}


def _receipt(correlation_id, subject_type, subject_key, counts) -> None:
    """Emit ``gdpr.section.erased`` for work that has just committed.

    Callers hold an open transaction; the emit rides the outbox, so the
    receipt leaves iff the erasure commits. An owner that receipts a
    rollback is worse than one that stays silent — the orchestrator counts
    the receipt and finalizes.
    """
    from stapel_core.comm import emit

    emit(
        "gdpr.section.erased",
        {
            "correlation_id": str(correlation_id),
            "owner": GDPR_OWNER,
            "subject_type": subject_type,
            "subject_key": str(subject_key),
            "counts": counts,
        },
        key=str(subject_key),
    )


@on_action("gdpr.erasure.requested", schema=ERASURE_REQUESTED_SCHEMA)
def handle_erasure_requested(event):
    """Erase the named subject and confirm with counts (stapel-gdpr 0.5.0).

    A subject type this module does not claim is not ours to answer: the
    orchestrator creates a part only for owners that declared the type, and
    a receipt against a part that does not exist teaches it nothing.
    """
    from django.db import transaction

    from .erasure import erase_subject

    payload = event.payload
    subject_type = payload.get("subject_type")
    subject_key = payload.get("subject_key")
    correlation_id = payload.get("correlation_id")
    if subject_type not in GDPR_SUBJECT_TYPES:
        return
    if not subject_key or not correlation_id:
        logger.error(
            "malformed gdpr.erasure.requested: %s", getattr(event, "event_id", "?"),
        )
        return

    try:
        with transaction.atomic():
            counts = erase_subject(subject_type, subject_key)
            _receipt(correlation_id, subject_type, subject_key, counts)
    except (TypeError, ValueError, ValidationError):
        # An unparseable key names no row here. Receipting would claim an
        # erasure that never happened; raising would retry forever.
        logger.error(
            "gdpr.erasure.requested with unusable %s key %r [correlation=%s]",
            subject_type, subject_key, correlation_id,
        )
        return
    logger.info(
        "profiles erased %s %s: %s [correlation=%s]",
        subject_type, subject_key, counts, correlation_id,
    )


@on_action("gdpr.owner.probe", schema=OWNER_PROBE_SCHEMA)
def handle_owner_probe(event):
    """Answer the liveness probe — see this module's docstring for why here."""
    from stapel_core.comm import emit

    emit(
        "gdpr.owner.alive",
        {
            "owner": GDPR_OWNER,
            "subject_types": list(GDPR_SUBJECT_TYPES),
            "correlation_id": str(event.payload.get("correlation_id") or ""),
        },
        key=GDPR_OWNER,
    )


@on_action("user.deleted")
def handle_user_deleted(event):
    """Erase profile PII when an account deletion is executed (GDPR Art. 17).

    Deprecated upstream: stapel-gdpr emits ``user.deleted`` alongside
    ``gdpr.erasure.requested`` for account subjects until 0.6.0. Both land
    here, both run the same :func:`~stapel_profiles.erasure.erase_account`,
    and both receipt — until now this handler erased and said nothing, so
    the orchestrator's part for this owner stayed unconfirmed until it timed
    out thirty days later. The part flips once and ignores the second
    receipt, so the two paths cannot drift into disagreeing.
    """
    from django.db import transaction

    from .erasure import erase_account

    user_id = event.payload.get("user_id")
    if not user_id:
        logger.error("user.deleted event without user_id: %s", event.event_id)
        return
    correlation_id = event.payload.get("correlation_id")
    with transaction.atomic():
        counts = erase_account(user_id)
        if correlation_id:
            _receipt(correlation_id, "account", user_id, counts)
    logger.info("profiles erased for deleted user %s: %s", user_id, counts)


def _provision_profile(user_id) -> None:
    """Create the profile row the moment the account is born.

    **The defect this closes.** Until 0.15.0 a profile row was created
    lazily, by the OWNER's first ``GET .../me``. Everything that renders a
    person to SOMEBODY ELSE — a seller block on a listing, a name next to a
    chat message, the author of a review — reads
    ``GET .../<user_id>`` instead, and for a registered user who had simply
    never opened their own profile that read was a 404. On a live
    marketplace that showed up as no names anywhere: the account existed,
    the product just had nowhere to read it from.

    Registration is the event that says a person now exists in this product,
    so it is the event that provisions their row. The row is EMPTY — the
    honest state of a person who has typed nothing yet — but it exists, so
    the public read answers 200 with a renderable shape instead of an error
    every consumer has to special-case.

    Idempotent by construction (``get_or_create``): delivery is at-least-once
    and a redelivery must not disturb a row the human has since filled in.

    Known interaction with erasure: :func:`~stapel_profiles.erasure.
    erase_account` DELETES the row, so a broker replay of a very old
    ``user.registered`` would re-create an empty one. It carries no personal
    data beyond the id, and the account it names is gone from auth — so the
    public read gates on the user still existing (``views._existing_users``)
    and answers 404 for it either way. Deliberately not defended with a
    tombstone table: that would be new permanent storage about erased people
    to protect against a stale empty row.
    """
    from .models import get_profile_model

    Profile = get_profile_model()
    _, created = Profile.objects.get_or_create(user_id=user_id)
    if created:
        logger.info("provisioned profile row for user %s at registration", user_id)


def _prefill_display_name(user_id, hint) -> None:
    """Pre-fill a new profile's display name from the registration hint.

    ``user.registered`` may carry a ``display_name`` — the name whoever
    created the account typed for this person (an org admin provisioning a
    login via ``auth.provision_user``, an admin inviting by email, an OAuth
    provider's profile name). It is a **pre-fill, not an assignment**: the
    owner of a name is the person it names, never the person who invited
    them, so the onboarding form must be free to show it and let the human
    overwrite it.

    That semantics is one guard: **never write over a name the human could
    have set themselves.** "The stored name is empty" alone is NOT that
    guard — delivery is at-least-once, so consider a user who deliberately
    CLEARS their name and then gets the registration event redelivered:
    with an emptiness-only test the admin's hint would resurrect itself over
    the user's deletion. So the pre-fill also stops at the onboarding
    boundary (``initial_setup_passed``): once the human has been through
    setup, the name is theirs — empty included — and a late/redelivered hint
    is a no-op. Concretely we write only when:

    * no profile row exists yet (the common case — the hint arrives before
      the user's first ``GET /me``), or
    * the row exists with an empty ``display_name`` AND onboarding is not
      done (``GET /me`` creates an empty row on first render; the hint must
      still land there).

    The hint is untrusted input from another service, so it is held to this
    module's own name canon (:func:`validators.validate_display_name` plus
    the model's ``max_length``) before it is written. A hint that fails is
    *declined and logged*, never truncated or sanitized into something the
    admin did not type: a mangled name is worse than an empty field the
    user fills in during onboarding.

    Best-effort, like the avatar import below: the account exists either
    way, and a name that failed to pre-fill is a blank onboarding field, not
    a failed registration.
    """
    if not hint or not isinstance(hint, str):
        # No hint (the common case — plain email/OTP registration) or a
        # non-string payload value: nothing to pre-fill, not an error.
        return

    from django.core.exceptions import FieldDoesNotExist

    from .models import get_profile_model

    Profile = get_profile_model()
    try:
        field = Profile._meta.get_field("display_name")
    except FieldDoesNotExist:
        # A host-swapped profile model without a display name (§66 field
        # constructor): there is nothing to pre-fill.
        return

    name = hint.strip()
    if not name:
        # Whitespace-only hint. Not an error, but not a name either — leave
        # the (already provisioned) row's empty display_name alone.
        return

    max_length = getattr(field, "max_length", None)
    if max_length and len(name) > max_length:
        logger.warning(
            "display_name hint for user %s declined: %d chars > max_length %d",
            user_id,
            len(name),
            max_length,
        )
        return

    from stapel_core.django.api.errors import StapelValidationError

    from .validators import validate_display_name

    try:
        validate_display_name(name)
    except StapelValidationError as exc:
        logger.warning(
            "display_name hint for user %s declined by the name canon (%s)",
            user_id,
            getattr(exc, "error_key", exc),
        )
        return

    existing = Profile.objects.filter(user_id=user_id).first()
    if existing is not None and (
        existing.display_name or getattr(existing, "initial_setup_passed", False)
    ):
        # The human already owns this field — a set name, or an empty one
        # they kept through onboarding. Never clobber, never resurrect.
        return

    Profile.objects.update_or_create(
        user_id=user_id, defaults={"display_name": name}
    )
    logger.info("pre-filled display name for user %s from the registration hint", user_id)


@on_action("user.registered")
def handle_user_registered(event):
    """Provision the profile row, pre-fill the name, import a provider avatar.

    Contract (``schemas/emits/user.registered.json`` in auth):
    ``{user_id, auth_type, email, avatar_url, language, display_name}``
    where ``avatar_url`` and ``display_name`` are ``str | null``.

    Provisioning comes FIRST and unconditionally — see
    :func:`_provision_profile` for why a registered user must have a row
    before they ever open the product. The two enrichments below (name
    hint, provider avatar) then fill that row in when the payload carries
    something to fill it with; neither is required for the row to exist.

    ``display_name`` is the pre-fill hint — see
    :func:`_prefill_display_name` for the "a person owns their own name"
    guard. It is handled FIRST and independently of the avatar: the avatar
    import is a network call that may fail, and a cosmetic avatar failure
    must not cost the account its name.

    ``avatar_url``: currently only OAuth registrations populate it. A
    payload without a usable ``avatar_url`` is a no-op: most registrations
    (email/phone/password OTP) carry no avatar and that is normal, not an
    error.

    Why re-host instead of storing the provider URL directly: even though
    ``avatar_source`` can now be ``url`` (§66), a raw external URL cannot be
    trusted long-term — provider hotlinks rot, and rendering one would leak
    every viewer's IP to Google/Facebook. So we pull the image once, through
    the SSRF-hardened ``cdn.import_from_url`` fetcher, and keep the CDN ref
    (``avatar_source="cdn"``).

    Idempotency + respect-user-choice (one guard serves both): if the profile
    already has a non-empty avatar we no-op *before* fetching. Delivery is
    at-least-once, so a redelivered event must not re-import; and a manually
    uploaded avatar is the user's choice and must never be clobbered by a
    late provider import. This also avoids re-hitting the provider on every
    redelivery.

    Best-effort, swallow-not-retry: any failure of the fetch/call/save is
    logged and swallowed. Letting it propagate would raise
    ``ActionDeliveryError`` and make the outbox relay redeliver the *whole*
    ``user.registered`` event — re-running every other subscriber (workspace
    creation, ...) in a retry storm — just because a cosmetic, non-critical
    avatar fetch of an attacker-influenced URL failed. The account exists
    without an avatar; that is an acceptable terminal state.
    """
    payload = event.payload
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("user.registered event without user_id: %s", event.event_id)
        return

    try:
        _provision_profile(user_id)
    except Exception:
        # Same swallow-not-retry contract as the two enrichments below. A
        # user whose row failed to provision is back to the pre-0.15.0
        # lazy-creation behaviour (their first GET /me makes it), not a
        # failed registration — and re-running every other subscriber of
        # this event to retry it would be a far worse trade.
        logger.warning(
            "failed to provision profile row for user %s", user_id, exc_info=True
        )

    try:
        _prefill_display_name(user_id, payload.get("display_name"))
    except Exception:
        # Same swallow-not-retry contract as the avatar import below: an
        # unfilled name must not make the outbox replay the whole
        # registration event through every other subscriber.
        logger.warning(
            "failed to pre-fill display name for user %s", user_id, exc_info=True
        )

    avatar_url = payload.get("avatar_url")
    if not avatar_url:
        # No provider avatar (the common case) — nothing to do.
        return

    from .models import get_profile_model

    Profile = get_profile_model()

    existing = Profile.objects.filter(user_id=user_id).first()
    if existing is not None and existing.avatar:
        # Already has an avatar (user-set or previously imported) — idempotent
        # no-op; never overwrite a deliberate choice, never re-fetch.
        return

    try:
        from stapel_core.comm import call

        result = call(
            "cdn.import_from_url",
            {"url": avatar_url, "image_type": "avatar", "caller": str(user_id)},
        )
        ref = result.get("ref") if isinstance(result, dict) else None
        if not ref:
            logger.warning(
                "cdn.import_from_url returned no ref for user %s (payload=%r)",
                user_id,
                result,
            )
            return
        from .models import AvatarSource

        Profile.objects.update_or_create(
            user_id=user_id,
            defaults={"avatar": ref, "avatar_source": AvatarSource.CDN},
        )
        logger.info("imported provider avatar %s for user %s", ref, user_id)
    except Exception:
        # Best-effort: registration is done; the avatar is optional cosmetic.
        logger.warning(
            "failed to import provider avatar for user %s — leaving profile "
            "without an avatar",
            user_id,
            exc_info=True,
        )
