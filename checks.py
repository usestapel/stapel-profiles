"""Boot-time checks — an opened switch has to be loud at deploy, not at audit.

This module's security-relevant settings are all *closed by default* and all
openable by one line in a deployment's settings. That line is the whole risk:
it is written once, months before anyone asks "why does this service fetch
images from anywhere?", and nothing in the running system says it is there.
A ``manage.py check`` finding is the cheapest place for that sentence to
appear — same genre as ``stapel_gdpr.checks`` W003 and ``stapel_cdn.checks``.

None of these are errors: a host is allowed to open them, and W-level
findings do not fail ``check`` without ``--fail-level WARNING``. They are
simply never silent.

* ``profiles.W001`` — ``PROFILES_AVATAR_CHECK="off"``: avatar references are
  saved without confirming the CDN object exists.
* ``profiles.W002`` — ``PROFILES_AVATAR_URL_ALLOWED_HOSTS=["*"]``: external
  avatars may point at any host, so every profile view is a fetch from a
  host the profile's owner chose.
* ``profiles.W003`` — anonymous callers see the full member field set on the
  two ``AllowAny`` public endpoints.
* ``profiles.W004`` — a public-lookup throttle is disabled, so one caller
  may walk the whole user base as fast as the service answers.
"""
from __future__ import annotations

from django.core.checks import Warning as CheckWarning, register

__all__ = ["check_open_switches", "register_checks"]

W001_AVATAR_CHECK_OFF = "profiles.W001"
W002_AVATAR_HOSTS_ANY = "profiles.W002"
W003_ANONYMOUS_SEES_EVERYTHING = "profiles.W003"
W004_ENUMERATION_UNBOUNDED = "profiles.W004"


def check_open_switches(app_configs=None, **kwargs):
    """Report every security switch this deployment has opened."""
    from .conf import profiles_settings
    from .serializers import ANONYMOUS_FIELDS_SAME_AS_MEMBERS
    from .validators import HOST_ALLOWLIST_ANY, avatar_url_allowed_hosts

    problems = []

    if str(profiles_settings.PROFILES_AVATAR_CHECK or "").lower() == "off":
        problems.append(
            CheckWarning(
                'STAPEL_PROFILES["PROFILES_AVATAR_CHECK"] is "off": an avatar '
                "reference is stored without confirming the CDN object it "
                "names exists, so a profile can point at media this "
                "deployment never received.",
                hint='Remove the setting to restore the default "comm" check.',
                id=W001_AVATAR_CHECK_OFF,
            )
        )

    if HOST_ALLOWLIST_ANY in avatar_url_allowed_hosts():
        problems.append(
            CheckWarning(
                'STAPEL_PROFILES["PROFILES_AVATAR_URL_ALLOWED_HOSTS"] is '
                '["*"]: an external avatar may point at any host, so every '
                "view of that profile is a fetch carrying the VIEWER's IP, "
                "user agent and referring page to a host the profile's OWNER "
                "chose.",
                hint=(
                    "Replace it with the hosts this deployment trusts "
                    '(exact "cdn.example.com" or suffix ".example.com").'
                ),
                id=W002_AVATAR_HOSTS_ANY,
            )
        )

    anonymous = profiles_settings.PROFILES_PUBLIC_FIELDS_ANONYMOUS
    if anonymous is None or ANONYMOUS_FIELDS_SAME_AS_MEMBERS in anonymous:
        problems.append(
            CheckWarning(
                'STAPEL_PROFILES["PROFILES_PUBLIC_FIELDS_ANONYMOUS"] gives '
                "unauthenticated callers the full member field set. GET "
                "/<user_id> and POST /batch are AllowAny and answer for any "
                "user id, so whatever PROFILES_PUBLIC_FIELDS holds — "
                "location, follower counts — is readable by the internet.",
                hint=(
                    "Set an explicit narrower list, or remove the setting to "
                    "restore the default (identity + avatar only)."
                ),
                id=W003_ANONYMOUS_SEES_EVERYTHING,
            )
        )

    for key in ("PROFILES_LOOKUP_RATE", "PROFILES_BATCH_RATE"):
        if not getattr(profiles_settings, key):
            problems.append(
                CheckWarning(
                    f'STAPEL_PROFILES["{key}"] is unset: the matching public '
                    "endpoint has no per-caller ceiling, so one client may "
                    "enumerate the whole user base as fast as the service "
                    "answers.",
                    hint="Set a DRF rate string, e.g. \"120/min\".",
                    id=W004_ENUMERATION_UNBOUNDED,
                )
            )

    return problems


def register_checks() -> None:
    """Called from ``AppConfig.ready``; idempotent."""
    register(check_open_switches, "profiles")
