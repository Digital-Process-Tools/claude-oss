"""Make the Windows Defender exclusion step (#938) resilient to cmdlet failure (#1081).

`Add-MpPreference -ExclusionPath ...` has been observed to fail on a GitHub-hosted
Windows runner with `0x800106ba` (the Defender service unavailable on that runner). The
step added for #938 carried no `continue-on-error` and no try/catch, so that failure
failed the step, failed the job, and made the pull request unmergeable over a cmdlet
that has nothing to do with the change under test -- and it renders identically to a
real Windows test failure in `gh-pr:N:status` (`failed: pytest (windows-latest,
3.10)`), distinguishable only by opening the job log.

The issue itself names two legitimate shapes and asks for a choice, stated with a
reason: bare `continue-on-error: true` (simpler, but silent on its own -- needs a
disclosure step to say whether the exclusion actually applied), or wrapping each
`Add-MpPreference` call in try/catch so the same step can distinguish "cmdlet failed"
from "applied cleanly" and disclose it in one place, mirroring the hit/miss/skip
disclosure #1196 already added to this same workflow file (the "Tool cache state"
step). This file pins the try/catch-and-disclose shape actually chosen:

* the step must not be able to fail the job on a cmdlet error -- either via
  `continue-on-error: true`, or by catching the error itself (`-ErrorAction Stop`
  paired with `try`/`catch`, or equivalent);
* a run where the exclusion did not apply must say so in the log, not just swallow it
  silently -- `continue-on-error` alone achieves the first without the second.

Python 3.9 compatible.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


def test_the_parser_this_file_needs_is_present_on_ci():
    """Mirrors tests/test_windows_defender_exclusion_938.py's own guard."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the resilience assertions in "
            "this file did not run on a runner."
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
def test_a_failed_cmdlet_cannot_fail_the_step():
    """Either continue-on-error: true, or a try/catch that swallows the error itself.

    A step that can fail the job on Add-MpPreference erroring is exactly #1081's bug:
    a Defender-service hiccup on the runner fails a PR that could not have caused it,
    and it is indistinguishable from a real test failure in gh-pr:N:status without
    opening the job log.
    """
    job = _workflow()["jobs"]["pytest"]
    step = _find_step(job, STEP_NAME)
    assert step is not None
    run = step.get("run", "")
    has_continue_on_error = step.get("continue-on-error") is True
    has_try_catch = "try" in run and "catch" in run
    assert has_continue_on_error or has_try_catch, (
        "the exclusion step must not be able to fail the job on a cmdlet error -- "
        "add continue-on-error: true, or wrap each Add-MpPreference call in "
        "try/catch, got continue-on-error={!r} run={!r}".format(
            step.get("continue-on-error"), run
        )
    )


@needs_yaml
def test_whether_the_exclusion_applied_is_disclosed_in_the_log():
    """continue-on-error alone is silent; #1081 requires the outcome be logged.

    #938's own pending speed measurement depends on knowing which legs actually had
    the exclusion active, so a run where it silently failed must not look identical
    to one where it silently succeeded.
    """
    job = _workflow()["jobs"]["pytest"]
    step = _find_step(job, STEP_NAME)
    assert step is not None
    run = step.get("run", "")
    lowered = run.lower()
    disclosed = (
        "write-host" in lowered
        or "echo" in lowered
        or "::warning::" in lowered
        or "::error::" in lowered
    )
    assert disclosed, (
        "the step must log whether the exclusion actually applied (e.g. via "
        "Write-Host / a ::warning:: annotation on failure), not swallow the "
        "outcome silently -- got run: {!r}".format(run)
    )


@needs_yaml
def test_step_still_excludes_workspace_and_runner_temp():
    """The fix for #1081 must not lose the substance #938 added."""
    job = _workflow()["jobs"]["pytest"]
    step = _find_step(job, STEP_NAME)
    assert step is not None
    run = step.get("run", "")
    assert "Add-MpPreference" in run
    assert "github.workspace" in run
    assert "RUNNER_TEMP" in run


@needs_yaml
def test_step_is_still_windows_only():
    job = _workflow()["jobs"]["pytest"]
    step = _find_step(job, STEP_NAME)
    assert step is not None
    assert step.get("if", "") == "runner.os == 'Windows'"
