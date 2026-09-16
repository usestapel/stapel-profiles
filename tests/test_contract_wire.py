"""Every response body the contract declares is a body the views actually send.

``docs/schema.json`` is emitted from the views' ``@extend_schema``
annotations, and an annotation is a CLAIM: it says what the view returns, and
the generator has no way to check it against the method body.
``tests/test_contract.py`` compares the committed document against a FRESH
EMISSION of the same annotations — it proves the file is not stale, and
nothing else, because both sides come from the claim.

This is the gate the generator cannot be: it performs every operation the
committed schema declares with a JSON response body, and validates the body
it gets against the schema it was promised.

Rules this file holds itself to:

* an operation with a declared JSON response and no entry in ``RECIPES``
  FAILS LOUDLY — a gate that quietly covers three of four rows is the family
  of green that proves nothing;
* a path parameter the gate cannot fill fails at the point of substitution,
  naming the operation;
* an operation is driven in BOTH of its interesting states wherever that is
  cheap — a profile with an avatar and one without, a verified contact and an
  unverified one, a contact with reveals and one with none. A recipe that
  only ever builds the fully populated object cannot see a field that is
  ``null`` on the empty state, which is the exact class this gate is for;
* the operations that genuinely cannot be driven in-process would be listed
  by name in ``UNDRIVABLE`` with a one-line reason each. That list is
  asserted to be exactly current: a stale entry, or a missing reason, fails.
  Today it is empty — all 24 declared operations run in-process.

Runs on every interpreter: it reads the committed schema and never emits.
``tests/test_contract.py`` skips off Python 3.12 because it EMITS and
compares bytes; this file does neither.

The urlconf below is the emission mount (``codegen_urls.py``): profiles under
``profiles/api/``, which ``stapel_profiles.urls`` extends with the mandatory
``v1/`` segment. The pytest urlconf (``_codegen_settings.settings_kwargs``'s
default, ``stapel_profiles.urls_v1``) mounts the paths BARE — ``/me``, not
``/profiles/api/v1/me`` — so every path in the committed document is
unreachable under it.

What it found on its first run (24 of 24 operations driven, 3 red — one
defect, three endpoints):

* ``GET /{user_id}``, ``POST /batch`` and ``GET /me/blocked`` answer a
  ``null`` where the contract declares a required, non-nullable value, in
  both cases on the EMPTY state of a profile:

  - a registered person with no profile row is answered, by design, from an
    UNSAVED model instance (``views._unwritten_profile``). ``created_at`` is
    ``auto_now_add``, so on an instance that was never saved it is ``None`` —
    while ``ProfilePublicResponse.created_at`` is a required ``string`` with
    no ``nullable``. The two public endpoints that take that branch (``GET
    /{user_id}`` and ``POST /batch``) therefore send ``created_at: null`` for
    every account that has never opened settings;
  - ``ProfilePublicSerializer.get_avatar_image`` returns ``None`` for a
    profile with no avatar (``serializers.avatar_image``, first branch),
    while ``@extend_schema_field(StapelImageSerializer)`` makes the emitter
    declare ``avatar_image`` a required, non-nullable ``StapelImage``. ``GET
    /me/blocked`` — the one operation whose declared body is the MODEL
    serializer ``ProfilePublic`` rather than a DTO — sends ``null`` there for
    every blocked profile without an avatar. The DTO-shaped surfaces do not
    share the defect: ``ProfileResponse``/``ProfilePublicResponse`` both
    declare ``avatar_image`` nullable, because the dataclass says
    ``Optional[StapelImageDTO]``.

Both are left exactly as they are: this is a gate, not a fix.
"""
import copy
import json
import re
import uuid
from pathlib import Path

import jsonschema
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import include, path as url_path
from django.utils import timezone
from rest_framework.test import APIClient

REPO = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((REPO / "docs" / "schema.json").read_text())

#: The mount the contract is emitted at, reproduced for the test client.
urlpatterns = [
    url_path("profiles/api/", include("stapel_profiles.urls")),
]

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]

V1 = "/profiles/api/v1"
PASSWORD = "wire-contract-password-7"
#: A 32-hex gravatar email hash — an avatar that renders through
#: ``media.image("link", ...)`` with no storage, no CDN and no host allowlist.
AVATAR_HASH = "0123456789abcdef0123456789abcdef"
#: Documentation-range numbers, never dialled.
PHONE = "+15550100"
SECOND_PHONE = "+15550111"


@pytest.fixture(autouse=True)
def _media_root(tmp_path):
    """No operation here uploads, but ``MEDIA_ROOT`` is unset in the harness
    settings, so anything that ever did would write into the checkout."""
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# The contract side: what the document declares
# ─────────────────────────────────────────────────────────────────────────────


def _blank_string_alternative(node):
    """A ``oneOf`` branch that means "or the empty string".

    ``URLField(allow_blank=True)`` is emitted as ``oneOf: [{format: uri,
    maxLength: 500}, {maxLength: 0}]``. The two branches are disjoint only
    under format-ASSERTING semantics; JSON Schema treats ``format`` as an
    annotation, so ``""`` matches both and the exclusive ``oneOf`` fails on a
    value the document plainly allows. That is a validator-semantics gap, not
    a claim the wire breaks — so the branches are read as alternatives.
    """
    branches = node.get("oneOf")
    if not isinstance(branches, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "string" and b.get("maxLength") == 0
        for b in branches
    )


def _json_schema(node):
    """OpenAPI 3.0 → JSON Schema, for the divergences that matter here.

    OAS 3.0 spells "may be null" as ``nullable: true`` beside a ``type``;
    JSON Schema has no such keyword and would refuse the null. The second
    conversion is the blank-string ``oneOf`` above. Everything else
    drf-spectacular emits (``$ref``, ``allOf``, ``enum``, ``required``,
    ``readOnly``) is JSON Schema as written.
    """
    if isinstance(node, list):
        return [_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    rebuilt = {k: _json_schema(v) for k, v in node.items() if k != "nullable"}
    if _blank_string_alternative(rebuilt):
        rebuilt["anyOf"] = rebuilt.pop("oneOf")
    if node.get("nullable"):
        return {"anyOf": [rebuilt, {"type": "null"}]}
    return rebuilt


def _validator(response_schema):
    root = copy.deepcopy(response_schema)
    root["components"] = copy.deepcopy(SCHEMA["components"])
    return jsonschema.Draft202012Validator(_json_schema(root))


def _operations():
    """Every ``(method, path, 2xx code, JSON body schema)`` the contract declares."""
    ops = []
    for path, methods in SCHEMA["paths"].items():
        for method, op in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for code, response in op.get("responses", {}).items():
                body = (
                    response.get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                if body is not None and code.startswith("2"):
                    ops.append((method.upper(), path, int(code), body))
    return sorted(ops, key=lambda o: (o[1], o[0]))


OPERATIONS = _operations()


# ─────────────────────────────────────────────────────────────────────────────
# The wire side: harness
# ─────────────────────────────────────────────────────────────────────────────


def _unique(prefix):
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def make_user(**kwargs):
    User = get_user_model()
    defaults = dict(
        username=_unique("wire_"),
        email=f"{_unique('wire-')}@example.com",
        password=PASSWORD,
    )
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def make_guest():
    """A guest session: ``is_authenticated`` and nobody registered."""
    return make_user(email=None, is_anonymous=True)


def client_for(user=None):
    """An APIClient, authenticated as ``user`` when one is given."""
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def anonymous():
    return APIClient()


def make_profile(user, *, avatar=True, **kwargs):
    """A profile row for ``user``. ``avatar=False`` is the empty state."""
    from stapel_profiles.models import AvatarSource, get_profile_model

    defaults = dict(display_name="Ada Lovelace")
    if avatar:
        defaults.update(avatar_source=AvatarSource.GRAVATAR, avatar=AVATAR_HASH)
    defaults.update(kwargs)
    profile, _created = get_profile_model().objects.update_or_create(
        user_id=user.id, defaults=defaults
    )
    return profile


def user_without_profile():
    """A registered person who has never opened settings.

    The public endpoints answer this account from an UNSAVED instance
    (``views._unwritten_profile``) rather than 404 — the state the
    fully-populated recipe can never reach.
    """
    from stapel_profiles.models import get_profile_model

    user = make_user()
    get_profile_model().objects.filter(user_id=user.id).delete()
    return user


def relate(follower, following, status):
    from stapel_profiles.models import UserRelationship

    return UserRelationship.objects.update_or_create(
        follower_id=follower.id, following_id=following.id, defaults={"status": status}
    )[0]


# ── the contacts OTP seam ────────────────────────────────────────────────────


class FixedCodeProvider:
    """Accepts one code, refuses every other. Wired in by dotted path."""

    CODE = "424242"

    def send_verification_code(self, phone, device_id=None):
        return type("Receipt", (), {"ttl": 600})()

    def verify_code(self, phone, code):
        if code == self.CODE:
            return {"success": True}
        return {"error": "invalid_code", "attempts_remaining": 4}


class TtllessCodeProvider(FixedCodeProvider):
    """A provider whose receipt states no lifetime.

    The contract's own words: ``expires_in`` is "seconds the code stays good,
    WHEN THE PROVIDER SAYS". A provider that does not say is the other half
    of that sentence, and the view reads it with
    ``getattr(receipt, "ttl", None)`` — so this is the state where the field
    is null.
    """

    def send_verification_code(self, phone, device_id=None):
        return object()


def contacts_settings(**contacts):
    """A fresh override each time: one instance cannot be entered twice."""
    return override_settings(
        STAPEL_PROFILES={
            "CONTACTS": {
                "OTP_PROVIDER": "tests.test_contract_wire.FixedCodeProvider",
                **contacts,
            }
        }
    )


def make_contact(owner, value=PHONE, *, verified=True, **kwargs):
    from stapel_profiles.contacts.models import Contact

    defaults = dict(
        owner_key=owner.id,
        value=value,
        verified_at=timezone.now() if verified else None,
    )
    defaults.update(kwargs)
    return Contact.objects.create(**defaults)


def make_reveal(contact, viewer):
    from stapel_profiles.contacts.models import ContactReveal

    return ContactReveal.objects.create(contact=contact, viewer_key=viewer.id)


def languages(*codes):
    """Declare exactly these languages; the viewset materialises the rows."""
    names = {"en": "English", "fr": "French", "de": "German"}
    return override_settings(LANGUAGES=[(c, names.get(c, c)) for c in codes])


def field_manifest():
    """A manifest with both an enum field and plain text ones.

    The default manifest is empty, and an empty array validates against any
    item schema — so the declared entry shape would go unchecked.
    """
    return override_settings(
        STAPEL_PROFILES={
            "PROFILES_FIELDS": {
                "identity": "first_last_name",
                "standard_fields": ["measurement_units"],
            }
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# The recipe table
# ─────────────────────────────────────────────────────────────────────────────


class Call:
    """Performs one declared operation, and refuses to guess a path parameter."""

    def __init__(self, method, path):
        self.method = method
        self.path = path

    def __call__(self, client, params=None, data=None, query="", **extra):
        url = self.path
        for name, value in (params or {}).items():
            url = url.replace("{%s}" % name, str(value))
        assert "{" not in url, (
            f"{self.method} {self.path}: a path parameter this gate does not "
            "know how to fill — teach its recipe, or the operation goes unchecked"
        )
        send = getattr(client, self.method.lower())
        if self.method in ("GET", "DELETE"):
            return send(url + query, **extra)
        return send(url + query, data if data is not None else {}, format="json", **extra)


#: How to perform each operation the contract declares with a JSON response
#: body, keyed by ``(METHOD, path template)``. Each recipe receives a ``Call``
#: bound to that operation and returns the response it produced — or a list of
#: responses, one per interesting state, every one of which is validated.
RECIPES = {}


def recipe(method, path):
    def register(fn):
        key = (method, V1 + path)
        assert key not in RECIPES, f"duplicate recipe for {method} {path}"
        RECIPES[key] = fn
        return fn

    return register


#: Operations that cannot be driven in-process, by name and with the reason.
#: EMPTY, and that is a result: every one of the 24 declared operations runs
#: here. The mechanism stays because a silent skip is never acceptable — an
#: operation that becomes undrivable must be named and explained, not dropped.
UNDRIVABLE: dict = {}


# ── the public profile ───────────────────────────────────────────────────────


@recipe("GET", "/{user_id}")
def _profile_detail(call):
    """Both states of the public read: a written profile, and an unwritten one."""
    viewer = make_user()
    written = make_user()
    make_profile(written)
    return [
        call(client_for(viewer), params={"user_id": written.id}),
        # A registered person with no row — answered 200 from an unsaved
        # instance, not 404 (views._unwritten_profile).
        call(client_for(viewer), params={"user_id": user_without_profile().id}),
    ]


@recipe("POST", "/batch")
def _profile_batch(call):
    """A page mixing every state the endpoint distinguishes."""
    viewer = make_user()
    with_avatar = make_user()
    make_profile(with_avatar)
    without_avatar = make_user()
    make_profile(without_avatar, avatar=False)
    unwritten = user_without_profile()
    return call(
        client_for(viewer),
        data={
            "user_ids": [
                str(with_avatar.id),
                str(without_avatar.id),
                str(unwritten.id),
                # An id that names nobody — the `missing` half of the answer.
                str(uuid.uuid4()),
            ]
        },
    )


@recipe("GET", "/me")
def _my_profile(call):
    """A filled-in profile and a brand-new one (get_or_create's own defaults)."""
    filled = make_user()
    make_profile(filled)
    return [
        call(client_for(filled)),
        call(client_for(make_user())),
    ]


@recipe("PATCH", "/me")
def _my_profile_patch(call):
    user = make_user()
    make_profile(user, avatar=False)
    return call(client_for(user), data={"display_name": "Grace Hopper"})


@recipe("GET", "/me/blocked")
def _my_blocked(call):
    """The blocked list, with an avatar-bearing profile and one without."""
    from stapel_profiles.models import RelationshipStatus

    me = make_user()
    with_avatar = make_user()
    make_profile(with_avatar)
    relate(me, with_avatar, RelationshipStatus.BLOCKED)
    without_avatar = make_user()
    make_profile(without_avatar, avatar=False)
    relate(me, without_avatar, RelationshipStatus.BLOCKED)
    return call(client_for(me))


@recipe("GET", "/field-manifest")
def _field_manifest(call):
    with field_manifest():
        return call(anonymous())


# ── languages ────────────────────────────────────────────────────────────────


@recipe("GET", "/languages/")
def _languages_list(call):
    with languages("en", "fr"):
        return call(anonymous())


@recipe("GET", "/languages/{code}/")
def _language_detail(call):
    with languages("en"):
        # The row is materialised by the list read (ensure_declared_languages).
        assert anonymous().get(f"{V1}/languages/").status_code == 200
        return call(anonymous(), params={"code": "en"})


# ── relationships ────────────────────────────────────────────────────────────


@recipe("POST", "/{user_id}/follow")
def _follow(call):
    me = make_user()
    target = make_user()
    make_profile(target)
    return call(client_for(me), params={"user_id": target.id})


@recipe("POST", "/{user_id}/unfollow")
def _unfollow(call):
    """A relationship that exists, and one that never did."""
    from stapel_profiles.models import RelationshipStatus

    me = make_user()
    followed = make_user()
    relate(me, followed, RelationshipStatus.FOLLOWING)
    return [
        call(client_for(me), params={"user_id": followed.id}),
        call(client_for(me), params={"user_id": make_user().id}),
    ]


@recipe("POST", "/{user_id}/block")
def _block(call):
    return call(client_for(make_user()), params={"user_id": make_user().id})


@recipe("POST", "/{user_id}/unblock")
def _unblock(call):
    from stapel_profiles.models import RelationshipStatus

    me = make_user()
    blocked = make_user()
    relate(me, blocked, RelationshipStatus.BLOCKED)
    return [
        call(client_for(me), params={"user_id": blocked.id}),
        call(client_for(me), params={"user_id": make_user().id}),
    ]


@recipe("GET", "/{user_id}/relationship")
def _relationship(call):
    from stapel_profiles.models import RelationshipStatus

    me = make_user()
    followed = make_user()
    relate(me, followed, RelationshipStatus.FOLLOWING)
    return [
        call(client_for(me), params={"user_id": followed.id}),
        # No row at all — "neutral" is an answer, not a missing one.
        call(client_for(me), params={"user_id": make_user().id}),
    ]


@recipe("GET", "/me/followers")
def _my_followers(call):
    from stapel_profiles.models import RelationshipStatus

    me = make_user()
    relate(make_user(), me, RelationshipStatus.FOLLOWING)
    return [call(client_for(me)), call(client_for(make_user()))]


@recipe("GET", "/me/following")
def _my_following(call):
    from stapel_profiles.models import RelationshipStatus

    me = make_user()
    relate(me, make_user(), RelationshipStatus.FOLLOWING)
    return [call(client_for(me)), call(client_for(make_user()))]


# ── notifications ────────────────────────────────────────────────────────────


@recipe("POST", "/notifications/unsubscribe")
def _unsubscribe(call):
    from stapel_core.notifications.tokens import generate_unsubscribe_token

    user = make_user()
    make_profile(user)
    token = generate_unsubscribe_token(str(user.id), "messages", "email")
    return [
        call(anonymous(), query=f"?token={token}"),
        # The idempotent repeat — the second branch of the same 200.
        call(anonymous(), query=f"?token={token}"),
    ]


# ── contacts: the owner's own ────────────────────────────────────────────────


@recipe("GET", "/contacts")
def _contacts_list(call):
    """A proven number and an unproven one, plus the empty screen."""
    owner = make_user()
    proven = make_contact(owner, PHONE, label="Work")
    make_contact(owner, SECOND_PHONE, verified=False)
    make_reveal(proven, make_user())
    with contacts_settings():
        return [call(client_for(owner)), call(client_for(make_user()))]


@recipe("POST", "/contacts")
def _contacts_create(call):
    with contacts_settings():
        return call(
            client_for(make_user()), data={"value": PHONE, "label": "Work"}
        )


@recipe("PATCH", "/contacts/{contact_id}")
def _contacts_update(call):
    owner = make_user()
    contact = make_contact(owner, verified=False)
    with contacts_settings():
        return call(
            client_for(owner),
            params={"contact_id": contact.id},
            data={"label": "Mobile", "policy": "verified", "enabled": False},
        )


@recipe("DELETE", "/contacts/{contact_id}")
def _contacts_delete(call):
    owner = make_user()
    contact = make_contact(owner)
    with contacts_settings():
        return call(client_for(owner), params={"contact_id": contact.id})


@recipe("GET", "/contacts/{contact_id}/reveals/summary")
def _contacts_reveal_summary(call):
    """A number that has been handed over, and one that never has."""
    owner = make_user()
    busy = make_contact(owner, PHONE)
    make_reveal(busy, make_user())
    quiet = make_contact(owner, SECOND_PHONE)
    with contacts_settings():
        client = client_for(owner)
        return [
            call(client, params={"contact_id": busy.id}),
            call(client, params={"contact_id": quiet.id}),
        ]


@recipe("POST", "/contacts/{contact_id}/verify/request")
def _contacts_verify_request(call):
    """A provider that states a lifetime, and one that does not."""
    owner = make_user()
    contact = make_contact(owner, verified=False)
    with contacts_settings():
        stated = call(client_for(owner), params={"contact_id": contact.id})
    with contacts_settings(
        OTP_PROVIDER="tests.test_contract_wire.TtllessCodeProvider"
    ):
        unstated = call(client_for(owner), params={"contact_id": contact.id})
    return [stated, unstated]


@recipe("POST", "/contacts/{contact_id}/verify/confirm")
def _contacts_verify_confirm(call):
    owner = make_user()
    contact = make_contact(owner, verified=False)
    with contacts_settings():
        return call(
            client_for(owner),
            params={"contact_id": contact.id},
            data={"code": FixedCodeProvider.CODE},
        )


@recipe("POST", "/contacts/reveal")
def _contacts_reveal(call):
    """A viewer the policy admits, and one with nothing to be handed."""
    seller = make_user()
    make_contact(seller, PHONE, label="Work")
    silent = make_user()
    viewer = make_user()
    with contacts_settings():
        return [
            call(client_for(viewer), data={"owner_key": str(seller.id)}),
            # An empty list is a normal 200 — the seller published nothing.
            call(client_for(viewer), data={"owner_key": str(silent.id)}),
        ]


# ─────────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────────


#: Operations whose declared body the wire does not send.
#:
#: Each entry names the defect and its owner, and ``strict=True`` turns a
#: fixed one into a failure until the entry is deleted — so a finding can be
#: neither forgotten nor quietly kept.
KNOWN_MISMATCHES: dict = {}
#: EMPTY, and by fix rather than exemption: all three entries this gate found
#: on the day it was written were repaired in the same release (created_at is
#: `str | None` on the public DTO, avatar_image is declared nullable on the one
#: surface whose body is the model serializer). The mechanism stays for the
#: next finding - an entry names the defect and its owner, and `strict=True`
#: turns a fixed one into a failure until the entry is deleted.


def test_the_contract_declares_something_to_check():
    assert OPERATIONS, "docs/schema.json declares no JSON responses at all"


def test_every_declared_path_resolves_under_this_urlconf():
    """The suite must be looking where the document describes.

    Three of the first four libraries this gate was written for had a
    committed contract that nothing had ever driven, because the test urlconf
    mounted somewhere the document does not describe: one mounted a different
    prefix AND one segment short, one mounted the paths bare, and this one
    mounted less than the emission did — so the gdpr half of its own contract
    was unreachable. In every case the operations were "covered" by a file
    that could not have reached a single one of them.

    That is the same family as a gate nobody asks: the recipes can all be
    written, the run can be green, and not one request went where the contract
    says it goes. A missing recipe already fails loudly; this fails when the
    MOUNT is wrong, which no per-operation check can see, because when the
    mount is wrong every operation is equally and silently unreachable.

    Asserted against the urlconf this module declares, so it fails at the one
    moment it is cheap to fix: when somebody changes a mount.
    """
    from django.urls import Resolver404, resolve

    # Resolution cares about the SHAPE of a segment, and this urlconf uses
    # several converters — uuid, int, slug. A path counts as reachable if any
    # one shape resolves: the question here is whether the mount exists, not
    # whether a particular id does.
    candidates = (
        "00000000-0000-4000-8000-000000000000",
        "1",
        "a-slug",
    )

    unreachable = []
    for _method, path, _code, _schema in OPERATIONS:
        for value in candidates:
            try:
                resolve(re.sub(r"\{[^}]+\}", value, path))
                break
            except Resolver404:
                continue
        else:
            unreachable.append(path)

    assert not unreachable, (
        "these declared paths do not resolve under this module's urlconf, so "
        "nothing here can be driving them — the mount is wrong, not the "
        "recipes:\n  " + "\n  ".join(sorted(set(unreachable)))
    )


def test_every_declared_operation_is_driven_or_named_undrivable():
    """No operation is covered by silence, and no entry outlives its operation."""
    declared = {(method, path) for method, path, _code, _schema in OPERATIONS}
    covered = set(RECIPES) | set(UNDRIVABLE)

    missing = sorted(declared - covered)
    assert not missing, (
        "operations with a declared JSON response body and no recipe:\n"
        + "\n".join(f"  {m} {p}" for m, p in missing)
    )
    stale = sorted(covered - declared)
    assert not stale, (
        "recipes/exclusions for operations the contract no longer declares:\n"
        + "\n".join(f"  {m} {p}" for m, p in stale)
    )
    both = sorted(set(RECIPES) & set(UNDRIVABLE))
    assert not both, f"driven AND excluded: {both}"
    for key, reason in UNDRIVABLE.items():
        assert reason and reason.strip(), f"{key} is excluded with no reason"


def test_every_known_mismatch_is_still_declared_and_explained():
    """A recorded defect must name a live operation and carry its reason.

    Without this, an operation that is renamed or removed leaves an entry that
    silences nothing and reads like a known problem forever.
    """
    declared = {(method, path) for method, path, _code, _schema in OPERATIONS}
    for key, reason in KNOWN_MISMATCHES.items():
        assert key in declared, (
            f"{key} is recorded as a known mismatch but the contract no longer "
            "declares it — delete the entry"
        )
        assert reason and reason.strip(), f"{key} is recorded with no reason"


@pytest.mark.parametrize(
    "method,path,code,body_schema",
    OPERATIONS,
    ids=[f"{m} {p}" for m, p, _, _ in OPERATIONS],
)
def test_the_wire_matches_the_declared_response(method, path, code, body_schema, request):
    if (method, path) in UNDRIVABLE:
        pytest.skip(f"excluded by name: {UNDRIVABLE[(method, path)]}")

    if (method, path) in KNOWN_MISMATCHES:
        request.node.add_marker(
            pytest.mark.xfail(
                strict=True,
                reason=f"{method} {path}: {KNOWN_MISMATCHES[(method, path)]}",
            )
        )

    perform = RECIPES.get((method, path))
    assert perform is not None, (
        f"{method} {path} declares a response body and has no recipe — an "
        "unchecked operation is a schema nobody proves. Teach RECIPES, or "
        "name it in UNDRIVABLE with a reason."
    )

    produced = perform(Call(method, path))
    responses = produced if isinstance(produced, list) else [produced]
    assert responses, f"{method} {path}: the recipe produced no response at all"

    validator = _validator(body_schema)
    for index, response in enumerate(responses):
        where = f"{method} {path} (state {index + 1} of {len(responses)})"
        assert response.status_code == code, (
            f"{where}: expected the declared {code}, got "
            f"{response.status_code}: {response.content[:400]}"
        )

        body = response.json()
        errors = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
        assert not errors, (
            f"{where} answers a body the contract does not describe:\n"
            + "\n".join(
                f"  at {list(e.path) or '<root>'}: {e.message}" for e in errors[:10]
            )
            + f"\n  body: {json.dumps(body)[:600]}"
        )
        # An empty list validates against any item schema, so a list response
        # must actually carry a row for the check to have looked at anything.
        if isinstance(body, list):
            assert body, f"{where}: the declared list came back empty"
