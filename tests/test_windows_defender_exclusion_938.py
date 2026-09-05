"""The Windows Defender exclusion step in the `pytest` job (#938).

`Digital-Process-Tools/claude-jit-context#310` (open at the time this landed, not yet
merged -- the shape ported here is that PR's own diff, confirmed via `gh api
repos/Digital-Process-Tools/claude-jit-context/pulls/310/files` rather than retyped from
the issue body, which itself flagged its snippet as unverified) identified Windows
Defender's real-time scanner walking every temp file a test suite creates as a
documented, codebase-independent cost on `windows-latest` GitHub Actions runners --
unrelated to subprocess spawning or test logic. `Add-MpPreference -ExclusionPath` against
the checkout and the runner temp directory is a known, safe pattern for removing it.

This file pins the two properties a rewrite of the step is most likely to lose:

* it is gated `if: runner.os == 'Windows'`, so the other two legs in this job's matrix
  never see it run -- an unconditional exclusion step would either no-op with a spurious
  warning on macOS/Linux or, worse, fail there since `Add-MpPreference` and `pwsh`'s
  `$env:RUNNER_TEMP` spelling are Windows/PowerShell-specific;
* it names both the checkout (`github.workspace`) and the runner temp directory
  (`RUNNER_TEMP`) -- excluding only one leaves the suite's `mktemp` fixtures, which the
  issue calls out by name, still walked by the scanner.

It also pins that the step lives in the `pytest` job (the one carrying the
`windows-latest` matrix leg) and not in `shell`, which never runs on Windows at all --
a step landed in the wrong job would be dead weight nobody would notice failing, because
it would never execute.

The actual measured timing saving on this repo's own suite is **not** asserted here and
cannot be: there is no local `windows-latest` run, and the issue itself says a live CI
round is needed to confirm it. This file only pins the step's shape and placement.

Python 3.9 compatible.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


def test_the_parser_this_file_needs_is_present_on_ci():
    """Mirrors tests/test_shell_leg_budget_303.py's own guard, for the same reason.

    A skip and a clean pass are the same tick from outside; CI installs pyyaml (see the
    comment beside it in tests.yml), so its absence there is a broken leg, not a
    contributor's laptop.
    """
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the Windows Defender assertions "
            "in this file did not run on a runner."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


STEP_NAME = "Exclude the checkout and temp dir from Windows Defender scanning"


def _find_step(job, name):
    for step in job.get("steps", []):
        if step.get("name") == name:
            return step
    return None


@needs_yaml
def test_step_is_present_in_the_pytest_job():
    job = _workflow()["jobs"]["pytest"]
    step = _find_step(job, STEP_NAME)
    assert step is not None, (
        "no step named {!r} in the pytest job; steps are {!r}".format(
            STEP_NAME, [s.get("name") or s.get("uses") for s in job["steps"]]
        )
    )


@needs_yaml
def test_step_is_windows_only():
    """Exact-match, not substring -- a substring check would pass `runner.os != 'Windows'`.

    An inverted or typo'd comparison operator (!= instead of ==) still contains both the
    string "runner.os" and the string "Windows", so a looser check here would not catch
    the one mutation most likely to actually happen and most likely to break the other
    two legs of the matrix (found by review, #938).
    """
    job = _workflow()["jobs"]["pytest"]
    step = _find_step(job, STEP_NAME)
    assert step is not None
    condition = step.get("if", "")
    assert condition == "runner.os == 'Windows'", (
        "the exclusion step must be gated exactly to runner.os == 'Windows', got "
        "if: {!r} -- an inverted or mistyped comparison would still contain the "
        "substrings 'runner.os' and 'Windows' while running the step on every other "
        "leg of the matrix too".format(condition)
    )


@needs_yaml
def test_step_uses_pwsh_and_excludes_workspace_and_runner_temp():
    job = _workflow()["jobs"]["pytest"]
    step = _find_step(job, STEP_NAME)
    assert step is not None
    assert step.get("shell") == "pwsh", (
        "Add-MpPreference is a PowerShell cmdlet; got shell: {!r}".format(
            step.get("shell")
        )
    )
    run = step.get("run", "")
    assert "Add-MpPreference" in run
    assert "github.workspace" in run, "the checkout itself must be excluded"
    assert "RUNNER_TEMP" in run, (
        "the runner temp dir must be excluded too -- that is where mktemp fixtures land"
    )


@needs_yaml
def test_step_is_not_in_the_shell_job():
    """The `shell` job runs on ubuntu-latest only and never sees a Windows runner.

    A step landed there instead of in `pytest` would be inert -- never executed, never
    caught by a red leg, and no evidence anything is wrong.
    """
    job = _workflow()["jobs"]["shell"]
    assert _find_step(job, STEP_NAME) is None


@needs_yaml
def test_step_runs_before_the_test_suite_starts():
    """The exclusion has to be registered before test files start piling up in temp.

    Placed after checkout is early enough; placed after `Run tests` would exclude
    nothing that mattered.
    """
    job = _workflow()["jobs"]["pytest"]
    names = [s.get("name") or s.get("uses") for s in job["steps"]]
    assert STEP_NAME in names
    run_tests_index = next(i for i, n in enumerate(names) if n == "Run tests")
    exclusion_index = names.index(STEP_NAME)
    assert exclusion_index < run_tests_index, (
        "the exclusion step must run before `Run tests`, not after"
    )
