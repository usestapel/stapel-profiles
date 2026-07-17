"""
Tests for avatar validation via the comm layer (cdn.media_exists).
"""
import pytest
from django.test import override_settings
from stapel_core.comm import function_registry, register_function

from stapel_profiles.errors import (
    ERR_400_AVATAR_NOT_FOUND,
    ERR_400_INVALID_AVATAR_FORMAT,
)
from stapel_profiles.serializers import ProfileCreateUpdateSerializer

VALID_REF = "avatar/" + "a" * 64


@pytest.fixture(autouse=True)
def clean_function_registry():
    """Each test starts and ends with an empty function registry."""
    function_registry.clear()
    yield
    function_registry.clear()


def _validate(avatar, source="cdn"):
    """Run serializer validation for the avatar field, return the serializer.

    §66: avatar format/existence checks only apply when avatar_source=cdn
    (the historical, still-default-tested-here, "cdn" behavior) — file/url/
    gravatar sources are free-form and skip both checks entirely.
    """
    data = {"avatar": avatar}
    if source is not None:
        data["avatar_source"] = source
    serializer = ProfileCreateUpdateSerializer(data=data)
    serializer.is_valid()
    return serializer


def _avatar_errors(serializer):
    return [str(err) for err in serializer.errors.get("avatar", [])]


class TestAvatarValidationViaComm:
    """Default PROFILES_AVATAR_CHECK='comm' path."""

    def test_exists_true_accepted(self):
        calls = []

        def provider(payload):
            calls.append(payload)
            return {"exists": True}

        register_function("cdn.media_exists", provider)

        serializer = _validate(VALID_REF)
        assert serializer.errors == {}
        assert serializer.validated_data["avatar"] == VALID_REF
        assert calls == [{"ref": VALID_REF}]

    def test_exists_false_rejected(self):
        register_function("cdn.media_exists", lambda payload: {"exists": False})

        serializer = _validate(VALID_REF)
        assert ERR_400_AVATAR_NOT_FOUND in _avatar_errors(serializer)

    def test_provider_raises_fail_closed(self):
        """Provider failure -> FunctionCallError -> rejected, not accepted."""

        def broken_provider(payload):
            raise RuntimeError("cdn exploded")

        register_function("cdn.media_exists", broken_provider)

        serializer = _validate(VALID_REF)
        assert ERR_400_AVATAR_NOT_FOUND in _avatar_errors(serializer)

    def test_no_provider_fail_closed(self):
        """No provider registered -> FunctionNotRegistered -> rejected."""
        serializer = _validate(VALID_REF)
        assert ERR_400_AVATAR_NOT_FOUND in _avatar_errors(serializer)

    def test_non_dict_result_fail_closed(self):
        register_function("cdn.media_exists", lambda payload: None)

        serializer = _validate(VALID_REF)
        assert ERR_400_AVATAR_NOT_FOUND in _avatar_errors(serializer)

    def test_invalid_format_rejected_before_comm(self):
        """Format errors never reach the existence check."""
        serializer = _validate("product/" + "a" * 64)
        assert ERR_400_INVALID_AVATAR_FORMAT in _avatar_errors(serializer)

    def test_empty_avatar_skips_check(self):
        serializer = _validate("")
        assert serializer.errors == {}

    def test_url_source_skips_cdn_checks(self):
        """A non-cdn source is a free-form string — no format/existence check."""
        serializer = _validate("https://example.com/me.png", source="url")
        assert serializer.errors == {}
        assert serializer.validated_data["avatar"] == "https://example.com/me.png"

    def test_file_source_is_default_and_skips_cdn_checks(self):
        """No avatar_source in the payload + no existing instance -> defaults
        to `file`, which never triggers the cdn-only format/existence check."""
        serializer = _validate(VALID_REF, source=None)
        assert serializer.errors == {}


class TestAvatarCheckOff:
    """PROFILES_AVATAR_CHECK='off' skips the existence check."""

    @override_settings(PROFILES_AVATAR_CHECK="off")
    def test_off_flat_setting_skips_existence_check(self):
        # No provider registered — would fail closed in "comm" mode.
        serializer = _validate(VALID_REF)
        assert serializer.errors == {}
        assert serializer.validated_data["avatar"] == VALID_REF

    @override_settings(STAPEL_PROFILES={"PROFILES_AVATAR_CHECK": "off"})
    def test_off_namespaced_setting_skips_existence_check(self):
        serializer = _validate(VALID_REF)
        assert serializer.errors == {}

    @override_settings(PROFILES_AVATAR_CHECK="off")
    def test_off_still_validates_ref_format(self):
        serializer = _validate("not-a-valid-ref")
        assert ERR_400_INVALID_AVATAR_FORMAT in _avatar_errors(serializer)
