"""Boot-time checks: an opened switch must never be silent (audit 2026-08-11).

Every security setting in this module is closed by default and openable by
one line in a deployment's settings. These pin that the line announces
itself at `manage.py check` — a switch nobody can see is a switch nobody
revisits.
"""
import pytest
from django.test import override_settings

from stapel_profiles.checks import (
    W001_AVATAR_CHECK_OFF,
    W002_AVATAR_HOSTS_ANY,
    W003_ANONYMOUS_SEES_EVERYTHING,
    W004_ENUMERATION_UNBOUNDED,
    check_open_switches,
)


def _ids(**overrides):
    with override_settings(STAPEL_PROFILES=overrides):
        return {finding.id for finding in check_open_switches()}


def test_the_shipped_defaults_are_silent():
    """Nothing is open out of the box, so there is nothing to report."""
    assert _ids() == set()


def test_a_skipped_avatar_existence_check_is_reported():
    assert W001_AVATAR_CHECK_OFF in _ids(PROFILES_AVATAR_CHECK="off")


def test_an_any_host_avatar_allowlist_is_reported():
    assert W002_AVATAR_HOSTS_ANY in _ids(PROFILES_AVATAR_URL_ALLOWED_HOSTS=["*"])
    # A real allowlist is a closed policy, not an opened switch.
    assert W002_AVATAR_HOSTS_ANY not in _ids(
        PROFILES_AVATAR_URL_ALLOWED_HOSTS=["cdn.example.com"]
    )


@pytest.mark.parametrize("value", [None, ["*"]])
def test_giving_anonymous_callers_the_member_view_is_reported(value):
    assert W003_ANONYMOUS_SEES_EVERYTHING in _ids(
        PROFILES_PUBLIC_FIELDS_ANONYMOUS=value
    )


def test_a_narrower_anonymous_policy_is_not_reported():
    assert W003_ANONYMOUS_SEES_EVERYTHING not in _ids(
        PROFILES_PUBLIC_FIELDS_ANONYMOUS=["user_id"]
    )


@pytest.mark.parametrize("key", ["PROFILES_LOOKUP_RATE", "PROFILES_BATCH_RATE"])
def test_a_disabled_enumeration_throttle_is_reported(key):
    assert W004_ENUMERATION_UNBOUNDED in _ids(**{key: None})


def test_the_checks_are_registered_with_django():
    """`manage.py check` has to actually run them (AppConfig.ready)."""
    from django.core.checks import registry

    assert check_open_switches in registry.registry.get_checks()
