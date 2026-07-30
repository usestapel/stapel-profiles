"""
Views for stapel-profiles service.

Guest (anonymous session) stance
--------------------------------
With ``AUTH_ANONYMOUS`` on, a guest session is ``is_authenticated``, so a bare
``IsAuthenticated`` says nothing about whether guests belong on a view
(``stapel_core.adoption`` E001/W002). Every view here states its answer, and
the module's rule is one line:

    **a guest may see the social graph, and may not write to it.**

Reading is safe and useful: every read below is scoped to
``request.user.id``, so a guest's answer is their own — necessarily empty or
``neutral``. Returning that empty answer is better than a 403, because the
caller is usually a frontend deciding what a "Follow" button should look like
for a visitor who has not registered yet.

Writing is not: follow/block mint a durable ``UserRelationship`` edge, and an
anonymous account is throwaway by construction — the edge outlives the
session that made it and can never be managed by anyone. Those four views
carry :class:`~stapel_core.django.api.permissions.IsNotAnonymousUser`.

``MyProfileView`` is the exception that proves the axis exists: it is on the
live guest path of a real consumer (meettoday — a guest types their display
name at ``PATCH /profiles/api/v1/me`` *before* joining a call, and the app
header reads the same view for the guest session). It is explicitly
``ANONYMOUS_ALLOWED``.
"""

import logging

from django.db.models import Count
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
from stapel_core.django.api.permissions import (
    ANONYMOUS_ALLOWED,
    IsNotAnonymousUser,
)
from stapel_core.notifications.tokens import verify_unsubscribe_token

logger = logging.getLogger(__name__)
from stapel_profiles.errors import (
    ERR_400_CANNOT_BLOCK_SELF,
    ERR_400_CANNOT_FOLLOW_SELF,
    ERR_400_TOO_MANY_IDS,
    ERR_404_PROFILE_NOT_FOUND,
)

from .conf import profiles_settings

from .dto import (
    FollowersResponse,
    FollowingResponse,
    RelationshipActionResponse,
    RelationshipResponse,
)
from .field_defs import IDENTITY_PRESETS, STANDARD_FIELDS
from .models import Language, RelationshipStatus, UserRelationship, get_profile_model
from .serializers import (
    CTX_FOLLOWERS,
    CTX_FOLLOWING,
    CTX_RELATIONSHIPS,
    FollowersResponseSerializer,
    FollowingResponseSerializer,
    LanguageResponseSerializer,
    LanguageSerializer,
    ProfileBatchRequestSerializer,
    ProfileBatchResponseSerializer,
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
    # A guest has a "me" too, and this is the view that gives them one: in
    # meettoday the display-name prompt shown *before* a guest joins a call
    # is a PATCH here, and the app header reads the same view for the guest
    # session. Both halves are scoped to `request.user.id` — a guest can only
    # ever read and write their own row.
    stapel_anonymous_access = ANONYMOUS_ALLOWED
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


def _batch_social_context(request, profiles):
    """Precompute the three social fields for a whole page of profiles.

    `ProfilePublicSerializer` computes `followers_count`, `following_count`
    and `relationship_status` with one query each per row. Serving a
    50-profile batch that way would swap 50 HTTP round-trips for 150 SQL
    queries — a worse deal than the problem the batch endpoint solves. Three
    grouped queries answer the whole page instead, handed to the serializer
    through the `CTX_*` context keys.

    A count that is absent from a map means zero, and a relationship absent
    from the map means `neutral` — the same reading as the per-row branch,
    because "no row" is an answer here, not a hole.
    """
    ids = [p.user_id for p in profiles]
    if not ids:
        return {}

    followers = dict(
        UserRelationship.objects.filter(
            following_id__in=ids, status=RelationshipStatus.FOLLOWING
        )
        .values_list("following_id")
        .annotate(n=Count("id"))
    )
    following = dict(
        UserRelationship.objects.filter(
            follower_id__in=ids, status=RelationshipStatus.FOLLOWING
        )
        .values_list("follower_id")
        .annotate(n=Count("id"))
    )

    relationships = {}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        relationships = dict(
            UserRelationship.objects.filter(
                follower_id=user.id, following_id__in=ids
            ).values_list("following_id", "status")
        )

    return {
        CTX_FOLLOWERS: followers,
        CTX_FOLLOWING: following,
        CTX_RELATIONSHIPS: relationships,
    }


@extend_schema(tags=["Profile"])
class ProfileBatchView(SerializerSeamsMixin, APIView):
    """Resolve many public profiles in one request (#111).

    A contact grid used to fire one `GET .../<id>` per tile and take a 404
    for every person who had never opened settings — 16 red lines in the
    console for a screen that was working exactly as intended. Two things
    were wrong with that: the fan-out, and calling a normal state an error.
    This endpoint fixes both, and the second one is the important one.

    Permission parity with `ProfileDetailView` (`AllowAny`): the batch
    exposes nothing the per-id endpoint does not already expose to the same
    caller, and a batch that answered differently from the single lookup
    would be a seam where the two disagree. `PROFILES_BATCH_MAX_IDS` caps
    how much one request can amplify.
    """

    permission_classes = [AllowAny]
    request_serializer_class = ProfileBatchRequestSerializer
    response_serializer_class = ProfilePublicSerializer

    @extend_schema(
        operation_id="batch_profiles",
        summary="Get many user profiles at once",
        description=(
            "Resolve up to PROFILES_BATCH_MAX_IDS (default 100) public "
            "profiles in one call. Ids with no profile row come back in "
            "`missing` — a normal state, never a 404. Ids in neither list "
            "were not part of the request. Over the limit the request is "
            "refused with `error.400.too_many_ids` carrying both numbers; "
            "the list is never silently truncated."
        ),
        request=ProfileBatchRequestSerializer,
        responses={
            200: ProfileBatchResponseSerializer,
            400: StapelErrorSerializer,
        },
    )
    def post(self, request):  # noqa: R007
        """Resolve a list of user ids to public profiles."""
        submitted = request.data.get("user_ids")
        limit = int(profiles_settings.PROFILES_BATCH_MAX_IDS)
        if isinstance(submitted, list) and len(submitted) > limit:
            # Refused, not truncated. A short 200 would render the overflow
            # as people who "have no profile" — a wrong answer delivered as
            # a successful one, with nothing saying part of the question was
            # dropped. Both numbers ride along so the caller can chunk
            # deterministically instead of bisecting the limit by hand.
            #
            # Checked on the payload as submitted, before parsing: the
            # ceiling bounds what the caller sends, so it must not depend on
            # how much of it happens to be redundant (a limit that
            # "sometimes lets 150 through" is not one anybody can code
            # against), and a 10k-id body must not cost 10k UUID parses to
            # reject. Anything that is not a list falls through to the
            # serializer's ordinary type error.
            return StapelErrorResponse(
                400,
                ERR_400_TOO_MANY_IDS,
                params={"requested": len(submitted), "limit": limit},
            )

        request_serializer = self.get_request_serializer_class()(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        # De-duplicate while keeping first-seen order: the response order is
        # the caller's order, so a grid can zip it back onto its tiles.
        requested = list(dict.fromkeys(request_serializer.validated_data.user_ids))

        found = {p.user_id: p for p in Profile.objects.filter(user_id__in=requested)}
        profiles = [found[uid] for uid in requested if uid in found]
        missing = [uid for uid in requested if uid not in found]

        context = {"request": request, **_batch_social_context(request, profiles)}
        serializer = self.get_response_serializer_class()(
            profiles, many=True, context=context
        )
        return StapelResponse({"profiles": serializer.data, "missing": missing})  # noqa: R006


# =============================================================================
# Relationship Views
# =============================================================================


@extend_schema(tags=["Relationships"])
class FollowView(SerializerSeamsMixin, APIView):
    """Follow a user."""

    # A follow is a durable edge; an anonymous account is throwaway. The edge
    # would outlive the session that made it, with nobody left to unfollow.
    permission_classes = [IsNotAnonymousUser]
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

    # Mirror of FollowView: a session that cannot follow has nothing to undo.
    permission_classes = [IsNotAnonymousUser]
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

    # Same durable edge as FollowView, and worse if left open: a block placed
    # by a throwaway account is a moderation decision nobody can revisit.
    permission_classes = [IsNotAnonymousUser]
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

    # Mirror of BlockView: a session that cannot block has nothing to undo.
    permission_classes = [IsNotAnonymousUser]
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
    # Read of the caller's own row. A guest cannot follow or block, so the
    # answer is always `neutral` — and `neutral` is the right answer for the
    # caller (a frontend rendering a "Follow" button for a visitor), where a
    # 403 would only make it render an error instead.
    stapel_anonymous_access = ANONYMOUS_ALLOWED
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
    # Own rows only (`following_id=request.user.id`); for a guest the list is
    # necessarily empty. An empty list is the truth, a 403 would not be.
    stapel_anonymous_access = ANONYMOUS_ALLOWED
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
    # Mirror of MyFollowersView: own rows only, empty for a guest.
    stapel_anonymous_access = ANONYMOUS_ALLOWED
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
    # Own rows only (`follower_id=request.user.id`); a guest cannot block, so
    # the list is necessarily empty and nothing about anyone else is exposed.
    stapel_anonymous_access = ANONYMOUS_ALLOWED
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
