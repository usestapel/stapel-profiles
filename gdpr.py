from stapel_core.gdpr import GDPRProvider


class ProfilesGDPRProvider(GDPRProvider):
    section = 'profile'

    def export(self, user_id: int) -> dict:
        from .models import Profile, UserRelationship

        try:
            profile = Profile.objects.get(user_id=user_id)
            profile_data = {
                'display_name':               profile.display_name,
                # avatar is a CdnImageField (CharField storing "avatar/<hash>")
                'avatar_ref':                 profile.avatar or None,
                'currency_code':              profile.currency_code,
                'measurement_units':          profile.measurement_units,
                'app_language':               profile.app_language.code if profile.app_language else None,
                'auto_translate_content':     profile.auto_translate_content,
                'location_display_name':      profile.location_display_name_broad,
                'email_notifications':        profile.email_messages,
                'push_notifications':         profile.push_messages,
                'created_at':                 profile.created_at.isoformat(),
                'updated_at':                 profile.updated_at.isoformat(),
            }
        except Profile.DoesNotExist:
            profile_data = {}

        following = list(UserRelationship.objects.filter(
            follower_id=user_id, status='following',
        ).values_list('following_id', flat=True))

        blocked = list(UserRelationship.objects.filter(
            follower_id=user_id, status='blocked',
        ).values_list('following_id', flat=True))

        return {
            'profile':    profile_data,
            'following':  following,
            'blocked':    blocked,
        }

    def delete(self, user_id: int) -> None:
        from .models import Profile, UserRelationship

        UserRelationship.objects.filter(follower_id=user_id).delete()
        UserRelationship.objects.filter(following_id=user_id).delete()
        # avatar is a CDN reference string; the binary lives in the CDN
        # service and is erased by its own GDPR provider/consumer.
        Profile.objects.filter(user_id=user_id).delete()

    def anonymize(self, user_id: int) -> None:
        # Profile is hard-deleted; public-facing references (reviews etc.)
        # are anonymized by the service that owns those models.
        pass
