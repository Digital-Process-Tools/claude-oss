"""#1177 candidate 2: the coverage floor is evaluated on one leg, and on exactly one.

`addopts` in `pyproject.toml` carries `--cov=scripts --cov-report=term-missing
--cov-fail-under=85`, so every one of the twelve pytest legs computed coverage and
evaluated the 85% floor. The twelve numbers were never compared to each other -- each
leg only ever checked its own against 85 -- so eleven of those evaluations bought nothing
a reader saw, at about 11% of wall time (#881's measurement), which is ~600s of the
matrix's ~5567s per run.

The three ways this change could go wrong, and what holds each one:

* **No leg runs coverage.** Then the floor is evaluated nowhere and twelve legs are green
  with the gate switched off. `test_exactly_one_leg_of_the_matrix_runs_with_coverage`.
* **No leg runs tests.** The obvious shape for this change is two `if:`-guarded steps, one
  with coverage and one without; two conditions that are both false is a leg that runs
  nothing and reports success. The step here is unconditional and branches inside the
  shell, and `test_the_test_step_is_unconditional` holds that.
* **The floor stops existing.** `--no-cov` on eleven legs is only a saving if the twelfth
  still fails under 85%. `test_the_floor_is_still_declared` reads `pyproject.toml`.

Python 3.9 compatible.
"""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: The leg that keeps coverage. Named once here and derived from the workflow below
#: rather than asserted as a literal in three places.
COVERAGE_LEG = ("ubuntu-latest", "3.12")

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
            "pyyaml is not importable and CI=true, so the coverage-leg assertions in "
            "this file did not run on a runner. The pytest job installs it; if that "
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


#: A pytest invocation at command position -- start of line, or after a `;`, `&&`, `||`,
#: `then` or `else`. `"pytest" in run` also matches the `pip install pytest` line in the
#: dependency step, which is how the first draft of this file located the wrong step and
#: reported the change as unmade.
_INVOCATION = re.compile(r"(?:^|[;&|]\s*|\bthen\s+|\belse\s+)pytest\b", re.MULTILINE)


def _test_step(job):
    """The one step that actually runs the suite, located by what it runs."""
    running = [
        step for step in job["steps"] if _INVOCATION.search(step.get("run") or "")
    ]
    assert running, "no step in the pytest job invokes pytest; steps are {!r}".format(
        [s.get("name") or s.get("uses") for s in job["steps"]]
    )
    assert len(running) == 1, (
        "{} steps invoke pytest, so `the` test step is ambiguous and a leg may run the "
        "suite twice or under two different flag sets: {!r}".format(
            len(running), [s.get("name") for s in running]
        )
    )
    return running[0]


def _cov_expression(step):
    """The `${{ ... }}` expression on the test step's own command line."""
    run = step.get("run") or ""
    assert "${{" in run, (
        "the test step's command line carries no expression, so nothing selects the "
        "coverage leg: {!r}".format(run)
    )
    return run


# --------------------------------------------------------- one leg, and exactly one


@needs_yaml
def test_exactly_one_leg_of_the_matrix_runs_with_coverage():
    """The expression names one os and one interpreter, and the matrix contains both.

    An expression naming `ubuntu-latest` and `3.13` would be syntactically fine, would
    match no leg, and would leave the floor evaluated nowhere while every leg stayed
    green -- so the two halves are checked against each other rather than separately.
    """
    job = _pytest_job()
    expression = _cov_expression(_test_step(job))
    matrix = job["strategy"]["matrix"]

    named_os = [value for value in matrix["os"] if "'{}'".format(value) in expression]
    named_py = [
        value
        for value in matrix["python-version"]
        if "'{}'".format(value) in expression
    ]
    assert named_os == [COVERAGE_LEG[0]], (
        "the COV expression selects {!r} of the matrix's own os values, not exactly "
        "one: {!r}".format(named_os, expression)
    )
    assert named_py == [COVERAGE_LEG[1]], (
        "the COV expression selects {!r} of the matrix's own python-version values, not "
        "exactly one: {!r}".format(named_py, expression)
    )


@needs_yaml
def test_the_flagged_arm_is_the_non_empty_one():
    """A GitHub `A && '' || B` ternary yields B when A is true, because '' is falsy.

    Written that way round, `--no-cov` lands on all twelve legs, coverage is measured
    nowhere, and the matrix is green throughout -- the single most likely way to write
    this change wrong. The condition is therefore inverted so the empty string is only
    ever the RESULT: `X && '--no-cov' || ''`. This pins that shape rather than trusting
    it, because both spellings look equally reasonable in review.
    """
    expression = _cov_expression(_test_step(_pytest_job()))
    arms = re.findall(r"&&\s*'([^']*)'\s*\|\|\s*'([^']*)'", expression)
    assert arms, "no `&& '...' || '...'` ternary in the command line: {!r}".format(
        expression
    )
    true_arm, false_arm = arms[0]
    assert true_arm == "--no-cov", (
        "the ternary's non-empty arm is {!r}, not '--no-cov'; a falsy arm is what makes "
        "this expression select nothing".format(true_arm)
    )
    assert false_arm == "", (
        "the fallback arm is {!r}; the coverage leg must get no extra flag at all so "
        "addopts' own --cov settings apply unchanged".format(false_arm)
    )


# --------------------------------------------------------- no leg runs nothing


@needs_yaml
def test_the_test_step_is_unconditional():
    """Two `if:`-guarded steps that are both false is a leg that runs no tests at all."""
    step = _test_step(_pytest_job())
    assert "if" not in step, (
        "the test step is conditional ({!r}); a leg whose condition is false runs no "
        "tests and still reports success".format(step.get("if"))
    )


@needs_yaml
def test_the_conditional_check_can_see_a_conditional_step():
    """Positive control: a step carrying an `if:` is visible to the assertion above."""
    conditional = [s for s in _pytest_job()["steps"] if "if" in s]
    assert conditional, (
        "no step in the pytest job carries an `if:`, so the assertion that the test "
        "step carries none is vacuous"
    )


@needs_yaml
def test_the_step_does_not_override_the_shell():
    """#1177, measured: `shell: bash` here cost 123 test failures on every Windows leg.

    The first version of this step branched on the flag inside `bash`, which replaced
    the default shell for the whole test run on `windows-latest`. pytest under Git Bash
    resolves a different `git` than pytest under PowerShell, and four launcher suites
    that pin their own PATH stopped finding one -- a serial run, so nothing to do with
    parallelism. Passing one flag does not need the interpreter changed underneath the
    suite, and this pins that: a `shell:` here is a far larger change than it looks.
    """
    step = _test_step(_pytest_job())
    assert "shell" not in step, (
        "the test step overrides the shell to {!r}. That changes which interpreter the "
        "whole suite runs under, per-platform, as a side effect of choosing a pytest "
        "flag".format(step.get("shell"))
    )


@needs_yaml
def test_the_saving_is_actually_asked_for():
    """`--no-cov` has to appear, or this change costs a step and saves nothing."""
    run = _test_step(_pytest_job())["run"]
    assert "--no-cov" in run, (
        "the test step never passes --no-cov, so all twelve legs still compute "
        "coverage: {!r}".format(run)
    )


# --------------------------------------------------------- the floor still exists


def test_the_floor_is_still_declared():
    """`--no-cov` on eleven legs is a saving only if the twelfth still fails under 85%."""
    addopts = PYPROJECT.read_text(encoding="utf-8")
    assert "--cov-fail-under=" in addopts, (
        "pyproject.toml declares no --cov-fail-under, so the leg that keeps coverage "
        "computes a number nothing checks"
    )
