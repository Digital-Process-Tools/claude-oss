"""#852: a short lane's fill and its reason, recorded so the tick's prose stops being
the only place the rule lives.

Every "must refuse" case is paired with a "must accept" case in the same fixture --
a refusal-only suite cannot tell a real refusal from a test that never triggers the
code path.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

WINDOW = "lanes dispatched this tick"
STAMP = "2026-09-02T12:00:00Z"


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# --------------------------------------------------------- library-level: lane_fill()


def test_a_short_lane_with_no_reason_is_refused():
    """The positive control's negative half: a short lane with no reason must not
    be silently recorded."""
    with pytest.raises(oss_state.StateError, match="board-exhausted"):
        oss_state.lane_fill(
            [{"primary": 852, "count": 1}], window=WINDOW
        )


def test_a_short_lane_with_a_valid_reason_is_recorded():
    record = oss_state.lane_fill(
        [{"primary": 852, "count": 1, "reason": "no-adjacent"}], window=WINDOW
    )
    assert record["state"] == oss_state.LANE_FILL_RECORDED
    assert record["lanes"][0]["count"] == 1
    assert record["lanes"][0]["reason"] == "no-adjacent"


def test_a_full_lane_of_three_needs_no_reason():
    record = oss_state.lane_fill([{"primary": 852, "count": 3}], window=WINDOW)
    assert record["state"] == oss_state.LANE_FILL_RECORDED
    assert record["lanes"][0]["count"] == 3
    assert record["lanes"][0]["reason"] is None


def test_a_full_lane_with_a_reason_anyway_is_refused():
    """A reason on a full lane is not harmless -- it is a claim about a
    constraint that did not bind, and dispatch_rank.check_lane already refuses it."""
    with pytest.raises(oss_state.StateError):
        oss_state.lane_fill(
            [{"primary": 852, "count": 3, "reason": "board-exhausted"}], window=WINDOW
        )


def test_an_invalid_reason_string_is_refused():
    with pytest.raises(oss_state.StateError):
        oss_state.lane_fill(
            [{"primary": 852, "count": 1, "reason": "not-a-real-reason"}], window=WINDOW
        )


def test_a_count_over_the_cap_is_refused():
    with pytest.raises(oss_state.StateError):
        oss_state.lane_fill([{"primary": 852, "count": 4}], window=WINDOW)


def test_a_count_of_zero_is_refused():
    with pytest.raises(oss_state.StateError):
        oss_state.lane_fill([{"primary": 852, "count": 0}], window=WINDOW)


def test_an_absurd_count_is_refused_without_materializing_a_list():
    """Found by review (#852): lane_fill() used to build list(range(count)) before
    dispatch_rank.check_lane ever compares it against MAX_LANE -- an over-cap count
    was still refused correctly, but only after allocating a list of that size. A
    caller passing an unbounded numeral hangs on the allocation rather than being
    refused in O(1). 10**8 takes ~1.9s to materialize as a list and microseconds as
    a bare range(), so a generous 1s budget is well clear of ordinary noise while
    still catching the list-materializing regression this guards against."""
    import time

    start = time.time()
    with pytest.raises(oss_state.StateError, match="over the cap"):
        oss_state.lane_fill([{"primary": 852, "count": 10**8}], window=WINDOW)
    elapsed = time.time() - start
    assert elapsed < 1.0, "refusal took {:.2f}s -- looks like a list got materialized".format(
        elapsed
    )


def test_no_lanes_dispatched_is_not_the_same_state_as_no_record():
    dispatched_none = oss_state.lane_fill([], window=WINDOW)
    assert dispatched_none["state"] == oss_state.LANE_FILL_NONE_DISPATCHED

    could_not_establish = oss_state.lane_fill(None, window=WINDOW, why="transcripts reaped")
    assert could_not_establish["state"] == oss_state.LANE_FILL_COULD_NOT_ESTABLISH
    assert could_not_establish["why"] == "transcripts reaped"


# ------------------------------------------------------------------------- CLI shape


def test_cli_refuses_the_whole_decision_call_when_a_short_lane_has_no_reason(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision",
            "dispatched one lane",
            "--at",
            STAMP,
            "--lane-fill",
            "852:1",
            "--lane-fill-window",
            WINDOW,
        ]
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout
    assert not path.exists()


def test_cli_accepts_a_short_lane_with_a_valid_reason(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision",
            "dispatched one lane",
            "--at",
            STAMP,
            "--lane-fill",
            "852:1:no-adjacent",
            "--lane-fill-window",
            WINDOW,
        ]
    )
    assert result.returncode == 0, result.stdout
    assert "RECORDED" in result.stdout
    entries = oss_state.read(str(path))
    assert entries[0]["detail"]["lane_fill"]["lanes"][0]["reason"] == "no-adjacent"


def test_cli_accepts_a_full_lane_of_three_with_no_reason(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision",
            "dispatched one lane",
            "--at",
            STAMP,
            "--lane-fill",
            "852:3",
            "--lane-fill-window",
            WINDOW,
        ]
    )
    assert result.returncode == 0, result.stdout
    entries = oss_state.read(str(path))
    assert entries[0]["detail"]["lane_fill"]["lanes"][0]["count"] == 3


# ------------------------------------------------------------------------------ trend


def test_trend_reports_the_reason_distribution():
    entries = [
        {
            "detail": {
                "lane_fill": oss_state.lane_fill(
                    [{"primary": 1, "count": 1, "reason": "could-not-tell"}],
                    window=WINDOW,
                )
            }
        },
        {
            "detail": {
                "lane_fill": oss_state.lane_fill(
                    [{"primary": 2, "count": 1, "reason": "could-not-tell"}],
                    window=WINDOW,
                )
            }
        },
        {
            "detail": {
                "lane_fill": oss_state.lane_fill(
                    [{"primary": 3, "count": 3}], window=WINDOW
                )
            }
        },
    ]
    trend = oss_state.lane_fill_trend(entries)
    assert trend["state"] == oss_state.LANE_FILL_RECORDED
    assert trend["counts"]["could-not-tell"] == 2
    assert trend["full_lanes"] == 1
    assert trend["lanes"] == 3


def test_trend_cli_reports_the_distribution(tmp_path):
    path = tmp_path / "state.json"
    assert (
        _piped(
            [
                str(path),
                "--decision",
                "one",
                "--at",
                STAMP,
                "--lane-fill",
                "1:1:board-exhausted",
                "--lane-fill-window",
                WINDOW,
            ]
        ).returncode
        == 0
    )
    assert (
        _piped(
            [
                str(path),
                "--decision",
                "two",
                "--at",
                STAMP,
                "--lane-fill",
                "2:1:board-exhausted",
                "--lane-fill-window",
                WINDOW,
            ]
        ).returncode
        == 0
    )
    result = _piped([str(path), "--lane-fill-trend"])
    assert result.returncode == 0
    assert "TREND" in result.stdout
    assert "board-exhausted" in result.stdout
    assert "2 board-exhausted" in result.stdout
