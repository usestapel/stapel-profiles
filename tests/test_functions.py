"""The comm Function surface: profiles' named write/check/read of a name.

These are the providers a sibling calls by name — never by importing this
package, never by resolving its symbols. What they hold down:

* the **canon runs on the write path**, not only in the serializer, so a
  caller that has no access to ``validate_display_name`` (it is in another
  process) still cannot store an emoji;
* refusals are **structural** (``ok=False`` + ``reason``), never exceptions
  — an invalid name is a user typing, not an error, and comm turns a raised
  exception into an opaque ``FunctionCallError``;
* the ``reason`` vocabulary round-trips onto this module's own error keys,
  which is the whole reason a caller does not mint its own;
* ``profile.changed`` is published, because a write that skips this module's
  serializers otherwise desyncs every projection downstream of the name.
"""
import uuid

import pytest

from stapel_core.comm import call
from stapel_profiles import functions
from stapel_profiles.errors import (
    ERR_400_DISPLAY_NAME_EMOJI,
    ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS,
    ERR_400_DISPLAY_NAME_INVISIBLE_CHARS,
    ERR_400_DISPLAY_NAME_TOO_SHORT,
)
from stapel_profiles.models import get_profile_model


@pytest.fixture
def registered():
    """The providers, registered exactly as ``apps.ready()`` registers them."""
    functions.register()


class TestSetDisplayName:
    def test_creates_the_profile_row_when_there_is_none(self, db, user, registered):
        result = call(functions.SET_DISPLAY_NAME, {
            "user_id": str(user.id), "display_name": "Ada Lovelace",
        })

        assert result == {
            "ok": True, "display_name": "Ada Lovelace", "reason": None,
        }
        # "has not opened the profile screen yet" must not make an admin's
        # correction unwritable — the account exists, so the row is minted.
        assert get_profile_model().objects.get(user_id=user.id).display_name == (
            "Ada Lovelace"
        )

    def test_overwrites_an_existing_name(self, db, user, registered):
        Profile = get_profile_model()
        Profile.objects.create(user_id=user.id, display_name="Old Name")

        call(functions.SET_DISPLAY_NAME, {
            "user_id": str(user.id), "display_name": "New Name",
        })

        assert Profile.objects.get(user_id=user.id).display_name == "New Name"

    def test_trims_and_clears(self, db, user, registered):
        Profile = get_profile_model()
        Profile.objects.create(user_id=user.id, display_name="Ada")

        assert call(functions.SET_DISPLAY_NAME, {
            "user_id": str(user.id), "display_name": "   ",
        })["ok"] is True
        # Clearing is not a canon violation: the empty string short-circuits
        # before the two-character minimum.
        assert Profile.objects.get(user_id=user.id).display_name == ""

    @pytest.mark.parametrize("name,error_key", [
        ("A", ERR_400_DISPLAY_NAME_TOO_SHORT),
        ("Ada <script>", ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS),
        ("Ada 😀", ERR_400_DISPLAY_NAME_EMOJI),
        ("Ada​Lovelace", ERR_400_DISPLAY_NAME_INVISIBLE_CHARS),
    ])
    def test_refuses_structurally_with_a_key_that_round_trips(
        self, db, user, registered, name, error_key
    ):
        result = call(functions.SET_DISPLAY_NAME, {
            "user_id": str(user.id), "display_name": name,
        })

        assert result["ok"] is False
        assert result["display_name"] is None
        # The caller rebuilds THIS module's key from the reason and refuses
        # in one vocabulary — no second display-name dialect anywhere.
        assert f"error.400.{result['reason']}" == error_key
        assert not get_profile_model().objects.filter(user_id=user.id).exists()

    def test_publishes_profile_changed(self, db, user, registered, monkeypatch):
        published = []
        monkeypatch.setattr(
            "stapel_profiles.events.publish_profile_changed", published.append
        )

        call(functions.SET_DISPLAY_NAME, {
            "user_id": str(user.id), "display_name": "Ada Lovelace",
        })

        assert [p.display_name for p in published] == ["Ada Lovelace"]

    def test_no_display_name_field_is_a_structural_refusal(
        self, db, user, registered, monkeypatch
    ):
        """A deployment whose profile model has no name has none to correct.

        §66 moved ``display_name`` out of the hard core. The caller must get
        a refusal it can turn into "profiles cannot serve this here", never a
        200 over a write that did not happen.
        """
        class _NoNameProfile:
            class _Meta:
                @staticmethod
                def get_field(name):
                    from django.core.exceptions import FieldDoesNotExist

                    raise FieldDoesNotExist(name)

            _meta = _Meta
            __name__ = "NoNameProfile"

        monkeypatch.setattr(
            "stapel_profiles.models.get_profile_model", lambda: _NoNameProfile
        )
        result = call(functions.SET_DISPLAY_NAME, {
            "user_id": str(user.id), "display_name": "Ada Lovelace",
        })

        assert result == {
            "ok": False,
            "display_name": None,
            "reason": functions.REASON_NO_DISPLAY_NAME_FIELD,
        }


class TestValidateDisplayName:
    def test_accepts(self, db, registered):
        assert call(functions.VALIDATE_DISPLAY_NAME, {
            "display_name": "Ada Lovelace",
        }) == {"ok": True, "reason": None}

    def test_accepts_the_empty_string(self, db, registered):
        assert call(functions.VALIDATE_DISPLAY_NAME, {"display_name": ""})["ok"]

    def test_refuses_with_the_same_vocabulary_as_the_write(self, db, registered):
        assert call(functions.VALIDATE_DISPLAY_NAME, {
            "display_name": "Ada 😀",
        }) == {"ok": False, "reason": "display_name_emoji"}

    def test_has_no_side_effect(self, db, user, registered):
        call(functions.VALIDATE_DISPLAY_NAME, {"display_name": "Ada Lovelace"})

        assert not get_profile_model().objects.filter(user_id=user.id).exists()


class TestDisplayNames:
    def test_returns_only_ids_that_have_a_name(self, db, user, other_user, registered):
        Profile = get_profile_model()
        Profile.objects.create(user_id=user.id, display_name="Ada Lovelace")
        Profile.objects.create(user_id=other_user.id, display_name="")
        absent = uuid.uuid4()

        result = call(functions.DISPLAY_NAMES, {
            "user_ids": [str(user.id), str(other_user.id), str(absent)],
        })

        # Missing is not invented: an empty name and no row at all are both
        # simply absent, so the caller can fall back to what it holds.
        assert result == {"display_names": {str(user.id): "Ada Lovelace"}}

    def test_empty_request_is_not_a_query(self, db, registered):
        assert call(functions.DISPLAY_NAMES, {"user_ids": []}) == {
            "display_names": {}
        }


def test_register_is_idempotent(db):
    functions.register()
    functions.register()


def test_schemas_are_committed_next_to_the_providers():
    """Every provider name has a schema file the autoloader can find."""
    from pathlib import Path

    base = Path(functions.__file__).resolve().parent / "schemas" / "functions"
    for name in (
        functions.SET_DISPLAY_NAME,
        functions.VALIDATE_DISPLAY_NAME,
        functions.DISPLAY_NAMES,
    ):
        schema = base / f"{name}.json"
        assert schema.exists(), f"missing schema for {name}"
        import json

        assert json.loads(schema.read_text())["title"] == name
