"""Action subscriptions of the profiles module.

Handlers must be idempotent: delivery is at-least-once (outbox retries,
broker redelivery).
"""
import logging

from stapel_core.comm import on_action

logger = logging.getLogger(__name__)


@on_action("user.deleted")
def handle_user_deleted(event):
    """Erase profile PII when an account deletion is executed (GDPR Art. 17)."""
    from .gdpr import ProfilesGDPRProvider

    user_id = event.payload.get("user_id")
    if not user_id:
        logger.error("user.deleted event without user_id: %s", event.event_id)
        return
    ProfilesGDPRProvider().delete(user_id)
    logger.info("profiles erased for deleted user %s", user_id)


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
        # Whitespace-only hint. Not an error, but not a name either — and
        # writing it would CREATE an empty profile row for a user who has
        # not touched the product yet, which is a row nobody asked for.
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
    """Pre-fill the display name and import an OAuth provider avatar.

    Contract (``schemas/emits/user.registered.json`` in auth):
    ``{user_id, auth_type, email, avatar_url, language, display_name}``
    where ``avatar_url`` and ``display_name`` are ``str | null``.

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
