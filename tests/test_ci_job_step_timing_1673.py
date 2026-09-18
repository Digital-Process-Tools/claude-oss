"""#1673: settle whether a CI cancellation's own wall-clock gap sits
before pytest starts, after pytest finishes, or inside pytest's own
execution window -- the "what would actually settle it" ask from that
issue's own body, none of which any prior diagnostic in this tree measures
directly. `posthang_diagnostics_1660.py` (in-process stack dumps) and
`test_pytest_leg_timeout_1658.py` (a hand-maintained margin constant) both
assume the process is genuinely blocked; this module answers a narrower,
prior question from outside the process entirely -- GitHub's own per-step
timestamps for one already-concluded job -- so a recurrence can be
classified without guessing.

Manually walked once against two REAL jobs before this module existed
(#1673's own recon): job 105522023801 (`pytest (windows-latest, 3.12)` on
PR #1654, cancelled) breaks down as pre-step 28s / `Run tests` step 1777s /
post-step 5s against a job total of 1810s -- so the ~1775.81s pytest itself
reported is almost the WHOLE gap, not a small remainder before or after it,
which is the one shape this module's own three-way split exists to name.
The comparison green run (job 105519970619, same leg, same day) was
pre-step ~31s / `Run tests` 343s / post-step ~5s -- a `Run tests` step
roughly 5x shorter, while both jobs' own `test-durations:` summary lines
(1120.68s vs 1168.75s "total") show almost IDENTICAL summed per-test call
time. That pairing -- same aggregate test work, wildly different wall
clock, all of it inside the pytest step itself -- is what actually
distinguishes "runner/fleet contention or worker starvation during the
run" from either "slow pre-pytest setup" or "something holds the step
open after pytest's own summary line" (the leaked-handle theory this
issue's own top comment proposes): a leaked handle predicts a large
POST-step gap, which the real data does not show. This module states the
three-way split so a future recurrence can be classified the same way
without hand-computing timestamps from a raw `gh api` read every time --
it does not itself decide which theory is right, and does not read pytest's
own `test-durations:` line out of the job log (a heavier, log-search
operation `gh-job:N:grep` already covers) -- a caller wanting that
cross-check still reads the log separately and compares by hand.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations. Same
``_gh``-through-injectable-``run`` shape as `release_ci_wait.py` and
`pr_green.py` -- a standalone script called via `subprocess`, not through
the Bash tool the raw-command guard hooks, so it can be polled or compared
from inside one call.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ci_job_step_timing as cjst  # noqa: E402


def _run_once(returncode, stdout, stderr=""):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd, returncode, stdout=stdout, stderr=stderr
        )

    run.calls = calls
    return run


def _job_payload(
    job_started="2026-09-18T07:41:03Z",
    job_completed="2026-09-18T08:11:13Z",
    steps=None,
):
    if steps is None:
        steps = [
            {
                "name": "Set up job",
                "started_at": "2026-09-18T07:41:04Z",
                "completed_at": "2026-09-18T07:41:05Z",
                "conclusion": "success",
            },
            {
                "name": "Run tests",
                "started_at": "2026-09-18T07:41:31Z",
                "completed_at": "2026-09-18T08:11:08Z",
                "conclusion": "cancelled",
            },
            {
                "name": "Complete job",
                "started_at": "2026-09-18T08:11:11Z",
                "completed_at": "2026-09-18T08:11:11Z",
                "conclusion": "success",
            },
        ]
    return {
        "started_at": job_started,
        "completed_at": job_completed,
        "conclusion": "cancelled",
        "steps": steps,
    }


# --------------------------------------------------------- read_job_timing: ok


def test_ok_splits_pre_step_test_step_and_post_step_seconds():
    run = _run_once(0, json.dumps(_job_payload()))
    entry = cjst.read_job_timing(
        "105522023801", "gh", run, repo="Digital-Process-Tools/claude-oss"
    )
    assert entry["state"] == cjst.STATE_OK
    # job start 07:41:03 -> "Run tests" start 07:41:31 = 28s
    assert entry["pre_step_seconds"] == pytest.approx(28.0)
    # "Run tests" 07:41:31 -> 08:11:08 = 1777s
    assert entry["step_seconds"] == pytest.approx(1777.0)
    # "Run tests" end 08:11:08 -> job end 08:11:13 = 5s
    assert entry["post_step_seconds"] == pytest.approx(5.0)
    assert entry["total_seconds"] == pytest.approx(1810.0)
    assert entry["step_conclusion"] == "cancelled"
    assert entry["step_seconds_approximate"] is False


def test_real_green_job_shape_has_a_short_test_step():
    """The comparison job from #1673's own recon -- same leg, same day,
    green -- so this is not a synthetic-only fixture: the SHAPE (pre-step
    short, `Run tests` short, post-step short) is what a healthy run looks
    like against this module's own split."""
    payload = _job_payload(
        job_started="2026-09-18T07:32:55Z",
        job_completed="2026-09-18T07:39:14Z",
        steps=[
            {
                "name": "Set up job",
                "started_at": "2026-09-18T07:32:56Z",
                "completed_at": "2026-09-18T07:32:57Z",
                "conclusion": "success",
            },
            {
                "name": "Run tests",
                "started_at": "2026-09-18T07:33:26Z",
                "completed_at": "2026-09-18T07:39:09Z",
                "conclusion": "success",
            },
            {
                "name": "Complete job",
                "started_at": "2026-09-18T07:39:12Z",
                "completed_at": "2026-09-18T07:39:12Z",
                "conclusion": "success",
            },
        ],
    )
    run = _run_once(0, json.dumps(payload))
    entry = cjst.read_job_timing(
        "105519970619", "gh", run, repo="Digital-Process-Tools/claude-oss"
    )
    assert entry["state"] == cjst.STATE_OK
    assert entry["step_seconds"] == pytest.approx(343.0)
    assert entry["step_seconds"] < 400
    assert entry["pre_step_seconds"] < 60
    assert entry["post_step_seconds"] < 60


def test_custom_test_step_name_is_used_verbatim():
    payload = _job_payload(
        steps=[
            {
                "name": "shellcheck",
                "started_at": "2026-09-18T07:41:04Z",
                "completed_at": "2026-09-18T07:41:20Z",
                "conclusion": "success",
            }
        ]
    )
    run = _run_once(0, json.dumps(payload))
    entry = cjst.read_job_timing(
        "1", "gh", run, repo="o/r", test_step_name="shellcheck"
    )
    assert entry["state"] == cjst.STATE_OK
    assert entry["test_step_name"] == "shellcheck"


# ------------------------------------------------- read_job_timing: not-approx vs approx


def test_step_with_no_completed_at_is_approximated_and_flagged():
    """A step that was still `in_progress` when GitHub recorded the job's
    own completion (observed shape: a runner killed mid-step sometimes
    leaves the step's own completed_at null) must not silently render as
    step_seconds=0 -- that would read as "the step finished instantly",
    the exact absence-as-signal mistake CLAUDE.md warns against. Approximate
    using the job's own end and say so."""
    payload = _job_payload(
        steps=[
            {
                "name": "Run tests",
                "started_at": "2026-09-18T07:41:31Z",
                "completed_at": None,
                "conclusion": None,
                "status": "in_progress",
            }
        ]
    )
    run = _run_once(0, json.dumps(payload))
    entry = cjst.read_job_timing("1", "gh", run, repo="o/r")
    assert entry["state"] == cjst.STATE_OK
    assert entry["step_seconds_approximate"] is True
    # 07:41:31 -> the job's own completed_at, 08:11:13 (this payload's default) = 1782s
    assert entry["step_seconds"] == pytest.approx(1782.0)


# ---------------------------------------------------- read_job_timing: no-matching-step


def test_no_matching_step_is_its_own_state_not_could_not_read():
    """A job that was genuinely read but carries no step by this name (a
    workflow rename, or the wrong --test-step-name) is a finding about the
    NAME, not a read failure -- folding it into could-not-read would hide a
    successful read behind the same label a broken `gh` call gets."""
    run = _run_once(0, json.dumps(_job_payload(steps=[])))
    entry = cjst.read_job_timing("1", "gh", run, repo="o/r", test_step_name="Run tests")
    assert entry["state"] == cjst.STATE_NO_MATCHING_STEP
    assert entry["state"] != cjst.STATE_COULD_NOT_READ


# -------------------------------------------------------- read_job_timing: could-not-read


def test_gh_failure_is_could_not_read_not_silently_empty():
    run = _run_once(1, "", "HTTP 404: Not Found")
    entry = cjst.read_job_timing("999999", "gh", run, repo="o/r")
    assert entry["state"] == cjst.STATE_COULD_NOT_READ
    assert "404" in entry["detail"]


# ------------------------------------------------------- read_job_timing: ambiguous-step


def test_two_steps_with_the_same_name_is_its_own_state_not_a_silent_first_match():
    """Self-review (#1673): taking the FIRST of two same-named steps would
    silently fold the SECOND one's own duration into `post_step_seconds`
    -- exactly the shape this module exists to tell apart from a real
    teardown gap. A composite action reused twice, or a workflow that
    reruns a step under the same name, is a real GitHub Actions shape,
    not a hypothetical."""
    payload = _job_payload(
        steps=[
            {
                "name": "Run tests",
                "started_at": "2026-09-18T07:41:31Z",
                "completed_at": "2026-09-18T07:50:00Z",
                "conclusion": "success",
            },
            {
                "name": "Run tests",
                "started_at": "2026-09-18T07:50:05Z",
                "completed_at": "2026-09-18T08:11:08Z",
                "conclusion": "cancelled",
            },
        ]
    )
    run = _run_once(0, json.dumps(payload))
    entry = cjst.read_job_timing("1", "gh", run, repo="o/r")
    assert entry["state"] == cjst.STATE_AMBIGUOUS_STEP
    assert entry["state"] != cjst.STATE_OK
    assert entry["step_count"] == 2


def test_unparseable_json_is_could_not_read():
    run = _run_once(0, "not json at all")
    entry = cjst.read_job_timing("1", "gh", run, repo="o/r")
    assert entry["state"] == cjst.STATE_COULD_NOT_READ


def test_missing_job_timestamps_is_could_not_read():
    payload = _job_payload()
    del payload["completed_at"]
    run = _run_once(0, json.dumps(payload))
    entry = cjst.read_job_timing("1", "gh", run, repo="o/r")
    assert entry["state"] == cjst.STATE_COULD_NOT_READ


def test_non_dict_payload_is_could_not_read():
    run = _run_once(0, json.dumps([1, 2, 3]))
    entry = cjst.read_job_timing("1", "gh", run, repo="o/r")
    assert entry["state"] == cjst.STATE_COULD_NOT_READ


# ------------------------------------------------------------------- main() CLI


def test_main_ok_prints_breakdown_and_exits_zero(capsys):
    run = _run_once(0, json.dumps(_job_payload()))
    code = cjst.main(
        ["--job", "105522023801", "--repo", "Digital-Process-Tools/claude-oss"],
        run=run,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "OK" in out
    assert "pre-step: 28.0s" in out
    assert "step (Run tests): 1777.0s" in out
    assert "post-step: 5.0s" in out


def test_main_could_not_read_is_nonzero_exit(capsys):
    """Self-review (#1673): assert the EXACT documented code (3), not
    merely nonzero -- a bare `!= 0` would still pass if this ever
    regressed to collide with argparse's own reserved usage-error code
    (2), which is precisely the collision the module's own comment next
    to `EXIT_CODES` says must never happen."""
    run = _run_once(1, "", "boom")
    code = cjst.main(["--job", "1", "--repo", "o/r"], run=run)
    out = capsys.readouterr().out
    assert code == 3
    assert code == cjst.EXIT_CODES[cjst.STATE_COULD_NOT_READ]
    assert "COULD-NOT-READ" in out


def test_main_usage_error_exits_2_never_colliding_with_a_state(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cjst.main(["--job", "1"], run=_run_once(0, "{}"))  # missing --repo
    assert excinfo.value.code == 2
    assert 2 not in cjst.EXIT_CODES.values()


def test_main_baseline_read_failure_is_folded_into_the_exit_code(capsys):
    """Self-review (#1673): a caller that scripts off `main()`'s return
    code alone must see a failed baseline read too -- before this fix,
    a failing --baseline-job left the exit code identical to a run where
    no baseline was requested at all (exit 0 from a healthy primary
    read), with the failure visible only in stdout text nobody checking
    the exit code would read."""
    responses = [(0, json.dumps(_job_payload()), ""), (1, "", "boom")]
    it = iter(responses)

    def run(cmd, **kwargs):
        rc, out, err = next(it)
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    code = cjst.main(["--job", "1", "--baseline-job", "2", "--repo", "o/r"], run=run)
    assert code == cjst.EXIT_CODES[cjst.STATE_COULD_NOT_READ]
    assert code != 0


def test_main_baseline_job_prints_a_ratio(capsys):
    """--baseline-job (e.g. a known-green run of the same leg) renders
    both breakdowns plus the step-duration ratio -- the exact comparison
    #1673's own recon had to do by hand across two separate `gh api`
    reads."""
    green_payload = _job_payload(
        job_started="2026-09-18T07:32:55Z",
        job_completed="2026-09-18T07:39:14Z",
        steps=[
            {
                "name": "Run tests",
                "started_at": "2026-09-18T07:33:26Z",
                "completed_at": "2026-09-18T07:39:09Z",
                "conclusion": "success",
            }
        ],
    )
    calls = {"n": 0}
    responses = [json.dumps(_job_payload()), json.dumps(green_payload)]

    def run(cmd, **kwargs):
        out = responses[calls["n"]]
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    code = cjst.main(
        [
            "--job",
            "105522023801",
            "--baseline-job",
            "105519970619",
            "--repo",
            "Digital-Process-Tools/claude-oss",
        ],
        run=run,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "ratio" in out.lower()
