"""
Models for stapel-profiles service.

§66 alpha-cut (docs/pending/profile-fields.md, owner GO 2026-07-17): the
Profile DAO shrinks to a hard core (`ProfileCore`) plus whatever a project
opts into from the standard-field registry (`field_defs.py`). Removed from
the hard model this pass — deletion-driven, no compat shim (pre-1.0 alpha
policy): `theme`, `currency_code`, `measurement_units`, `display_name`.
Projects that need them pick them back up as STANDARD_FIELDS / an
IDENTITY_PRESETS choice (`field_defs.assemble_profile_fields` /
`build_profile_model`) in their OWN app.

Owner directive kept HARD in core (overrides the spec doc's own §6.2
recommendation to make it opt-in): the whole language block, and avatar.
"""
from django.db import models
from stapel_core.django.cdn.fields import validate_cdn_reference
from stapel_core.django.swappable import declare_swap, get_model

from .field_defs import StapelProfileEnum


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


class AvatarSource(StapelProfileEnum):
    """Where an avatar reference points.

    Ahead of §67 (core/cdn): avatar becomes source+ref instead of an
    always-CDN reference, so a project can store an uploaded file key, an
    arbitrary URL, or a Gravatar email-hash without a CDN service at all.
    Default is `FILE` — a project must opt INTO `CDN`, not out of it. The
    system check that flags "source=CDN chosen but no CDN service
    configured" belongs to the §67 agent's work in stapel-core/stapel-cdn,
    not here — this model only stores the choice.
    """

    FILE = "file", "File"
    URL = "url", "URL"
    GRAVATAR = "gravatar", "Gravatar"
    CDN = "cdn", "CDN"


def validate_avatar_reference(source: str, value: str) -> None:
    """Format-validate `avatar` against its declared `avatar_source`.

    Only the `cdn` source has a fixed wire format (`avatar/<64-hex>`,
    `stapel_core.django.cdn.fields.validate_cdn_reference`) — `file`/`url`/
    `gravatar` are free-form strings (upload key / URL / email-hash), this
    model does not police their shape.
    """
    if not value or source != AvatarSource.CDN:
        return
    validate_cdn_reference(value, "avatar")


class ProfileCore(models.Model):
    """Common denominator every Stapel profile needs regardless of domain.

    Everything a specific product might or might not need (identity shape,
    theme, currency, measurement units, geohash) lives in the standard-field
    registry (`field_defs.py`) instead — a project without customization gets
    the plain `Profile(ProfileCore)` below; a project that picks standard/
    custom fields gets its own extended model (`field_defs.build_profile_model`,
    swapped in via `STAPEL_SWAP["PROFILES_PROFILE_MODEL"]` — see
    `get_profile_model()` below), assembled from this same registry.
    """

    user_id = models.UUIDField(
        primary_key=True, help_text="User UUID from auth service"
    )

    # Avatar — source+ref (§66 prep for §67). Kept hard in core: no
    # inventoried product turns it off (owner directive).
    avatar_source = models.CharField(
        max_length=10,
        choices=AvatarSource.choices,
        default=AvatarSource.FILE,
        help_text="Where `avatar` points: uploaded file key, arbitrary URL, "
                   "Gravatar email-hash, or a CDN ref. Defaults to file/url — "
                   "cdn is opt-in, not the default.",
    )
    avatar = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Avatar reference matching avatar_source: CDN 'avatar/<hash>' "
                   "ref, a Gravatar email-hash, a plain URL, or an uploaded file key.",
    )

    # Language settings — hard in core (owner directive 2026-07-17):
    # multi-understand-language is universal account infrastructure, not a
    # per-product preference, even though a real product (miттудей) may
    # front it with a simpler single-code UI of its own.
    app_language = models.ForeignKey(
        Language,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Primary app language (default: English)",
    )
    understands = models.ManyToManyField(
        Language,
        blank=True,
        related_name="+",
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

    # Notification preferences — untouched this pass (a separate, already
    # documented question re: overlap with stapel-notifications).
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

    # Location — untouched this pass.
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
        abstract = True


#: Swap key for the profile DAO model override (`STAPEL_SWAP` registry) — the
#: first real `get_model()` case in the framework (§66 slice; §55 declared
#: the primitive, this is its first non-pilot user). The default stays a
#: plain, zero-standard-fields Profile so a project that customizes nothing
#: pays nothing.
PROFILE_MODEL_KEY = "PROFILES_PROFILE_MODEL"
DEFAULT_PROFILE_MODEL = "stapel_profiles.models.Profile"
declare_swap(PROFILE_MODEL_KEY, DEFAULT_PROFILE_MODEL)


class Profile(ProfileCore):
    """Default profile — zero standard/custom fields selected.

    Active when a project's manifest picks nothing beyond core. A project
    that wants theme/currency/measurement-units/identity/geohash or its own
    custom fields builds its own extended model
    (`field_defs.build_profile_model`, in its own app so the migration lives
    there too) and points `STAPEL_SWAP["PROFILES_PROFILE_MODEL"]` at it —
    this class stays the swap DEFAULT, never imported directly by library
    internals (`get_profile_model()` below is the required indirection; a
    stray direct `from .models import Profile` elsewhere in library code is
    exactly what the SWAP001 lint flags).
    """

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

    def __str__(self):
        return f"Profile({self.user_id})"


def get_profile_model():
    """The active (possibly host-swapped) Profile DAO model.

    Views/serializers/admin/gdpr/events/actions call this instead of
    importing `Profile` directly — see the `Profile` docstring and
    `stapel_core.django.swappable` for why.
    """
    return get_model(PROFILE_MODEL_KEY, default=DEFAULT_PROFILE_MODEL)


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
