"""Kafka event publishers for profiles service."""
import logging

logger = logging.getLogger(__name__)


def publish_profile_changed(instance):
    """Publish profile-changed Kafka event."""
    try:
        from stapel_core.bus import publish, Event
        from stapel_core.kafka.events import EventType
        from stapel_core.kafka.topics import TOPIC_PROFILE_CHANGED
        publish(
            TOPIC_PROFILE_CHANGED,
            Event(
                event_type=EventType.PROFILE_CHANGED,
                service="profiles",
                payload={
                    "user_id": str(instance.user_id),
                    "display_name": instance.display_name,
                    "avatar": instance.avatar or '',
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
            ),
        )
    except Exception:
        logger.exception("Failed to publish profile-changed event")
