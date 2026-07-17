"""
URL configuration for profiles app.
"""
from typing import NamedTuple

from django.urls import path, include
from stapel_core.django.api.routers import OptionalSlashRouter

from .views import (
    LanguageViewSet,
    MyProfileView,
    ProfileDetailView,
    FollowView,
    UnfollowView,
    BlockView,
    UnblockView,
    RelationshipStatusView,
    MyFollowersView,
    MyFollowingView,
    MyBlockedView,
    UnsubscribeView,
    FieldManifestView,
)

router = OptionalSlashRouter()
router.register(r'languages', LanguageViewSet, basename='language')

urlpatterns = [
    # Router URLs (languages)
    path('', include(router.urls)),

    # Profile endpoints
    path('me', MyProfileView.as_view(), name='my-profile'),
    path('me/followers', MyFollowersView.as_view(), name='my-followers'),
    path('me/following', MyFollowingView.as_view(), name='my-following'),
    path('me/blocked', MyBlockedView.as_view(), name='my-blocked'),
    path('field-manifest', FieldManifestView.as_view(), name='field-manifest'),
    path('<uuid:user_id>', ProfileDetailView.as_view(), name='profile-detail'),

    # Relationship actions
    path('<uuid:user_id>/follow', FollowView.as_view(), name='follow-user'),
    path('<uuid:user_id>/unfollow', UnfollowView.as_view(), name='unfollow-user'),
    path('<uuid:user_id>/block', BlockView.as_view(), name='block-user'),
    path('<uuid:user_id>/unblock', UnblockView.as_view(), name='unblock-user'),
    path('<uuid:user_id>/relationship', RelationshipStatusView.as_view(), name='relationship-status'),

    # Notification unsubscribe
    path('notifications/unsubscribe', UnsubscribeView.as_view(), name='unsubscribe'),
]


class GateEntry(NamedTuple):
    """One gated URL block: which flags gate which url patterns (capability-config.md §2 p.2).

    ``flags`` compose with OR — the block is mounted while ANY flag is on,
    and disappears only when ALL of them are off. Empty flags = always on.
    """
    name: str
    flags: tuple
    patterns: tuple


#: Gate registry (capability-config.md §2 p.2): profiles has no per-method
#: config gates (unlike auth) — the whole URL surface is a single always-on
#: block. Declared as a registry entry (rather than left implicit) so the
#: capabilities.json emitter has a uniform mechanism across every module.
GATE_REGISTRY: dict = {
    'profiles.api': GateEntry('profiles.api', (), tuple(urlpatterns)),
}
