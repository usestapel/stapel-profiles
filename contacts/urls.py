"""URL patterns for the contacts sub-module, included by ``urls_v1``.

Trailing slashes follow the module's own convention (``me``, ``batch``): the
path is the bare segment. ``reveal`` is declared ABOVE the
``<int:contact_id>`` routes — the converter rejects it today, and ordering it
first makes the literal safe independently of that.
"""
from django.urls import path

from .views import (
    ContactDetailView,
    ContactListCreateView,
    ContactRevealSummaryView,
    ContactRevealView,
    ContactVerifyConfirmView,
    ContactVerifyRequestView,
)

urlpatterns = [
    path("contacts", ContactListCreateView.as_view(), name="contacts"),
    path("contacts/reveal", ContactRevealView.as_view(), name="contacts-reveal"),
    path(
        "contacts/<int:contact_id>",
        ContactDetailView.as_view(),
        name="contact-detail",
    ),
    path(
        "contacts/<int:contact_id>/verify/request",
        ContactVerifyRequestView.as_view(),
        name="contact-verify-request",
    ),
    path(
        "contacts/<int:contact_id>/verify/confirm",
        ContactVerifyConfirmView.as_view(),
        name="contact-verify-confirm",
    ),
    path(
        "contacts/<int:contact_id>/reveals/summary",
        ContactRevealSummaryView.as_view(),
        name="contact-reveals-summary",
    ),
]
