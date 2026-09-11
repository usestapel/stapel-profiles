from stapel_core.gdpr import GDPRProvider

from .erasure import GDPR_OWNER


class ProfilesGDPRProvider(GDPRProvider):
    #: Same name the comm receipts and probe answers carry — one owner, one
    #: declaration in ``STAPEL_GDPR["DATA_OWNERS"]``, whichever of the two
    #: participation modes a deployment uses.
    section = GDPR_OWNER

    def export(self, user_id: int) -> dict:
        from .models import UserRelationship, get_profile_model

        Profile = get_profile_model()

        try:
            profile = Profile.objects.get(user_id=user_id)
            # `getattr(..., None)` on the standard/identity fields — those
            # moved out of the hard core (§66); a swapped-in extended model
            # may or may not have picked them back up, so export whatever is
            # actually present instead of assuming a fixed shape.
            profile_data = {
                'display_name':               getattr(profile, 'display_name', None),
                'first_name':                 getattr(profile, 'first_name', None),
                'last_name':                  getattr(profile, 'last_name', None),
                'avatar_source':              profile.avatar_source,
                'avatar_ref':                 profile.avatar or None,
                'currency_code':              getattr(profile, 'currency_code', None),
                'measurement_units':          getattr(profile, 'measurement_units', None),
                'theme':                      getattr(profile, 'theme', None),
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

        # Contacts (contacts/): the numbers this person published and how
        # often each was handed over, plus the reveals they THEMSELVES
        # performed. Both halves are their data — the first is what the site
        # holds about them, the second is what the site recorded them doing —
        # and an export that carried only the first would be an export of
        # half the module.
        from .contacts.models import Contact, ContactReveal

        contacts = [
            {
                'kind':         c.kind,
                'value':        c.value,
                'label':        c.label,
                'policy':       c.policy,
                'enabled':      c.enabled,
                'verified_at':  c.verified_at.isoformat() if c.verified_at else None,
                'created_at':   c.created_at.isoformat(),
                'reveal_count': c.reveals.count(),
            }
            for c in Contact.objects.filter(owner_key=user_id)
        ]
        # The viewer side names the contact by its VALUE, not its id: an id
        # means nothing outside this database, and the number is the thing
        # the person actually looked up.
        contact_reveals_made = [
            {
                'contact':    r.contact.value,
                'listing_id': r.listing_id or None,
                'at':         r.at.isoformat(),
                'ip':         r.ip,
            }
            for r in ContactReveal.objects.filter(
                viewer_key=user_id
            ).select_related('contact')
        ]

        return {
            'profile':               profile_data,
            'following':             following,
            'blocked':               blocked,
            'contacts':              contacts,
            'contact_reveals_made':  contact_reveals_made,
        }

    def delete(self, user_id: int) -> None:
        """Erase the account slice — one implementation, three callers.

        The in-process provider, the deprecated ``user.deleted`` subscriber
        and the ``gdpr.erasure.requested`` subscriber all reach
        :func:`~stapel_profiles.erasure.erase_account`, so a deployment
        cannot get a different erasure depending on which participation
        mode it happens to use.
        """
        from .erasure import erase_account

        erase_account(user_id)

    def anonymize(self, user_id: int) -> None:
        # Profile is hard-deleted; public-facing references (reviews etc.)
        # are anonymized by the service that owns those models.
        pass
