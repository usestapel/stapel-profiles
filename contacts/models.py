"""The two tables: what a person published, and every time it was handed over.

Both live in the ``profiles`` app label (``app_label`` is stated explicitly
because the module lives in a sub-package, not in ``stapel_profiles.models``)
and are imported from ``stapel_profiles.models`` so Django's app registry
sees them.

Not swappable, deliberately — unlike ``Profile``. A project extends the
profile because "what a person is" differs per product; "a phone number, its
proof and who may read it" does not, and a swapped-in variant would be a
second place where the reveal rules could disagree with these.
"""
from django.db import models


class ContactKind(models.TextChoices):
    """What sort of contact a row carries.

    Members:
        PHONE: A telephone number, stored E.164.
    """

    PHONE = "phone", "Phone"


class ContactPolicy(models.TextChoices):
    """Who may be handed this contact.

    Members:
        MEMBERS: Any authenticated, non-anonymous account.
        VERIFIED: An account with a verified email or phone of its own.
        NOBODY: Nobody — the number stays stored and stays private.
    """

    MEMBERS = "members", "Any registered member"
    VERIFIED = "verified", "Members with a verified email or phone"
    NOBODY = "nobody", "Nobody"


class Contact(models.Model):
    """One contact a person published, with its proof and its policy.

    ``owner_key`` is the user UUID, the same key ``Profile.user_id`` carries —
    a plain column and not a foreign key, for the same reason every other id
    in this module is: the user table belongs to whichever module owns
    accounts in this deployment, and profiles must keep working in a
    microservice split where that table is not in the same database.

    Uniqueness is ``(owner_key, value)``: the same person may not store the
    same number twice, and two different people MAY hold the same number —
    a shared family phone is a real thing, and a global unique index on the
    value would turn this table into an oracle answering "is this number
    already on the site" for anybody able to hit the create endpoint.
    """

    owner_key = models.UUIDField(
        db_index=True, help_text="User UUID this contact belongs to"
    )
    kind = models.CharField(
        max_length=16, choices=ContactKind.choices, default=ContactKind.PHONE
    )
    #: E.164, normalised on the way in (`phones.normalize_phone`). Stored as
    #: written by the owner, not hashed: it is handed back out to viewers the
    #: policy admits, so a one-way transform would make the feature
    #: impossible. Column-level encryption is a deployment decision this
    #: wave does not take (see MODULE.md).
    value = models.CharField(max_length=32, help_text="E.164 phone number")
    label = models.CharField(
        max_length=64, blank=True, default="", help_text='Owner\'s own label, e.g. "Work"'
    )
    #: When the SMS code was confirmed. NULL means unproven, and an unproven
    #: number is revealed to nobody — the single condition the whole reveal
    #: path is built around.
    verified_at = models.DateTimeField(null=True, blank=True)
    #: The owner's on/off switch, independent of the policy: "not right now"
    #: without having to decide the policy again later.
    enabled = models.BooleanField(default=True)
    policy = models.CharField(
        max_length=16, choices=ContactPolicy.choices, default=ContactPolicy.MEMBERS
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "profiles"
        db_table = "profiles_contact"
        ordering = ["created_at", "id"]
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_key", "value"], name="profiles_contact_owner_value_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["owner_key", "kind"], name="profiles_contact_own_kind"),
        ]

    def __str__(self):
        return f"{self.kind}:{self.value} ({self.owner_key})"

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    @property
    def is_revealable(self) -> bool:
        """Could this number be handed to SOMEBODY — before asking to whom.

        The three owner-side conditions, in one place: switched on, proven,
        and not withheld from everyone. Whether a PARTICULAR viewer may have
        it is the policy question, and it lives in :mod:`~.policy`.
        """
        return bool(
            self.enabled
            and self.verified_at is not None
            and self.policy != ContactPolicy.NOBODY
        )


class ContactReveal(models.Model):
    """One hand-over: who asked, for which listing, from where, when.

    The journal is the half of the feature that makes the permission model
    checkable after the fact. A policy says who MAY read a number; only these
    rows say who DID — which is what an owner reads on their contacts screen,
    and what tells a scraped number from a busy one.
    """

    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="reveals"
    )
    viewer_key = models.UUIDField(db_index=True, help_text="User UUID of the viewer")
    #: Where the viewer was standing. Opaque to this module (a listing id
    #: belongs to stapel-listings/classified), so it is a string and it is
    #: optional — a reveal from a seller page has no listing.
    listing_id = models.CharField(max_length=64, blank=True, default="")
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        app_label = "profiles"
        db_table = "profiles_contact_reveal"
        ordering = ["-at", "-id"]
        verbose_name = "Contact reveal"
        verbose_name_plural = "Contact reveals"
        indexes = [
            models.Index(fields=["contact", "at"], name="profiles_reveal_cont_at"),
            models.Index(fields=["viewer_key", "at"], name="profiles_reveal_view_at"),
        ]

    def __str__(self):
        return f"reveal {self.contact_id} -> {self.viewer_key} @ {self.at}"


__all__ = ["Contact", "ContactKind", "ContactPolicy", "ContactReveal"]
