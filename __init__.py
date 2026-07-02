"""Stapel Profiles — user profiles Django app for the Stapel framework.

Public API (see ``__all__``):

- ``profiles_settings`` — package settings object (``PROFILES_*`` keys,
  resolved via ``STAPEL_PROFILES`` / flat settings / env vars).
- ``publish_profile_changed`` — emit the ``profile.changed`` comm action
  for a mutated profile.
- ``validate_display_name`` — display-name validation helper (raises
  ``StapelValidationError``).
- ``ProfilesGDPRProvider`` — GDPR export/delete provider for profile data.

Signal usage (``profile_updated``) stays in ``stapel_core.signals``.

All exports are lazily imported (PEP 562): importing ``stapel_profiles``
itself does not require Django to be configured.
"""

_EXPORTS = {
    "profiles_settings": ".conf",
    "publish_profile_changed": ".events",
    "validate_display_name": ".validators",
    "ProfilesGDPRProvider": ".gdpr",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        value = getattr(importlib.import_module(_EXPORTS[name], __name__), name)
        globals()[name] = value  # cache for subsequent lookups
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))
