"""Wire shapes for the contacts surface.

Owner-facing reads carry the number; the reveal response carries it only for
numbers the policy admitted; nothing else in this module ever does.
"""
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID


@dataclass
class ContactResponse:
    """One of the OWNER's own contacts, as they see it on their own screen.

    This shape is never sent to anybody but the owner, which is why it
    carries both the number and its reveal counter. A viewer's answer is
    `RevealedPhone`, which carries neither.

    Attributes:
        id: Contact id. Example: 7
        kind: What sort of contact this is. Example: phone
        value: The number in E.164. Example: +15550100
        label: The owner's own label for it. Example: Work
        policy: Who may be handed this number (members, verified, nobody). Example: members
        enabled: The owner's on/off switch, independent of the policy. Example: true
        verified: Whether the SMS code has been confirmed. An unverified number is revealed to nobody. Example: true
        verified_at: When the code was confirmed, or null. Example: 2026-09-11T09:00:00Z
        reveal_count: How many times this number has been handed over, ever. Example: 12
        created_at: When the contact was added. Example: 2026-09-11T08:00:00Z
    """
    id: int
    kind: str
    value: str
    label: str
    policy: str
    enabled: bool
    verified: bool
    verified_at: Optional[str]
    reveal_count: int
    created_at: str


@dataclass
class ContactListResponse:
    """The owner's contacts, plus the policy vocabulary this deployment offers.

    `policies` rides along so a contacts screen can render the picker from
    the server's answer instead of hardcoding three strings — a deployment
    that narrowed `STAPEL_PROFILES["CONTACTS"]["POLICIES"]` would otherwise
    show options its own API refuses.

    Attributes:
        contacts: The caller's own contacts, oldest first.
        policies: Policy values this deployment accepts, in picker order; the first is the default for a new contact. Example: ["members", "verified", "nobody"]
    """
    contacts: List[ContactResponse]
    policies: List[str]


@dataclass
class ContactCreateRequest:
    """Add a contact.

    The number must be in international form (leading `+`); it is stored
    E.164, and the same number cannot be added twice by the same person. A
    new contact starts UNVERIFIED, and therefore invisible to every viewer
    until `verify/request` + `verify/confirm` have run.

    Attributes:
        value: Phone number in international form. Example: +15550100
        label: The owner's own label for it. Example: Work
        policy: Who may be handed it; omitted means this deployment's default policy. Example: members
        kind: What sort of contact this is. Only "phone" exists today. Example: phone
    """
    value: str
    label: str = ""
    policy: Optional[str] = None
    kind: str = "phone"


@dataclass
class ContactUpdateRequest:
    """Change a contact (PATCH, all optional).

    The number itself is not editable: a different number is a different
    thing to prove, so it is a different contact. Everything else the owner
    may change at will, and none of it touches `verified_at`.

    Attributes:
        label: The owner's own label for it. Example: Mobile
        policy: Who may be handed it. Example: verified
        enabled: Switch it off without deleting it or changing its policy. Example: false
    """
    label: Optional[str] = None
    policy: Optional[str] = None
    enabled: Optional[bool] = None


@dataclass
class ContactActionResponse:
    """Result of a contact action that returns no contact.

    Attributes:
        success: Whether the action succeeded. Example: true
    """
    success: bool


@dataclass
class ContactVerifyRequestResponse:
    """A verification code was sent to the number.

    Attributes:
        sent: Always true — a refusal is an error envelope, not a false here. Example: true
        expires_in: Seconds the code stays good, when the provider says. Example: 600
    """
    sent: bool
    expires_in: Optional[int]


@dataclass
class ContactVerifyConfirmRequest:
    """Confirm the code that was sent to the number.

    Attributes:
        code: The code from the SMS. Example: 123456
    """
    code: str


@dataclass
class RevealedPhone:
    """One number a viewer was admitted to.

    Deliberately minimal: a label and a number. No id, no policy, no
    counters — a viewer has no business knowing how a seller's contacts are
    organised, only how to call them.

    Attributes:
        label: The owner's own label for it, possibly empty. Example: Work
        value: The number in E.164. Example: +15550100
    """
    label: str
    value: str


@dataclass
class ContactRevealRequest:
    """Ask for a seller's numbers.

    Attributes:
        owner_key: User UUID of the person whose numbers are asked for. Example: 550e8400-e29b-41d4-a716-446655440000
        listing_id: Where the viewer was standing, for the owner's journal. Opaque to this module. Example: 91823
    """
    owner_key: UUID
    listing_id: Optional[str] = None


@dataclass
class ContactRevealResponse:
    """The numbers this viewer was admitted to.

    An empty list is a normal, successful answer: the seller has no
    published number, or none whose policy admits this viewer. The two cases
    are deliberately indistinguishable — "there is a number you may not
    read" is itself a fact about the seller, and this endpoint does not
    disclose it.

    Sent with `Cache-Control: no-store`: the answer is per-viewer, budgeted
    and journalled, and a shared cache copy would be a hand-over nobody
    recorded.

    Attributes:
        phones: The numbers, in the order the owner added them.
    """
    phones: List[RevealedPhone]


@dataclass
class ContactRevealSummaryResponse:
    """How often one of the OWNER's numbers has been handed over.

    Attributes:
        contact_id: Which contact this counts. Example: 7
        total: Hand-overs ever. Example: 128
        last_24h: Hand-overs in the last 24 hours. Example: 4
        last_7d: Hand-overs in the last 7 days. Example: 19
        last_reveal_at: When it was last handed over, or null. Example: 2026-09-11T09:30:00Z
    """
    contact_id: int
    total: int
    last_24h: int
    last_7d: int
    last_reveal_at: Optional[str]


@dataclass
class ProfileContactFlags:
    """What a public profile says about a person's contacts — one bit.

    True means: there is at least one phone on this profile that is
    switched on, proven by SMS, and not withheld from everyone. It is what a
    storefront draws the "Show phone" button from. It is NOT a promise that
    the caller will get a number: the policy on each number is applied by
    `POST /profiles/api/v1/contacts/reveal`, and the answer there may still
    be an empty list or the registration door.

    Viewer-independent on purpose: a bit that changed with the viewer would
    leak the policy itself ("the button vanished when I signed out, so that
    number is members-only") and would make a public field uncacheable.

    Attributes:
        phone: Whether there is a phone worth asking for. Example: true
    """
    phone: bool
