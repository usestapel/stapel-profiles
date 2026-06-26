"""
Publish Kafka profile-changed events for all existing profiles.

Used for backfilling SellerProfile in catalog service with display_name,
avatar, and location data.

Usage:
    python manage.py publish_all_profiles
"""
import logging

from django.core.management.base import BaseCommand

from stapel_core.bus import publish, Event
from stapel_core.kafka.events import EventType
from stapel_core.kafka.topics import TOPIC_PROFILE_CHANGED
from stapel_profiles.models import Profile

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Publish Kafka profile-changed events for all existing profiles"

    def handle(self, *args, **options):
        profiles = Profile.objects.all()
        total = profiles.count()
        self.stdout.write(f"Publishing events for {total} profiles")

        published = 0
        errors = 0

        for i, profile in enumerate(profiles.iterator(), 1):
            try:
                publish(
                    TOPIC_PROFILE_CHANGED,
                    Event(
                        event_type=EventType.PROFILE_CHANGED,
                        service="profiles",
                        payload={
                            "user_id": str(profile.user_id),
                            "display_name": profile.display_name,
                            "avatar": profile.avatar or '',
                            "location_display_name_narrow": profile.location_display_name_narrow,
                            "location_display_name_broad": profile.location_display_name_broad,
                        },
                        key=str(profile.user_id),
                    ),
                )
                published += 1
            except Exception:
                logger.exception("Failed to publish for user %s", profile.user_id)
                errors += 1

            if i % 100 == 0:
                self.stdout.write(f"  processed {i}/{total}")

        self.stdout.write(self.style.SUCCESS(
            f"Done: {published} published, {errors} errors"
        ))
