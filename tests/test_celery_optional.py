"""Celery is not a dependency of stapel-profiles.

No runtime code path uses it; the contract-emission harness used to import it
unconditionally (and the package declared it to satisfy that import), so a
project without celery could not emit or install this module lean. Both run
here with celery made unimportable.
"""
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_BLOCK_CELERY = (
    "import sys; sys.modules['celery'] = None; "
    "import runpy; sys.argv = ['x', '--out', sys.argv[1]]; "
    "runpy.run_module('stapel_profiles._codegen', run_name='__main__')"
)
#: The harness boot alone — what imported celery — runs on every interpreter.
_BOOT_WITHOUT_CELERY = (
    "import sys; sys.modules['celery'] = None; "
    "from stapel_profiles._codegen import _configure; _configure(); "
    "from django.apps import apps; print(apps.ready)"
)


def test_celery_is_not_a_declared_dependency():
    deps = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["dependencies"]
    assert not [d for d in deps if d.split(">")[0].split("=")[0].strip() == "celery"]


def test_the_emission_harness_boots_without_celery(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", _BOOT_WITHOUT_CELERY],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "True"


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 12),
    reason="the contract canon is emitted on Python 3.12 only (see test_contract.py)",
)
def test_the_contract_emits_without_celery(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", _BLOCK_CELERY, str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert (tmp_path / "schema.v2.json").is_file()
    assert (tmp_path / "schema.json").read_bytes() == (REPO / "docs" / "schema.json").read_bytes()
