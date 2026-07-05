"""Comm event publishers for the profiles module.

Events go through stapel_core.comm (transport is deployment configuration:
in-process in a monolith, bus in microservices). Payload contract lives in
schemas/emits/profile.changed.json.
"""
import logging

logger = logging.getLogger(__name__)


def publish_profile_changed(instance):
    """Emit the ``profile.changed`` action for a mutated profile.

    Best-effort fan-out: a broker/outbox/schema failure must never fail the
    profile mutation. The emit runs inside its OWN atomic block so that is
    true in BOTH request modes. Under ATOMIC_REQUESTS=True the caller is inside
    the request transaction; a failing emit there marks it rollback-only
    (comm/actions.py), so a plain swallow would still 500 the request on the
    next query. Wrapping emit in a nested atomic isolates the failure to a
    savepoint (Django rolls it back and clears needs_rollback), leaving the
    request transaction healthy. In autocommit mode the block is the outermost
    atomic and behaves identically. The nested atomic also silences the
    emit-outside-atomic guard's per-request WARNING spam.
    """
    try:
        from django.db import transaction

        from stapel_core.comm import emit

        with transaction.atomic():
            emit(  # emit-check: ok — best-effort fan-out wrapped in its own atomic; the profile is saved by the caller, this helper has no local ORM write, and the swallow + savepoint isolation mean an emit failure never fails the request in either mode
                "profile.changed",
                {
                    "user_id": str(instance.user_id),
                    "display_name": instance.display_name,
                    "avatar": instance.avatar or "",
                    "location_id": instance.location_id,
                    "location_display_name_narrow": instance.location_display_name_narrow,
                    "location_display_name_broad": instance.location_display_name_broad,
                    "app_language": instance.app_language_id if instance.app_language_id else None,
                    "auto_detected_language": instance.auto_detected_language or None,
                    "email_messages": instance.email_messages,
                    "email_system": instance.email_system,
                    "push_messages": instance.push_messages,
                    "push_system": instance.push_system,
                },
                key=str(instance.user_id),
            )
    except Exception:
        logger.exception("Failed to publish profile-changed event")
