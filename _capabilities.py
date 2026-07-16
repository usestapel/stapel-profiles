"""stapel-profiles capabilities.json emitter — thin shim over stapel_tools.capabilities."""
from pathlib import Path

from stapel_tools.capabilities import axis_group_rules, run_capabilities_cli


def main(argv=None):
    from stapel_profiles._codegen import _configure

    _configure()
    from stapel_profiles.conf import DEFAULTS
    from stapel_profiles.urls import GATE_REGISTRY

    return run_capabilities_cli(
        argv,
        repo=Path(__file__).resolve().parent,
        canonical_prefix="/profiles/api/v1",
        defaults=DEFAULTS,
        registry=GATE_REGISTRY,
        is_axis=lambda k: k == "PROFILES_AVATAR_CHECK",
        axis_group=axis_group_rules(exact={"PROFILES_AVATAR_CHECK": "profiles.avatar"}),
        prog="stapel-profiles-capabilities",
    )


if __name__ == "__main__":
    raise SystemExit(main())
