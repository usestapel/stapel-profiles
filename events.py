"""Comm event publishers for the profiles module.

Events go through stapel_core.comm (transport is deployment configuration:
in-process in a monolith, bus in microservices). Payload contract lives in
schemas/emits/profile.changed.json.
"""
import logging

logger = logging.getLogger(__name__)


def publish_profile_changed(instance):
    """Emit the ``profile.changed`` action for a mutated profile."""
    try:
        from stapel_core.comm import emit

        emit(  # emit-check: ok — best-effort post-commit publisher, not a mutation+emit unit: this helper has no local ORM write, the caller saves+commits the profile independently (autocommit) before calling it, and the swallow is intentional so a broker/listener outage never fails the request
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
