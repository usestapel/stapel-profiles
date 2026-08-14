"""
Tests for avatar validation via the comm layer (cdn.media_exists).
"""
import pytest
from django.test import override_settings
from stapel_core.comm import function_registry, register_function

from stapel_profiles.errors import (
    ERR_400_AVATAR_NOT_FOUND,
    ERR_400_AVATAR_SOURCE_MISMATCH,
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

    @override_settings(
        STAPEL_PROFILES={"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["example.com"]}
    )
    def test_url_source_skips_cdn_checks(self):
        """A non-cdn source skips the CDN format/existence check.

        It still passes the URL boundary — hence the allowlisted host here.
        """
        serializer = _validate("https://example.com/me.png", source="url")
        assert serializer.errors == {}
        assert serializer.validated_data["avatar"] == "https://example.com/me.png"

    def test_untagged_cdn_ref_is_derived_not_defaulted_to_file(self):
        """No `avatar_source` in the payload + a ref that IS a cdn ref -> the
        source is DERIVED as `cdn`, so the cdn checks run.

        This test used to assert the opposite ("defaults to file, skips the
        cdn checks") and that assertion was the defect, written down. Both
        profiles on the meettoday sandbox that ever had an avatar (2 of 2)
        were stored exactly this way — `PATCH {avatar: "avatar/<hash>"}` with
        no source — and serializing them 500'd `/profiles/api/v1/me`.
        """
        register_function("cdn.media_exists", lambda payload: {"exists": True})

        serializer = _validate(VALID_REF, source=None)

        assert serializer.errors == {}
        assert serializer.validated_data["avatar_source"] == "cdn"

    def test_untagged_free_form_ref_still_defaults_to_file(self):
        """Derivation is not a land grab: only an unmistakable cdn ref moves
        the tag. A free-form key stays `file` and skips the cdn checks."""
        serializer = _validate("uploads/me.png", source=None)

        assert serializer.errors == {}
        assert "avatar_source" not in serializer.validated_data

    def test_cdn_ref_tagged_file_is_rejected_not_coerced(self):
        """A STATED source that the ref contradicts is a caller bug and is
        told so — coercing an assertion would hide it."""
        serializer = _validate(VALID_REF, source="file")

        assert ERR_400_AVATAR_SOURCE_MISMATCH in _avatar_errors(serializer)

    def test_cdn_ref_tagged_url_is_rejected(self):
        serializer = _validate(VALID_REF, source="url")

        assert ERR_400_AVATAR_SOURCE_MISMATCH in _avatar_errors(serializer)


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
