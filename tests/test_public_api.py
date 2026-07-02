"""Tests for the package-level public API (__all__, lazy PEP 562 exports)
and the serializer seams on the API views."""

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

import stapel_profiles


class TestPublicAPI:
    def test_all_matches_exports(self):
        assert sorted(stapel_profiles.__all__) == sorted(
            [
                "profiles_settings",
                "publish_profile_changed",
                "validate_display_name",
                "ProfilesGDPRProvider",
            ]
        )

    def test_lazy_exports_resolve(self):
        from stapel_profiles.conf import profiles_settings
        from stapel_profiles.events import publish_profile_changed
        from stapel_profiles.gdpr import ProfilesGDPRProvider
        from stapel_profiles.validators import validate_display_name

        assert stapel_profiles.profiles_settings is profiles_settings
        assert stapel_profiles.publish_profile_changed is publish_profile_changed
        assert stapel_profiles.validate_display_name is validate_display_name
        assert stapel_profiles.ProfilesGDPRProvider is ProfilesGDPRProvider

    def test_dir_lists_exports(self):
        assert set(stapel_profiles.__all__) <= set(dir(stapel_profiles))

    def test_unknown_attribute_raises(self):
        with pytest.raises(AttributeError):
            stapel_profiles.does_not_exist


@pytest.mark.django_db
class TestSerializerSeams:
    def test_subclass_can_swap_response_serializer(self, user):
        """A view subclass overriding response_serializer_class changes the
        payload without touching the method bodies."""
        from stapel_profiles.serializers import RelationshipActionResponseSerializer
        from stapel_profiles.views import MyFollowersView, UnfollowView

        class StampedSerializer(RelationshipActionResponseSerializer):
            def to_representation(self, instance):
                data = super().to_representation(instance)
                data["swapped"] = True
                return data

        class StampedUnfollowView(UnfollowView):
            response_serializer_class = StampedSerializer

        factory = APIRequestFactory()
        request = factory.post("/x/unfollow")
        force_authenticate(request, user=user)
        import uuid as _uuid

        resp = StampedUnfollowView.as_view()(request, user_id=_uuid.uuid4())
        assert resp.status_code == 200
        assert resp.data["swapped"] is True
        assert resp.data["status"] == "neutral"

        # Defaults are exposed as class attributes on every view.
        assert (
            MyFollowersView().get_response_serializer_class()
            is MyFollowersView.response_serializer_class
        )
