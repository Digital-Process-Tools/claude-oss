"""#1176: content-guard sweeps (marked `invariant`) run once, not on all 12 legs.

126 of the 428 tracked test files #1176 counted at filing time touch no `tmp_path`, no
`subprocess` and no `monkeypatch` --
content guards over this repository's own markdown/config. #1176's own measurement found
that heuristic is the wrong SET for savings: it selects the cheap tests (9.67s total, none
of the 25 slowest on `pytest (ubuntu-latest, 3.12)`). The actually expensive content-guard
tests are the ones that DO spawn a subprocess or read this repo's whole tree, because they
sweep tracked files -- 51.30s across nine tests in four files, 21.9% of that leg's measured
test time, none of it OS- or interpreter-dependent (each reads the same tracked bytes,
pinned to LF by `.gitattributes`, and derives an answer from them; see #675 for the
counterexample that makes that pin load-bearing).

Marked here, one test at a time rather than one file at a time: three of these four files
mix genuinely invariant sweeps with `tmp_path`/`monkeypatch` unit tests exercising this
repo's own scripts against synthetic fixtures -- those ARE platform-sensitive (a `tmp_path`
is a real filesystem path, and Windows' separators and permission model differ), so the
marker sits on the nine slow, real-tree-reading tests only, never on the file as a whole.

The route (`-m "not invariant"` on 11 legs, nothing deselected on the twelfth) follows
#1177's own shape for the coverage floor -- a single conditional expression on the one
unconditional test step, never a second `if:`-guarded step, because two conditions that
are both false is a leg that runs nothing and reports success. The chosen full leg is the
same one #1177 already designated to keep coverage, `(ubuntu-latest, 3.12)`: reusing it
avoids inventing a second "special leg" concept, and it is a non-Windows leg, so it is not
added to the 51.6%-of-wall-clock Windows legs #1176's own issue body says a deselect must
not land on.

Python 3.9 compatible.
"""

import sys
import os
import re
from pathlib import Path

import pytest

import spawn_guard

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: The leg that runs every test, invariant sweeps included. Matches #1177's own
#: COVERAGE_LEG -- one full leg is reused rather than two special legs invented.
FULL_LEG = ("ubuntu-latest", "3.12")

#: The current, hand-audited set of tests whose answer cannot vary by OS or interpreter
#: and that were expensive enough to be worth deselecting (#1176's own per-file measurement
#: table). A test added to this file later without updating this registry is a guard that
#: went stale silently -- `test_the_registered_set_matches_what_is_actually_marked` below
#: is what catches that, in the direction collection can see: an UNREGISTERED test that
#: still carries the marker. It cannot see the opposite drift (a new expensive content
#: sweep that nobody marked at all) -- that half stays a human judgment call at write time.
INVARIANT_TESTS = {
    "tests/test_no_test_pins_the_current_version_350.py::"
    "test_the_sweep_is_clean_for_the_version_this_repository_reaches_next",
    "tests/test_no_test_pins_the_current_version_350.py::test_no_test_file_pins_the_current_version",
    "tests/test_no_test_pins_the_current_version_350.py::"
    "test_the_real_sweep_two_minors_out_is_reported_as_a_warning_not_a_failure",
    "tests/test_unwired_scripts_253.py::test_every_exception_is_still_needed",
    "tests/test_unwired_scripts_253.py::"
    "test_nothing_in_the_surveyed_directories_is_referenced_by_nothing",
    "tests/test_unwired_scripts_253.py::test_unsearchable_files_are_surfaced_rather_than_silent",
    "tests/test_unwired_scripts_253.py::test_absent_files_are_surfaced_rather_than_silent",
    "tests/test_spawn_guard_716.py::test_the_sweep_reached_this_suite_at_all",
    "tests/test_prose_script_refs_1070.py::test_survey_over_this_repos_own_prose_has_no_findings",
}

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


def test_the_parser_this_file_needs_is_present_on_ci():
    """A skipped file and a clean file are the same tick, so CI must not skip this one."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the invariant-marker assertions "
            "in this file did not run on a runner. The pytest job installs it; if that "
            "line changed, this file went quiet rather than red."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def _pytest_job():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["pytest"]
    assert job.get("steps"), (
        "the `pytest` job has no steps, so everything below asserts nothing"
    )
    return job


_INVOCATION = re.compile(r"(?:^|[;&|]\s*|\bthen\s+|\belse\s+)pytest\b", re.MULTILINE)


def _test_step(job):
    running = [s for s in job["steps"] if _INVOCATION.search(s.get("run") or "")]
    assert running, "no step in the pytest job invokes pytest; steps are {!r}".format(
        [s.get("name") or s.get("uses") for s in job["steps"]]
    )
    assert len(running) == 1, (
        "{} steps invoke pytest, so `the` test step is ambiguous: {!r}".format(
            len(running), [s.get("name") for s in running]
        )
    )
    return running[0]


@needs_yaml
def test_the_test_step_still_runs_pytest_unconditionally():
    """The step this whole file is about must exist and must run on every leg."""
    step = _test_step(_pytest_job())
    assert "if" not in step, (
        "the test step is conditional ({!r}); a leg whose condition is false runs no "
        "tests and still reports success".format(step.get("if"))
    )
    assert "shell" not in step, (
        "the test step overrides the shell ({!r}); #1177 measured that as 123 launcher "
        "failures on Windows from a side effect of choosing a flag this way".format(
            step.get("shell")
        )
    )


@needs_yaml
def test_exactly_one_leg_of_the_matrix_runs_without_the_invariant_deselect():
    """An expression naming a leg outside the matrix would match no leg at all, and every
    invariant test would then be deselected everywhere -- so the two halves are checked
    against each other rather than separately, the same shape #1177's own coverage-leg
    test uses.
    """
    job = _pytest_job()
    run = _test_step(job)["run"]
    assert "not invariant" in run, (
        'no `-m "not invariant"` deselect appears on the test step\'s command line: '
        "{!r}".format(run)
    )
    matrix = job["strategy"]["matrix"]

    # The deselect sits behind a condition that is true on every leg except the full one.
    # Find that condition's os/python literals the same way #1177's coverage test does.
    ternaries = re.findall(r"\$\{\{([^}]*not invariant[^}]*)\}\}", run)
    assert ternaries, "no `${{ ... not invariant ... }}` expression on the command line"
    expression = ternaries[0]

    named_os = [v for v in matrix["os"] if "'{}'".format(v) in expression]
    named_py = [v for v in matrix["python-version"] if "'{}'".format(v) in expression]
    assert named_os == [FULL_LEG[0]], (
        "the invariant-deselect expression names {!r} of the matrix's os values, not "
        "exactly the full leg's: {!r}".format(named_os, expression)
    )
    assert named_py == [FULL_LEG[1]], (
        "the invariant-deselect expression names {!r} of the matrix's python-version "
        "values, not exactly the full leg's: {!r}".format(named_py, expression)
    )


@needs_yaml
def test_invariant_marker_is_registered_in_pyproject():
    """An unregistered marker warns rather than silently applying nothing (see the
    `must_assert_on` marker just above it in the same list, registered for the same
    reason)."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert '"invariant:' in text, (
        "pyproject.toml's [tool.pytest.ini_options] markers list does not register "
        "`invariant`, so pytest would warn on every use of it rather than recognising it"
    )


def test_the_registered_set_matches_what_is_actually_marked():
    """The registry above and the real marker have to agree in both directions:
    something marked `invariant` that this file does not know about is a marker nobody
    is accounting for, and something in this file's registry that lost its marker (e.g.
    a rename during a later edit) would otherwise still say it is covered while running
    on all 12 legs again.
    """
    result = spawn_guard.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-m",
            "invariant",
            "--collect-only",
            "-q",
            "--no-cov",
        ],
        subject="the invariant-marker registry",
        timeout=120,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "collecting the `invariant`-marked tests failed (exit {}): {}".format(
            result.returncode, result.stdout + result.stderr
        )
    )
    collected = {
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and line.strip().startswith("tests/")
    }
    assert collected == INVARIANT_TESTS, (
        "the tests actually collected under -m invariant do not match this file's own "
        "registry.\n  only collected: {}\n  only registered: {}".format(
            sorted(collected - INVARIANT_TESTS), sorted(INVARIANT_TESTS - collected)
        )
    )
