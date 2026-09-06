"""#1177 candidate 1: the matrix runs under xdist, and under the distribution it needs.

The worker-sizing probe (#1189) reported 4 workers on ubuntu and windows and 3 on macOS,
so the parallelism exists; nothing consumed it, because `pytest-xdist` was not installed
on any leg and no `-n` was passed.

Two properties this file holds, both of which a later edit can lose silently:

* **The plugin is installed.** `-n auto` with no `pytest-xdist` present is not an error
  that stops a leg -- pytest reports `unrecognized arguments` and exits 4, which is red,
  but the reverse edit is the quiet one: dropping `-n auto` while leaving the package
  installed leaves twelve serial legs that look exactly like twelve parallel ones.
* **`--dist loadfile`, not the default.** This suite builds git repositories, changes
  working directory and manages worktrees. `--dist load` spreads one file's tests across
  workers, and a fixture that chdirs or writes a fixed path then races against itself.
  The failure that produces is order-dependent, so it renders as a flake attached to
  whatever pull request happens to be open, not to this one.

What this file deliberately does not assert: that the suite is parallel-safe. No static
check establishes that, and a green first run does not either -- see the pull request for
the repeated runs that stand as the evidence, and their limits.

Python 3.9 compatible.
"""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None

_INVOCATION = re.compile(r"(?:^|[;&|]\s*|\bthen\s+|\belse\s+)pytest\b", re.MULTILINE)


def test_the_parser_this_file_needs_is_present_on_ci():
    """A skipped file and a clean file are the same tick, so CI must not skip this one."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the xdist assertions in this file "
            "did not run on a runner. The pytest job installs it; if that line changed, "
            "this file went quiet rather than red."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def _pytest_job():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["pytest"]
    assert job.get("steps"), "the `pytest` job has no steps, so everything below asserts nothing"
    return job


def _steps_running_pytest(job):
    return [s for s in job["steps"] if _INVOCATION.search(s.get("run") or "")]


def _invocations(job):
    """Every pytest command line in the job's test step, one per shell branch."""
    steps = _steps_running_pytest(job)
    assert len(steps) == 1, (
        "{} steps invoke pytest, so `the` test step is ambiguous: {!r}".format(
            len(steps), [s.get("name") for s in steps]
        )
    )
    # `.strip()` before the match, not after: the branch body is indented inside the
    # `if`, and `^pytest` under re.MULTILINE anchors at column 0. Matching the raw line
    # found nothing and reported the step as invoking pytest nowhere.
    lines = [
        stripped
        for stripped in (line.strip() for line in steps[0]["run"].splitlines())
        if _INVOCATION.search(stripped)
    ]
    assert lines, "the test step invokes pytest on no line of its own body"
    return lines


@needs_yaml
def test_every_pytest_invocation_asks_for_workers():
    """Both arms of the coverage branch, not just the one a reader happens to check."""
    for line in _invocations(_pytest_job()):
        assert "-n auto" in line, (
            "a pytest invocation runs serially while the others parallelise, so one leg "
            "silently keeps the old cost: {!r}".format(line)
        )


@needs_yaml
def test_the_distribution_is_loadfile():
    """`--dist load` races this suite's chdir and worktree fixtures against each other."""
    for line in _invocations(_pytest_job()):
        assert "--dist loadfile" in line, (
            "a pytest invocation does not pin --dist loadfile, so xdist's default `load` "
            "spreads one file's tests across workers: {!r}".format(line)
        )


@needs_yaml
def test_the_plugin_that_consumes_n_auto_is_installed():
    """`-n auto` with no pytest-xdist present is `unrecognized arguments`, exit 4."""
    job = _pytest_job()
    installs = [
        s for s in job["steps"] if "pip install" in (s.get("run") or "")
    ]
    assert installs, "no step in the pytest job installs anything"
    assert any("pytest-xdist" in (s["run"]) for s in installs), (
        "no install step names pytest-xdist, so every leg would fail on the `-n auto` "
        "the test step passes: {!r}".format([s.get("name") for s in installs])
    )


@needs_yaml
def test_psutil_is_not_installed_alongside_it():
    """A regression guard with a measured reason, not a style preference.

    `-n auto` reads `psutil.cpu_count(logical=False)` FIRST, and only falls through to
    `os.sched_getaffinity(0)` / `os.cpu_count()` when psutil is absent. The probe read 4
    workers on ubuntu and windows through that fallback. Installing psutil here would
    switch the source to physical cores -- halving the workers on any SMT runner -- and
    nothing would report the change: the legs would just get slower again.
    """
    for step in _pytest_job()["steps"]:
        run = step.get("run") or ""
        if "pip install" in run:
            assert "psutil" not in run, (
                "psutil is installed for the matrix, which changes what `-n auto` "
                "resolves to without changing anything a reader sees: {!r}".format(
                    step.get("name")
                )
            )
