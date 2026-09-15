"""#1492: `pr_green.py --wait` polled at a fixed 45s cadence with zero
rate-limit awareness, sharing GitHub's 5000/h REST budget with watchers,
ticks and log reads that poll on no schedule at all. One overnight
`/oss:run` session exhausted the budget three times.

`_read_core_rate_limit` reads `gh api rate_limit`'s `resources.core` once
per poll -- GitHub documents that reading the limit does not itself count
against it, so this is free to call every iteration rather than only after
a poll has already failed (reacting only once already throttled is too
late: the budget is shared, so another process can drain it between our
own polls). `_rate_limit_backoff` is a step function, not a continuous
scale -- easier to test and reason about, and the issue names no existing
threshold to match: below 25% remaining doubles the interval, below 10%
quadruples it, a failed read leaves the interval unchanged (guessing under
uncertainty is exactly the absence-as-signal mistake CLAUDE.md warns
against).

Per CLAUDE.md's own negative-assertion rule: the existing fixed-cadence
case (`sleeps == [45, 45]`) is the positive control proving a *healthy*
budget produces no backoff at all, paired here with the "must fire" case
proving a low budget does.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pr_green  # noqa: E402


def _run_sequence(responses):
    calls = []
    it = iter(responses)

    def run(cmd, **kwargs):
        calls.append(cmd)
        try:
            rc, out, err = next(it)
        except StopIteration:  # pragma: no cover - a fixture bug
            raise AssertionError(
                "more gh calls than the fixture staged: {0}".format(cmd)
            )
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    run.calls = calls
    return run


def _row(name, context, status="COMPLETED", conclusion="SUCCESS"):
    return {
        "__typename": "CheckRun",
        "name": name,
        "workflowName": context,
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": "",
    }


def _rollup_json(number, branch, sha, rows):
    return json.dumps(
        {
            "number": number,
            "headRefName": branch,
            "headRefOid": sha,
            "state": "OPEN",
            "statusCheckRollup": rows,
        }
    )


# --------------------------------------------------------------- _read_core_rate_limit


def test_read_core_rate_limit_parses_the_core_resource():
    run = _run_sequence(
        [(0, json.dumps({"resources": {"core": {"remaining": 42, "limit": 5000}}}), "")]
    )
    remaining, limit = pr_green._read_core_rate_limit("gh", run)
    assert (remaining, limit) == (42, 5000)


def test_read_core_rate_limit_is_none_none_on_gh_failure():
    run = _run_sequence([(1, "", "gh: not authenticated")])
    remaining, limit = pr_green._read_core_rate_limit("gh", run)
    assert (remaining, limit) == (None, None)


def test_read_core_rate_limit_is_none_none_on_unparseable_body():
    run = _run_sequence([(0, "not json", "")])
    remaining, limit = pr_green._read_core_rate_limit("gh", run)
    assert (remaining, limit) == (None, None)


# --------------------------------------------------------------- _rate_limit_backoff


def test_rate_limit_backoff_is_unchanged_above_the_first_threshold():
    assert pr_green._rate_limit_backoff(45, 4000, 5000) == 45


def test_rate_limit_backoff_doubles_under_25_percent():
    assert pr_green._rate_limit_backoff(45, 1000, 5000) == 90


def test_rate_limit_backoff_quadruples_under_10_percent():
    assert pr_green._rate_limit_backoff(45, 100, 5000) == 180


def test_rate_limit_backoff_is_unchanged_when_the_read_failed():
    """Must-fire pair for the "must not fold" rule: a failed read is not a
    low-budget signal, and must not be read as one."""
    assert pr_green._rate_limit_backoff(45, None, None) == 45


# --------------------------------------------------------------- wait_for_first_actionable backoff


def test_wait_keeps_the_fixed_cadence_when_the_budget_is_healthy():
    """Positive control: a rate_limit_reader that reports a healthy budget
    produces the identical cadence as no reader at all."""
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    green_rows = [_row("tests", "tests")]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", green_rows), ""),
        ]
    )
    sleeps = []
    entry = pr_green.wait_for_first_actionable(
        [1],
        "gh",
        run,
        workflows_dir=None,
        interval=45,
        sleep=sleeps.append,
        rate_limit_reader=lambda: (5000, 5000),
    )
    assert entry["state"] == pr_green.STATE_GREEN
    assert sleeps == [45, 45]


def test_wait_backs_off_when_the_budget_is_low():
    """Must-fire case: a rate_limit_reader reporting a low budget widens
    every sleep, not just the cadence's own healthy path."""
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    green_rows = [_row("tests", "tests")]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", green_rows), ""),
        ]
    )
    sleeps = []
    entry = pr_green.wait_for_first_actionable(
        [1],
        "gh",
        run,
        workflows_dir=None,
        interval=45,
        sleep=sleeps.append,
        rate_limit_reader=lambda: (100, 5000),
    )
    assert entry["state"] == pr_green.STATE_GREEN
    assert sleeps == [180, 180]


def test_wait_bounds_backoff_overshoot_near_the_deadline_when_timeout_is_set():
    """#1554, correcting #1492's own first cut: a backed-off interval must
    never widen how far a `--timeout` caller can be kept waiting past the
    deadline it asked for -- but it must not be discarded outright either.
    10s left of a 20s timeout, base interval 45: a 4x backoff (180) is
    clamped to `(timeout - elapsed) + interval` = 10 + 45 = 55, never to the
    bare `interval` #1492's original fix collapsed it to."""
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
        ]
    )
    clock = iter([0.0, 10.0, 999.0])
    sleeps = []
    entry = pr_green.wait_for_first_actionable(
        [1],
        "gh",
        run,
        workflows_dir=None,
        interval=45,
        timeout=20,
        sleep=sleeps.append,
        clock=lambda: next(clock),
        rate_limit_reader=lambda: (100, 5000),  # 2% remaining -- would be 4x uncapped
    )
    assert entry is None
    assert sleeps == [55]


def test_wait_backoff_still_widens_early_in_a_long_timeout_window():
    """MUST-FIRE control for the test above: with plenty of time left before
    the deadline, the overshoot ceiling must not clamp anything -- a
    `--timeout` caller early in a long wait still gets the full backoff,
    the exact behaviour #1492's original fix accidentally suppressed on
    every `--wait --timeout N` call regardless of how much time was left
    (#1554)."""
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    green_rows = [_row("tests", "tests")]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", green_rows), ""),
        ]
    )
    clock = iter([0.0, 1.0, 2.0])
    sleeps = []
    entry = pr_green.wait_for_first_actionable(
        [1],
        "gh",
        run,
        workflows_dir=None,
        interval=45,
        timeout=3600,
        sleep=sleeps.append,
        clock=lambda: next(clock),
        rate_limit_reader=lambda: (100, 5000),  # 2% remaining
    )
    assert entry["state"] == pr_green.STATE_GREEN
    assert sleeps == [180, 180]


def test_cli_wait_warns_once_to_stderr_when_the_rate_limit_read_fails(
    monkeypatch, capsys
):
    """Self-review finding (auditor): a failed rate-limit read and a healthy
    budget both leave the poll cadence unchanged, so without this note an
    operator has no way to tell them apart from a --wait run's own output."""
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    green_rows = [_row("tests", "tests")]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (1, "", "gh: not authenticated"),  # the rate_limit read itself
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (1, "", "gh: not authenticated"),
            (0, _rollup_json(1, "fix/1", "a", green_rows), ""),
        ]
    )
    monkeypatch.setattr(
        pr_green.gh_which, "safe_which", lambda name, path=None: "/usr/bin/gh"
    )
    # #1492: `main()` never overrides `wait_for_first_actionable`'s `sleep`
    # default -- that default is bound to `time.sleep` at function-definition
    # time, so patching the `time` module's own attribute afterwards would
    # not reach it. `--interval 0` keeps the test from actually sleeping.
    rc = pr_green.main(["1", "--wait", "--interval", "0"], run=run)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err.count("could not read GitHub's rate limit") == 1


def test_wait_with_no_rate_limit_reader_is_unaffected():
    """Backward-compatible default: omitting rate_limit_reader entirely
    keeps the original fixed cadence, unconditionally."""
    pending_rows = [_row("tests", "tests", status="IN_PROGRESS", conclusion=None)]
    green_rows = [_row("tests", "tests")]
    run = _run_sequence(
        [
            (0, _rollup_json(1, "fix/1", "a", pending_rows), ""),
            (0, _rollup_json(1, "fix/1", "a", green_rows), ""),
        ]
    )
    sleeps = []
    entry = pr_green.wait_for_first_actionable(
        [1], "gh", run, workflows_dir=None, interval=45, sleep=sleeps.append
    )
    assert entry["state"] == pr_green.STATE_GREEN
    assert sleeps == [45]
