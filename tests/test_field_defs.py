"""Tests for the standard-field registry (§66, field_defs.py) and the first
real STAPEL_SWAP model swap (docs/pending/profile-fields.md §2/§3).

`SwapTestProfile` below is built via `field_defs.build_profile_model()` at
MODULE IMPORT TIME (not inside a test function) so its table is created by
pytest-django's syncdb pass alongside the rest of the unmigrated-in-tests
`profiles` app models (MIGRATION_MODULES={"profiles": None} in
_codegen_settings.py) — a model class assembled *inside* a test function
would have no backing table.
"""
import uuid

import pytest
from django.test import override_settings

from stapel_profiles.field_defs import (
    IDENTITY_PRESETS,
    STANDARD_FIELDS,
    MeasurementUnit,
    ProfileFieldDef,
    ProfileFieldKind,
    assemble_profile_fields,
    build_profile_model,
)
from stapel_profiles.models import ProfileCore, get_profile_model

# The extended model a project would build in its OWN app's models.py after
# picking identity="first_last_name" + standard_fields=["currency_code"] from
# its STAPEL_PROFILES["FIELDS"] manifest. (display_name/theme are no longer
# registry-selectable — they are hard core now, owner 2026-07-22.) Reusing
# app_label="profiles" here (test-only) so the table lands in the same
# already-migration-disabled app as Profile itself.
SwapTestProfile = build_profile_model(
    {"identity": "first_last_name", "standard_fields": ["currency_code"]},
    app_label="profiles",
    model_name="SwapTestProfile",
    module=__name__,
)


class TestStandardFieldsRegistry:
    """STANDARD_FIELDS / IDENTITY_PRESETS shape."""

    def test_standard_fields_have_mandatory_docstrings(self):
        for key, field_def in STANDARD_FIELDS.items():
            assert field_def.doc, f"{key} has no docstring"

    def test_identity_presets_have_mandatory_docstrings(self):
        for key, field_defs in IDENTITY_PRESETS.items():
            for field_def in field_defs:
                assert field_def.doc, f"{key}.{field_def.name} has no docstring"

    def test_theme_left_the_registry_for_the_hard_core(self):
        # owner 2026-07-22: theme is a models.ProfileCore field now, not a
        # registry opt-in.
        assert "theme" not in STANDARD_FIELDS

    def test_currency_code_is_model_ref_kind(self):
        field_def = STANDARD_FIELDS["currency_code"]
        assert field_def.kind is ProfileFieldKind.MODEL_REF
        assert field_def.model_ref == "stapel_currencies.Currency"
        assert field_def.enum_values is None

    def test_measurement_units_is_enum_kind(self):
        field_def = STANDARD_FIELDS["measurement_units"]
        assert field_def.kind is ProfileFieldKind.ENUM
        assert field_def.enum is MeasurementUnit

    def test_geohash_is_geohash_kind(self):
        field_def = STANDARD_FIELDS["geohash"]
        assert field_def.kind is ProfileFieldKind.GEOHASH

    def test_identity_is_mutually_exclusive_presets(self):
        # display_name left for the hard core (owner 2026-07-22); first/last
        # stays as the one remaining opt-in identity preset.
        assert set(IDENTITY_PRESETS) == {"first_last_name"}
        assert [f.name for f in IDENTITY_PRESETS["first_last_name"]] == [
            "first_name", "last_name",
        ]

    def test_to_model_field_builds_django_fields(self):
        from django.db import models as dj_models

        enum_field = STANDARD_FIELDS["measurement_units"].to_model_field()
        assert isinstance(enum_field, dj_models.CharField)
        assert enum_field.default == MeasurementUnit.METRIC
        assert dict(enum_field.choices) == dict(MeasurementUnit.choices)

        bool_field = ProfileFieldDef(
            name="camera_on", kind=ProfileFieldKind.BOOL, doc="Default camera state.",
            default=True,
        ).to_model_field()
        assert isinstance(bool_field, dj_models.BooleanField)
        assert bool_field.default is True

    def test_to_presenter_field_carries_help_text(self):
        from stapel_core.django.api.presenters import PresenterField

        presenter_field = STANDARD_FIELDS["measurement_units"].to_presenter_field()
        assert isinstance(presenter_field, PresenterField)
        assert presenter_field.help_text == STANDARD_FIELDS["measurement_units"].doc
        assert presenter_field.source == "measurement_units"

    def test_attribute_kind_none_without_stapel_attributes(self):
        # stapel-attributes isn't a dependency of this repo's test env —
        # the bridge is optional (docs/pending/profile-fields.md §4).
        assert STANDARD_FIELDS["geohash"].attribute_kind is None

    def test_unknown_identity_preset_raises(self):
        with pytest.raises(ValueError):
            assemble_profile_fields(identity="nickname")

    def test_unknown_standard_field_raises(self):
        with pytest.raises(ValueError):
            assemble_profile_fields(standard_fields=["nonexistent"])

    def test_assemble_profile_fields_combines_identity_and_standard(self):
        fields = assemble_profile_fields(
            identity="first_last_name", standard_fields=["currency_code"],
        )
        assert set(fields) == {"first_name", "last_name", "currency_code"}


@pytest.mark.django_db
class TestSwapProfileModel:
    """`build_profile_model()` output actually works as a Django model,
    including the fields it inherits from the hard `ProfileCore`."""

    def test_is_subclass_of_profile_core(self):
        assert issubclass(SwapTestProfile, ProfileCore)

    def test_has_core_and_selected_fields(self):
        field_names = {f.name for f in SwapTestProfile._meta.get_fields()}
        # Hard core (never absent regardless of manifest) — display_name/theme
        # are core again (owner 2026-07-22), inherited even by a swapped model:
        assert {"user_id", "avatar_source", "avatar", "app_language",
                "display_name", "theme"} <= field_names
        # Manifest-selected (identity="first_last_name" + currency_code):
        assert {"first_name", "last_name", "currency_code"} <= field_names

    def test_create_and_read_extended_fields(self):
        user_id = uuid.uuid4()
        profile = SwapTestProfile.objects.create(
            user_id=user_id, display_name="Ada", theme="dark", currency_code="EUR",
        )
        profile.refresh_from_db()
        assert profile.display_name == "Ada"
        assert profile.theme == "dark"
        assert profile.currency_code == "EUR"
        # Core fields still present and defaulted normally:
        assert profile.avatar_source == "file"


@pytest.mark.django_db
class TestSwapEndToEnd:
    """The actual `STAPEL_SWAP["PROFILES_PROFILE_MODEL"]` override
    (docs/pending/profile-fields.md §3) — the first real `get_model()` case."""

    def test_get_profile_model_resolves_swap_override(self):
        target = f"{__name__}.SwapTestProfile"
        with override_settings(STAPEL_SWAP={"PROFILES_PROFILE_MODEL": target}):
            assert get_profile_model() is SwapTestProfile
        # Cache clears back to the default once the override is gone
        # (setting_changed -> clear_swap_cache(), stapel_core.django.swappable).
        assert get_profile_model() is not SwapTestProfile

    def test_swapped_model_round_trips_through_a_fresh_serializer(self):
        """End-to-end: a serializer built AFTER the swap (mirroring what a
        project's generated/hand-written serializer would do) sees the
        extended fields — the swap is not just a class-identity check."""
        from rest_framework import serializers as drf_serializers

        target = f"{__name__}.SwapTestProfile"
        with override_settings(STAPEL_SWAP={"PROFILES_PROFILE_MODEL": target}):
            model = get_profile_model()

            class ExtendedProfileSerializer(drf_serializers.ModelSerializer):
                class Meta:
                    model = get_profile_model()
                    fields = ["user_id", "display_name", "theme", "currency_code", "avatar_source"]

            user_id = uuid.uuid4()
            instance = model.objects.create(
                user_id=user_id, display_name="Grace", theme="light", currency_code="USD",
            )
            data = ExtendedProfileSerializer(instance).data
            assert data["display_name"] == "Grace"
            assert data["theme"] == "light"
            assert data["currency_code"] == "USD"
            assert data["avatar_source"] == "file"
