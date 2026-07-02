"""
Serializers for stapel-profiles service.
"""

import logging

from rest_framework import serializers
from stapel_core.django.api.errors import StapelValidationError
from stapel_core.django.api.serializers import StapelDataclassSerializer

from .errors import (
    ERR_400_AVATAR_NOT_FOUND,
    ERR_400_INVALID_AVATAR_FORMAT,
)

logger = logging.getLogger(__name__)

from .dto import (
    FollowersResponse,
    FollowingResponse,
    LanguageResponse,
    ProfilePublicResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    RelationshipActionResponse,
    RelationshipResponse,
)
from .models import (
    Language,
    MeasurementUnit,
    Profile,
    Theme,
    UserRelationship,
)

# =============================================================================
# Model Serializers
# =============================================================================


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
    """Serializer for Profile model (full profile for /me endpoint)."""

    app_language = LanguageSerializer(read_only=True)
    understands = serializers.SlugRelatedField(
        many=True, slug_field="code", queryset=Language.objects.all()
    )
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "user_id",
            "display_name",
            "avatar",
            "location_id",
            "location_display_name_narrow",
            "location_display_name_broad",
            "currency_code",
            "measurement_units",
            "theme",
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


class ProfilePublicSerializer(serializers.ModelSerializer):
    """Compact serializer for viewing other user's profile."""

    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    relationship_status = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "user_id",
            "display_name",
            "avatar",
            "location_id",
            "location_display_name_narrow",
            "location_display_name_broad",
            "followers_count",
            "following_count",
            "relationship_status",
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

    def get_relationship_status(self, obj):
        """Get relationship status with current user."""
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return None

        current_user_id = request.user.id
        if str(current_user_id) == str(obj.user_id):
            return "self"

        try:
            relationship = UserRelationship.objects.get(
                follower_id=current_user_id, following_id=obj.user_id
            )
            return relationship.status
        except UserRelationship.DoesNotExist:
            return "neutral"


class ProfileCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating Profile."""

    display_name = serializers.CharField(
        required=False, max_length=35, allow_blank=True
    )
    avatar = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="CDN avatar reference (avatar/hash)",
    )
    location_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Location ID"
    )
    app_language = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Language.objects.all(),
        required=False,
        allow_null=True,
    )
    understands = serializers.SlugRelatedField(
        many=True, slug_field="code", queryset=Language.objects.all(), required=False
    )
    currency_code = serializers.CharField(required=False, max_length=3)
    measurement_units = serializers.ChoiceField(
        choices=MeasurementUnit.choices, required=False
    )
    theme = serializers.ChoiceField(choices=Theme.choices, required=False)
    use_device_language = serializers.BooleanField(required=False)
    auto_translate_content = serializers.BooleanField(required=False)
    email_messages = serializers.BooleanField(required=False)
    email_system = serializers.BooleanField(required=False)
    push_messages = serializers.BooleanField(required=False)
    push_system = serializers.BooleanField(required=False)
    essential_cookies_accepted = serializers.BooleanField(required=False)
    initial_setup_passed = serializers.BooleanField(required=False)

    class Meta:
        model = Profile
        fields = [
            "display_name",
            "avatar",
            "location_id",
            "currency_code",
            "measurement_units",
            "theme",
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

    def validate_display_name(self, value):
        """Trim and validate display_name."""
        if isinstance(value, str):
            value = value.strip()
        if value:
            from .validators import validate_display_name

            validate_display_name(value)
        return value

    def validate_avatar(self, value):
        """Validate avatar format and existence on CDN."""
        if not value:
            return value

        # Enforce the full reference contract ("avatar/<64-hex>"), not just
        # the presence of a slash — otherwise cross-type refs and path-like
        # strings slip through.
        from django.core.exceptions import ValidationError as DjangoValidationError

        from stapel_core.django.cdn.fields import validate_cdn_reference

        try:
            validate_cdn_reference(value, "avatar")
        except DjangoValidationError:
            raise StapelValidationError(ERR_400_INVALID_AVATAR_FORMAT)

        # Check avatar exists on CDN (read-only — no refs created).
        # Fail closed: an unverifiable reference is rejected, not accepted.
        try:
            from stapel_core.django.cdn.ref_sync import check_cdn_media_exists

            exists = check_cdn_media_exists(value)
        except Exception:
            logger.warning("CDN avatar check failed for %s", value, exc_info=True)
            exists = False
        if not exists:
            raise StapelValidationError(ERR_400_AVATAR_NOT_FOUND)
        return value

    def update(self, instance, validated_data):
        # Capture old avatar for ref sync
        old_avatar = instance.avatar or ""

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
        from .events import publish_profile_changed

        publish_profile_changed(instance)

        return result

    def create(self, validated_data):
        result = super().create(validated_data)

        # Publish profile-changed event for SellerProfile sync
        from .events import publish_profile_changed

        publish_profile_changed(result)

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
