"""Settings for stapel-profiles.

Resolution order per key (see stapel_core.conf.AppSettings):
settings.STAPEL_PROFILES dict -> flat Django setting of the same name ->
environment variable -> default.

Keys are intentionally prefixed (``PROFILES_...``) so the flat Django
setting / env var form is unambiguous:

    # settings.py — either form works
    PROFILES_AVATAR_CHECK = "off"
    STAPEL_PROFILES = {"PROFILES_AVATAR_CHECK": "off"}

PROFILES_AVATAR_CHECK — how validate_avatar verifies the CDN reference:
    "comm" (default) — stapel_core.comm.call("cdn.media_exists", ...)
    "off"            — skip the existence check (format still validated)

PROFILES_FIELDS — the profile field-constructor manifest (§66,
docs/pending/profile-fields.md §2/§3), NOT a capability axis (structural
config, not a binary toggle — excluded from capabilities.json accordingly):
    {}                                    (default) — hard core only
    {"identity": "display_name",
     "standard_fields": ["theme"],
     "custom_fields": [...ProfileFieldDef]}

    Consumed by `views._active_field_manifest()` (GET .../field-manifest/,
    the data-driven skin's source of truth) and by
    `field_defs.build_profile_model()` when a project assembles its own
    swapped-in extended Profile model.
"""
from stapel_core.conf import AppSettings

#: AppSettings-shaped literal dict (capability-config.md §2): a top-level
#: DEFAULTS lets the capabilities.json emitter introspect axis keys/kinds
#: without re-parsing the AppSettings() call.
DEFAULTS = {
    "PROFILES_AVATAR_CHECK": "comm",
    "PROFILES_FIELDS": {},
}

profiles_settings = AppSettings(
    "STAPEL_PROFILES",
    defaults=DEFAULTS,
)
