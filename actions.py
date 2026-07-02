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
