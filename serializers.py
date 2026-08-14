"""
Serializers for stapel-profiles service.
"""

import logging

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from stapel_core.django.api.errors import StapelValidationError
from stapel_core.django.api.serializers import StapelDataclassSerializer
from stapel_core.media import image as build_image
from stapel_core.media.drf import StapelImageSerializer

from .errors import (
    ERR_400_AVATAR_NOT_FOUND,
    ERR_400_AVATAR_SOURCE_MISMATCH,
    ERR_400_INVALID_AVATAR_FORMAT,
)
from .validators import (
    is_gravatar_hash,
    is_safe_avatar_url,
    validate_avatar_url,
    validate_gravatar_hash,
)

logger = logging.getLogger(__name__)

from .dto import (
    FollowersResponse,
    FollowingResponse,
    LanguageResponse,
    ProfileBatchRequest,
    ProfileBatchResponse,
    ProfileFieldManifestEntry,
    ProfilePublicResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    RelationshipActionResponse,
    RelationshipResponse,
)
from .models import (
    AvatarSource,
    Language,
    Theme,
    UserRelationship,
    get_profile_model,
    is_cdn_avatar_reference,
    validate_avatar_reference,
)

#: Resolved once at import time — see the identical note in views.py; used
#: as `sender=` for the `profile_updated` signal below.
Profile = get_profile_model()


def avatar_image(profile):
    """The renderable `StapelImage` for a profile's avatar, or ``None``.

    Denormalizes the avatar NEXT TO the raw ref (which stays writable on the
    serializer for the upload round-trip) so a frontend `<Image>` gets the
    variant ladder + blur-up without a second round-trip — THE DESIGN RULE
    (owner directive 2026-07-20). Maps this module's `AvatarSource` taxonomy
    onto `stapel_core.media`'s source-agnostic builder:

    - CDN → the cdn provider (its own variant naming — the fix for the empty
      ladder meettoday hit when a pil-default deployment described cdn refs);
    - FILE → the PIL provider over plain Django storage;
    - URL → an external link, subject to the URL boundary below;
    - GRAVATAR → the gravatar URL built from the stored email-hash (square).

    Read boundary (security audit PROFILE-01): an external `url` avatar is
    emitted only when it still satisfies the URL boundary, and a `gravatar`
    avatar only when it is an email hash. Rows written before the rule (or
    by a writer that bypassed the API) therefore degrade to "no avatar"
    instead of handing every consumer a reference the boundary would refuse
    today — no client should ever have to defend itself against this field.
    """
    value = profile.avatar
    if not value:
        return None
    source = profile.avatar_source
    if source == AvatarSource.CDN:
        return build_image("cdn", value)
    if source == AvatarSource.FILE:
        return build_image("file", value)
    if source == AvatarSource.URL:
        if not is_safe_avatar_url(value):
            logger.warning(
                "profiles: suppressed unsafe stored avatar URL for %s", profile.user_id
            )
            return None
        return build_image("link", value)
    if source == AvatarSource.GRAVATAR:
        if not is_gravatar_hash(value):
            logger.warning(
                "profiles: suppressed non-hash gravatar avatar for %s", profile.user_id
            )
            return None
        return build_image(
            "link", f"https://www.gravatar.com/avatar/{value}", aspect=1.0
        )
    return None

# =============================================================================
# Model Serializers
# =============================================================================


class LanguageCodeField(serializers.SlugRelatedField):
    """A language code this deployment DECLARES — not only one a fixture seeded.

    ``Language`` is a reference table with display metadata (name, flag), and
    it is populated by ``manage.py sync_languages``. Validating a write
    against its rows alone made the language a user can CHOOSE depend on
    whether anybody had ever run that command: a deployment that declares
    ``LANGUAGES = [("ru", ...), ("en", ...)]`` and never ran it answered an
    empty picker to the settings screen and 400 ``does_not_exist`` to every
    PATCH — so ``app_language`` stayed NULL for every user, forever, and
    every notification fell back to guessing at their language.

    Measured on the meettoday sandbox 2026-08: 0 ``Language`` rows, 0 of 66
    profiles with an ``app_language``, and ``{"app_language": "en"}``
    rejected as nonexistent while ``settings.LANGUAGES`` declared exactly
    that code.

    So a declared code is accepted, and its row is materialised on first use
    (name from ``settings.LANGUAGES``; flags stay a ``sync_languages``
    concern). Rows that exist keep working unchanged — this only widens what
    a write may say, never narrows it.
    """

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError:
            from .models import declared_languages

            declared = declared_languages()
            code = str(data).strip()
            if code not in declared:
                raise
            language, _created = Language.objects.get_or_create(
                code=code, defaults={"name": str(declared[code])}
            )
            return language


class LanguageSerializer(serializers.ModelSerializer):
    """Serializer for Language model."""

    flag = serializers.SerializerMethodField()

    class Meta:
        model = Language
        fields = ["code", "name", "flag"]

    def get_flag(self, obj):
        """Return flag URL or None.

        Returns relative URL starting with / to avoid internal hostnames like dev.profiles.local
        """
        if obj.flag:
            # Return relative URL starting with /
            # obj.flag.url already includes MEDIA_URL prefix (e.g., /media/profiles/flags/...)
            return obj.flag.url
        return None


class ProfileSerializer(serializers.ModelSerializer):
    """Serializer for Profile model (full profile for /me endpoint).

    Only the hard core (§66) is listed here as-is. A project that swapped in
    an extended Profile (STAPEL_SWAP["PROFILES_PROFILE_MODEL"]) with extra
    standard/custom fields gets those through its OWN generated/hand-written
    serializer — this base serializer is the zero-customization contract,
    kept deliberately narrow so it never has to guess at fields that may not
    exist on a swapped-in model.
    """

    app_language = LanguageSerializer(read_only=True)
    understands = serializers.SlugRelatedField(
        many=True, slug_field="code", queryset=Language.objects.all()
    )
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    #: Read-only renderable descriptor denormalized from `avatar`+`avatar_source`
    #: (the raw `avatar` ref stays writable above for the upload round-trip).
    avatar_image = serializers.SerializerMethodField()

    class Meta:
        model = get_profile_model()
        fields = [
            "user_id",
            "display_name",
            "theme",
            "avatar_source",
            "avatar",
            "avatar_image",
            "location_id",
            "location_display_name_narrow",
            "location_display_name_broad",
            "app_language",
            "understands",
            "use_device_language",
            "auto_detected_language",
            "auto_translate_content",
            "email_messages",
            "email_system",
            "push_messages",
            "push_system",
            "essential_cookies_accepted",
            "initial_setup_passed",
            "followers_count",
            "following_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "user_id",
            "created_at",
            "updated_at",
            "location_display_name_narrow",
            "location_display_name_broad",
            "auto_detected_language",
        ]

    def get_followers_count(self, obj):
        """Get count of users following this profile."""
        return UserRelationship.objects.filter(
            following_id=obj.user_id, status="following"
        ).count()

    def get_following_count(self, obj):
        """Get count of users this profile is following."""
        return UserRelationship.objects.filter(
            follower_id=obj.user_id, status="following"
        ).count()

    @extend_schema_field(StapelImageSerializer)
    def get_avatar_image(self, obj):
        return avatar_image(obj)


#: Context keys a batched caller may fill so N profiles cost O(1) queries
#: instead of 3N (two COUNTs + one relationship lookup per row). Filled by
#: `views._batch_social_context()`; absent for the single-profile views,
#: which keep the per-row queries (one row, one query — nothing to batch).
CTX_FOLLOWERS = "batch_followers"
CTX_FOLLOWING = "batch_following"
CTX_RELATIONSHIPS = "batch_relationships"

#: The one entry that reopens the anonymous view to the full member set in
#: PROFILES_PUBLIC_FIELDS_ANONYMOUS. Not a wildcard over field names — a
#: whole-policy opt-out, expressible where a flat setting or env var cannot
#: carry `None`.
ANONYMOUS_FIELDS_SAME_AS_MEMBERS = "*"


class ProfilePublicSerializer(serializers.ModelSerializer):
    """Compact serializer for viewing other user's profile.

    The three social fields (`followers_count`, `following_count`,
    `relationship_status`) are per-row queries by default. A caller
    serializing MANY profiles at once (POST .../batch) precomputes them for
    the whole page and passes the maps through the serializer context (the
    `CTX_*` keys above); the methods below prefer the map when it is there.
    Without that, a 50-tile grid would trade 50 HTTP requests for 150 SQL
    queries — a worse deal than the problem the batch endpoint solves.
    """

    # VISIBILITY (security audit PROFILE-01). What a public lookup exposes
    # is a declared policy, not an accident of which fields this class
    # happens to list: PROFILES_PUBLIC_FIELDS is the set an authenticated
    # caller sees and PROFILES_PUBLIC_FIELDS_ANONYMOUS the one the internet
    # sees. Both public entry points — GET .../<user_id> and POST .../batch —
    # serialize through this class, so they cannot disagree about a person's
    # privacy. The anonymous default is deliberately NARROWER than the member
    # set (identity + avatar, no whereabouts and no social graph): these
    # endpoints are AllowAny and answer for any user id, so their default
    # answer is what an unauthenticated scraper gets. `None` (or ["*"])
    # restores "anonymous sees what members see" as a stated decision.
    # (Kept out of the docstring on purpose: the docstring is the emitted
    # OpenAPI component description, byte-compared against the monolith
    # aggregate's slice.)

    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    relationship_status = serializers.SerializerMethodField()
    #: Renderable descriptor for OTHER users' avatars (participant lists,
    #: waiting rooms) — same denormalize-next-to-the-ref rule as /me.
    avatar_image = serializers.SerializerMethodField()

    class Meta:
        model = get_profile_model()
        fields = [
            "user_id",
            "display_name",
            "avatar_source",
            "avatar",
            "avatar_image",
            "location_id",
            "location_display_name_narrow",
            "location_display_name_broad",
            "followers_count",
            "following_count",
            "relationship_status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in set(self.fields) - set(self._visible_fields()):
            self.fields.pop(name)

    def _visible_fields(self) -> list[str]:
        """The policy for THIS caller (see the class docstring)."""
        from .conf import profiles_settings

        visible = list(profiles_settings.PROFILES_PUBLIC_FIELDS or [])
        request = self.context.get("request")
        if request is None:
            # No caller at all: schema emission and internal construction.
            # The DECLARED surface of both endpoints is the member policy —
            # narrowing here would publish the anonymous subset as the
            # contract every client codegens against. Every HTTP path builds
            # this serializer with the request in context (views.py), so this
            # branch is never how a real caller is answered.
            return visible
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return visible
        anonymous = profiles_settings.PROFILES_PUBLIC_FIELDS_ANONYMOUS
        if anonymous is None or ANONYMOUS_FIELDS_SAME_AS_MEMBERS in anonymous:
            # The explicit reopening: this deployment states that anonymous
            # callers get the member view. `None` says it in a settings dict,
            # ["*"] says it in a form a flat setting / env var can carry.
            return visible
        # An anonymous policy may only ever narrow: a field the host hid from
        # members must not reappear for the internet through this list.
        return [name for name in anonymous if name in visible]

    def get_followers_count(self, obj) -> int:
        """Get count of users following this profile."""
        precomputed = self.context.get(CTX_FOLLOWERS)
        if precomputed is not None:
            return precomputed.get(obj.user_id, 0)
        return UserRelationship.objects.filter(
            following_id=obj.user_id, status="following"
        ).count()

    def get_following_count(self, obj) -> int:
        """Get count of users this profile is following."""
        precomputed = self.context.get(CTX_FOLLOWING)
        if precomputed is not None:
            return precomputed.get(obj.user_id, 0)
        return UserRelationship.objects.filter(
            follower_id=obj.user_id, status="following"
        ).count()

    @extend_schema_field(StapelImageSerializer)
    def get_avatar_image(self, obj):
        return avatar_image(obj)

    def get_relationship_status(self, obj) -> str | None:
        """Get relationship status with current user."""
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return None

        current_user_id = request.user.id
        if str(current_user_id) == str(obj.user_id):
            return "self"

        precomputed = self.context.get(CTX_RELATIONSHIPS)
        if precomputed is not None:
            # "No row" is "neutral" here exactly as in the per-row branch —
            # the absence of a relationship is a relationship state, not a
            # missing answer.
            return precomputed.get(obj.user_id, "neutral")

        try:
            relationship = UserRelationship.objects.get(
                follower_id=current_user_id, following_id=obj.user_id
            )
            return relationship.status
        except UserRelationship.DoesNotExist:
            return "neutral"


class ProfileCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating Profile (hard-core §66 fields only —
    see the ProfileSerializer docstring for why a swapped-in extended model's
    extra fields aren't listed here)."""

    display_name = serializers.CharField(
        max_length=35, required=False, allow_blank=True
    )
    theme = serializers.ChoiceField(choices=Theme.choices, required=False)
    avatar_source = serializers.ChoiceField(choices=AvatarSource.choices, required=False)
    avatar = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Avatar reference matching avatar_source (CDN ref / URL / "
                   "Gravatar hash / file key).",
    )
    location_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Location ID"
    )
    app_language = LanguageCodeField(
        slug_field="code",
        queryset=Language.objects.all(),
        required=False,
        allow_null=True,
    )
    understands = LanguageCodeField(
        many=True, slug_field="code", queryset=Language.objects.all(), required=False
    )
    use_device_language = serializers.BooleanField(required=False)
    auto_translate_content = serializers.BooleanField(required=False)
    email_messages = serializers.BooleanField(required=False)
    email_system = serializers.BooleanField(required=False)
    push_messages = serializers.BooleanField(required=False)
    push_system = serializers.BooleanField(required=False)
    essential_cookies_accepted = serializers.BooleanField(required=False)
    initial_setup_passed = serializers.BooleanField(required=False)

    class Meta:
        model = get_profile_model()
        fields = [
            "display_name",
            "theme",
            "avatar_source",
            "avatar",
            "location_id",
            "app_language",
            "understands",
            "use_device_language",
            "auto_translate_content",
            "email_messages",
            "email_system",
            "push_messages",
            "push_system",
            "essential_cookies_accepted",
            "initial_setup_passed",
        ]

    def _stated_avatar_source(self):
        """The source this REQUEST states, or `None` when it states nothing.

        The distinction is the whole design: a stated source is a belief that
        can be wrong and must be contradicted (400); an unstated one is a gap
        the ref itself fills (`models.resolve_avatar_source`).
        """
        stated = self.initial_data.get("avatar_source")
        return stated or None

    def _effective_avatar_source(self, value):
        """The source that will actually be stored for `value`."""
        stated = self._stated_avatar_source()
        if stated:
            return stated
        if is_cdn_avatar_reference(value):
            # Derived, not defaulted — see resolve_avatar_source.
            return AvatarSource.CDN
        if self.instance is not None:
            return self.instance.avatar_source
        return AvatarSource.FILE

    def validate_avatar(self, value):
        """Validate the avatar PAIR: format, source agreement, and existence.

        `file`/`url`/`gravatar` are free-form strings this serializer does not
        police the shape of; `cdn` keeps the fixed `avatar/<64-hex>` wire
        format + existence check. What is NEW here (and what the live
        meettoday outage cost): the check no longer only runs when the source
        already says `cdn` — i.e. only in the case that was already correct.
        A request whose ref is a CDN ref is now either tagged `cdn` by the
        caller, tagged `cdn` by derivation, or REJECTED. It can no longer end
        up stored as `file` because nobody said otherwise.
        """
        if not value:
            return value

        stated = self._stated_avatar_source()
        if (
            stated
            and stated != AvatarSource.CDN
            and is_cdn_avatar_reference(value)
        ):
            # The caller asserted a source the ref contradicts. Refuse rather
            # than coerce: coercing an ASSERTION hides the caller's bug, and
            # this is the bug that took the stand down.
            raise StapelValidationError(ERR_400_AVATAR_SOURCE_MISMATCH)

        source = self._effective_avatar_source(value)
        # The URL boundary (audit PROFILE-01): `url` and `gravatar` are
        # user-controlled values every consumer renders, so they are policed
        # on import — an active scheme, a plain-http reference, a host the
        # deployment does not allow, or a "hash" that is really a path never
        # becomes a stored profile field.
        if source == AvatarSource.URL:
            return validate_avatar_url(value)
        if source == AvatarSource.GRAVATAR:
            return validate_gravatar_hash(value)
        if source != AvatarSource.CDN:
            return value

        # Enforce the full reference contract ("avatar/<64-hex>"), not just
        # the presence of a slash — otherwise cross-type refs and path-like
        # strings slip through.
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            validate_avatar_reference(AvatarSource.CDN, value)
        except DjangoValidationError:
            raise StapelValidationError(ERR_400_INVALID_AVATAR_FORMAT)

        # Check avatar exists on CDN (read-only — no refs created).
        # Fail closed: an unverifiable reference is rejected, not accepted.
        from .conf import profiles_settings

        mode = profiles_settings.PROFILES_AVATAR_CHECK
        if mode == "off":
            # Escape hatch: skip the existence check (format already validated).
            return value

        # Default ("comm"): name-addressed function call — no direct
        # dependency on the CDN service's HTTP API.
        from stapel_core.comm import (
            FunctionCallError,
            FunctionNotRegistered,
            call,
        )

        try:
            result = call("cdn.media_exists", {"ref": value}, timeout=2.0)
            exists = bool(result.get("exists")) if isinstance(result, dict) else False
        except (FunctionCallError, FunctionNotRegistered):
            logger.warning("CDN avatar check failed for %s", value, exc_info=True)
            exists = False

        if not exists:
            raise StapelValidationError(ERR_400_AVATAR_NOT_FOUND)
        return value

    def validate(self, attrs):
        """Write the derived `avatar_source` into the data being saved.

        A request that sends only `avatar` used to leave the tag to the model
        default (`FILE`) — that is how the live rows got a CDN ref tagged
        `file`. Now the pair leaves this serializer complete. (The model's
        `save()` holds the same invariant for every writer that never passes
        through here; this one exists so the RESPONSE body already carries the
        source the caller will read back.)
        """
        attrs = super().validate(attrs)
        avatar = attrs.get("avatar")
        if (
            "avatar" in attrs
            and is_cdn_avatar_reference(avatar)
            and not self._stated_avatar_source()
        ):
            attrs["avatar_source"] = AvatarSource.CDN
        return attrs

    def update(self, instance, validated_data):
        # Capture old avatar for ref sync
        old_avatar = instance.avatar or ""
        fields_changed = sorted(validated_data.keys())

        result = super().update(instance, validated_data)

        # Sync CDN refs if avatar changed (tracking only — validation done in validate_avatar)
        new_avatar = instance.avatar or ""
        if "avatar" in validated_data and old_avatar != new_avatar:
            try:
                from stapel_core.django.cdn.ref_sync import sync_cdn_refs

                old_refs = [old_avatar] if old_avatar else []
                new_refs = [new_avatar] if new_avatar else []
                sync_cdn_refs(
                    "profiles", "profile", instance.user_id, old_refs, new_refs
                )
            except Exception:
                logger.warning(
                    "CDN ref sync failed for profile %s",
                    instance.user_id,
                    exc_info=True,
                )

        # Publish profile-changed event for SellerProfile sync
        from stapel_core.signals import profile_updated

        from .events import publish_profile_changed

        publish_profile_changed(instance)
        profile_updated.send(
            sender=Profile, profile=instance, fields_changed=fields_changed
        )

        return result

    def create(self, validated_data):
        fields_changed = sorted(validated_data.keys())
        result = super().create(validated_data)

        # Publish profile-changed event for SellerProfile sync
        from stapel_core.signals import profile_updated

        from .events import publish_profile_changed

        publish_profile_changed(result)
        profile_updated.send(
            sender=Profile, profile=result, fields_changed=fields_changed
        )

        return result


class UserRelationshipSerializer(serializers.ModelSerializer):
    """Serializer for UserRelationship model."""

    class Meta:
        model = UserRelationship
        fields = ["follower_id", "following_id", "status", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


# =============================================================================
# Dataclass Serializers (for API documentation)
# =============================================================================


class LanguageResponseSerializer(StapelDataclassSerializer):
    """Response serializer for language."""

    class Meta:
        dataclass = LanguageResponse


class ProfileResponseSerializer(StapelDataclassSerializer):
    """Response serializer for profile."""

    class Meta:
        dataclass = ProfileResponse


class ProfilePublicResponseSerializer(StapelDataclassSerializer):
    """Response serializer for public profile view."""

    class Meta:
        dataclass = ProfilePublicResponse


class ProfileUpdateRequestSerializer(StapelDataclassSerializer):
    """Request serializer for profile update."""

    class Meta:
        dataclass = ProfileUpdateRequest


class ProfileBatchRequestSerializer(StapelDataclassSerializer):
    """Request serializer for the batch profile lookup.

    Shape and types only. The `PROFILES_BATCH_MAX_IDS` ceiling is enforced
    in the view instead — it has to be answered as a first-class
    `error.400.too_many_ids` envelope carrying both numbers, and it has to
    reject a 10k-id body without parsing 10k UUIDs first.
    """

    class Meta:
        dataclass = ProfileBatchRequest


class ProfileBatchResponseSerializer(StapelDataclassSerializer):
    """Response serializer for the batch profile lookup (schema contract).

    Like every other `*ResponseSerializer` here it describes the wire shape
    for the contract emitter; the body itself is rendered by
    `ProfilePublicSerializer` in the view, off live model rows.
    """

    class Meta:
        dataclass = ProfileBatchResponse


class RelationshipResponseSerializer(StapelDataclassSerializer):
    """Response serializer for relationship."""

    class Meta:
        dataclass = RelationshipResponse


class RelationshipActionResponseSerializer(StapelDataclassSerializer):
    """Response serializer for relationship action."""

    class Meta:
        dataclass = RelationshipActionResponse


class FollowersResponseSerializer(StapelDataclassSerializer):
    """Response serializer for followers list."""

    class Meta:
        dataclass = FollowersResponse


class FollowingResponseSerializer(StapelDataclassSerializer):
    """Response serializer for following list."""

    class Meta:
        dataclass = FollowingResponse


class ProfileFieldManifestEntrySerializer(StapelDataclassSerializer):
    """Response serializer for one field-manifest entry (§66 data-driven skin)."""

    class Meta:
        dataclass = ProfileFieldManifestEntry
