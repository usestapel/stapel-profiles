"""Root URLconf for stapel-profiles — v1 canon mount (api-versioning.md §2, §6).

Canon: ``/<mod>/api/v1/...`` — the version segment sits right after ``api/``.
Hosts keep mounting ``include('stapel_profiles.urls')`` under their
``.../api/`` prefix; this module contributes the mandatory ``v1/``
sub-prefix. The actual URL set (paths inside unchanged) and the gate
registry live in ``urls_v1.py``; ``GATE_REGISTRY`` is re-exported here so
``from stapel_profiles.urls import GATE_REGISTRY`` keeps working.
"""
from django.urls import include, path

from stapel_profiles.urls_v1 import GATE_REGISTRY  # noqa: F401  (re-export)

urlpatterns = [
    path('v1/', include('stapel_profiles.urls_v1')),
]
