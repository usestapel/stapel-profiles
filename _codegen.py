"""stapel-profiles contract-emission harness (contract-pipeline.md §2-3).

Emits the module's own contract triad into ``docs/`` from a single-module
``{profiles + core}`` Django instance mounted at the canonical
``profiles/api/`` prefix:

  docs/schema.json   drf-spectacular OpenAPI, this module only, canonical prefix
  docs/flows.json    generate_flow_docs machine artifact, canonical-prefix paths
  docs/errors.json   generate_error_keys registry (already the etalon)

Copied from stapel-auth's reference implementation (``_codegen.py``,
ETALON); the *mechanism* is stapel_tools.codegen (unchanged, shared), this
file is the thin per-module *config* that wires the module's settings +
canonical mount into it.

Usage:
    python -m stapel_profiles._codegen --out docs        # `make contract`
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _configure() -> None:
    """Configure + boot the single-module Django instance for emission."""
    # `python -m` prepends cwd to sys.path; strip the repo root the same way
    # conftest.py does, so a locally-shadowed package can never win over an
    # installed dependency (mirrors auth's flat-package-layout guard, applied
    # here defensively even though profiles has no colliding subpackage).
    repo_root = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != repo_root]

    # Bootstrap an eager Celery app before Django setup so shared_task decorators
    # bind to a configured app (mirrors conftest.pytest_configure).
    from celery import Celery

    celery = Celery("stapel_profiles_codegen")
    celery.config_from_object(
        {
            "task_always_eager": True,
            "task_eager_propagates": True,
            "broker_url": "memory://",
            "result_backend": "cache+memory://",
        }
    )
    celery.set_default()

    from django.conf import settings

    if not settings.configured:
        from stapel_profiles._codegen_settings import settings_kwargs

        settings.configure(
            **settings_kwargs(root_urlconf="stapel_profiles.codegen_urls", contract=True)
        )

    import django

    django.setup()

    # drf-spectacular froze its settings singleton at import time (before this
    # harness ran configure()), so it is on drf defaults — the same state the
    # monolith emits under. The one knob to force is SCHEMA_PATH_PREFIX: left None,
    # drf derives the operationId prefix from the common path of all endpoints —
    # "/" across the multi-module monolith (operationIds keep the mount segment,
    # profiles_api_*), but "/profiles/api" in a single-module harness (which would
    # strip it to bare anonymous names). Pin it to the monolith's common prefix so
    # the operationIds are byte-identical; SCHEMA_PATH_PREFIX_TRIM stays False
    # (default) so the path *keys* keep /profiles/api/ on both sides.
    from drf_spectacular.settings import spectacular_settings

    from stapel_profiles._codegen_settings import CODEGEN_SCHEMA_PATH_PREFIX

    spectacular_settings.SCHEMA_PATH_PREFIX = CODEGEN_SCHEMA_PATH_PREFIX

    # The monolith's own codegen harness runs with DJANGO_ENV=local
    # (codegen/generate.sh), which makes its root urls.py include
    # get_dev_urls() -> get_swagger_urls() -> _register_jwt_auth_extension()
    # as a side effect of importing the URLconf — a *global* registration on
    # drf-spectacular's extension registry, not tied to any one module's
    # urls.py. stapel-auth's harness gets this for free only because its
    # co-mounted sibling (stapel_gdpr.urls) happens to call
    # get_app_swagger_urls() unconditionally; profiles has no such sibling.
    # Without registering it explicitly here, protected profiles endpoints
    # would emit without their monolith `security: [{"JWTCookieAuth": []}]`
    # entry — a real byte-identity delta, not a component-closure gap
    # (contract-pipeline.md §9 Q2 is about $ref'd schemas; this is about a
    # side-effecting extension registration the monolith always performs).
    from stapel_core.django.openapi.swagger import _register_jwt_auth_extension

    _register_jwt_auth_extension()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stapel-profiles-contract",
        description="Emit this module's contract triad (schema.json + flows.json "
        "+ errors.json) into --out, canonical /profiles/api/ prefix.",
    )
    parser.add_argument(
        "--out",
        default="docs",
        help="Output directory for the triad (default: docs).",
    )
    args = parser.parse_args(argv)

    _configure()

    # Reuse the shared mechanism's byte-stable emitters (contract-pipeline.md §2:
    # "the single-module harness already exists").
    from stapel_tools.codegen import emit_errors, emit_flows, emit_schema

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = emit_schema(out / "schema.json")
    flows = emit_flows(out / "flows.json")
    errors = emit_errors(out / "errors.json")

    print(
        f"stapel-profiles contract: {paths} paths, {flows} flows, {errors} error keys "
        f"→ {out}/",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
