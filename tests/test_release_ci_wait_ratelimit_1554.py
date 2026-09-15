"""#1554: `release_ci_wait.py` had zero GitHub REST rate-limit awareness,
even though its own docstring claims to keep `pr_green.py`'s own
`wait_for_first_actionable` contract -- the earlier fix (#1492) only reached
half of the mirror. This module ports the identical
`_read_core_rate_limit`/`_rate_limit_backoff` shape and wires it into
`wait_for_conclusion`, the releaser's own gate-3 wait, sharing the same
5000/h budget as watchers, ticks and log reads.

Per CLAUDE.md's own negative-assertion rule: the existing fixed-cadence case
(a healthy-budget reader producing no backoff) is the positive control
pairing every "must back off" case with a "must not" one, the same pairing
`tests/test_pr_green_ratelimit_1492.py` already uses for the sibling script.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_ci_wait as rcw  # noqa: E402

SHA = "a" * 40


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


def _row(name="tests", status="completed", conclusion="success"):
    return {
        "workflowName": name,
        "status": status,
        "conclusion": conclusion,
        "headSha": SHA,
        "url": "",
        "event": None,
    }


def _runs_json(rows):
    return json.dumps(rows)


# --------------------------------------------------------------- _read_core_rate_limit


def test_read_core_rate_limit_parses_the_core_resource():
    run = _run_sequence(
        [(0, json.dumps({"resources": {"core": {"remaining": 42, "limit": 5000}}}), "")]
    )
    remaining, limit = rcw._read_core_rate_limit("gh", run)
    assert (remaining, limit) == (42, 5000)


def test_read_core_rate_limit_is_none_none_on_gh_failure():
    run = _run_sequence([(1, "", "gh: not authenticated")])
    remaining, limit = rcw._read_core_rate_limit("gh", run)
    assert (remaining, limit) == (None, None)


def test_read_core_rate_limit_is_none_none_on_unparseable_body():
    run = _run_sequence([(0, "not json", "")])
    remaining, limit = rcw._read_core_rate_limit("gh", run)
    assert (remaining, limit) == (None, None)


# --------------------------------------------------------------- _rate_limit_backoff


def test_rate_limit_backoff_is_unchanged_above_the_first_threshold():
    assert rcw._rate_limit_backoff(45, 4000, 5000) == 45


def test_rate_limit_backoff_doubles_under_25_percent():
    assert rcw._rate_limit_backoff(45, 1000, 5000) == 90


def test_rate_limit_backoff_quadruples_under_10_percent():
    assert rcw._rate_limit_backoff(45, 100, 5000) == 180


def test_rate_limit_backoff_is_unchanged_when_the_read_failed():
    """Must-fire pair for the "must not fold" rule: a failed read is not a
    low-budget signal, and must not be read as one."""
    assert rcw._rate_limit_backoff(45, None, None) == 45


# --------------------------------------------------------------- wait_for_conclusion backoff


def test_wait_keeps_the_fixed_cadence_when_the_budget_is_healthy():
    """Positive control: a rate_limit_reader that reports a healthy budget
    produces the identical cadence as no reader at all -- must-not-fire half
    of the pair below."""
    responses = [
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row()]), ""),
    ]
    run = _run_sequence(responses)
    sleeps = []
    entry = rcw.wait_for_conclusion(
        SHA,
        "gh",
        run,
        interval=45,
        sleep=sleeps.append,
        rate_limit_reader=lambda: (5000, 5000),
    )
    assert entry["state"] == rcw.STATE_GREEN
    assert sleeps == [45, 45]


def test_wait_backs_off_when_the_budget_is_low():
    """MUST-FIRE: a rate_limit_reader reporting a low budget widens every
    sleep, not just the fixed cadence's own healthy path -- the gap #1554
    found this module had entirely, unlike `pr_green.py`."""
    responses = [
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row()]), ""),
    ]
    run = _run_sequence(responses)
    sleeps = []
    entry = rcw.wait_for_conclusion(
        SHA,
        "gh",
        run,
        interval=45,
        sleep=sleeps.append,
        rate_limit_reader=lambda: (100, 5000),
    )
    assert entry["state"] == rcw.STATE_GREEN
    assert sleeps == [180, 180]


def test_wait_bounds_backoff_overshoot_near_the_deadline_when_timeout_is_set():
    """A backed-off interval must never widen how far a `--timeout` caller
    can be kept waiting past the deadline it asked for -- the same #1554
    fix `pr_green.py`'s own `wait_for_first_actionable` carries, ported
    here rather than reproducing the collapsed (#1492) version this module
    never had at all."""
    responses = [
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
    ]
    run = _run_sequence(responses)
    clock = iter([0.0, 10.0, 999.0])
    sleeps = []
    entry = rcw.wait_for_conclusion(
        SHA,
        "gh",
        run,
        interval=45,
        timeout=20,
        sleep=sleeps.append,
        clock=lambda: next(clock),
        rate_limit_reader=lambda: (100, 5000),  # 2% remaining -- would be 4x uncapped
    )
    assert entry is None
    assert sleeps == [55]


def test_wait_with_no_rate_limit_reader_is_unaffected():
    """Backward-compatible default: omitting rate_limit_reader entirely
    keeps the original fixed cadence, unconditionally -- every existing
    caller of `wait_for_conclusion` (including
    `test_release_ci_wait_1266.py`'s own tests) is unaffected."""
    responses = [
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
        (0, _runs_json([_row()]), ""),
    ]
    run = _run_sequence(responses)
    sleeps = []
    entry = rcw.wait_for_conclusion(SHA, "gh", run, interval=45, sleep=sleeps.append)
    assert entry["state"] == rcw.STATE_GREEN
    assert sleeps == [45]


def test_cli_wait_warns_once_to_stderr_when_the_rate_limit_read_fails(
    monkeypatch, capsys
):
    """Self-review finding (mirrored from `pr_green.py`'s own #1492
    self-review): a failed rate-limit read and a healthy budget both leave
    the poll cadence unchanged, so without this note an operator has no way
    to tell them apart from a --wait run's own output."""
    responses = [
        (0, _runs_json([_row(status="in_progress", conclusion=None)]), ""),
        (1, "", "gh: not authenticated"),  # the rate_limit read itself
        (0, _runs_json([_row()]), ""),
    ]
    run = _run_sequence(responses)
    monkeypatch.setattr(
        rcw.gh_which, "safe_which", lambda name, path=None: "/usr/bin/gh"
    )
    rc = rcw.main(["--commit", SHA, "--wait", "--interval", "0"], run=run)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err.count("could not read GitHub's rate limit") == 1
