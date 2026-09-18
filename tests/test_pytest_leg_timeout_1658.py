"""The `pytest` job's own wall-clock cap, and the margin it must leave.

Measured across three back-to-back CI runs on PR #1654 (jobs #105401634166,
#105406249723, #105410692355), the `pytest (windows-latest, 3.12)` leg finished its
own suite green -- `7546 passed, 156 skipped, 5 warnings` -- in 862.98s-873.43s
(0:14:22-0:14:33) of wall time, then received a `KeyboardInterrupt` and was reported
`cancelled` by GitHub Actions because the job's total wall time (suite plus
checkout/setup/dependency-install overhead) crossed the job's own
`timeout-minutes: 15` ceiling. A cancelled job renders as a non-`SUCCESS` leg for
the pull request as a whole, identically to a real test failure, even though every
test passed (#1658).

This mirrors #303's own shape (see `test_shell_leg_budget_303.py`): a
`timeout-minutes` kill on Windows always reads as `cancelled`, never `failure`, so
the tests results being all-green does not save the leg.

#1658's own fix (15 -> 20) was not the last word: on PR #1654 the same leg was
cancelled AGAIN, on two independent back-to-back runs against the identical commit
`fad72a25` (jobs #105421966394, #105427076121), both reporting `7559 passed, 156
skipped, 5 warnings in 1176.55s (0:19:36)` -- ~5 minutes longer than #1658's own
measured baseline, and within 24 seconds of the 20-minute cap itself (#1660). The
suite's own reported runtime is not stable; the constant below tracks the most
recent measured worst case, and the margin below is deliberately generous rather
than exact, since the growth trend itself is unexplained (#1660 also adds a
faulthandler-based diagnostic -- `tests/posthang_diagnostics_1660.py` -- for
whichever thread is still alive if this recurs).

What this file holds: the `pytest` job still carries *some* wall-clock cap (a
regression of #1658's own fix could remove the cap entirely rather than raise it),
and that cap leaves real headroom over the slowest leg's own observed suite runtime
-- not just greater than zero, the weaker bound #303 settled for on the `shell` job,
which has no comparable per-leg runtime measurement to check against.

Python 3.9 compatible.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

#: The slowest leg's own observed suite runtime, in minutes -- updated by #1660 to
#: the most recent measured worst case (job #105427076121, 1176.55s), since #1658's
#: own reading (873.43s) was already superseded twice on the same commit. The cap
#: must clear this with real margin for setup/checkout/install overhead on top of
#: it, AND for the fact that this number has grown once already and may again.
OBSERVED_WORST_CASE_SUITE_MINUTES = 1176.55 / 60.0

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None

needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def test_the_parser_this_file_needs_is_present_on_ci():
    """A skipped file and a clean file are the same tick, so CI must not skip this one."""
    import os

    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the pytest-leg timeout "
            "assertions in this file did not run on a runner."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


def _pytest_job():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["pytest"]
    assert job, "the `pytest` job is empty, so everything below asserts nothing"
    return job


@needs_yaml
def test_the_pytest_job_still_carries_a_wall_clock_cap():
    """Fixing #1658 is not a licence to remove the bound on a real hang."""
    job = _pytest_job()
    cap = job.get("timeout-minutes")
    assert isinstance(cap, int) and cap > 0, (
        "the pytest job has no usable timeout-minutes ({!r}); a hung test would "
        "then run to the runner's own six-hour limit".format(cap)
    )


@needs_yaml
def test_the_pytest_job_cap_clears_the_observed_worst_case_with_margin():
    """#1658: 15 minutes was measured too tight against a ~14.5 minute suite run.

    Three back-to-back cancellations on the same green commit is not noise -- the
    ceiling left no room at all for setup overhead on the slowest leg
    (windows-latest). This asserts real headroom exists over the worst run this
    file's own docstring cites, not just `cap > 0` (#303's weaker bound, which had
    no comparable runtime measurement available for the job it covered).
    """
    job = _pytest_job()
    cap = job.get("timeout-minutes")
    assert isinstance(cap, int), "timeout-minutes is not an int: {!r}".format(cap)
    margin = cap - OBSERVED_WORST_CASE_SUITE_MINUTES
    assert margin >= 3, (
        "the pytest job's timeout-minutes ({!r}) leaves only {:.1f} minutes over "
        "the observed worst-case suite runtime of {:.1f} minutes (job "
        "#105427076121, 1176.55s) -- #1658 and #1660 were exactly this: a green "
        "suite cancelled by the job's own ceiling before it could report as "
        "such".format(cap, margin, OBSERVED_WORST_CASE_SUITE_MINUTES)
    )
