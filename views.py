"""
Views for stapel-profiles service.
"""

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from stapel_core.core.language import (
    COOKIE_APP_LANGUAGE,
    COOKIE_USE_DEVICE_LANGUAGE,
    parse_accept_language,
)
from stapel_core.django.api.errors import (
    StapelErrorResponse,
    StapelErrorSerializer,
    StapelResponse,
)
from stapel_core.notifications.tokens import verify_unsubscribe_token

logger = logging.getLogger(__name__)
from stapel_profiles.errors import (
    ERR_400_CANNOT_BLOCK_SELF,
    ERR_400_CANNOT_FOLLOW_SELF,
    ERR_404_PROFILE_NOT_FOUND,
)

from .dto import (
    FollowersResponse,
    FollowingResponse,
    RelationshipActionResponse,
    RelationshipResponse,
)
from .field_defs import IDENTITY_PRESETS, STANDARD_FIELDS
from .models import Language, RelationshipStatus, UserRelationship, get_profile_model
from .serializers import (
    FollowersResponseSerializer,
    FollowingResponseSerializer,
    LanguageResponseSerializer,
    LanguageSerializer,
    ProfileCreateUpdateSerializer,
    ProfileFieldManifestEntrySerializer,
    ProfilePublicResponseSerializer,
    ProfilePublicSerializer,
    ProfileResponseSerializer,
    ProfileSerializer,
    ProfileUpdateRequestSerializer,
    RelationshipActionResponseSerializer,
    RelationshipResponseSerializer,
)

#: Resolved once at import time — the active (possibly host-swapped) Profile
#: DAO model (§66; same swap-at-import-time convention already used by
#: serializers.py's Meta.model and stapel_core's User-presenter pilot).
#: Views must never `from .models import Profile` directly — that is exactly
#: what SWAP001 (stapel_tools.swap_lint) flags.
Profile = get_profile_model()


class SerializerSeamsMixin:
    """Overridable serializer seams for API views.

    Subclasses (or downstream projects) can swap the request/response
    serializers without copying method bodies:

        class MyProfileViewV2(MyProfileView):
            response_serializer_class = MyProfileSerializer
    """

    request_serializer_class = None
    response_serializer_class = None

    def get_request_serializer_class(self):
        return self.request_serializer_class

    def get_response_serializer_class(self):
        return self.response_serializer_class


# =============================================================================
# Language Views
# =============================================================================


@extend_schema(tags=["Languages"])
class LanguageViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only viewset for languages.

    Owner UX audit 2026-07-17 (point 5): `GET /languages/` used to return
    every `Language` row with `is_active=True` — which, since the model
    defaults `is_active` to `True` and nothing seeds/syncs the table
    automatically (`sync_languages` is a manual management command, see its
    own docstring), meant either the FULL global fixture (33 languages,
    whatever `sync_languages` was last run against) or, on a deployment that
    never ran it at all, an EMPTY table — neither reflects which languages
    THIS project actually supports. `get_queryset` now additionally
    intersects with the project's own `django.conf.settings.LANGUAGES` (the
    standard Django i18n axis a real project already configures for
    translated UI strings) — a project that configured e.g. `[("en", …),
    ("ru", …)]` gets exactly those two; a project that never touched
    `LANGUAGES` still gets Django's own (large) built-in default, which is a
    permissive no-op filter, not a behavior change.
    """

    # Kept (in addition to `get_queryset` below) SOLELY so drf-spectacular can
    # still introspect the PK field (`code`, not `id`) for the `retrieve`
    # path parameter's name/type/description — dropping it silently renamed
    # the generated `{code}` path param to a generic `{id}` string. Runtime
    # filtering always goes through `get_queryset`, never this attribute.
    queryset = Language.objects.filter(is_active=True)
    serializer_class = LanguageSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        from django.conf import settings

        qs = Language.objects.filter(is_active=True)
        configured_codes = {code for code, _name in getattr(settings, "LANGUAGES", [])}
        if configured_codes:
            qs = qs.filter(code__in=configured_codes)
        return qs

    @extend_schema(
        operation_id="list_languages",
        summary="List all languages",
        description="Get list of all available languages.",
        responses={200: LanguageResponseSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="get_language",
        summary="Get language by code",
        description="Get language details by code.",
        responses={
            200: LanguageResponseSerializer,
            404: StapelErrorSerializer,
        },
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


# =============================================================================
# Profile Views
# =============================================================================


def _set_language_cookies(response, profile):
    """Set language preference cookies from profile."""
    from django.conf import settings

    cookie_domain = getattr(settings, "JWT_COOKIE_DOMAIN", None)
    cookie_secure = getattr(settings, "JWT_COOKIE_SECURE", False)
    cookie_samesite = getattr(settings, "JWT_COOKIE_SAMESITE", "Lax")
    max_age = 365 * 24 * 3600  # 1 year

    kwargs = dict(
        max_age=max_age,
        domain=cookie_domain,
        path="/",
        secure=cookie_secure,
        httponly=False,  # readable by frontend
        samesite=cookie_samesite,
    )

    app_lang = profile.app_language_id  # FK code or None
    if app_lang:
        response.set_cookie(COOKIE_APP_LANGUAGE, app_lang, **kwargs)
    else:
        response.delete_cookie(COOKIE_APP_LANGUAGE, domain=cookie_domain, path="/")

    response.set_cookie(
        COOKIE_USE_DEVICE_LANGUAGE,
        "1" if profile.use_device_language else "0",
        **kwargs,
    )
    return response


def _update_auto_detected_language(request, profile):
    """Update auto_detected_language from Accept-Language header if changed."""
    detected = parse_accept_language(request.META.get("HTTP_ACCEPT_LANGUAGE", ""))
    if detected and detected != profile.auto_detected_language:
        profile.auto_detected_language = detected
        profile.save(update_fields=["auto_detected_language"])


@extend_schema(tags=["Profile"])
class MyProfileView(SerializerSeamsMixin, APIView):
    """Current user's profile management."""

    permission_classes = [IsAuthenticated]
    request_serializer_class = ProfileCreateUpdateSerializer
    response_serializer_class = ProfileSerializer

    @extend_schema(
        operation_id="get_my_profile",
        summary="Get my profile",
        description="Get current user's profile. Creates profile with defaults if not exists.",
        responses={
            200: ProfileResponseSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):  # noqa: R007
        """Get or create current user's profile."""
        profile, created = Profile.objects.get_or_create(user_id=request.user.id)
        _update_auto_detected_language(request, profile)
        serializer = self.get_response_serializer_class()(
            profile, context={"request": request}
        )
        response = Response(serializer.data)
        _set_language_cookies(response, profile)
        return response

    @extend_schema(
        operation_id="update_my_profile",
        summary="Update my profile",
        description="Update current user's profile. All fields are optional (PATCH semantics).",
        request=ProfileUpdateRequestSerializer,
        responses={
            200: ProfileResponseSerializer,
            400: StapelErrorSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def patch(self, request):  # noqa: R007
        """Update current user's profile."""
        profile, created = Profile.objects.get_or_create(user_id=request.user.id)
        serializer = self.get_request_serializer_class()(
            profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        _update_auto_detected_language(request, profile)

        # Return full profile with nested data
        response_serializer = self.get_response_serializer_class()(
            profile, context={"request": request}
        )
        response = Response(response_serializer.data)
        _set_language_cookies(response, profile)
        return response


@extend_schema(tags=["Profile"])
class ProfileDetailView(SerializerSeamsMixin, APIView):
    """View other user's profile (compact public view)."""

    permission_classes = [AllowAny]
    response_serializer_class = ProfilePublicSerializer

    @extend_schema(
        operation_id="get_profile",
        summary="Get user profile",
        description="Get compact profile of a specific user by UUID. Includes relationship status with current user if authenticated.",
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="User UUID",
            )
        ],
        responses={
            200: ProfilePublicResponseSerializer,
            404: StapelErrorSerializer,
        },
    )
    def get(self, request, user_id):  # noqa: R007
        """Get user profile by UUID."""
        try:
            profile = Profile.objects.get(user_id=user_id)
        except Profile.DoesNotExist:
            return StapelErrorResponse(404, ERR_404_PROFILE_NOT_FOUND)
        serializer = self.get_response_serializer_class()(
            profile, context={"request": request}
        )
        return StapelResponse(serializer)


# =============================================================================
# Relationship Views
# =============================================================================


@extend_schema(tags=["Relationships"])
class FollowView(SerializerSeamsMixin, APIView):
    """Follow a user."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = RelationshipActionResponseSerializer

    @extend_schema(
        operation_id="follow_user",
        summary="Follow user",
        description='Follow a user. Creates or updates relationship to "following" status.',
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="User UUID to follow",
            )
        ],
        request=None,
        responses={
            200: RelationshipActionResponseSerializer,
            400: StapelErrorSerializer,
            401: OpenApiTypes.OBJECT,
            404: StapelErrorSerializer,
        },
    )
    def post(self, request, user_id):  # noqa: R007
        """Follow a user."""
        follower_id = request.user.id

        if str(follower_id) == str(user_id):
            return StapelErrorResponse(400, ERR_400_CANNOT_FOLLOW_SELF)

        if not Profile.objects.filter(user_id=user_id).exists():
            return StapelErrorResponse(404, ERR_404_PROFILE_NOT_FOUND)

        relationship, created = UserRelationship.objects.update_or_create(
            follower_id=follower_id,
            following_id=user_id,
            defaults={"status": RelationshipStatus.FOLLOWING},
        )

        dto = RelationshipActionResponse(success=True, status=relationship.status)
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Relationships"])
class UnfollowView(SerializerSeamsMixin, APIView):
    """Unfollow a user."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = RelationshipActionResponseSerializer

    @extend_schema(
        operation_id="unfollow_user",
        summary="Unfollow user",
        description='Unfollow a user. Sets relationship to "neutral" status.',
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="User UUID to unfollow",
            )
        ],
        request=None,
        responses={
            200: RelationshipActionResponseSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request, user_id):  # noqa: R007
        """Unfollow a user."""
        follower_id = request.user.id

        # Only clear a FOLLOWING relationship: unfollow must not silently
        # unblock, and it must not create rows for users never followed.
        UserRelationship.objects.filter(
            follower_id=follower_id,
            following_id=user_id,
            status=RelationshipStatus.FOLLOWING,
        ).delete()

        current = (
            UserRelationship.objects.filter(
                follower_id=follower_id, following_id=user_id
            )
            .values_list("status", flat=True)
            .first()
        ) or RelationshipStatus.NEUTRAL

        dto = RelationshipActionResponse(success=True, status=current)
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Relationships"])
class BlockView(SerializerSeamsMixin, APIView):
    """Block a user."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = RelationshipActionResponseSerializer

    @extend_schema(
        operation_id="block_user",
        summary="Block user",
        description='Block a user. Creates or updates relationship to "blocked" status.',
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="User UUID to block",
            )
        ],
        request=None,
        responses={
            200: RelationshipActionResponseSerializer,
            400: StapelErrorSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request, user_id):  # noqa: R007
        """Block a user."""
        follower_id = request.user.id

        if str(follower_id) == str(user_id):
            return StapelErrorResponse(400, ERR_400_CANNOT_BLOCK_SELF)

        relationship, created = UserRelationship.objects.update_or_create(
            follower_id=follower_id,
            following_id=user_id,
            defaults={"status": RelationshipStatus.BLOCKED},
        )

        dto = RelationshipActionResponse(success=True, status=relationship.status)
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Relationships"])
class UnblockView(SerializerSeamsMixin, APIView):
    """Unblock a user."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = RelationshipActionResponseSerializer

    @extend_schema(
        operation_id="unblock_user",
        summary="Unblock user",
        description='Unblock a user. Sets relationship to "neutral" status.',
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="User UUID to unblock",
            )
        ],
        request=None,
        responses={
            200: RelationshipActionResponseSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request, user_id):  # noqa: R007
        """Unblock a user."""
        follower_id = request.user.id

        # Only clear a BLOCKED relationship; do not create rows for users
        # who were never blocked.
        UserRelationship.objects.filter(
            follower_id=follower_id,
            following_id=user_id,
            status=RelationshipStatus.BLOCKED,
        ).delete()

        current = (
            UserRelationship.objects.filter(
                follower_id=follower_id, following_id=user_id
            )
            .values_list("status", flat=True)
            .first()
        ) or RelationshipStatus.NEUTRAL

        dto = RelationshipActionResponse(success=True, status=current)
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Relationships"])
class RelationshipStatusView(SerializerSeamsMixin, APIView):
    """Get relationship status with a user."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = RelationshipResponseSerializer

    @extend_schema(
        operation_id="get_relationship",
        summary="Get relationship status",
        description="Get current relationship status with a user.",
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="User UUID",
            )
        ],
        responses={
            200: RelationshipResponseSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request, user_id):  # noqa: R007
        """Get relationship status with a user."""
        follower_id = request.user.id

        try:
            relationship = UserRelationship.objects.get(
                follower_id=follower_id, following_id=user_id
            )
            dto = RelationshipResponse(user_id=user_id, status=relationship.status)
            return StapelResponse(self.get_response_serializer_class()(dto))
        except UserRelationship.DoesNotExist:
            dto = RelationshipResponse(
                user_id=user_id, status=RelationshipStatus.NEUTRAL
            )
            return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Relationships"])
class MyFollowersView(SerializerSeamsMixin, APIView):
    """List current user's followers."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = FollowersResponseSerializer

    @extend_schema(
        operation_id="get_my_followers",
        summary="Get my followers",
        description="Get list of users following the current user.",
        responses={
            200: FollowersResponseSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):  # noqa: R007
        """Get followers of current user."""
        user_id = request.user.id

        followers = UserRelationship.objects.filter(
            following_id=user_id, status=RelationshipStatus.FOLLOWING
        ).values_list("follower_id", flat=True)

        followers_list = list(followers)
        dto = FollowersResponse(followers=followers_list, count=len(followers_list))
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Relationships"])
class MyFollowingView(SerializerSeamsMixin, APIView):
    """List users the current user is following."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = FollowingResponseSerializer

    @extend_schema(
        operation_id="get_my_following",
        summary="Get my following",
        description="Get list of users the current user is following.",
        responses={
            200: FollowingResponseSerializer,
            401: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):  # noqa: R007
        """Get users current user is following."""
        user_id = request.user.id

        following = UserRelationship.objects.filter(
            follower_id=user_id, status=RelationshipStatus.FOLLOWING
        ).values_list("following_id", flat=True)

        following_list = list(following)
        dto = FollowingResponse(following=following_list, count=len(following_list))
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Relationships"])
class MyBlockedView(SerializerSeamsMixin, APIView):
    """List profiles of users the current user has blocked."""

    permission_classes = [IsAuthenticated]
    response_serializer_class = ProfilePublicSerializer

    @extend_schema(
        operation_id="get_my_blocked",
        summary="Get my blocked users",
        description="Get list of profiles of users the current user has blocked.",
        responses={
            200: ProfilePublicSerializer(many=True),
            401: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):  # noqa: R007
        """Get profiles of blocked users."""
        user_id = request.user.id

        blocked_ids = UserRelationship.objects.filter(
            follower_id=user_id, status=RelationshipStatus.BLOCKED
        ).values_list("following_id", flat=True)

        profiles = Profile.objects.filter(user_id__in=blocked_ids)
        # Public serializer only: these are other users' profiles — the
        # private ProfileSerializer would leak their settings and consents.
        serializer = self.get_response_serializer_class()(
            profiles, many=True, context={"request": request}
        )
        return StapelResponse(serializer)


# =============================================================================
# Unsubscribe
# =============================================================================


@extend_schema(tags=["Notifications"])
class UnsubscribeView(APIView):
    """One-click unsubscribe via HMAC token (RFC 8058)."""

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="unsubscribe_notifications",
        summary="Unsubscribe from notifications",
        description="Verify HMAC token and toggle the corresponding notification preference off. "
        "Uses POST per RFC 8058 (List-Unsubscribe-Post).",
        parameters=[
            OpenApiParameter(
                name="token", type=str, location=OpenApiParameter.QUERY, required=True
            ),
        ],
        request=None,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):  # noqa: R007
        token = request.query_params.get("token", "") or request.data.get("token", "")
        result = verify_unsubscribe_token(token)
        if not result:
            return StapelResponse(  # noqa: R006
                {"error": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id = result["user_id"]
        group = result["group"]
        channel = result["channel"]

        # Map to profile field
        field_name = f"{channel}_{group}"
        if field_name not in (
            "email_messages",
            "email_system",
            "push_messages",
            "push_system",
        ):
            return StapelResponse(  # noqa: R006
                {"error": "Invalid preference"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            profile = Profile.objects.get(user_id=user_id)
        except Profile.DoesNotExist:
            return StapelResponse(  # noqa: R006
                {"error": "Profile not found"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Skip if already unsubscribed (idempotent)
        if getattr(profile, field_name) is False:
            return StapelResponse({"success": True, "unsubscribed": field_name})  # noqa: R006

        setattr(profile, field_name, False)
        profile.save(update_fields=[field_name])

        from stapel_core.signals import profile_updated

        from .events import publish_profile_changed

        publish_profile_changed(profile)
        profile_updated.send(
            sender=Profile, profile=profile, fields_changed=[field_name]
        )

        return StapelResponse({"success": True, "unsubscribed": field_name})  # noqa: R006


# =============================================================================
# Field manifest (§66 — data-driven skin, tier 1)
# =============================================================================


def _active_field_manifest():
    """Build the ordered list of `ProfileFieldManifestEntry` for the
    project's configured manifest (`STAPEL_PROFILES["FIELDS"]` /
    `PROFILES_FIELDS`) — identity preset first, then standard_fields in
    listed order, then custom_fields (already `ProfileFieldDef` instances,
    since a project's own occupation/camera_on/... enums aren't stapel's to
    import). An empty/unset manifest yields an empty list — the hard core
    (avatar/language/timestamps/onboarding/consent) is not "a field" in this
    sense, it's never absent, so it has no manifest entry.
    """
    from .conf import profiles_settings
    from .dto import ProfileFieldManifestEntry

    def _entry(field_def, order):
        # SWAP002 exemption (deliberate, not an oversight): the lint's whole
        # point is "a DAO->DTO mapping a host presenter swap could not
        # intercept" — there is no DAO row here at all, this DTO is built
        # straight from the field-def *registry* (config, not data), which
        # is exactly what a host customizes by changing STAPEL_PROFILES
        # instead of by swapping a presenter.
        return ProfileFieldManifestEntry(  # noqa: SWAP002
            name=field_def.name, kind=field_def.kind.value,
            docstring=field_def.doc, required=not field_def.blank,
            order=order, enum_values=field_def.enum_values,
        )

    manifest = profiles_settings.PROFILES_FIELDS or {}
    entries = []
    order = 0

    identity = manifest.get("identity")
    if identity:
        for field_def in IDENTITY_PRESETS.get(identity, ()):
            entries.append(_entry(field_def, order))
            order += 1

    for key in manifest.get("standard_fields", ()):
        field_def = STANDARD_FIELDS.get(key)
        if field_def is None:
            continue
        entries.append(_entry(field_def, order))
        order += 1

    for field_def in manifest.get("custom_fields", ()):
        entries.append(_entry(field_def, order))
        order += 1

    return entries


@extend_schema(tags=["Profile"])
class FieldManifestView(APIView):
    """Active profile field manifest — canon for the frontend's data-driven
    skin (docs/pending/profile-fields.md, "Дополнение владельца" §1): the
    default skin renders identity/standard/custom fields from this response
    instead of a hardcoded field list, so a host's STAPEL_PROFILES["FIELDS"]
    selection is reflected in the UI with zero frontend code changes.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="get_field_manifest",
        summary="Get active profile field manifest",
        description="List the profile fields the project's manifest activated "
        "(identity preset + standard_fields + custom_fields), in declaration order.",
        responses={200: ProfileFieldManifestEntrySerializer(many=True)},
    )
    def get(self, request):  # noqa: R007
        """List active profile fields for the data-driven skin."""
        entries = _active_field_manifest()
        serializer = ProfileFieldManifestEntrySerializer(entries, many=True)
        return StapelResponse(serializer)
