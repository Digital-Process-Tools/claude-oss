"""A recorded wait is dropped from view the moment any other entry lands after it
(#436).

`--pending-wait` and `--check-wait` (#337) both read `last(args.path)` and nothing
else. Once a tick appends any other entry -- a cohort freeze (#407), a lane record, a
plain intake -- the wait sits untouched on disk, still `holds`, and both readers report
exactly what they report when no wait was ever recorded: `no pending wait`. The two
absences are byte-identical, which is this repository's own defect class, found inside
the feature #337 wrote to close it.

Settled here as: a wait's lifetime is not one entry. Both readers scan back to the most
recent entry that carries a `detail.wait` record, skipping over entries that recorded
something else entirely. Every case below pairs the "must still see it" behaviour with
the positive control that a file which genuinely never recorded a wait keeps answering
`no pending wait` even after the same intervening entry -- without that control, a
reader that answered "wait pending" unconditionally would also pass.
"""

import subprocess
import sys
from pathlib import Path

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


def _record_wait(path):
    result = _piped(
        [
            str(path),
            "--decision",
            "blocked on gate 3 audit",
            "--at",
            RECORDED_AT,
            "--wait-dispatch",
            DISPATCH,
            "--wait-observable",
            OBSERVABLE,
        ]
    )
    assert result.returncode == 0, result.stdout


def _record_cohort_freeze(path):
    """The #407 shape from the issue: a cohort freeze landing after a wait, with no
    wait flag anywhere on the call -- the ordinary way a wait goes unreachable.
    """
    result = _piped(
        [
            str(path),
            "--decision",
            "froze cohort-6 at 12",
            "--at",
            "2026-08-16T23:45:00Z",
            "--cohort",
            "cohort-6",
            "--cohort-count",
            "filtered_query=12",
            "--cohort-count",
            "per_issue_read=12",
        ]
    )
    assert result.returncode == 0, result.stdout


# --------------------------------------------- CLI: --pending-wait across an entry gap


def test_pending_wait_survives_an_unrelated_entry_landing_after_it(tmp_path):
    path = tmp_path / "state.json"
    _record_wait(path)
    _record_cohort_freeze(path)

    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    assert DISPATCH in result.stdout
    assert oss_state.WAIT_HOLDS in result.stdout
    assert "no pending wait" not in result.stdout.lower()


def test_pending_wait_still_reports_none_when_none_was_ever_recorded(tmp_path):
    """Positive control for the case above, in the same fixture shape: a file that
    never recorded a wait must keep answering `no pending wait` even after the exact
    same kind of intervening entry -- otherwise a reader that always says "pending"
    would also pass the case above.
    """
    path = tmp_path / "state.json"
    _piped(
        [str(path), "--decision", "first tick, nothing pending", "--at", RECORDED_AT]
    )
    _record_cohort_freeze(path)

    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    assert "no pending wait" in result.stdout.lower()


def test_pending_wait_reports_none_once_cleared_even_behind_an_unrelated_entry(
    tmp_path,
):
    """A cleared wait must not resurface as pending just because the scan now looks
    past the entry that cleared it -- the clearing entry itself carries the record, so
    it is what the scan finds first.
    """
    path = tmp_path / "state.json"
    _record_wait(path)
    _piped(
        [
            str(path),
            "--decision",
            "cleared",
            "--at",
            "2026-08-17T01:15:00Z",
            "--check-wait",
            "cleared",
            "--wait-cleared-by",
            "issues filed",
        ]
    )
    _record_cohort_freeze(path)

    result = _piped([str(path), "--pending-wait"])
    assert result.returncode == 0, result.stdout
    assert "no pending wait" in result.stdout.lower()


# ----------------------------------------------- CLI: --check-wait across an entry gap


def test_check_wait_finds_a_holding_wait_behind_an_unrelated_entry(tmp_path):
    path = tmp_path / "state.json"
    _record_wait(path)
    _record_cohort_freeze(path)

    result = _piped(
        [
            str(path),
            "--decision",
            "wait cleared, resuming",
            "--at",
            "2026-08-17T01:15:00Z",
            "--check-wait",
            "cleared",
            "--wait-cleared-by",
            "four issues filed at 23:30Z",
        ]
    )
    assert result.returncode == 0, result.stdout
    entry = oss_state.last(str(path))
    assert entry["detail"]["wait"]["state"] == oss_state.WAIT_CLEARED
    assert entry["detail"]["wait"]["dispatch"] == DISPATCH


def test_check_wait_still_refuses_when_none_was_ever_recorded_behind_an_unrelated_entry(
    tmp_path,
):
    """Positive control for the case above: an unrelated entry must not manufacture a
    wait to re-derive where none was ever recorded.
    """
    path = tmp_path / "state.json"
    _piped(
        [str(path), "--decision", "first tick, nothing pending", "--at", RECORDED_AT]
    )
    _record_cohort_freeze(path)

    result = _piped(
        [
            str(path),
            "--decision",
            "second tick",
            "--at",
            "2026-08-17T01:15:00Z",
            "--check-wait",
            "cleared",
            "--wait-cleared-by",
            "nothing to clear",
        ]
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout


# ------------------------------------------- an explicit null does not read as absent


def test_pending_wait_refuses_a_hand_authored_null_wait_rather_than_reporting_none(
    tmp_path,
):
    """Found by audit: `_last_wait` distinguishes "no entry ever carried a `wait`
    key" from "the most recent one carrying it holds a `None`/malformed value" by
    returning the entry itself as the sentinel, not the record. Checking the record
    for `None` instead would fold a hand-authored `detail.wait: null` entry back
    into "never recorded" -- the exact absence this issue exists to close, one layer
    down from the entry-lifetime bug.
    """
    path = tmp_path / "state.json"
    _record_wait(path)
    oss_state.append(
        str(path),
        "2026-08-16T23:45:00Z",
        "a hand-authored entry with a null wait value",
        detail={"wait": None},
    )

    result = _piped([str(path), "--pending-wait"])
    assert result.returncode != 0
    assert "FAIL" in result.stdout
    assert "no pending wait" not in result.stdout.lower()


def test_check_wait_refuses_a_hand_authored_null_wait_rather_than_reporting_absent(
    tmp_path,
):
    path = tmp_path / "state.json"
    _record_wait(path)
    oss_state.append(
        str(path),
        "2026-08-16T23:45:00Z",
        "a hand-authored entry with a null wait value",
        detail={"wait": None},
    )

    result = _piped(
        [
            str(path),
            "--decision",
            "re-check anyway",
            "--at",
            "2026-08-17T02:00:00Z",
            "--check-wait",
            "cleared",
            "--wait-cleared-by",
            "nothing to clear",
        ]
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout
    # The old bug: a record of None collapsed to "no entry has ever recorded a
    # wait", which is a different, misleading claim from "the most recent one is
    # not usable".
    assert "no entry has ever recorded a wait" not in result.stdout.lower()


def test_check_wait_refusal_names_the_state_it_actually_found_not_always_holds(
    tmp_path,
):
    """Second defect in the same issue: the refusal used to fill its `{}` slot with
    `WAIT_HOLDS` -- the *required* constant -- so a last entry carrying no `wait` key
    at all was reported as "state holds", in a position every reader takes as the
    state that was found. Here the most recently recorded wait is `cleared`, and the
    refusal must say `cleared`, never `holds`.
    """
    path = tmp_path / "state.json"
    _record_wait(path)
    _piped(
        [
            str(path),
            "--decision",
            "cleared",
            "--at",
            "2026-08-17T01:15:00Z",
            "--check-wait",
            "cleared",
            "--wait-cleared-by",
            "issues filed",
        ]
    )

    result = _piped(
        [
            str(path),
            "--decision",
            "re-check anyway",
            "--at",
            "2026-08-17T02:00:00Z",
            "--check-wait",
            "cleared",
            "--wait-cleared-by",
            "nothing left to clear",
        ]
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout
    assert oss_state.WAIT_CLEARED in result.stdout
    # The old bug: this string appears in the refusal no matter what was actually
    # found, because the format argument was the literal constant rather than the
    # state read off disk.
    assert "state holds" not in result.stdout.lower()
