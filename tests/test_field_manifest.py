"""Tests for GET /field-manifest/ (§66 data-driven skin, tier 1 —
docs/pending/profile-fields.md, "Дополнение владельца" §1)."""
import pytest
from django.test import override_settings

from stapel_profiles.field_defs import ProfileFieldDef, ProfileFieldKind


@pytest.mark.django_db
class TestFieldManifestEndpoint:
    def test_empty_manifest_returns_empty_list(self, api_client):
        resp = api_client.get("/field-manifest")
        assert resp.status_code == 200, resp.content
        assert resp.json() == []

    def test_manifest_reflects_identity_and_standard_fields(self, api_client):
        # display_name/theme are hard core now (owner 2026-07-22) — the manifest
        # covers only the still-opt-in registry: first/last identity + the
        # remaining standard fields.
        manifest = {"identity": "first_last_name", "standard_fields": ["measurement_units"]}
        with override_settings(STAPEL_PROFILES={"PROFILES_FIELDS": manifest}):
            resp = api_client.get("/field-manifest")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        names = [entry["name"] for entry in data]
        assert names == ["first_name", "last_name", "measurement_units"]

        first_name_entry = data[0]
        assert first_name_entry["kind"] == "text"
        assert first_name_entry["order"] == 0
        assert first_name_entry["enum_values"] is None
        assert first_name_entry["docstring"]

        mu_entry = data[2]
        assert mu_entry["kind"] == "enum"
        assert mu_entry["order"] == 2
        assert set(mu_entry["enum_values"]) == {"metric", "imperial"}

    def test_manifest_includes_custom_fields_last(self, api_client):
        custom = ProfileFieldDef(
            name="occupation", kind=ProfileFieldKind.TEXT,
            doc="Professional category.", default="",
        )
        manifest = {"standard_fields": ["measurement_units"], "custom_fields": [custom]}
        with override_settings(STAPEL_PROFILES={"PROFILES_FIELDS": manifest}):
            resp = api_client.get("/field-manifest")
        assert resp.status_code == 200, resp.content
        names = [entry["name"] for entry in resp.json()]
        assert names == ["measurement_units", "occupation"]

    def test_manifest_endpoint_is_public(self, api_client):
        """No auth required — the frontend skin needs this before login too."""
        resp = api_client.get("/field-manifest")
        assert resp.status_code == 200
