"""
URL configuration for profiles app.
"""
from django.urls import path, include
from stapel_core.django.routers import OptionalSlashRouter

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
