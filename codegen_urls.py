"""Canonical-prefix URLconf for contract emission (contract-pipeline.md §2).

The pytest urlconf mounts profiles *bare* (``stapel_profiles.urls`` →
``/me``). That is the repoint bug: the monolith aggregate — and therefore
every frontend projection — serves profiles under its canonical public API
prefix, ``/profiles/api/me``.

This URLconf reproduces the monolith mount **exactly** (svc-app/core/urls.py
line 38: profiles alone, no sibling co-mount, under ``profiles/api/``), so
drf-spectacular emits ``/profiles/api/...`` paths (and the matching
``profiles_api_*`` operationIds) and ``generate_flow_docs`` resolves flow
endpoints to the same. Getting this prefix exact is the make-or-break for a
zero-diff repoint (contract-pipeline.md §2, §9).
"""
from django.conf.urls import include
from django.urls import path

urlpatterns = [
    path("profiles/api/", include("stapel_profiles.urls")),
]
