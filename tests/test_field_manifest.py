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
        manifest = {"identity": "display_name", "standard_fields": ["theme"]}
        with override_settings(STAPEL_PROFILES={"PROFILES_FIELDS": manifest}):
            resp = api_client.get("/field-manifest")
        assert resp.status_code == 200, resp.content
        data = resp.json()
        names = [entry["name"] for entry in data]
        assert names == ["display_name", "theme"]

        display_name_entry = data[0]
        assert display_name_entry["kind"] == "text"
        assert display_name_entry["order"] == 0
        assert display_name_entry["enum_values"] is None
        assert display_name_entry["docstring"]

        theme_entry = data[1]
        assert theme_entry["kind"] == "enum"
        assert theme_entry["order"] == 1
        assert set(theme_entry["enum_values"]) == {"light", "dark", "system"}

    def test_manifest_includes_custom_fields_last(self, api_client):
        custom = ProfileFieldDef(
            name="occupation", kind=ProfileFieldKind.TEXT,
            doc="Professional category.", default="",
        )
        manifest = {"standard_fields": ["theme"], "custom_fields": [custom]}
        with override_settings(STAPEL_PROFILES={"PROFILES_FIELDS": manifest}):
            resp = api_client.get("/field-manifest")
        assert resp.status_code == 200, resp.content
        names = [entry["name"] for entry in resp.json()]
        assert names == ["theme", "occupation"]

    def test_manifest_endpoint_is_public(self, api_client):
        """No auth required — the frontend skin needs this before login too."""
        resp = api_client.get("/field-manifest")
        assert resp.status_code == 200
