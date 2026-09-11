"""Gates for the contacts sub-module (SPEC §6, back half).

The number in these tests is the fixed string :data:`PHONE`. It is a
documentation-range number and it is the *same* string the leak test greps
every serialized response for — if any surface of this module ever starts
carrying a stored phone number, that test is the one that says so.
"""
import uuid

import pytest
from stapel_core.django.api.permissions import ANONYMOUS_DENIED, IsNotAnonymousUser

from stapel_profiles.contacts import views as contact_views
from stapel_profiles.contacts.models import Contact, ContactPolicy, ContactReveal

#: The fixture number. Documentation range, never dialled.
PHONE = "+15550100"
SECOND_PHONE = "+15550111"


# ---------------------------------------------------------------------------
# Test doubles for the OTP seam
# ---------------------------------------------------------------------------

class FixedCodeProvider:
    """Accepts one code, refuses every other. Wired in by dotted path."""

    CODE = "424242"

    def send_verification_code(self, phone, device_id=None):
        return type("Receipt", (), {"ttl": 600})()

    def verify_code(self, phone, code):
        if code == self.CODE:
            return {"success": True}
        return {"error": "invalid_code", "attempts_remaining": 4}


class BlockedProvider:
    """Every send is refused by a rate limit."""

    def send_verification_code(self, phone, device_id=None):
        return {"error": "rate_limit", "retry_after": 42}

    def verify_code(self, phone, code):
        return {"error": "blocked", "retry_after": 42}


class DownProvider:
    """The store cannot answer at all."""

    def send_verification_code(self, phone, device_id=None):
        return None

    def verify_code(self, phone, code):
        return {"error": "unavailable"}


def _settings(client_settings, **contacts):
    client_settings.STAPEL_PROFILES = {
        "CONTACTS": {
            "OTP_PROVIDER": "tests.test_contacts.FixedCodeProvider",
            **contacts,
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def otp(settings):
    _settings(settings)
    return FixedCodeProvider


@pytest.fixture
def guest(db):
    from stapel_core.django.users.models import User

    return User.objects.create_user(
        username=f"anon-{uuid.uuid4().hex[:8]}",
        password="testpass-1234",
        is_anonymous=True,
    )


@pytest.fixture
def guest_client(api_client, guest):
    api_client.force_authenticate(user=guest)
    return api_client


@pytest.fixture
def verified_user(db):
    from stapel_core.django.users.models import User

    return User.objects.create_user(
        username=f"v-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password="testpass-1234",
        is_email_verified=True,
    )


@pytest.fixture
def seller(db):
    from stapel_core.django.users.models import User

    return User.objects.create_user(
        username=f"s-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password="testpass-1234",
    )


def _contact(owner, value=PHONE, *, verified=True, **kw):
    from django.utils import timezone

    return Contact.objects.create(
        owner_key=owner.id,
        value=value,
        verified_at=timezone.now() if verified else None,
        **kw,
    )


# ---------------------------------------------------------------------------
# §1 — storage and normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+1 555 0100", "+15550100"),
        ("+1 (555) 0100", "+15550100"),
        ("+1-555-0100", "+15550100"),
    ],
)
def test_the_same_number_has_one_spelling(raw, expected):
    from stapel_profiles.contacts.phones import normalize_phone

    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["15550100", "not a number", "", "+1"])
def test_a_number_without_a_country_or_a_length_is_refused(raw):
    from stapel_profiles.contacts.phones import InvalidPhoneNumber, normalize_phone

    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


@pytest.mark.django_db
def test_one_person_cannot_store_one_number_twice(authed_client, user, otp):
    first = authed_client.post("/contacts", {"value": PHONE}, format="json")
    assert first.status_code == 201, first.content
    again = authed_client.post("/contacts", {"value": "+1 555 0100"}, format="json")
    assert again.status_code == 409, again.content
    assert again.json()["localizable_error"] == "error.409.contacts_duplicate"


@pytest.mark.django_db
def test_two_people_may_share_one_number(authed_client, user, seller, otp):
    _contact(seller)
    resp = authed_client.post("/contacts", {"value": PHONE}, format="json")
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db
def test_a_new_contact_starts_unproven(authed_client, user, otp):
    resp = authed_client.post("/contacts", {"value": PHONE}, format="json")
    body = resp.json()
    assert body["verified"] is False
    assert body["verified_at"] is None
    assert body["policy"] == "members"
    assert body["enabled"] is True


@pytest.mark.django_db
def test_a_policy_this_deployment_does_not_offer_is_refused(
    authed_client, user, settings
):
    _settings(settings, POLICIES=["verified", "nobody"])
    resp = authed_client.post(
        "/contacts", {"value": PHONE, "policy": "members"}, format="json"
    )
    assert resp.status_code == 400, resp.content
    assert resp.json()["localizable_error"] == "error.400.contacts_invalid_policy"


@pytest.mark.django_db
def test_the_first_configured_policy_is_the_default(authed_client, user, settings):
    _settings(settings, POLICIES=["verified", "nobody"])
    resp = authed_client.post("/contacts", {"value": PHONE}, format="json")
    assert resp.status_code == 201, resp.content
    assert resp.json()["policy"] == "verified"


@pytest.mark.django_db
def test_a_bad_number_is_refused_with_its_own_key(authed_client, user, otp):
    resp = authed_client.post("/contacts", {"value": "15550100"}, format="json")
    assert resp.status_code == 400, resp.content
    assert resp.json()["localizable_error"] == "error.400.contacts_invalid_phone"


# ---------------------------------------------------------------------------
# §3 — owner CRUD, verification, foreign contacts
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_owner_lists_their_own_numbers_and_the_policy_vocabulary(
    authed_client, user, otp
):
    _contact(user)
    body = authed_client.get("/contacts").json()
    assert [c["value"] for c in body["contacts"]] == [PHONE]
    assert body["policies"] == ["members", "verified", "nobody"]


@pytest.mark.django_db
def test_the_owner_changes_label_policy_and_switch(authed_client, user, otp):
    contact = _contact(user)
    resp = authed_client.patch(
        f"/contacts/{contact.id}",
        {"label": "Work", "policy": "verified", "enabled": False},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert (body["label"], body["policy"], body["enabled"]) == ("Work", "verified", False)
    # None of that touched the proof.
    assert body["verified"] is True


@pytest.mark.django_db
def test_the_owner_deletes_a_contact_and_its_journal(authed_client, user, seller, otp):
    contact = _contact(user)
    ContactReveal.objects.create(contact=contact, viewer_key=seller.id)
    assert authed_client.delete(f"/contacts/{contact.id}").status_code == 200
    assert not Contact.objects.filter(id=contact.id).exists()
    assert not ContactReveal.objects.filter(contact_id=contact.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("patch", "/contacts/{id}", {"label": "x"}),
        ("delete", "/contacts/{id}", None),
        ("post", "/contacts/{id}/verify/request", None),
        ("post", "/contacts/{id}/verify/confirm", {"code": "424242"}),
        ("get", "/contacts/{id}/reveals/summary", None),
    ],
)
def test_somebody_elses_contact_is_a_404_not_a_403(
    authed_client, seller, otp, method, path, payload
):
    """A 403 would confirm the row exists. It must be indistinguishable
    from a contact id that was never issued."""
    contact = _contact(seller)
    call = getattr(authed_client, method)
    url = path.format(id=contact.id)
    resp = call(url, payload, format="json") if payload else call(url)
    assert resp.status_code == 404, resp.content
    assert resp.json()["localizable_error"] == "error.404.contact_not_found"


@pytest.mark.django_db
def test_the_code_proves_the_number(authed_client, user, otp):
    contact = _contact(user, verified=False)
    sent = authed_client.post(f"/contacts/{contact.id}/verify/request")
    assert sent.status_code == 200, sent.content
    assert sent.json() == {"sent": True, "expires_in": 600}

    confirmed = authed_client.post(
        f"/contacts/{contact.id}/verify/confirm",
        {"code": FixedCodeProvider.CODE},
        format="json",
    )
    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["verified"] is True
    contact.refresh_from_db()
    assert contact.verified_at is not None


@pytest.mark.django_db
def test_a_wrong_code_proves_nothing(authed_client, user, otp):
    contact = _contact(user, verified=False)
    resp = authed_client.post(
        f"/contacts/{contact.id}/verify/confirm", {"code": "000000"}, format="json"
    )
    assert resp.status_code == 400, resp.content
    body = resp.json()
    assert body["localizable_error"] == "error.400.contacts_invalid_code"
    assert body["params"]["attempts_remaining"] == 4
    contact.refresh_from_db()
    assert contact.verified_at is None


@pytest.mark.django_db
def test_a_refused_send_is_a_429_with_its_wait(authed_client, user, settings):
    _settings(settings, OTP_PROVIDER="tests.test_contacts.BlockedProvider")
    contact = _contact(user, verified=False)
    resp = authed_client.post(f"/contacts/{contact.id}/verify/request")
    assert resp.status_code == 429, resp.content
    body = resp.json()
    assert body["localizable_error"] == "error.429.contacts_code_rate"
    assert body["params"]["retry_after"] == 42


@pytest.mark.django_db
def test_a_provider_that_cannot_answer_is_a_503_not_a_400(
    authed_client, user, settings
):
    """"We could not ask" must never be rendered as "your code is wrong"."""
    _settings(settings, OTP_PROVIDER="tests.test_contacts.DownProvider")
    contact = _contact(user, verified=False)
    assert authed_client.post(
        f"/contacts/{contact.id}/verify/request"
    ).status_code == 503
    confirm = authed_client.post(
        f"/contacts/{contact.id}/verify/confirm", {"code": "424242"}, format="json"
    )
    assert confirm.status_code == 503, confirm.content
    assert confirm.json()["localizable_error"] == "error.503.contacts_code_unavailable"


@pytest.mark.django_db
def test_the_owner_reads_counters_but_never_the_viewers(
    authed_client, user, seller, otp
):
    contact = _contact(user)
    ContactReveal.objects.create(contact=contact, viewer_key=seller.id, ip="10.0.0.1")
    body = authed_client.get(f"/contacts/{contact.id}/reveals/summary").json()
    assert body["total"] == 1
    assert body["last_24h"] == 1
    assert body["last_7d"] == 1
    assert body["last_reveal_at"]
    assert str(seller.id) not in str(body)
    assert "10.0.0.1" not in str(body)


# ---------------------------------------------------------------------------
# §2 — the reveal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_a_member_gets_a_proven_number(authed_client, user, seller, otp):
    _contact(seller, label="Work")
    resp = authed_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert resp.status_code == 200, resp.content
    assert resp.json() == {"phones": [{"label": "Work", "value": PHONE}]}


@pytest.mark.django_db
def test_the_reveal_is_never_cached(authed_client, user, seller, otp):
    _contact(seller)
    resp = authed_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert resp["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_an_unproven_number_is_revealed_to_nobody(authed_client, user, seller, otp):
    _contact(seller, verified=False)
    resp = authed_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json() == {"phones": []}


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [("enabled", False), ("policy", "nobody")])
def test_a_withheld_number_is_revealed_to_nobody(
    authed_client, user, seller, otp, field, value
):
    _contact(seller, **{field: value})
    resp = authed_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert resp.json() == {"phones": []}


@pytest.mark.django_db
def test_the_verified_policy_cuts_off_an_unverified_account(
    api_client, user, verified_user, seller, otp
):
    _contact(seller, policy=ContactPolicy.VERIFIED)

    api_client.force_authenticate(user=user)
    plain = api_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert plain.json() == {"phones": []}

    api_client.force_authenticate(user=verified_user)
    proven = api_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert proven.json() == {"phones": [{"label": "", "value": PHONE}]}


@pytest.mark.django_db
def test_a_guest_is_sent_to_registration(guest_client, seller, otp):
    _contact(seller)
    resp = guest_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert resp.status_code == 403, resp.content
    assert (
        resp.json()["localizable_error"]
        == "error.403.contacts_registration_required"
    )
    assert PHONE not in resp.content.decode()


@pytest.mark.django_db
def test_the_unsigned_internet_gets_the_same_door(api_client, seller, otp):
    """One door, one key: a 401 for the signed-out and a 403 for the guest
    would give the storefront two answers to one question."""
    _contact(seller)
    resp = api_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    )
    assert resp.status_code == 403, resp.content
    assert (
        resp.json()["localizable_error"]
        == "error.403.contacts_registration_required"
    )


@pytest.mark.django_db
def test_every_hand_over_is_written_down(authed_client, user, seller, otp):
    contact = _contact(seller)
    authed_client.post(
        "/contacts/reveal",
        {"owner_key": str(seller.id), "listing_id": "91823"},
        format="json",
    )
    row = ContactReveal.objects.get(contact=contact)
    assert str(row.viewer_key) == str(user.id)
    assert row.listing_id == "91823"
    assert row.ip is not None


@pytest.mark.django_db
def test_the_hourly_budget_refuses_with_its_wait(
    api_client, user, seller, settings
):
    _settings(settings, REVEAL_PER_HOUR=2)
    _contact(seller)
    api_client.force_authenticate(user=user)
    body = {"owner_key": str(seller.id)}

    for _ in range(2):
        assert api_client.post("/contacts/reveal", body, format="json").status_code == 200
    refused = api_client.post("/contacts/reveal", body, format="json")
    assert refused.status_code == 429, refused.content
    payload = refused.json()
    assert payload["localizable_error"] == "error.429.contacts_reveal_budget"
    assert 0 < payload["params"]["retry_after"] <= 3601
    assert PHONE not in refused.content.decode()
    assert refused["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_the_budget_is_spent_before_the_row_is_written(
    api_client, user, seller, settings
):
    """A refused reveal hands over nothing, so it journals nothing."""
    _settings(settings, REVEAL_PER_HOUR=1)
    _contact(seller)
    api_client.force_authenticate(user=user)
    body = {"owner_key": str(seller.id)}
    api_client.post("/contacts/reveal", body, format="json")
    api_client.post("/contacts/reveal", body, format="json")
    assert ContactReveal.objects.count() == 1


@pytest.mark.django_db
def test_the_owner_always_sees_their_own_numbers(api_client, seller, settings):
    """Unproven, switched off, withheld from everyone — still theirs. And
    reading their own contacts costs them no budget and writes no journal."""
    _settings(settings, REVEAL_PER_HOUR=1)
    _contact(seller, verified=False, enabled=False, policy=ContactPolicy.NOBODY)
    api_client.force_authenticate(user=seller)
    body = {"owner_key": str(seller.id)}

    for _ in range(3):
        resp = api_client.post("/contacts/reveal", body, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json() == {"phones": [{"label": "", "value": PHONE}]}
    assert ContactReveal.objects.count() == 0


@pytest.mark.django_db
def test_a_seller_with_nothing_published_answers_the_same_as_one_withholding(
    authed_client, user, seller, otp
):
    """Two indistinguishable 200s. "There is a number you may not read" is
    itself a fact about the seller, and this endpoint does not disclose it."""
    nothing = authed_client.post(
        "/contacts/reveal", {"owner_key": str(uuid.uuid4())}, format="json"
    ).json()
    _contact(seller, policy=ContactPolicy.NOBODY)
    withholding = authed_client.post(
        "/contacts/reveal", {"owner_key": str(seller.id)}, format="json"
    ).json()
    assert nothing == withholding == {"phones": []}


# ---------------------------------------------------------------------------
# The public profile carries the bit and nothing else
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_public_profile_carries_the_bit(api_client, user, seller, db):
    from stapel_profiles.models import get_profile_model

    get_profile_model().objects.create(user_id=seller.id)

    off = api_client.get(f"/{seller.id}").json()
    assert off["contacts"] == {"phone": False}

    _contact(seller)
    on = api_client.get(f"/{seller.id}").json()
    assert on["contacts"] == {"phone": True}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kw", [{"verified": False}, {"enabled": False}, {"policy": "nobody"}]
)
def test_the_bit_is_false_for_a_number_nobody_can_get(api_client, seller, kw):
    from stapel_profiles.models import get_profile_model

    get_profile_model().objects.create(user_id=seller.id)
    _contact(seller, **kw)
    assert api_client.get(f"/{seller.id}").json()["contacts"] == {"phone": False}


@pytest.mark.django_db
def test_the_bit_does_not_move_with_the_viewer(api_client, user, seller):
    """Viewer-dependence would leak the policy itself ("the button vanished
    when I signed out, so that number is members-only")."""
    from stapel_profiles.models import get_profile_model

    get_profile_model().objects.create(user_id=seller.id)
    _contact(seller, policy=ContactPolicy.VERIFIED)

    anonymous = api_client.get(f"/{seller.id}").json()["contacts"]
    api_client.force_authenticate(user=user)
    member = api_client.get(f"/{seller.id}").json()["contacts"]
    assert anonymous == member == {"phone": True}


@pytest.mark.django_db
def test_the_batch_read_carries_the_bit_too(api_client, seller):
    from stapel_profiles.models import get_profile_model

    get_profile_model().objects.create(user_id=seller.id)
    _contact(seller)
    body = api_client.post(
        "/batch", {"user_ids": [str(seller.id)]}, format="json"
    ).json()
    assert body["profiles"][0]["contacts"] == {"phone": True}


# ---------------------------------------------------------------------------
# THE leak gate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_number_never_leaks_from_any_other_response(
    api_client, user, seller, otp
):
    """Grep EVERY response this module serves for the stored number.

    Not "check the fields we remembered to think about": the whole point of
    a separate reveal endpoint is that no other surface may carry the value,
    and the only way to keep that true as the module grows is to walk the
    surface and search the bytes. The one endpoint allowed to answer with it
    is asserted separately above, and is excluded here by name.
    """
    from stapel_profiles.models import get_profile_model

    profile = get_profile_model().objects.create(user_id=seller.id)
    assert profile is not None
    contact = _contact(seller, label="Work")
    ContactReveal.objects.create(contact=contact, viewer_key=user.id)
    api_client.force_authenticate(user=user)

    reads = [
        ("get", f"/{seller.id}", None),
        ("get", "/me", None),
        ("get", "/me/followers", None),
        ("get", "/me/following", None),
        ("get", "/me/blocked", None),
        ("get", "/languages", None),
        ("get", "/field-manifest", None),
        ("get", f"/{seller.id}/relationship", None),
        ("get", "/contacts", None),
        ("post", "/batch", {"user_ids": [str(seller.id), str(user.id)]}),
        ("post", f"/{seller.id}/follow", None),
        ("post", f"/{seller.id}/unfollow", None),
    ]

    leaked = []
    for method, path, payload in reads:
        call = getattr(api_client, method)
        resp = call(path, payload, format="json") if payload else call(path)
        text = resp.content.decode()
        if path == "/contacts":
            # The OWNER's own list is the one read that must carry it; here
            # the caller is NOT the owner, so it must not.
            assert PHONE not in text, "a non-owner read their own empty list wrong"
            continue
        if PHONE in text:
            leaked.append(f"{method.upper()} {path} -> {resp.status_code}")

    assert not leaked, "the stored number appeared in: " + ", ".join(leaked)


@pytest.mark.django_db
def test_the_owners_own_list_does_carry_it(authed_client, user, otp):
    """The counterweight to the leak test: a gate that would also pass if
    contacts simply did not work is not a gate."""
    _contact(user)
    assert PHONE in authed_client.get("/contacts").content.decode()


# ---------------------------------------------------------------------------
# Declarations and permission stack
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "view",
    [
        contact_views.ContactListCreateView,
        contact_views.ContactDetailView,
        contact_views.ContactVerifyRequestView,
        contact_views.ContactVerifyConfirmView,
        contact_views.ContactRevealSummaryView,
        contact_views.ContactRevealView,
    ],
)
def test_every_contacts_view_denies_the_guest_twice(view):
    assert IsNotAnonymousUser in view.permission_classes, view.__name__
    assert view.stapel_anonymous_access == ANONYMOUS_DENIED, view.__name__


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/contacts"),
        ("post", "/contacts"),
    ],
)
def test_a_guest_may_not_manage_contacts(guest_client, method, path):
    resp = getattr(guest_client, method)(path, {"value": PHONE}, format="json")
    assert resp.status_code in (401, 403), resp.content


# ---------------------------------------------------------------------------
# GDPR
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_export_carries_contacts_and_the_reveals_this_person_made(
    user, seller, otp
):
    from stapel_profiles.gdpr import ProfilesGDPRProvider

    mine = _contact(user, label="Work")
    theirs = _contact(seller, value=SECOND_PHONE)
    ContactReveal.objects.create(contact=mine, viewer_key=seller.id)
    ContactReveal.objects.create(
        contact=theirs, viewer_key=user.id, listing_id="91823", ip="10.0.0.1"
    )

    export = ProfilesGDPRProvider().export(user.id)
    assert [c["value"] for c in export["contacts"]] == [PHONE]
    assert export["contacts"][0]["reveal_count"] == 1
    made = export["contact_reveals_made"]
    assert [r["contact"] for r in made] == [SECOND_PHONE]
    assert made[0]["listing_id"] == "91823"
    assert made[0]["ip"] == "10.0.0.1"


@pytest.mark.django_db
def test_erasure_removes_both_the_numbers_and_the_lookups(user, seller, otp):
    from stapel_profiles.erasure import erase_account

    mine = _contact(user)
    theirs = _contact(seller, value=SECOND_PHONE)
    ContactReveal.objects.create(contact=mine, viewer_key=seller.id)
    ContactReveal.objects.create(contact=theirs, viewer_key=user.id)

    counts = erase_account(user.id)
    assert counts["contacts"] == 1
    # One row they were the viewer of, plus one that cascaded with their own
    # number — both of them their data.
    assert counts["contact_reveals"] == 2
    assert not Contact.objects.filter(owner_key=user.id).exists()
    assert not ContactReveal.objects.filter(viewer_key=user.id).exists()
    # Somebody else's number is untouched.
    assert Contact.objects.filter(id=theirs.id).exists()


@pytest.mark.django_db
def test_erasure_is_idempotent(user, otp):
    from stapel_profiles.erasure import erase_account

    _contact(user)
    erase_account(user.id)
    assert erase_account(user.id)["contacts"] == 0


# ---------------------------------------------------------------------------
# The OTP seam itself
# ---------------------------------------------------------------------------

def test_the_seam_defaults_to_stapel_auths_service():
    from stapel_profiles.contacts.conf import CONTACTS_DEFAULTS

    assert (
        CONTACTS_DEFAULTS["OTP_PROVIDER"]
        == "stapel_auth.otp.services.PhoneVerificationService"
    )


def test_without_stapel_auth_the_default_falls_back_to_the_core_store(settings):
    """A profiles-only deployment still has a working verification flow —
    the same core code store, this module's own policy numbers."""
    settings.STAPEL_PROFILES = {}
    from stapel_profiles.contacts.otp import CoreOneTimeCodeProvider, get_otp_provider

    try:
        import stapel_auth  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("stapel-auth is installed here; the fallback cannot be observed")
    assert isinstance(get_otp_provider(), CoreOneTimeCodeProvider)


def test_a_configured_path_that_cannot_be_imported_is_an_error(settings):
    """Only the shipped default falls back. A stated path that does not
    import is a typo, and hiding it behind a working-looking flow would give
    the deployment a verification policy it never asked for."""
    _settings(settings, OTP_PROVIDER="nope.NotAProvider")
    from stapel_profiles.contacts.otp import get_otp_provider

    with pytest.raises(ImportError):
        get_otp_provider()


def test_one_knob_may_be_stated_without_losing_the_others(settings):
    """AppSettings REPLACES a key's value; a dict of independent knobs must
    not be all-or-nothing, so the per-key read merges over the defaults."""
    settings.STAPEL_PROFILES = {"CONTACTS": {"REVEAL_PER_HOUR": 7}}
    from stapel_profiles.contacts.conf import contacts_setting

    assert contacts_setting("REVEAL_PER_HOUR") == 7
    assert (
        contacts_setting("OTP_PROVIDER")
        == "stapel_auth.otp.services.PhoneVerificationService"
    )
    assert contacts_setting("POLICIES") == ["members", "verified", "nobody"]
