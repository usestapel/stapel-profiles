"""The contacts HTTP surface: the owner's five, and the viewer's one.

Guest (anonymous session) stance — the module's rule, applied here
--------------------------------------------------------------------
Every view in this package denies the anonymous session, and says so twice:
in ``permission_classes`` (:class:`IsNotAnonymousUser`, which enforces it)
and in ``stapel_anonymous_access = ANONYMOUS_DENIED`` (which records the
intent where a reader looks). A guest is ``is_authenticated`` and nobody:
letting one manage contacts would mint rows with no owner left to manage
them, and letting one reveal a number would sell the entire permission model
for the price of one POST.

The reveal endpoint denies with this module's OWN key
(``error.403.contacts_registration_required``) instead of the generic 403,
because the storefront's correct reaction is to open full registration and
it can only know that from the key. That single difference is the only reason
:class:`ContactsDoorMixin` exists.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions
from stapel_core.django.api.errors import (
    StapelErrorResponse,
    StapelErrorSerializer,
    StapelResponse,
)
from stapel_core.django.api.permissions import ANONYMOUS_DENIED, IsNotAnonymousUser
from stapel_core.django.api.views import StapelAPIView
from stapel_core.netintel import client_ip

from stapel_profiles.errors import (
    ERR_400_CONTACTS_CODE_EXPIRED,
    ERR_400_CONTACTS_INVALID_CODE,
    ERR_400_CONTACTS_INVALID_PHONE,
    ERR_400_CONTACTS_INVALID_POLICY,
    ERR_403_CONTACTS_REGISTRATION_REQUIRED,
    ERR_404_CONTACT_NOT_FOUND,
    ERR_409_CONTACTS_DUPLICATE,
    ERR_429_CONTACTS_CODE_RATE,
    ERR_429_CONTACTS_REVEAL_BUDGET,
    ERR_503_CONTACTS_CODE_UNAVAILABLE,
)

from . import budget, policy as policy_rules
from .conf import allowed_policies, default_policy
from .dto import (
    ContactActionResponse,
    ContactListResponse,
    ContactResponse,
    ContactRevealResponse,
    ContactRevealSummaryResponse,
    ContactVerifyRequestResponse,
    RevealedPhone,
)
from .models import Contact, ContactKind, ContactReveal
from .otp import get_otp_provider
from .phones import InvalidPhoneNumber, normalize_phone
from .serializers import (
    ContactActionResponseSerializer,
    ContactCreateRequestSerializer,
    ContactListResponseSerializer,
    ContactResponseSerializer,
    ContactRevealRequestSerializer,
    ContactRevealResponseSerializer,
    ContactRevealSummaryResponseSerializer,
    ContactUpdateRequestSerializer,
    ContactVerifyConfirmRequestSerializer,
    ContactVerifyRequestResponseSerializer,
)

logger = logging.getLogger(__name__)


class ContactsRegistrationRequired(exceptions.PermissionDenied):
    """403 carrying this module's door key, whatever the exception handler is.

    The body is built by ``StapelErrorResponse`` and handed to DRF as the
    exception's ``detail``, which DRF renders verbatim when it is a dict. So
    the envelope is identical under the stapel exception handler and under
    DRF's own — a module's error contract must not depend on which handler a
    host happens to have installed.
    """

    def __init__(self):
        body = StapelErrorResponse(403, ERR_403_CONTACTS_REGISTRATION_REQUIRED).data
        super().__init__(detail=body)


class ContactsDoorMixin:
    """Turn every permission refusal on this view into the registration door.

    Overriding ``permission_denied`` rather than adding a permission class:
    DRF's own implementation raises ``NotAuthenticated`` (401) for a caller
    with no credentials and ``PermissionDenied`` (403) for a guest, which
    would give the storefront two different answers to one question — "you
    need an account". One door, one key, both callers.
    """

    def permission_denied(self, request, message=None, code=None):
        raise ContactsRegistrationRequired()


def _reveal_counts(contact_ids):
    """``{contact_id: total reveals}`` for a page of contacts, in one query."""
    from django.db.models import Count

    if not contact_ids:
        return {}
    rows = (
        ContactReveal.objects.filter(contact_id__in=contact_ids)
        .values("contact_id")
        .annotate(n=Count("id"))
    )
    return {r["contact_id"]: r["n"] for r in rows}


def _contact_dto(contact, reveal_count: int) -> ContactResponse:
    return ContactResponse(
        id=contact.id,
        kind=contact.kind,
        value=contact.value,
        label=contact.label,
        policy=contact.policy,
        enabled=contact.enabled,
        verified=contact.is_verified,
        verified_at=contact.verified_at.isoformat() if contact.verified_at else None,
        reveal_count=reveal_count,
        created_at=contact.created_at.isoformat(),
    )


def _own_contact(request, contact_id):
    """The caller's contact, or ``None``.

    Scoped to ``owner_key`` in the QUERY, not checked after fetching: a
    foreign contact must be indistinguishable from a missing one, and the
    surest way to keep it that way is never to load it.
    """
    return Contact.objects.filter(id=contact_id, owner_key=request.user.id).first()


def _otp_error_response(envelope):
    """Map a provider envelope onto this module's error keys, or ``None``.

    ``None`` means the envelope was a success and the caller should carry on.
    """
    if envelope is None:
        return StapelErrorResponse(503, ERR_503_CONTACTS_CODE_UNAVAILABLE)
    if not isinstance(envelope, dict):
        return None
    error = envelope.get("error")
    if not error:
        return None
    if error in ("rate_limit", "blocked"):
        return StapelErrorResponse(
            429,
            ERR_429_CONTACTS_CODE_RATE,
            params={"retry_after": int(envelope.get("retry_after") or 0)},
        )
    if error == "expired":
        return StapelErrorResponse(400, ERR_400_CONTACTS_CODE_EXPIRED)
    if error == "invalid_code":
        return StapelErrorResponse(
            400,
            ERR_400_CONTACTS_INVALID_CODE,
            params={"attempts_remaining": int(envelope.get("attempts_remaining") or 0)},
        )
    # "unavailable", "server_error", and anything a future provider invents:
    # fail closed and say we could not ask, never that the user was wrong.
    return StapelErrorResponse(503, ERR_503_CONTACTS_CODE_UNAVAILABLE)


@extend_schema(tags=["Contacts"])
class ContactListCreateView(StapelAPIView):
    """The owner's own contacts: list them, add one."""

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = ContactCreateRequestSerializer
    response_serializer_class = ContactResponseSerializer
    list_response_serializer_class = ContactListResponseSerializer

    @extend_schema(
        operation_id="list_my_contacts",
        summary="List my contacts",
        description=(
            "The caller's own contacts, oldest first, WITH their numbers and "
            "reveal counters — this shape is never sent to anybody else. "
            "`policies` carries the policy vocabulary this deployment "
            "accepts, so the picker renders from the server's answer."
        ),
        responses={
            200: ContactListResponseSerializer,
            401: OpenApiTypes.OBJECT,
            403: StapelErrorSerializer,
        },
    )
    def get(self, request):  # noqa: R007
        """List the caller's contacts."""
        contacts = list(Contact.objects.filter(owner_key=request.user.id))
        counts = _reveal_counts([c.id for c in contacts])
        dto = ContactListResponse(
            contacts=[_contact_dto(c, counts.get(c.id, 0)) for c in contacts],
            policies=allowed_policies(),
        )
        return StapelResponse(self.list_response_serializer_class(dto))

    @extend_schema(
        operation_id="add_my_contact",
        summary="Add a contact",
        description=(
            "Store a phone number for the caller. It is normalised to E.164 "
            "and starts UNVERIFIED — until `verify/request` + "
            "`verify/confirm` have run it is revealed to nobody and the "
            "caller's public profile keeps saying `contacts.phone: false`."
        ),
        request=ContactCreateRequestSerializer,
        responses={
            201: ContactResponseSerializer,
            400: StapelErrorSerializer,
            401: OpenApiTypes.OBJECT,
            403: StapelErrorSerializer,
            409: StapelErrorSerializer,
        },
    )
    def post(self, request):  # noqa: R007
        """Add a contact."""
        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            value = normalize_phone(data.value)
        except InvalidPhoneNumber:
            return StapelErrorResponse(400, ERR_400_CONTACTS_INVALID_PHONE)

        chosen = data.policy or default_policy()
        if chosen not in allowed_policies():
            return StapelErrorResponse(
                400,
                ERR_400_CONTACTS_INVALID_POLICY,
                params={"policies": ", ".join(allowed_policies())},
            )

        try:
            contact = Contact.objects.create(
                owner_key=request.user.id,
                kind=ContactKind.PHONE,
                value=value,
                label=data.label or "",
                policy=chosen,
            )
        except IntegrityError:
            # The uniqueness constraint, reported as what it means. Returning
            # the existing row with a 200 would claim the policy the caller
            # just sent had been applied, which it was not.
            return StapelErrorResponse(409, ERR_409_CONTACTS_DUPLICATE)

        return StapelResponse(
            self.get_response_serializer_class()(_contact_dto(contact, 0)), status=201
        )


@extend_schema(tags=["Contacts"])
class ContactDetailView(StapelAPIView):
    """One of the owner's contacts: change it, delete it."""

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = ContactUpdateRequestSerializer
    response_serializer_class = ContactResponseSerializer
    action_response_serializer_class = ContactActionResponseSerializer

    @extend_schema(
        operation_id="update_my_contact",
        summary="Update a contact",
        description=(
            "Change the label, the policy or the on/off switch (PATCH "
            "semantics). The number itself is not editable — a different "
            "number is a different thing to prove — and nothing here touches "
            "`verified_at`. Somebody else's contact answers 404."
        ),
        parameters=[
            OpenApiParameter(
                name="contact_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="Contact id",
            )
        ],
        request=ContactUpdateRequestSerializer,
        responses={
            200: ContactResponseSerializer,
            400: StapelErrorSerializer,
            401: OpenApiTypes.OBJECT,
            403: StapelErrorSerializer,
            404: StapelErrorSerializer,
        },
    )
    def patch(self, request, contact_id):  # noqa: R007
        """Update a contact."""
        contact = _own_contact(request, contact_id)
        if contact is None:
            return StapelErrorResponse(404, ERR_404_CONTACT_NOT_FOUND)

        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.policy is not None:
            if data.policy not in allowed_policies():
                return StapelErrorResponse(
                    400,
                    ERR_400_CONTACTS_INVALID_POLICY,
                    params={"policies": ", ".join(allowed_policies())},
                )
            contact.policy = data.policy
        if data.label is not None:
            contact.label = data.label
        if data.enabled is not None:
            contact.enabled = bool(data.enabled)
        contact.save()

        counts = _reveal_counts([contact.id])
        return StapelResponse(
            self.get_response_serializer_class()(
                _contact_dto(contact, counts.get(contact.id, 0))
            )
        )

    @extend_schema(
        operation_id="delete_my_contact",
        summary="Delete a contact",
        description=(
            "Remove the number and its journal. The journal goes with it on "
            "purpose: the rows exist to tell the OWNER who asked for THIS "
            "number, and a number nobody holds any more has no owner to tell."
        ),
        parameters=[
            OpenApiParameter(
                name="contact_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="Contact id",
            )
        ],
        request=None,
        responses={
            200: ContactActionResponseSerializer,
            401: OpenApiTypes.OBJECT,
            403: StapelErrorSerializer,
            404: StapelErrorSerializer,
        },
    )
    def delete(self, request, contact_id):  # noqa: R007
        """Delete a contact."""
        contact = _own_contact(request, contact_id)
        if contact is None:
            return StapelErrorResponse(404, ERR_404_CONTACT_NOT_FOUND)
        contact.delete()
        return StapelResponse(
            self.action_response_serializer_class(ContactActionResponse(success=True))
        )


@extend_schema(tags=["Contacts"])
class ContactVerifyRequestView(StapelAPIView):
    """Send an SMS code to one of the owner's numbers."""

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    response_serializer_class = ContactVerifyRequestResponseSerializer

    @extend_schema(
        operation_id="request_contact_verification",
        summary="Send a verification code",
        description=(
            "Ask the OTP provider "
            "(`STAPEL_PROFILES['CONTACTS']['OTP_PROVIDER']`, stapel-auth's "
            "phone service by default) to send a code to this number. The "
            "provider owns the code's lifetime, its attempt budget and its "
            "resend cooldown; this module owns none of it. Repeats answer "
            "429 `error.429.contacts_code_rate` with `retry_after`."
        ),
        parameters=[
            OpenApiParameter(
                name="contact_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="Contact id",
            )
        ],
        request=None,
        responses={
            200: ContactVerifyRequestResponseSerializer,
            401: OpenApiTypes.OBJECT,
            403: StapelErrorSerializer,
            404: StapelErrorSerializer,
            429: StapelErrorSerializer,
            503: StapelErrorSerializer,
        },
    )
    def post(self, request, contact_id):  # noqa: R007
        """Send a verification code to a contact."""
        contact = _own_contact(request, contact_id)
        if contact is None:
            return StapelErrorResponse(404, ERR_404_CONTACT_NOT_FOUND)

        receipt = get_otp_provider().send_verification_code(contact.value)
        refusal = _otp_error_response(receipt)
        if refusal is not None:
            return refusal

        dto = ContactVerifyRequestResponse(
            sent=True, expires_in=getattr(receipt, "ttl", None)
        )
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Contacts"])
class ContactVerifyConfirmView(StapelAPIView):
    """Confirm the SMS code and mark the number proven."""

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = ContactVerifyConfirmRequestSerializer
    response_serializer_class = ContactResponseSerializer

    @extend_schema(
        operation_id="confirm_contact_verification",
        summary="Confirm a verification code",
        description=(
            "Check the code against the provider and, on a match, stamp "
            "`verified_at`. This is the moment the number becomes revealable "
            "and the owner's public profile starts saying "
            "`contacts.phone: true` (policy permitting)."
        ),
        parameters=[
            OpenApiParameter(
                name="contact_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="Contact id",
            )
        ],
        request=ContactVerifyConfirmRequestSerializer,
        responses={
            200: ContactResponseSerializer,
            400: StapelErrorSerializer,
            401: OpenApiTypes.OBJECT,
            403: StapelErrorSerializer,
            404: StapelErrorSerializer,
            429: StapelErrorSerializer,
            503: StapelErrorSerializer,
        },
    )
    def post(self, request, contact_id):  # noqa: R007
        """Confirm a contact's verification code."""
        contact = _own_contact(request, contact_id)
        if contact is None:
            return StapelErrorResponse(404, ERR_404_CONTACT_NOT_FOUND)

        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = get_otp_provider().verify_code(
            contact.value, serializer.validated_data.code
        )
        refusal = _otp_error_response(result)
        if refusal is not None:
            return refusal

        if not contact.verified_at:
            contact.verified_at = timezone.now()
            contact.save(update_fields=["verified_at", "updated_at"])

        counts = _reveal_counts([contact.id])
        return StapelResponse(
            self.get_response_serializer_class()(
                _contact_dto(contact, counts.get(contact.id, 0))
            )
        )


@extend_schema(tags=["Contacts"])
class ContactRevealSummaryView(StapelAPIView):
    """How often one of the owner's numbers has been handed over."""

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    response_serializer_class = ContactRevealSummaryResponseSerializer

    @extend_schema(
        operation_id="get_contact_reveal_summary",
        summary="Reveal counters for one of my contacts",
        description=(
            "Counts only — never who. The owner is entitled to know how "
            "often their number was handed out; the identity of the people "
            "who asked is the viewers' data, and this module does not trade "
            "one person's privacy for another's curiosity."
        ),
        parameters=[
            OpenApiParameter(
                name="contact_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="Contact id",
            )
        ],
        responses={
            200: ContactRevealSummaryResponseSerializer,
            401: OpenApiTypes.OBJECT,
            403: StapelErrorSerializer,
            404: StapelErrorSerializer,
        },
    )
    def get(self, request, contact_id):  # noqa: R007
        """Reveal counters for one contact."""
        contact = _own_contact(request, contact_id)
        if contact is None:
            return StapelErrorResponse(404, ERR_404_CONTACT_NOT_FOUND)

        now = timezone.now()
        reveals = ContactReveal.objects.filter(contact=contact)
        last = reveals.order_by("-at").values_list("at", flat=True).first()
        dto = ContactRevealSummaryResponse(
            contact_id=contact.id,
            total=reveals.count(),
            last_24h=reveals.filter(at__gte=now - timedelta(days=1)).count(),
            last_7d=reveals.filter(at__gte=now - timedelta(days=7)).count(),
            last_reveal_at=last.isoformat() if last else None,
        )
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Contacts"])
class ContactRevealView(ContactsDoorMixin, StapelAPIView):
    """Hand a seller's numbers to a viewer the policy admits.

    The only endpoint in the fleet that emits a stored phone number to
    somebody who does not own it. Four things happen, in this order, and the
    order is the design:

    1. the door — no account, no number (`ContactsDoorMixin`);
    2. the hourly budget, SPENT BEFORE the read, so abandoning responses
       does not mine the endpoint;
    3. the policy, per number, per viewer;
    4. the journal, one row per number actually handed over.

    The response carries `Cache-Control: no-store`: it is per-viewer,
    budgeted and journalled, and a shared cache copy would be a hand-over
    nobody recorded.
    """

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = ContactRevealRequestSerializer
    response_serializer_class = ContactRevealResponseSerializer

    @extend_schema(
        operation_id="reveal_contacts",
        summary="Show a seller's phone numbers",
        description=(
            "Return the seller's numbers this viewer is admitted to, per the "
            "policy on each number. An empty list is a normal 200: the "
            "seller has no published number, or none for this viewer — the "
            "two are deliberately indistinguishable. A caller without an "
            "account (signed out OR a guest session) gets 403 "
            "`error.403.contacts_registration_required`, which is the "
            "storefront's cue to open full registration. Over the hourly "
            "budget the answer is 429 `error.429.contacts_reveal_budget` "
            "with `retry_after` in seconds. The owner asking for their own "
            "numbers always gets all of them, unbudgeted and unjournalled."
        ),
        request=ContactRevealRequestSerializer,
        responses={
            200: ContactRevealResponseSerializer,
            400: StapelErrorSerializer,
            403: StapelErrorSerializer,
            429: StapelErrorSerializer,
        },
    )
    def post(self, request):  # noqa: R007
        """Reveal a seller's phone numbers."""
        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        owner_key = data.owner_key
        viewer = request.user
        is_owner = str(owner_key) == str(viewer.id)

        if not is_owner:
            wait = budget.spend(viewer.id)
            if wait is not None:
                return self._no_store(
                    StapelErrorResponse(
                        429,
                        ERR_429_CONTACTS_REVEAL_BUDGET,
                        params={"retry_after": wait},
                    )
                )

        contacts = policy_rules.revealable_for(owner_key, viewer)

        if not is_owner and contacts:
            ip = client_ip(request)
            listing_id = (data.listing_id or "")[:64]
            ContactReveal.objects.bulk_create(
                [
                    ContactReveal(
                        contact=c,
                        viewer_key=viewer.id,
                        listing_id=listing_id,
                        ip=ip,
                    )
                    for c in contacts
                ]
            )

        dto = ContactRevealResponse(
            phones=[RevealedPhone(label=c.label, value=c.value) for c in contacts]
        )
        return self._no_store(
            StapelResponse(self.get_response_serializer_class()(dto))
        )

    @staticmethod
    def _no_store(response):
        """Applied to the 429 as well as the 200.

        A cached refusal is as wrong as a cached number: it would make a
        viewer's spent budget look permanent to a shared cache, and the next
        hour's answer would come from the cache instead of from here.
        """
        response["Cache-Control"] = "no-store"
        return response


__all__ = [
    "ContactDetailView",
    "ContactListCreateView",
    "ContactRevealSummaryView",
    "ContactRevealView",
    "ContactVerifyConfirmView",
    "ContactVerifyRequestView",
    "ContactsDoorMixin",
    "ContactsRegistrationRequired",
]
