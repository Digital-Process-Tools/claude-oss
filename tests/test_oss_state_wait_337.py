"""A recorded wait is a claim a later tick can test, not prose it must trust (#337).

Measured on 2026-08-16 and quoted from the session buffer: at 01:15Z the loop recorded
itself as "blocked on audit completion". The audit it named had returned at 23:25Z and
its four output issues were filed by 23:30Z -- so the loop was blocked on a condition
that had cleared an hour and fifty minutes earlier, and nothing re-read it. Three hours
ten minutes passed with a green default branch, an empty pull request board and four
unstarted issues.

The mechanism: a wait recorded as prose names no dispatch, no observable and no time, so
no later turn can test it, and a wait that cannot be tested is indistinguishable from one
that is still true.

`oss_state.wait` records the claim in a form a later tick can re-derive; `check_wait`
re-derives it. The check has three states for the same reason `intake` and
`cohort_freeze` do: a wait that still holds and a wait nobody could evaluate must not
render alike, or the second reads as the first forever. Every "must not read as cleared"
case below is paired with a "must read as cleared" case in the same fixture -- the
positive control this file's own docstring above demands of every negative assertion in
this repo.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


DISPATCH = "gate 3 audit dispatched at 23:12Z"
OBSERVABLE = "four output issues filed on the tracker"
RECORDED_AT = "2026-08-16T23:12:00Z"


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# --------------------------------------------------------------- library: wait()


def test_wait_records_dispatch_observable_and_starts_holding():
    record = oss_state.wait(DISPATCH, OBSERVABLE, RECORDED_AT)
    assert record["dispatch"] == DISPATCH
    assert record["observable"] == OBSERVABLE
    assert record["recorded_at"] == RECORDED_AT
    assert record["state"] == oss_state.WAIT_HOLDS


def test_wait_refuses_an_empty_dispatch():
    with pytest.raises(oss_state.StateError):
        oss_state.wait("", OBSERVABLE, RECORDED_AT)


def test_wait_refuses_an_empty_observable():
    with pytest.raises(oss_state.StateError):
        oss_state.wait(DISPATCH, "", RECORDED_AT)


def test_wait_refuses_no_timestamp():
    with pytest.raises(oss_state.StateError):
        oss_state.wait(DISPATCH, OBSERVABLE, "")


# ------------------------------------------------------ library: check_wait(), 3 states


def _recorded():
    return oss_state.wait(DISPATCH, OBSERVABLE, RECORDED_AT)


def test_check_wait_still_holds_carries_the_original_claim():
    """The positive control for the cleared/could-not-evaluate cases below: the
    still-holds outcome must not silently report the wait as settled.
    """
    record = oss_state.check_wait(_recorded(), oss_state.WAIT_HOLDS)
    assert record["state"] == oss_state.WAIT_HOLDS
    assert record["dispatch"] == DISPATCH
    assert record["observable"] == OBSERVABLE
    assert "cleared_by" not in record
    assert "why" not in record


def test_check_wait_cleared_names_what_cleared_it():
    record = oss_state.check_wait(
        _recorded(), oss_state.WAIT_CLEARED, cleared_by="four issues filed at 23:30Z"
    )
    assert record["state"] == oss_state.WAIT_CLEARED
    assert record["cleared_by"] == "four issues filed at 23:30Z"
    assert record["dispatch"] == DISPATCH


def test_check_wait_cleared_requires_cleared_by():
    with pytest.raises(oss_state.StateError):
        oss_state.check_wait(_recorded(), oss_state.WAIT_CLEARED)


def test_check_wait_could_not_evaluate_carries_why():
    record = oss_state.check_wait(
        _recorded(), oss_state.WAIT_COULD_NOT_EVALUATE, why="the tracker was unreachable"
    )
    assert record["state"] == oss_state.WAIT_COULD_NOT_EVALUATE
    assert record["why"] == "the tracker was unreachable"
    # Must not be readable as either of the other two states.
    assert record["state"] != oss_state.WAIT_HOLDS
    assert record["state"] != oss_state.WAIT_CLEARED


def test_check_wait_could_not_evaluate_requires_why():
    with pytest.raises(oss_state.StateError):
        oss_state.check_wait(_recorded(), oss_state.WAIT_COULD_NOT_EVALUATE)


def test_check_wait_refuses_an_unrecognised_state():
    with pytest.raises(oss_state.StateError):
        oss_state.check_wait(_recorded(), "settled")


def test_check_wait_refuses_a_record_missing_dispatch_or_observable():
    with pytest.raises(oss_state.StateError):
        oss_state.check_wait({"observable": OBSERVABLE}, oss_state.WAIT_HOLDS)
    with pytest.raises(oss_state.StateError):
        oss_state.check_wait({"dispatch": DISPATCH}, oss_state.WAIT_HOLDS)


# --------------------------------------------------------------------- wait_line()


def test_wait_line_names_cleared_by_and_the_still_holds_line_never_does():
    cleared = oss_state.check_wait(
        _recorded(), oss_state.WAIT_CLEARED, cleared_by="issues filed at 23:30Z"
    )
    held = oss_state.check_wait(_recorded(), oss_state.WAIT_HOLDS)
    assert "issues filed at 23:30Z" in oss_state.wait_line(cleared)
    assert "issues filed at 23:30Z" not in oss_state.wait_line(held)


def test_wait_line_could_not_evaluate_names_why():
    record = oss_state.check_wait(
        _recorded(), oss_state.WAIT_COULD_NOT_EVALUATE, why="tracker unreachable"
    )
    assert "tracker unreachable" in oss_state.wait_line(record)


# --------------------------------------------------------------- CLI: recording a wait


def test_cli_records_a_fresh_wait_under_detail(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision", "blocked on gate 3 audit",
            "--at", RECORDED_AT,
            "--wait-dispatch", DISPATCH,
            "--wait-observable", OBSERVABLE,
        ]
    )
    assert result.returncode == 0, result.stdout
    entry = oss_state.last(str(path))
    assert entry["detail"]["wait"]["state"] == oss_state.WAIT_HOLDS
    assert entry["detail"]["wait"]["dispatch"] == DISPATCH


def test_cli_refuses_wait_dispatch_without_observable(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision", "blocked",
            "--at", RECORDED_AT,
            "--wait-dispatch", DISPATCH,
        ]
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout
    assert oss_state.read(str(path)) == []


# ---------------------------------------------------------------- CLI: checking a wait


def test_cli_check_wait_cleared_reads_the_previous_entrys_wait(tmp_path):
    path = tmp_path / "state.json"
    first = _piped(
        [
            str(path),
            "--decision", "blocked on gate 3 audit",
            "--at", RECORDED_AT,
            "--wait-dispatch", DISPATCH,
            "--wait-observable", OBSERVABLE,
        ]
    )
    assert first.returncode == 0, first.stdout
    result = _piped(
        [
            str(path),
            "--decision", "wait cleared, resuming",
            "--at", "2026-08-17T01:15:00Z",
            "--check-wait", "cleared",
            "--wait-cleared-by", "four issues filed at 23:30Z",
        ]
    )
    assert result.returncode == 0, result.stdout
    entry = oss_state.last(str(path))
    assert entry["detail"]["wait"]["state"] == oss_state.WAIT_CLEARED
    assert entry["detail"]["wait"]["cleared_by"] == "four issues filed at 23:30Z"
    assert entry["detail"]["wait"]["dispatch"] == DISPATCH


def test_cli_check_wait_could_not_evaluate_is_not_rendered_as_cleared(tmp_path):
    """Positive control for the case above: the same wait, checked and found
    unevaluable, must land as `could-not-evaluate`, never as `cleared` or `holds`.
    """
    path = tmp_path / "state.json"
    _piped(
        [
            str(path),
            "--decision", "blocked on gate 3 audit",
            "--at", RECORDED_AT,
            "--wait-dispatch", DISPATCH,
            "--wait-observable", OBSERVABLE,
        ]
    )
    result = _piped(
        [
            str(path),
            "--decision", "could not re-check the tracker",
            "--at", "2026-08-17T01:15:00Z",
            "--check-wait", "could-not-evaluate",
            "--wait-why", "the tracker was unreachable",
        ]
    )
    assert result.returncode == 0, result.stdout
    entry = oss_state.last(str(path))
    assert entry["detail"]["wait"]["state"] == oss_state.WAIT_COULD_NOT_EVALUATE
    assert entry["detail"]["wait"]["why"] == "the tracker was unreachable"
    assert entry["detail"]["wait"]["state"] != oss_state.WAIT_CLEARED
    assert entry["detail"]["wait"]["state"] != oss_state.WAIT_HOLDS


def test_cli_check_wait_refuses_when_nothing_is_pending(tmp_path):
    path = tmp_path / "state.json"
    _piped(
        [
            str(path),
            "--decision", "first tick, nothing pending",
            "--at", "2026-08-16T00:00:00Z",
        ]
    )
    result = _piped(
        [
            str(path),
            "--decision", "second tick",
            "--at", "2026-08-16T01:00:00Z",
            "--check-wait", "cleared",
            "--wait-cleared-by", "nothing to clear",
        ]
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout


# --------------------------------------------------------------- CLI: --pending-wait


def test_cli_pending_wait_prints_the_holding_record(tmp_path):
    path = tmp_path / "state.json"
    _piped(
        [
            str(path),
            "--decision", "blocked on gate 3 audit",
            "--at", RECORDED_AT,
            "--wait-dispatch", DISPATCH,
            "--wait-observable", OBSERVABLE,
        ]
    )
    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    assert DISPATCH in result.stdout
    assert oss_state.WAIT_HOLDS in result.stdout


def test_cli_pending_wait_reports_none_once_cleared(tmp_path):
    """Positive control for the case above: once cleared, `--pending-wait` must not
    keep reporting the wait as pending.
    """
    path = tmp_path / "state.json"
    _piped(
        [
            str(path),
            "--decision", "blocked", "--at", RECORDED_AT,
            "--wait-dispatch", DISPATCH,
            "--wait-observable", OBSERVABLE,
        ]
    )
    _piped(
        [
            str(path),
            "--decision", "cleared", "--at", "2026-08-17T01:15:00Z",
            "--check-wait", "cleared", "--wait-cleared-by", "issues filed",
        ]
    )
    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    assert "no pending wait" in result.stdout.lower()


def test_cli_pending_wait_on_a_first_tick_reports_none(tmp_path):
    path = tmp_path / "state.json"
    _piped([str(path), "--decision", "first tick", "--at", "2026-08-16T00:00:00Z"])
    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    assert "no pending wait" in result.stdout.lower()
