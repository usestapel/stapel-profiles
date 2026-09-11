"""Subject-scoped erasure — what this module removes, and how it is counted.

stapel-gdpr 0.5.0 made the subject of an erasure a parameter. This module
holds data about exactly one subject: the ``account``. A profile is not
partitioned by workspace and never outlives the person it describes, so
there is no second subject to claim — and claiming one this module cannot
erase would be worse than claiming none, because the orchestrator would
wait for a receipt that means nothing.

:func:`erase_account` is idempotent (delivery is at-least-once) and returns
a ``counts`` dict, which is the difference between an owner saying "it ran"
and an owner saying what it did.
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)

#: The name this module answers to in ``STAPEL_GDPR["DATA_OWNERS"]`` — the
#: same name the in-process provider has always registered as, so a host
#: that already declares this owner needs no settings change.
GDPR_OWNER = "profile"

#: The subject types this module claims. An erasure for anything else is
#: not ours and gets no receipt.
GDPR_SUBJECT_TYPES = ("account",)


@transaction.atomic
def erase_account(user_id) -> dict[str, int]:
    """Erase everything this module holds about one account.

    The same work the in-process
    :class:`~stapel_profiles.gdpr.ProfilesGDPRProvider` has always done, now
    counted and reachable from the comm path, so the two participation modes
    cannot drift apart.

    The avatar is a reference string, not a binary: whatever it points at
    lives in the CDN and is erased by that module's own receipt for the same
    request.
    """
    from .models import UserRelationship, get_profile_model

    Profile = get_profile_model()

    following, _ = UserRelationship.objects.filter(follower_id=user_id).delete()
    # The other direction is somebody else's row ABOUT this person, and it
    # is just as much their data — a follower list that still names an
    # erased account is not erased.
    followers, _ = UserRelationship.objects.filter(following_id=user_id).delete()
    profiles, _ = Profile.objects.filter(user_id=user_id).delete()
    # Profiles archived INTO this account (``actions.handle_user_merged``)
    # are this person's rows too: the merge said so. Leaving them would
    # keep a row whose ``merged_into`` names an account we just swore was
    # gone — the account it points at is exactly the subject of this
    # erasure.
    merged, _ = Profile.objects.filter(merged_into=user_id).delete()

    # Contacts (contacts/) — the numbers this person published, and the
    # journal of every time one was handed over. Deleted in BOTH directions,
    # for the same reason the relationship rows are:
    #
    #   * the contacts they own — their phone numbers, the most directly
    #     identifying thing this module has ever stored;
    #   * the reveal rows where they were the VIEWER — somebody else's
    #     journal, but it names this person and their IP, so it is their data
    #     sitting in another owner's counter. Erasing it costs the owner a
    #     number in a count; keeping it would leave an erased account's id
    #     and address in a table anyone could be shown.
    #
    # The owner's own reveal rows go with the contacts by cascade.
    from .contacts.models import Contact, ContactReveal

    seen, _ = ContactReveal.objects.filter(viewer_key=user_id).delete()
    # Counted per model, not off the first element of `.delete()`: that
    # number is the TOTAL including cascaded rows, and reporting it as
    # "contacts" would tell an owner they held twelve phone numbers because
    # one of them had been revealed eleven times.
    _total, dropped = Contact.objects.filter(owner_key=user_id).delete()
    contacts = dropped.get("profiles.Contact", 0)

    return {
        "profiles": int(profiles),
        "profiles_merged_in": int(merged),
        "relationships_outgoing": int(following),
        "relationships_incoming": int(followers),
        "contacts": int(contacts),
        "contact_reveals": int(seen) + int(dropped.get("profiles.ContactReveal", 0)),
    }


#: subject_type -> the callable that erases it.
ERASERS = {"account": erase_account}


def erase_subject(subject_type: str, subject_key) -> dict[str, int]:
    """Erase one subject; raise :class:`KeyError` for a type we do not claim."""
    return ERASERS[subject_type](subject_key)
