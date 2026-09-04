"""Tests for scripts/ruff_ratchet.py (#635).

The write-time supertool validator (registered in .supertool.json) catches a
lint finding the moment a file is written, but it never sees the whole tree
and cannot be skipped -- there is no gate anywhere that fails when 250
untouched files stay unlinted forever. This is that gate: a CI leg over the
whole tree, ratcheted rather than "fix everything first", because #635's own
measurement (95 findings across 51 files, none in this lane's claimed files)
made "fix the selected classes first" the wrong call for one issue's lane.

Three states, not two, on purpose (CLAUDE.md's own defect class): `ok` (at or
under baseline), a finding (over baseline), and `could-not-run` (ruff itself
missing or broken) -- the last one must never render as `ok`, or a CI runner
that lost ruff would report a clean lint on a tree nobody checked.

Both a "must fire" and a "must not fire" fixture, so a harness that runs
nothing is not indistinguishable from a harness that found no violations.

Python 3.9 compatible.
"""

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RATCHET = REPO_ROOT / "scripts" / "ruff_ratchet.py"

pytestmark = pytest.mark.skipif(
    shutil.which("ruff") is None, reason="ruff not on PATH"
)

_PYPROJECT = textwrap.dedent(
    """\
    [tool.ruff]
    target-version = "py39"

    [tool.ruff.lint]
    select = ["F401", "F841", "E722", "B006", "A001"]
    """
)


def _fixture(tmp_path, body):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    (tmp_path / "a.py").write_text(body)
    return tmp_path


def _run(root, baseline, env=None):
    return subprocess.run(
        [sys.executable, str(RATCHET), "--root", str(root),
         "--baseline", str(baseline)],
        capture_output=True, text=True, env=env,
    )


def test_clean_tree_at_zero_baseline_passes(tmp_path):
    root = _fixture(tmp_path, "def f():\n    return 1\n")
    r = _run(root, baseline=0)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_new_violation_over_baseline_fails(tmp_path):
    root = _fixture(tmp_path, "import os\n\n\ndef f():\n    return 1\n")
    r = _run(root, baseline=0)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "1" in r.stdout


def test_violation_within_baseline_passes(tmp_path):
    root = _fixture(tmp_path, "import os\n\n\ndef f():\n    return 1\n")
    r = _run(root, baseline=1)
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_ruff_reports_third_state_not_ok(tmp_path):
    root = _fixture(tmp_path, "def f():\n    return 1\n")
    env = {"PATH": ""}
    r = _run(root, baseline=0, env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "COULD NOT RUN" in r.stdout
    assert "OK" not in r.stdout
