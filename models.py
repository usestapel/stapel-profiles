"""
Models for stapel-profiles service.
"""

from django.db import models
from stapel_core.django.cdn.fields import CdnImageField


class Language(models.Model):
    """
    Language configuration.

    Stores available languages with their codes, flags, and names.
    """

    code = models.CharField(
        max_length=10,
        primary_key=True,
        help_text="Language code (e.g., 'en', 'ru', 'de')",
    )
    flag = models.FileField(
        upload_to="flags/", blank=True, help_text="Flag image (SVG preferred)"
    )
    name = models.CharField(
        max_length=100, help_text="Language name (e.g., 'English', 'Russian')"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this language is available for selection"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Language"
        verbose_name_plural = "Languages"

    def __str__(self):
        return f"{self.name} ({self.code})"


class MeasurementUnit(models.TextChoices):
    """Measurement unit system choices."""

    METRIC = "metric", "Metric"
    IMPERIAL = "imperial", "Imperial"


class Theme(models.TextChoices):
    """UI theme choices."""

    LIGHT = "light", "Light"
    DARK = "dark", "Dark"
    SYSTEM = "system", "System"


class Profile(models.Model):
    """
    User profile with preferences and settings.

    Links to User in auth service via user_id (UUID).
    """

    user_id = models.UUIDField(
        primary_key=True, help_text="User UUID from auth service"
    )

    # Display name
    display_name = models.CharField(
        max_length=35, blank=True, default="", help_text="User's display name"
    )

    # Avatar
    avatar = CdnImageField(  # type: ignore[call-arg]
        image_type="avatar",
        null=True,
        blank=True,
        help_text="CDN avatar image reference (avatar/hash)",
    )

    # Preferences
    currency_code = models.CharField(
        max_length=3,
        default="EUR",
        help_text="Preferred currency code (e.g., 'EUR', 'USD')",
    )
    measurement_units = models.CharField(
        max_length=10,
        choices=MeasurementUnit,
        default=MeasurementUnit.METRIC,
        help_text="Preferred measurement system",
    )
    theme = models.CharField(
        max_length=10,
        choices=Theme,
        default=Theme.SYSTEM,
        help_text="UI theme preference",
    )

    # Language settings
    app_language = models.ForeignKey(
        Language,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users_with_app_language",
        help_text="Primary app language (default: English)",
    )
    understands = models.ManyToManyField(
        Language,
        blank=True,
        related_name="users_who_understand",
        help_text="Languages the user understands",
    )
    use_device_language = models.BooleanField(
        default=True, help_text="Use device language for app UI"
    )
    auto_detected_language = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Last detected language from Accept-Language header",
    )
    auto_translate_content = models.BooleanField(
        default=False, help_text="Automatically translate content"
    )

    # Notification preferences
    email_messages = models.BooleanField(
        default=True, help_text="Receive message notifications via email"
    )
    email_system = models.BooleanField(
        default=True, help_text="Receive system notifications via email"
    )
    push_messages = models.BooleanField(
        default=True, help_text="Receive message notifications via push"
    )
    push_system = models.BooleanField(
        default=True, help_text="Receive system notifications via push"
    )

    # Privacy/consent
    essential_cookies_accepted = models.BooleanField(
        default=False, help_text="User accepted essential cookies"
    )

    # Onboarding
    initial_setup_passed = models.BooleanField(
        default=False, help_text="User completed initial profile setup"
    )

    # Location
    location_id = models.IntegerField(
        null=True, blank=True, help_text="User's location ID from geo service"
    )
    location_display_name_narrow = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Cached narrow location display name from geo service",
    )
    location_display_name_broad = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Cached broad location display name from geo service",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

    def __str__(self):
        return f"Profile({self.user_id})"


class RelationshipStatus(models.TextChoices):
    """User relationship status choices."""

    NEUTRAL = "neutral", "Neutral"
    FOLLOWING = "following", "Following"
    BLOCKED = "blocked", "Blocked"


class UserRelationship(models.Model):
    """
    Relationship between two users.

    Tracks follow/block status from follower to following.
    """

    follower_id = models.UUIDField(
        db_index=True, help_text="UUID of the user who follows/blocks"
    )
    following_id = models.UUIDField(
        db_index=True, help_text="UUID of the user being followed/blocked"
    )
    status = models.CharField(
        max_length=10,
        choices=RelationshipStatus,
        default=RelationshipStatus.NEUTRAL,
        help_text="Relationship status",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Relationship"
        verbose_name_plural = "User Relationships"
        constraints = [
            models.UniqueConstraint(
                fields=["follower_id", "following_id"], name="unique_relationship"
            ),
            models.CheckConstraint(
                condition=~models.Q(follower_id=models.F("following_id")),
                name="no_self_relationship",
            ),
        ]
        indexes = [
            models.Index(fields=["follower_id", "status"]),
            models.Index(fields=["following_id", "status"]),
        ]

    def __str__(self):
        return f"{self.follower_id} -> {self.following_id} ({self.status})"
