"""Tests for scripts/ruff_ratchet.py (#635, and its #1061 set-diff rewrite).

The write-time supertool validator (registered in .supertool.json) catches a
lint finding the moment a file is written, but it never sees the whole tree
and cannot be skipped -- there is no gate anywhere that fails when 250
untouched files stay unlinted forever. This is that gate: a CI leg over the
whole tree, ratcheted rather than "fix everything first", because #635's own
measurement (95 findings across 51 files, none in this lane's claimed files)
made "fix the selected classes first" the wrong call for one issue's lane.

Three states, not two, on purpose (CLAUDE.md's own defect class): `ok` (no
new/increased finding against the baseline snapshot), a finding (one or
more), and `could-not-run` (ruff itself missing/broken, or the baseline file
missing/malformed) -- the last one must never render as `ok`, or a CI runner
that lost ruff, or whose checkout dropped the baseline file, would report a
clean lint on a tree nobody checked.

#1061 replaced the bare `--baseline N` integer comparison with a checked-in
per-finding snapshot (`--baseline-file`, default
`scripts/ruff_ratchet_baseline.txt`), so every fixture here builds its own
snapshot file explicitly rather than passing a count -- see
`tests/test_ruff_ratchet_1061.py` for the set-diff behaviour itself (the
same-total-different-composition case the old count-only gate could not
catch).

Both a "must fire" and a "must not fire" fixture, so a harness that runs
nothing is not indistinguishable from a harness that found no violations.

Python 3.9 compatible.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RATCHET = REPO_ROOT / "scripts" / "ruff_ratchet.py"

pytestmark = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not on PATH")

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


def _write_baseline_file(tmp_path, lines):
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return baseline


def _run(root, baseline_file, env=None, extra_args=()):
    return subprocess.run(
        [
            sys.executable,
            str(RATCHET),
            "--root",
            str(root),
            "--baseline-file",
            str(baseline_file),
        ]
        + list(extra_args),
        capture_output=True,
        text=True,
        env=env,
    )


def test_clean_tree_at_an_empty_baseline_passes(tmp_path):
    root = _fixture(tmp_path, "def f():\n    return 1\n")
    baseline = _write_baseline_file(tmp_path, [])
    r = _run(root, baseline)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_a_finding_absent_from_the_baseline_fails(tmp_path):
    root = _fixture(tmp_path, "import os\n\n\ndef f():\n    return 1\n")
    baseline = _write_baseline_file(tmp_path, [])
    r = _run(root, baseline)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "F401" in r.stdout


def test_a_finding_already_in_the_baseline_passes(tmp_path):
    root = _fixture(tmp_path, "import os\n\n\ndef f():\n    return 1\n")
    baseline = _write_baseline_file(tmp_path, ["a.py\tF401\t`os` imported but unused"])
    r = _run(root, baseline)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_missing_ruff_reports_third_state_not_ok(tmp_path):
    root = _fixture(tmp_path, "def f():\n    return 1\n")
    baseline = _write_baseline_file(tmp_path, [])
    # Copy the real environment and clear only PATH, rather than env={"PATH": ""} --
    # that replaces the child's *entire* environment, which on Windows also strips
    # SystemRoot/SYSTEMROOT that the interpreter's own startup and the CRT depend on,
    # so the child can fail to start for reasons unrelated to "ruff not found" and this
    # test would then fail on a returncode that is neither 2 nor a real ruff run --
    # never reaching the third-state logic this test exists to exercise (#635 review).
    env = dict(os.environ)
    env["PATH"] = ""
    r = _run(root, baseline, env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "COULD NOT RUN" in r.stdout
    assert "OK" not in r.stdout


def test_a_missing_baseline_file_is_could_not_run_not_ok(tmp_path):
    root = _fixture(tmp_path, "def f():\n    return 1\n")
    r = _run(root, tmp_path / "does-not-exist.txt")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "COULD NOT RUN" in r.stdout
    assert "OK" not in r.stdout


def test_write_baseline_regenerates_the_snapshot(tmp_path):
    root = _fixture(tmp_path, "import os\n\n\ndef f():\n    return 1\n")
    baseline = tmp_path / "baseline.txt"
    r = _run(root, baseline, extra_args=["--write-baseline"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WROTE" in r.stdout
    assert baseline.is_file()
    assert "F401" in baseline.read_text(encoding="utf-8")
    # written, the same tree now passes against its own fresh snapshot
    r2 = _run(root, baseline)
    assert r2.returncode == 0, r2.stdout + r2.stderr
