"""Per-module contract triad + drift gate (contract-pipeline.md §2-3).

stapel-profiles emits its **own** contract triad — ``docs/schema.json``
(drf-spectacular OpenAPI), ``docs/flows.json`` (generate_flow_docs machine
artifact — empty here, profiles has no ``@flow_step`` annotations) and
``docs/errors.json`` (generate_error_keys registry) — from a single-module
``{profiles + core}`` Django instance mounted at the canonical
``/profiles/api/`` prefix. The frontend codegen consumes these committed
artifacts instead of the monolith aggregate.

The emitted schema/flows are **byte-identical to the monolith aggregate's
profiles slice** (paths under ``/profiles/api/`` + their transitive component
closure); see ``test_matches_monolith_profiles_slice`` — the guarantee the
whole repoint rests on.

Regenerate after any change to a serializer / view / url / flow / error key:

    make contract        # or: python -m stapel_profiles._codegen --out docs

then commit ``docs/{schema,flows,errors}.json``. Without regenerating, the drift
gate below fails — the same byte-stable regenerate-and-diff discipline as
``test_error_keys``.

The harness runs in a **subprocess**: this test process already configured Django
(via conftest, on the bare test urlconf), and the harness needs its own
canonical-prefix urlconf + drf-spectacular singleton — a clean interpreter is the
honest way to exercise exactly what ``make contract`` runs.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PY = sys.version_info[:2]
if _PY != (3, 12):
    _GOT = f"{_PY[0]}.{_PY[1]}"
    _PY312_MSG = (
        "stapel-profiles contract tests require Python 3.12 (the CI/monolith "
        f"pin) — running {_GOT}. drf-spectacular renders component "
        "descriptions (Optional[X] vs X | None) differently across Python "
        "minor versions, so drift/identity checks emitted+compared under any "
        "other minor produce false diffs."
    )
    pytest.skip(
        _PY312_MSG + " Skipping on any non-3.12 interpreter (CI or local) — "
        "the contract canon is only defined on Python 3.12.",
        allow_module_level=True,
    )

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
TRIAD = ("schema.json", "flows.json", "errors.json")
# The fourth artifact (capability-config.md §2): config axes over STAPEL_PROFILES,
# emitted from conf.py DEFAULTS + the urls.py gate registry + schema.json + the
# curated docs/capabilities.meta.json. Same emit/drift discipline.
ARTIFACTS = TRIAD + ("capabilities.json",)


def _emit(out_dir: Path) -> None:
    for module in ("stapel_profiles._codegen", "stapel_profiles._capabilities"):
        subprocess.run(
            [sys.executable, "-m", module, "--out", str(out_dir)],
            cwd=str(REPO),
            check=True,
            capture_output=True,
        )


def test_contract_artifacts_committed():
    for name in ARTIFACTS:
        assert (DOCS / name).is_file(), f"missing docs/{name} — run `make contract`"
    assert (DOCS / "capabilities.meta.json").is_file(), (
        "missing docs/capabilities.meta.json — the curated layer is "
        "hand-written and committed, not generated"
    )


def test_contract_has_no_drift(tmp_path):
    """Regenerate into a temp dir; committed artifacts must match byte-for-byte."""
    _emit(tmp_path)
    for name in ARTIFACTS:
        committed = (DOCS / name).read_bytes()
        regenerated = (tmp_path / name).read_bytes()
        assert committed == regenerated, (
            f"docs/{name} drifted — run `make contract` and commit docs/{name}"
        )


def test_emission_is_deterministic(tmp_path):
    """Two independent emissions are byte-identical (drift gate is meaningful)."""
    a, b = tmp_path / "a", tmp_path / "b"
    _emit(a)
    _emit(b)
    for name in ARTIFACTS:
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_paths_carry_canonical_prefix():
    """The mount-prefix fix: schema paths + flow endpoints are /profiles/api/*, not bare."""
    schema = json.loads((DOCS / "schema.json").read_text())
    assert schema["paths"], "schema has no paths"
    assert all(p.startswith("/profiles/api/") for p in schema["paths"]), (
        "schema paths are not mounted at the canonical /profiles/api/ prefix"
    )
    flows = json.loads((DOCS / "flows.json").read_text())
    for flow in flows:
        for step in flow.get("steps", []):
            for ep in step.get("endpoints", []):
                assert ep["path"].startswith("/profiles/api/"), (
                    f"flow endpoint {ep['path']} is not canonically prefixed"
                )


# --- Byte-identity regression vs the monolith aggregate's profiles slice ------
# Only runs in the workspace (the monolith is a sibling repo, absent in module CI).

_MONO = REPO.parent / "stapel-example-monolith" / "codegen" / "generated" / "schema.json"


def _closure(schema: dict, seeds: set[str]) -> set[str]:
    import re

    comps = schema["components"]["schemas"]
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        name = stack.pop()
        if name in seen or name not in comps:
            continue
        seen.add(name)
        for ref in re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(comps[name])):
            stack.append(ref)
    return seen


def _refs(obj) -> set[str]:
    import re

    return set(re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(obj)))


@pytest.mark.skipif(
    not _MONO.exists() or os.environ.get("STAPEL_SKIP_MONOLITH_IDENTITY"),
    reason="monolith aggregate not present (module CI checks out only this repo)",
)
def test_matches_monolith_profiles_slice():
    """docs/schema.json == the monolith aggregate's /profiles/api/ slice, byte-for-byte.

    Compares path objects and the transitive component closure — the envelope
    (info/servers) is intentionally not compared (it names profiles, not the
    monolith).
    """
    mine = json.loads((DOCS / "schema.json").read_text())
    mono = json.loads(_MONO.read_text())

    mono_paths = {p: v for p, v in mono["paths"].items() if p.startswith("/profiles/api/")}
    assert set(mine["paths"]) == set(mono_paths), "path set differs from monolith slice"
    for p in mono_paths:
        assert json.dumps(mine["paths"][p], sort_keys=True) == json.dumps(
            mono_paths[p], sort_keys=True
        ), f"path object {p} differs from monolith slice"

    seeds: set[str] = set()
    for v in mono_paths.values():
        seeds |= _refs(v)
    mono_cl = _closure(mono, seeds)
    my_seeds: set[str] = set()
    for v in mine["paths"].values():
        my_seeds |= _refs(v)
    my_cl = _closure(mine, my_seeds)
    assert mono_cl == my_cl, "component closure differs from monolith slice"
    for c in mono_cl:
        assert json.dumps(mine["components"]["schemas"][c], sort_keys=True) == json.dumps(
            mono["components"]["schemas"][c], sort_keys=True
        ), f"component {c} differs from monolith slice"


# --- capabilities.json content sanity (capability-config.md §2) ---------------


def _capabilities() -> dict:
    return json.loads((DOCS / "capabilities.json").read_text())


def test_capabilities_axes_inventory():
    """One enum axis: how avatar existence is verified against the CDN."""
    doc = _capabilities()
    assert {a["key"] for a in doc["axes"]} == {"PROFILES_AVATAR_CHECK"}
    axis = doc["axes"][0]
    assert axis["kind"] == "enum"
    assert axis["default"] == "comm"
    assert axis["group"] == "profiles.avatar"


def test_capabilities_every_axis_curated():
    """Every axis carries non-empty curated business semantics."""
    for axis in _capabilities()["axes"]:
        assert axis["curated"]["summary"], axis["key"]
        assert axis["curated"]["business_label"], axis["key"]


def test_capabilities_axis_has_no_operations_gate():
    """PROFILES_AVATAR_CHECK is a behavior selector, not an endpoint gate."""
    axis = next(a for a in _capabilities()["axes"] if a["key"] == "PROFILES_AVATAR_CHECK")
    assert axis["gates"]["operations"] == []
    assert axis["gates"]["co_gates"] == []


def test_capabilities_operations_total_matches_schema():
    schema = json.loads((DOCS / "schema.json").read_text())
    methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    total = sum(
        1 for item in schema["paths"].values() for m in item if m in methods
    )
    assert _capabilities()["operations_total"] == total


def test_capabilities_envelope():
    doc = _capabilities()
    import tomllib

    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert doc["module"] == pyproject["project"]["name"]
    assert doc["version"] == pyproject["project"]["version"]
    assert doc["provides"]
    assert isinstance(doc["extension_points"], list)
    assert doc["requires"]


def test_capabilities_meta_out_of_sync_fails_loudly():
    """A curated-layer gap must be an emission ERROR, never a silent skip."""
    from stapel_tools.capabilities import axis_group_rules, build_capabilities

    from stapel_profiles.conf import DEFAULTS
    from stapel_profiles.urls import GATE_REGISTRY

    schema = json.loads((DOCS / "schema.json").read_text())
    meta = json.loads((DOCS / "capabilities.meta.json").read_text())

    def _build(broken_meta):
        return build_capabilities(
            module="stapel-profiles",
            version="0.0.0",
            defaults=DEFAULTS,
            registry=GATE_REGISTRY,
            schema=schema,
            meta=broken_meta,
            is_axis=lambda k: k == "PROFILES_AVATAR_CHECK",
            axis_group=axis_group_rules(
                exact={"PROFILES_AVATAR_CHECK": "profiles.avatar"}
            ),
            canonical_prefix="/profiles/api",
        )

    # Baseline: intact meta builds.
    assert _build(json.loads(json.dumps(meta)))["axes"]

    # Missing axis entry → loud failure.
    broken = json.loads(json.dumps(meta))
    del broken["axes"]["PROFILES_AVATAR_CHECK"]
    with pytest.raises(SystemExit, match="PROFILES_AVATAR_CHECK"):
        _build(broken)

    # Stale (unknown) axis entry → loud failure.
    broken = json.loads(json.dumps(meta))
    broken["axes"]["PROFILES_NO_SUCH_AXIS"] = {"summary": "x", "business_label": "x"}
    with pytest.raises(SystemExit, match="PROFILES_NO_SUCH_AXIS"):
        _build(broken)

    # Empty business_label → loud failure.
    broken = json.loads(json.dumps(meta))
    broken["axes"]["PROFILES_AVATAR_CHECK"]["business_label"] = ""
    with pytest.raises(SystemExit, match="business_label"):
        _build(broken)
