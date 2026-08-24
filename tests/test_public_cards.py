"""The public card — and the promise that it is never more than public.

``profiles.public_cards`` is read by servers (a classified seller card, a
chat conversation header) and rendered to strangers. The defect this suite
exists to prevent is a caller receiving MORE than a stranger may see, so the
pins are:

* the card's key set is exactly ``cards.CARD_KEYS`` — a field added to
  ``Profile`` tomorrow cannot reach a caller through this path;
* every profile field in it obeys ``PROFILES_PUBLIC_FIELDS``, the same
  setting the public HTTP lookups obey, without this function being named
  anywhere in a host's settings;
* the avatar READ boundary (audit PROFILE-01) applies here too — a stored
  reference today's policy would refuse degrades to "no avatar";
* the CDN enrichment is one call for a whole page, and its failure is data
  (``meta_reason``), never an exception: a conversation must not fail to
  open because the CDN blinked.
"""

import uuid

import pytest
from django.test import override_settings

from stapel_core.comm import call, function_registry, register_function
from stapel_profiles import functions
from stapel_profiles.cards import CARD_KEYS
from stapel_profiles.models import Profile

CDN_REF = "avatar/" + "a" * 64
OTHER_REF = "avatar/" + "b" * 64


@pytest.fixture(autouse=True)
def clean_function_registry():
    function_registry.clear()
    yield
    function_registry.clear()


@pytest.fixture
def registered():
    functions.register()


@pytest.fixture
def cdn():
    """A registered FAKE of ``cdn.describe_many``.

    A fake, not an import of stapel-cdn: this suite proves profiles' half of
    a comm contract, and a test that imports a sibling passes in a shared
    workspace venv and dies on a clean runner.
    """
    calls = []

    def provider(payload):
        calls.append(payload)
        refs = list(payload.get("refs") or [])
        items = {
            ref: {
                "mime": "image/jpeg", "ext": "jpg", "bytes": 12345,
                "width": 400, "height": 400, "aspect": 1.0, "square": True,
                "animated": False, "preview_b64": "data:image/jpeg;base64,AA",
                "preview_kind": "blur",
                "variants": [{"tier": "thumb", "branch": None, "size": 96}],
                "meta_status": "ok", "meta_reason": None,
            }
            for ref in refs
            if ref == CDN_REF
        }
        return {"items": items, "missing": [r for r in refs if r not in items]}

    register_function("cdn.describe_many", provider)
    return calls


def _cards(user_ids):
    return call(functions.PUBLIC_CARDS, {"user_ids": [str(uid) for uid in user_ids]})


@pytest.mark.django_db
class TestTheProjection:
    def test_a_card_carries_exactly_the_declared_keys(self, registered, cdn):
        profile = Profile.objects.create(
            user_id=uuid.uuid4(), display_name="Ada Lovelace",
        )
        answer = _cards([profile.user_id])
        card = answer["profiles"][str(profile.user_id)]

        assert set(card) == set(CARD_KEYS)
        assert card["display_name"] == "Ada Lovelace"
        assert card["member_since"] == profile.created_at.date().isoformat()
        assert card["seller_type"] == ""

    def test_nothing_private_rides_along(self, registered, cdn):
        profile = Profile.objects.create(
            user_id=uuid.uuid4(),
            display_name="Ada",
            location_display_name_broad="Kyiv, Ukraine",
            auto_translate_content=True,
        )
        card = _cards([profile.user_id])["profiles"][str(profile.user_id)]

        # Whereabouts, notification consents, language, onboarding state:
        # a stranger sees none of it, so neither does a comm caller.
        for private in (
            "location_display_name_broad", "location_id", "email_messages",
            "push_messages", "app_language", "auto_translate_content",
            "created_at", "updated_at",
        ):
            assert private not in card

    def test_the_public_field_policy_governs_the_card(self, registered, cdn):
        profile = Profile.objects.create(
            user_id=uuid.uuid4(), display_name="Ada",
            avatar_source="cdn", avatar=CDN_REF,
        )
        with override_settings(
            STAPEL_PROFILES={"PROFILES_PUBLIC_FIELDS": ["user_id"]}
        ):
            card = _cards([profile.user_id])["profiles"][str(profile.user_id)]

        # A host that hid the name and the avatar from public lookups hid
        # them here too, without having heard of this function.
        assert card["display_name"] == ""
        assert card["avatar"] is None

    def test_member_since_is_a_date_not_a_timestamp(self, registered, cdn):
        profile = Profile.objects.create(user_id=uuid.uuid4())
        card = _cards([profile.user_id])["profiles"][str(profile.user_id)]
        assert len(card["member_since"]) == len("2026-08-24")


@pytest.mark.django_db
class TestWhoGetsACard:
    def test_a_registered_person_with_no_row_gets_a_renderable_card(
        self, registered, cdn, user
    ):
        answer = _cards([user.id])

        # The 0.15.0 lesson, in comm form: a registered person is somebody.
        # An empty name is an answer; the caller renders its own fallback.
        card = answer["profiles"][str(user.id)]
        assert card["display_name"] == ""
        assert card["avatar"] is None
        assert card["member_since"] is None
        assert answer["missing"] == []

    def test_an_id_that_names_nobody_is_missing_not_an_error(self, registered, cdn):
        ghost = uuid.uuid4()
        answer = _cards([ghost])
        assert answer["profiles"] == {}
        assert answer["missing"] == [str(ghost)]

    def test_a_malformed_id_is_missing_and_the_page_still_answers(
        self, registered, cdn
    ):
        profile = Profile.objects.create(user_id=uuid.uuid4())
        answer = call(functions.PUBLIC_CARDS, {
            "user_ids": ["not-a-uuid", str(profile.user_id)],
        })
        # A card is a render, not an enforcement path: one bad id must not
        # blank a whole page. (The block check, where being wrong has a
        # direction, refuses instead — see test_relationships.py.)
        assert answer["missing"] == ["not-a-uuid"]
        assert str(profile.user_id) in answer["profiles"]

    def test_ids_are_de_duplicated(self, registered, cdn):
        profile = Profile.objects.create(user_id=uuid.uuid4())
        answer = _cards([profile.user_id, profile.user_id])
        assert list(answer["profiles"]) == [str(profile.user_id)]


@pytest.mark.django_db
class TestTheAvatar:
    def test_render_metadata_comes_from_cdn_describe_many(self, registered, cdn):
        profile = Profile.objects.create(
            user_id=uuid.uuid4(), avatar_source="cdn", avatar=CDN_REF,
        )
        card = _cards([profile.user_id])["profiles"][str(profile.user_id)]

        assert cdn == [{"refs": [CDN_REF]}]
        avatar = card["avatar"]
        assert avatar["ref"] == CDN_REF
        assert avatar["width"] == 400 and avatar["aspect"] == 1.0
        assert avatar["preview_b64"].startswith("data:image/")
        assert avatar["variants"] == [{"tier": "thumb", "branch": None, "size": 96}]
        assert avatar["meta_status"] == "ok" and avatar["meta_reason"] is None

    def test_one_call_for_a_whole_page(self, registered, cdn):
        for _ in range(5):
            Profile.objects.create(
                user_id=uuid.uuid4(), avatar_source="cdn", avatar=CDN_REF,
            )
        ids = list(Profile.objects.values_list("user_id", flat=True))
        _cards(ids)
        assert len(cdn) == 1

    def test_a_ref_the_cdn_does_not_know_says_so(self, registered, cdn):
        profile = Profile.objects.create(
            user_id=uuid.uuid4(), avatar_source="cdn", avatar=OTHER_REF,
        )
        avatar = _cards([profile.user_id])["profiles"][str(profile.user_id)]["avatar"]
        assert avatar["ref"] == OTHER_REF
        assert avatar["meta_status"] == "missing"
        assert avatar["meta_reason"] == "unknown_ref"

    def test_a_cdn_outage_degrades_the_card_it_does_not_fail_it(self, registered):
        def broken(payload):
            raise RuntimeError("cdn is down")

        register_function("cdn.describe_many", broken)
        profile = Profile.objects.create(
            user_id=uuid.uuid4(), display_name="Ada",
            avatar_source="cdn", avatar=CDN_REF,
        )

        card = _cards([profile.user_id])["profiles"][str(profile.user_id)]

        assert card["display_name"] == "Ada"
        assert card["avatar"]["ref"] == CDN_REF
        assert card["avatar"]["width"] is None
        assert card["avatar"]["meta_status"] == "partial"
        assert card["avatar"]["meta_reason"] == "cdn_unavailable"

    def test_the_enrichment_can_be_switched_off(self, registered, cdn):
        profile = Profile.objects.create(
            user_id=uuid.uuid4(), avatar_source="cdn", avatar=CDN_REF,
        )
        with override_settings(
            STAPEL_PROFILES={"PROFILES_CARD_MEDIA_FUNCTION": ""}
        ):
            card = _cards([profile.user_id])["profiles"][str(profile.user_id)]
        assert cdn == []
        assert card["avatar"]["meta_reason"] == "cdn_unavailable"

    def test_an_allowed_external_avatar_is_a_ref_with_no_numbers(
        self, registered, cdn
    ):
        with override_settings(
            STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["cdn.example.com"]}
        ):
            profile = Profile.objects.create(
                user_id=uuid.uuid4(), avatar_source="url",
                avatar="https://cdn.example.com/me.png",
            )
            avatar = _cards([profile.user_id])["profiles"][str(profile.user_id)]["avatar"]

        assert avatar["ref"] == "https://cdn.example.com/me.png"
        assert avatar["meta_status"] == "partial"
        assert avatar["meta_reason"] == "external_avatar"
        # The CDN was never asked about a link it does not own.
        assert cdn == []

    def test_a_stored_avatar_todays_policy_would_refuse_degrades_to_none(
        self, registered, cdn
    ):
        with override_settings(
            STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["*"]}
        ):
            profile = Profile.objects.create(
                user_id=uuid.uuid4(), avatar_source="url",
                avatar="https://tracker.example.net/beacon.png",
            )
        # Host allowlist closed again: an old row is not evidence that
        # today's policy allows it, and no client should have to defend
        # itself against this field.
        card = _cards([profile.user_id])["profiles"][str(profile.user_id)]
        assert card["avatar"] is None
