"""Settings for stapel-profiles.

Resolution order per key (see stapel_core.conf.AppSettings):
settings.STAPEL_PROFILES dict -> flat Django setting of the same name ->
environment variable -> default.

Keys are intentionally prefixed (``PROFILES_...``) so the flat Django
setting / env var form is unambiguous:

    # settings.py — either form works
    PROFILES_AVATAR_CHECK = "http"
    STAPEL_PROFILES = {"PROFILES_AVATAR_CHECK": "off"}

PROFILES_AVATAR_CHECK — how validate_avatar verifies the CDN reference:
    "comm" (default) — stapel_core.comm.call("cdn.media_exists", ...)
    "http"           — legacy direct HTTP via check_cdn_media_exists
    "off"            — skip the existence check (format still validated)
"""
from stapel_core.conf import AppSettings

profiles_settings = AppSettings(
    "STAPEL_PROFILES",
    defaults={
        "PROFILES_AVATAR_CHECK": "comm",
    },
)
