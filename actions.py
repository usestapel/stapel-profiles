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


@on_action("user.registered")
def handle_user_registered(event):
    """Import an OAuth provider avatar onto the CDN for a new account.

    Contract (``schemas/emits/user.registered.json`` in auth):
    ``{user_id, auth_type, email, avatar_url}`` where ``avatar_url`` is
    ``str | null`` — currently only OAuth registrations populate it. A
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
