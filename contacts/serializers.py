"""Contract serializers for the contacts surface.

Same split as the rest of the module: dataclass serializers describe the
wire for the contract emitter and validate request bodies; the response
bodies themselves are built from live rows by :mod:`~.views`.
"""
from stapel_core.django.api.serializers import StapelDataclassSerializer

from .dto import (
    ContactActionResponse,
    ContactCreateRequest,
    ContactListResponse,
    ContactResponse,
    ContactRevealRequest,
    ContactRevealResponse,
    ContactRevealSummaryResponse,
    ContactUpdateRequest,
    ContactVerifyConfirmRequest,
    ContactVerifyRequestResponse,
    ProfileContactFlags,
    RevealedPhone,
)


class ContactResponseSerializer(StapelDataclassSerializer):
    """Response serializer for one of the owner's own contacts."""

    class Meta:
        dataclass = ContactResponse


class ContactListResponseSerializer(StapelDataclassSerializer):
    """Response serializer for the owner's contact list."""

    class Meta:
        dataclass = ContactListResponse


class ContactCreateRequestSerializer(StapelDataclassSerializer):
    """Request serializer for adding a contact.

    Shape and types only. The number's normalisation, the policy
    vocabulary and the duplicate check are answered in the view as
    first-class error envelopes (`error.400.contacts_invalid_phone`,
    `error.400.contacts_invalid_policy`, `error.409.contacts_duplicate`) —
    a caller has to be able to tell "that is not a number" from "you already
    have that one" without parsing prose.
    """

    class Meta:
        dataclass = ContactCreateRequest


class ContactUpdateRequestSerializer(StapelDataclassSerializer):
    """Request serializer for changing a contact."""

    class Meta:
        dataclass = ContactUpdateRequest


class ContactActionResponseSerializer(StapelDataclassSerializer):
    """Response serializer for a contact action with no contact to return."""

    class Meta:
        dataclass = ContactActionResponse


class ContactVerifyRequestResponseSerializer(StapelDataclassSerializer):
    """Response serializer for "the code was sent"."""

    class Meta:
        dataclass = ContactVerifyRequestResponse


class ContactVerifyConfirmRequestSerializer(StapelDataclassSerializer):
    """Request serializer for confirming the code."""

    class Meta:
        dataclass = ContactVerifyConfirmRequest


class RevealedPhoneSerializer(StapelDataclassSerializer):
    """Response serializer for one revealed number."""

    class Meta:
        dataclass = RevealedPhone


class ContactRevealRequestSerializer(StapelDataclassSerializer):
    """Request serializer for the reveal call."""

    class Meta:
        dataclass = ContactRevealRequest


class ContactRevealResponseSerializer(StapelDataclassSerializer):
    """Response serializer for the reveal call."""

    class Meta:
        dataclass = ContactRevealResponse


class ContactRevealSummaryResponseSerializer(StapelDataclassSerializer):
    """Response serializer for the owner's reveal counters."""

    class Meta:
        dataclass = ContactRevealSummaryResponse


class ProfileContactFlagsSerializer(StapelDataclassSerializer):
    """Response serializer for the public profile's one contacts bit."""

    class Meta:
        dataclass = ProfileContactFlags


__all__ = [
    "ContactActionResponseSerializer",
    "ContactCreateRequestSerializer",
    "ContactListResponseSerializer",
    "ContactResponseSerializer",
    "ContactRevealRequestSerializer",
    "ContactRevealResponseSerializer",
    "ContactRevealSummaryResponseSerializer",
    "ContactUpdateRequestSerializer",
    "ContactVerifyConfirmRequestSerializer",
    "ContactVerifyRequestResponseSerializer",
    "ProfileContactFlagsSerializer",
    "RevealedPhoneSerializer",
]
