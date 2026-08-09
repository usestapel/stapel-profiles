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
import logging
import re

from django.core.exceptions import ValidationError
from django.db import models
from stapel_core.django.cdn.fields import validate_cdn_reference
from stapel_core.django.swappable import declare_swap, get_model

from .field_defs import StapelProfileEnum, Theme

logger = logging.getLogger(__name__)


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


#: `avatar/<64-hex>` — stapel-cdn's ref format, and nothing else's. A `file`
#: upload key, a URL and a Gravatar email-hash cannot collide with it: the
#: first has no `avatar/` prefix from any writer in this fleet, the second
#: carries a scheme, the third has no slash at all. That total discrimination
#: is what makes `avatar_source` DERIVABLE from the ref below.
_CDN_AVATAR_REF = re.compile(r"^avatar/[a-fA-F0-9]{64}$")


def is_cdn_avatar_reference(value: str | None) -> bool:
    """True when `value` is unmistakably a stapel-cdn avatar ref."""
    return bool(value) and bool(_CDN_AVATAR_REF.match(value))


def validate_avatar_reference(source: str, value: str) -> None:
    """Validate the PAIR `avatar` + `avatar_source`, in both directions.

    `cdn` has a fixed wire format (`avatar/<64-hex>`,
    `stapel_core.django.cdn.fields.validate_cdn_reference`); `file`/`url`/
    `gravatar` are free-form strings (upload key / URL / email-hash) whose
    shape this model does not police — with ONE exception, which is the whole
    point of this function: a value that IS a cdn ref may not be tagged
    anything but `cdn`.

    That mismatch is not hypothetical. On the meettoday sandbox both profiles
    that ever had an avatar (2 of 2 — a 100% failure rate of the manual upload
    path, not an edge case) stored a real cdn ref tagged `file`, because the
    frontend PATCHed `{avatar: ref}` and let the model default decide the tag.
    Serialization then routed the ref to the PIL provider, which opened the
    ladder DIRECTORY as a file and raised — 500 on `/profiles/api/v1/me`, so
    the frontend saw no `display_name`, blocked the meeting door with an
    "enter your name" dialog, and that dialog's PATCH 500'd on the same
    avatar. A cosmetic ref locked two people out of the product.

    The invariant is enforced, not merely documented — see
    `resolve_avatar_source` and `ProfileCore.save`.
    """
    if not value:
        return
    if source == AvatarSource.CDN:
        validate_cdn_reference(value, "avatar")
        return
    if is_cdn_avatar_reference(value):
        raise ValidationError(
            f"avatar {value!r} is a CDN reference but avatar_source is "
            f"{source!r} — the pair must agree (use avatar_source='cdn')."
        )


def resolve_avatar_source(source: str, value: str | None) -> str:
    """The `avatar_source` that MUST accompany `value`.

    Returns `source` unchanged unless the ref is unmistakably a cdn ref that
    is tagged otherwise, in which case it returns `cdn`.

    WHY DERIVE HERE AND REJECT AT THE API BOUNDARY (see
    `serializers.ProfileCreateUpdateSerializer.validate`). Two different
    situations wear the same shape:

    - A CLIENT that sent `avatar_source="file"` alongside a cdn ref has stated
      a belief that is wrong. Silently overriding a stated belief hides the
      caller's bug — it gets a 400 so the caller is fixed.
    - A WRITER with no stated belief (a client that sent only `avatar`, an
      internal `update_or_create`, the admin, a data migration) left the field
      to a default that predates the ref. There is no caller to correct, and
      refusing the save would turn a cosmetic avatar defect into a write
      failure on unrelated fields — the exact escalation this whole incident
      was. So the ref, which is self-describing, decides; loudly, at WARNING.

    The coercion is not a guess: `avatar/<64-hex>` is produced by exactly one
    writer in the fleet (stapel-cdn) and by nothing else.
    """
    if is_cdn_avatar_reference(value) and source != AvatarSource.CDN:
        return AvatarSource.CDN
    return source


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

    # Display name + theme — back in the hard core (owner directive 2026-07-22,
    # partial §66 reversal): every product wants a name to show and a
    # light/dark toggle, and making agents/scaffolds opt into them via the
    # field registry was friction with no upside. currency/measurement stay
    # opt-in in the registry (they're genuinely product-specific). The frontend
    # default skin can still hide either one per host (a prop), so "in the
    # default" does not mean "forced on screen".
    display_name = models.CharField(
        max_length=35,
        blank=True,
        default="",
        help_text="User's display name.",
    )
    theme = models.CharField(
        max_length=10,
        choices=Theme.choices,
        default=Theme.SYSTEM,
        help_text="UI theme preference (light/dark/system).",
    )

    # Language settings — hard in core (owner directive 2026-07-17):
    # multi-understand-language is universal account infrastructure, not a
    # per-product preference, even though a real product (meettoday) may
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

    # -- avatar pair invariant -------------------------------------------
    # `avatar` and `avatar_source` are one value in two columns. Nothing used
    # to hold them together: the serializer only format-checked the ref when
    # the source ALREADY said `cdn` (i.e. exactly the case that was already
    # right), and every other writer — admin, shell, data migration, an
    # `update_or_create` whose defaults predate the ref — could store any
    # combination it liked. Two rows on the meettoday sandbox did, and 500'd
    # the profile endpoint. The invariant lives HERE, at the last gate every
    # writer passes, so "inconsistent" stops being a storable state rather
    # than a state the read path has to survive.

    def clean(self):
        """Reject an inconsistent pair for callers that validate (admin,
        `full_clean()`). `save()` below repairs instead of raising — see
        `resolve_avatar_source` for why the two differ."""
        super().clean()
        validate_avatar_reference(self.avatar_source, self.avatar or "")

    def save(self, *args, **kwargs):
        resolved = resolve_avatar_source(self.avatar_source, self.avatar)
        if resolved != self.avatar_source:
            logger.warning(
                "profile %s: avatar %r is a CDN reference but avatar_source "
                "was %r — storing 'cdn'. The writer should send the pair; a "
                "ref stored under the wrong source renders as no avatar at "
                "best and used to 500 the profile endpoint.",
                self.pk,
                self.avatar,
                self.avatar_source,
            )
            self.avatar_source = resolved
            # `update_or_create` and any partial save pass `update_fields`;
            # without this the repaired tag would be computed and dropped.
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"avatar_source"}
        return super().save(*args, **kwargs)


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
