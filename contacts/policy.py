"""Who may read which number — the one place that decides it.

Three callers ask slightly different versions of the same question and must
never get different answers:

* the reveal endpoint asks "which of this owner's numbers may THIS viewer
  have" (:func:`revealable_for`);
* the public profile asks "is there a number worth showing a button for"
  (:func:`has_revealable_phone`) — the single bit that leaves this module on
  any surface other than the reveal response;
* the batch profile read asks the same for a page of owners at once
  (:func:`owners_with_revealable_phone`), because a 50-tile grid must not
  cost 50 queries.

The owner-side conditions (``enabled`` + ``verified_at`` + policy not
``nobody``) live on the model (:attr:`~.models.Contact.is_revealable`); the
viewer-side condition lives here.
"""
from .models import Contact, ContactKind, ContactPolicy


def viewer_is_member(user) -> bool:
    """An ACCOUNT, not merely an authenticated request.

    With ``AUTH_ANONYMOUS`` on, a guest session is ``is_authenticated`` and
    nobody registered — the same distinction every write view in this module
    already draws, drawn here for the same reason: a throwaway session must
    not be able to read what a registered person may.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return not getattr(user, "is_anonymous", False)


def viewer_is_verified(user) -> bool:
    """The ``verified`` policy's test: this account proved an identity anchor.

    Read exactly as stapel-auth sets them — ``is_email_verified`` /
    ``is_phone_verified`` on the user model, either one being enough. That is
    the same pair that flips a guest into a registered account there, so
    "verified" means here what it means everywhere else in the fleet, and a
    deployment that verifies only by email does not accidentally have an
    empty category.
    """
    if not viewer_is_member(user):
        return False
    return bool(
        getattr(user, "is_email_verified", False)
        or getattr(user, "is_phone_verified", False)
    )


def policy_admits(policy: str, user) -> bool:
    """Does *policy* let *user* read the number it guards."""
    if policy == ContactPolicy.NOBODY:
        return False
    if policy == ContactPolicy.VERIFIED:
        return viewer_is_verified(user)
    if policy == ContactPolicy.MEMBERS:
        return viewer_is_member(user)
    # An unknown policy admits nobody. A value this module does not
    # implement must fail CLOSED: the alternative is a host typo that
    # publishes every number it touches.
    return False


def own_phones(owner_key) -> list[Contact]:
    """Every phone the owner holds — theirs, so no policy applies.

    Including the unproven and the switched-off ones: the owner is not a
    viewer of their own contacts, they are the author of them, and hiding a
    row from the person who typed it would only make the contacts screen and
    the reveal answer disagree.
    """
    return list(
        Contact.objects.filter(owner_key=owner_key, kind=ContactKind.PHONE)
    )


def revealable_for(owner_key, viewer) -> list[Contact]:
    """The owner's phones *viewer* may be handed, in the owner's order.

    Empty is a perfectly good answer and is what a viewer gets when every
    number is withheld — never a 404. "This seller has numbers you may not
    read" is itself information about the seller, and the endpoint does not
    disclose it.
    """
    if str(owner_key) == str(getattr(viewer, "id", "")):
        return own_phones(owner_key)
    if not viewer_is_member(viewer):
        return []
    rows = Contact.objects.filter(
        owner_key=owner_key,
        kind=ContactKind.PHONE,
        enabled=True,
        verified_at__isnull=False,
    ).exclude(policy=ContactPolicy.NOBODY)
    return [c for c in rows if policy_admits(c.policy, viewer)]


def owners_with_revealable_phone(owner_keys) -> set:
    """Of *owner_keys*, those with at least one phone worth asking for.

    Deliberately viewer-INDEPENDENT: this is the bit the public profile
    carries, and making it depend on the viewer would turn a cached public
    field into a per-caller one and would leak the policy itself ("the button
    disappeared when I signed out, so that number is members-only"). It says
    exactly what a storefront needs to decide whether to draw the button:
    there is a proven, enabled, not-withheld-from-everyone number behind this
    seller. Whether THIS viewer gets it is settled by the reveal call.
    """
    keys = [k for k in owner_keys if k]
    if not keys:
        return set()
    return set(
        Contact.objects.filter(
            owner_key__in=keys,
            kind=ContactKind.PHONE,
            enabled=True,
            verified_at__isnull=False,
        )
        .exclude(policy=ContactPolicy.NOBODY)
        .values_list("owner_key", flat=True)
    )


def has_revealable_phone(owner_key) -> bool:
    """:func:`owners_with_revealable_phone` for one owner."""
    if not owner_key:
        return False
    return bool(owners_with_revealable_phone([owner_key]))


__all__ = [
    "has_revealable_phone",
    "own_phones",
    "owners_with_revealable_phone",
    "policy_admits",
    "revealable_for",
    "viewer_is_member",
    "viewer_is_verified",
]
