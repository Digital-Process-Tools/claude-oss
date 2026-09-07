"""#1246: an ordinary push/PR runs a reduced matrix; a release-triggered dispatch runs the full one.

Measured on run `34099357435` (`tests` on `main` at `0dee1e2`, 14 jobs): 35.9 leg-minutes total,
critical path 311s on `pytest (windows-latest, 3.12)`, and 13 of 14 jobs started within 7 seconds
of each other. Cutting legs saves almost no wall-clock on an isolated push -- the legs already run
in parallel and the critical-path leg stays in the reduced set -- but during a merge train the
account's runner-concurrency cap (20 concurrent jobs, 5 macOS) is what a 14-job-per-run matrix
blows through, serialising a train of pushes behind itself.

So the push/PR matrix is cut to the five legs that stay: `ubuntu-latest`/3.12 (the cheap default),
`ubuntu-latest`/3.9 (the declared floor), `windows-latest`/3.12 (the observed failure platform),
`macos-latest`/3.12 (the third OS), and `shellcheck` (unchanged). The full 3-OS x Python 3.9-3.12
matrix still exists in the same workflow -- no second file -- and is reached only through an
explicit `workflow_dispatch` input, `full_matrix: true`, which the release process sets when it
dispatches a run against the commit about to be tagged. An ordinary `workflow_dispatch` (the #679
dropped-push-run remedy, `full_matrix` defaulting to `false`) still mirrors the reduced push matrix
rather than silently ballooning to 12 legs.

The matrix is expressed as the unconditional 3x4 cross product (`os` x `python-version`) plus a
conditional `exclude:` list -- the eight combinations dropped for an ordinary run, and an empty
list when `full_matrix` is true. This file evaluates that expression's two literal JSON branches
directly rather than running the workflow, which is the only way to check a GitHub Actions
expression without a runner.

Python 3.9 compatible.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None

needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def test_the_parser_this_file_needs_is_present_on_ci():
    """Same shape as test_shell_leg_budget_303.py's own guard: a skip here must never be
    the CI answer, only a local-machine one."""
    import os

    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the CI-matrix assertions in this "
            "file did not run on a runner."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _pytest_job():
    job = _workflow()["jobs"]["pytest"]
    assert job, "the `pytest` job is empty, so everything below asserts nothing"
    return job


#: The five legs #1246 keeps on an ordinary push/PR. `shellcheck` is the `shell` job and is
#: unchanged by this issue -- checked separately, below, as a stays-as-is control.
REDUCED_PYTEST_LEGS = {
    ("ubuntu-latest", "3.12"),
    ("ubuntu-latest", "3.9"),
    ("windows-latest", "3.12"),
    ("macos-latest", "3.12"),
}

FULL_PYTEST_LEGS = {
    (os_, py)
    for os_ in ("ubuntu-latest", "macos-latest", "windows-latest")
    for py in ("3.9", "3.10", "3.11", "3.12")
}


@needs_yaml
def test_pytest_matrix_is_the_unconditional_full_cross_product():
    """`os` and `python-version` themselves stay the full 3x4 product -- the reduction is
    carried entirely by `exclude:`, so a release dispatch can restore full coverage by
    excluding nothing rather than needing a second, separately-maintained matrix."""
    matrix = _pytest_job()["strategy"]["matrix"]
    assert set(matrix["os"]) == {"ubuntu-latest", "macos-latest", "windows-latest"}
    assert set(matrix["python-version"]) == {"3.9", "3.10", "3.11", "3.12"}


@needs_yaml
def test_pytest_matrix_carries_a_conditional_exclude():
    matrix = _pytest_job()["strategy"]["matrix"]
    assert "exclude" in matrix, (
        "no `exclude:` on the pytest job's matrix -- #1246 needs a per-event exclusion, "
        "not a second hardcoded matrix"
    )
    assert isinstance(matrix["exclude"], str), (
        "matrix.exclude is not a `${{ }}` expression string, so it cannot vary by event"
    )


def _exclude_expression():
    matrix = _pytest_job()["strategy"]["matrix"]
    return matrix["exclude"]


def _ternary_branches(expression):
    """Pull the two `fromJson('...')` literals out of `cond && A || B`.

    Order matters: GitHub Actions evaluates left-to-right with `&&` binding tighter than
    `||`, so the first `fromJson(...)` is the TRUE arm (the `full_matrix` dispatch) and the
    second is the FALSE arm (an ordinary push/PR/dispatch). A workflow that got this
    backwards would run 12 legs on every push and 4 at release -- the exact inversion
    #1177's own comment in this file warns about for a different pair of flags.
    """
    literals = re.findall(r"fromJson\('(\[.*?\])'\)", expression, flags=re.DOTALL)
    assert len(literals) == 2, (
        "expected exactly two fromJson(...) literals (true-arm, false-arm) in the "
        "exclude expression, found {}: {!r}".format(len(literals), expression)
    )
    true_arm = json.loads(literals[0])
    false_arm = json.loads(literals[1])
    return true_arm, false_arm


@needs_yaml
def test_full_matrix_dispatch_excludes_nothing():
    expression = _exclude_expression()
    true_arm, _false_arm = _ternary_branches(expression)
    assert true_arm == [], (
        "the full_matrix=true arm of the exclude expression is not empty, so a release "
        "dispatch would still drop legs: {!r}".format(true_arm)
    )


@needs_yaml
def test_ordinary_run_excludes_down_to_the_reduced_five():
    expression = _exclude_expression()
    _true_arm, false_arm = _ternary_branches(expression)
    excluded = {(entry["os"], entry["python-version"]) for entry in false_arm}
    remaining = FULL_PYTEST_LEGS - excluded
    assert remaining == REDUCED_PYTEST_LEGS, (
        "excluding the false-arm entries from the full matrix does not land on the five "
        "legs #1246 keeps: got {!r}, wanted {!r}".format(remaining, REDUCED_PYTEST_LEGS)
    )
    assert excluded == FULL_PYTEST_LEGS - REDUCED_PYTEST_LEGS


@needs_yaml
def test_exclude_expression_is_keyed_on_a_workflow_dispatch_input():
    expression = _exclude_expression()
    assert "workflow_dispatch" in expression
    assert "full_matrix" in expression


@needs_yaml
def test_workflow_dispatch_carries_a_full_matrix_input():
    # YAML 1.1's bareword booleans mean pyyaml parses the unquoted `on:` key as the
    # Python bool `True`, not the string "on" -- #679's own `_on_block` helper works
    # around this with a hand-rolled text parser rather than `safe_load`; this
    # assertion only needs one nested key, so it reads the boolean key directly
    # instead of duplicating that parser.
    workflow = _workflow()
    dispatch = workflow[True]["workflow_dispatch"]
    assert dispatch, "workflow_dispatch has no inputs block; #1246 needs `full_matrix`"
    assert "full_matrix" in dispatch["inputs"]
    full_matrix_input = dispatch["inputs"]["full_matrix"]
    # Defaulting to false is what keeps an ordinary #679 dropped-push-run recreation
    # mirroring the reduced push matrix instead of silently ballooning to 12 legs.
    assert str(full_matrix_input.get("default")).lower() == "false"


@needs_yaml
def test_shell_job_is_unchanged_by_this_issue():
    """`shellcheck` is listed in the issue's own table as `unchanged` -- still one
    unconditional ubuntu-only job, not folded into the matrix reduction above."""
    workflow = _workflow()
    shell_job = workflow["jobs"]["shell"]
    assert shell_job["runs-on"] == "ubuntu-latest"
    assert "strategy" not in shell_job
