import uuid

import pytest


def pytest_configure(config):
    from django.conf import settings
    if not settings.configured:
        # Single source of truth for this block lives in _codegen_settings.py
        # so the test harness and the contract-emission harness (make
        # contract) can never drift (contract-pipeline.md §3). Tests keep the
        # bare mount + historical REST_FRAMEWORK (unset), exactly as before
        # the extraction.
        from stapel_profiles._codegen_settings import settings_kwargs

        settings.configure(**settings_kwargs())


@pytest.fixture(autouse=True)
def _reset_throttle_state():
    """Public lookups are rate-limited per caller (audit PROFILE-01) and the
    counters live in the process cache, keyed by user/IP — which every test
    shares. Without this reset a test would inherit the budget its
    predecessors spent, and the suite's outcome would depend on its order."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def user(db):
    from stapel_core.django.users.models import User

    return User.objects.create_user(
        username=f"u-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password="testpass-1234",
    )


@pytest.fixture
def other_user(db):
    from stapel_core.django.users.models import User

    return User.objects.create_user(
        username=f"u-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password="testpass-1234",
    )


@pytest.fixture
def authed_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client
