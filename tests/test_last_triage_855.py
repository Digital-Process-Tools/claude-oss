"""#855: the loop's cadence needs a checkable receipt, not only prose -- when a
triage sweep last completed, in the same three states everything else in this
file uses. `--triage-recorded AT` attaches the fact to a `--decision` entry;
`last_triage`/`--last-triage` re-derive it later, scanning back past any entry
that recorded something else, the same shape `_last_wait` already uses.

Every "must find" case is paired with a "must not find" case in the same
fixture, per this repo's own rule that a positive-only sweep proves nothing.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# --------------------------------------------------------- library-level


def test_triage_recorded_needs_an_at():
    with pytest.raises(oss_state.StateError, match="ISO timestamp"):
        oss_state.triage_recorded(None)


def test_triage_recorded_needs_a_non_blank_at():
    with pytest.raises(oss_state.StateError, match="ISO timestamp"):
        oss_state.triage_recorded("   ")


def test_triage_recorded_returns_the_stripped_timestamp():
    assert oss_state.triage_recorded(" 2026-09-02T22:10:00Z ") == {
        "recorded_at": "2026-09-02T22:10:00Z"
    }


def test_last_triage_on_an_empty_history_is_never_not_could_not_read(tmp_path):
    """The positive control for the absence-vs-failure distinction below: an
    absent state file is a real, established zero-history, not a read failure."""
    record = oss_state.last_triage(tmp_path / "nonexistent.json")
    assert record["state"] == oss_state.TRIAGE_NEVER
    assert record["recorded_at"] is None


def test_last_triage_finds_the_most_recent_sweep_past_other_entries():
    """Scans backward past a lane record and a cohort freeze that landed after
    the sweep -- the same shape `_last_wait` is already tested against, and the
    exact failure #436 fixed for waits: a one-entry-lifetime read."""
    entries = [
        {
            "at": "2026-09-01T00:00:00Z",
            "decision": "sweep",
            "detail": {"triage": {"recorded_at": "2026-09-01T00:00:00Z"}},
        },
        {
            "at": "2026-09-01T05:00:00Z",
            "decision": "dispatch",
            "detail": {"lanes": {"state": "recorded", "lanes": []}},
        },
        {"at": "2026-09-01T09:00:00Z", "decision": "close", "detail": {}},
    ]

    class _Fake:
        pass

    # last_triage() calls read(path); monkeypatch it narrowly rather than
    # writing a real state file, since the function under test is the scan,
    # not the file format.
    original_read = oss_state.read
    try:
        oss_state.read = lambda path: entries
        record = oss_state.last_triage("unused")
    finally:
        oss_state.read = original_read
    assert record["state"] == oss_state.TRIAGE_RECORDED
    assert record["recorded_at"] == "2026-09-01T00:00:00Z"


def test_last_triage_with_no_sweep_entry_anywhere_is_never():
    """Negative control for the scan above: a history with real entries, none
    of them a triage record, is a real `never`, not a `could-not-read`."""
    entries = [
        {
            "at": "2026-09-01T05:00:00Z",
            "decision": "dispatch",
            "detail": {"lanes": {"state": "recorded", "lanes": []}},
        },
    ]
    original_read = oss_state.read
    try:
        oss_state.read = lambda path: entries
        record = oss_state.last_triage("unused")
    finally:
        oss_state.read = original_read
    assert record["state"] == oss_state.TRIAGE_NEVER


def test_last_triage_does_not_fall_back_to_an_older_valid_record_behind_a_malformed_one():
    """Found by review: the freshest triage entry in history is malformed (no
    recorded_at) with a genuinely older, valid one behind it. The scan must
    stop at the freshest statement -- even though it is unusable -- rather
    than silently reading past it to the stale valid one, which would render
    an out-of-date answer as though it were current. This is `_last_wait`'s
    own stated discipline; `last_triage`'s docstring claims to follow it and
    initially did not."""
    entries = [
        {
            "at": "2026-08-01T00:00:00Z",
            "detail": {"triage": {"recorded_at": "2026-08-01T00:00:00Z"}},
        },
        {"at": "2026-09-01T00:00:00Z", "detail": {"triage": {"recorded_at": ""}}},
    ]
    original_read = oss_state.read
    try:
        oss_state.read = lambda path: entries
        record = oss_state.last_triage("unused")
    finally:
        oss_state.read = original_read
    assert record["state"] == oss_state.TRIAGE_COULD_NOT_READ
    assert record["recorded_at"] is None
    assert record["state"] != oss_state.TRIAGE_RECORDED


def test_last_triage_could_not_read_is_distinct_from_never(tmp_path):
    """The load-bearing distinction #855 asks for: an unreadable state file
    must never render the same as a history that was read and found empty."""
    bad = tmp_path / "state.json"
    bad.write_text("{not json", encoding="utf-8")
    record = oss_state.last_triage(bad)
    assert record["state"] == oss_state.TRIAGE_COULD_NOT_READ
    assert record["state"] != oss_state.TRIAGE_NEVER
    assert record["why"]


def test_triage_line_names_each_state():
    assert "never" in oss_state.triage_line({"state": oss_state.TRIAGE_NEVER})
    assert "2026-09-02" in oss_state.triage_line(
        {"state": oss_state.TRIAGE_RECORDED, "recorded_at": "2026-09-02T22:10:00Z"}
    )
    assert "could not read" in oss_state.triage_line(
        {"state": oss_state.TRIAGE_COULD_NOT_READ, "why": "disk full"}
    )


# --------------------------------------------------------- CLI-level


def test_cli_last_triage_on_a_fresh_state_file_says_never(tmp_path):
    result = _piped([str(tmp_path / "state.json"), "--last-triage"])
    assert result.returncode == 0, result.stdout
    assert "last triaged: never" in result.stdout
    assert '"state": "never"' in result.stdout


def test_cli_records_and_rereads_a_triage_sweep(tmp_path):
    state_path = tmp_path / "state.json"
    record = _piped(
        [
            str(state_path),
            "--decision",
            "triage sweep",
            "--at",
            "2026-09-02T22:10:00Z",
            "--triage-recorded",
            "2026-09-02T22:10:00Z",
        ]
    )
    assert record.returncode == 0, record.stdout
    assert "RECORDED triage sweep at 2026-09-02T22:10:00Z" in record.stdout

    reread = _piped([str(state_path), "--last-triage"])
    assert reread.returncode == 0, reread.stdout
    assert "last triaged: 2026-09-02T22:10:00Z" in reread.stdout
    assert '"state": "recorded"' in reread.stdout


def test_cli_last_triage_finds_the_sweep_behind_a_later_ordinary_tick(tmp_path):
    """End-to-end version of the backward-scan test above: a tick recorded
    after the sweep, with no triage of its own, must not hide it."""
    state_path = tmp_path / "state.json"
    _piped(
        [
            str(state_path),
            "--decision",
            "triage sweep",
            "--at",
            "2026-09-01T00:00:00Z",
            "--triage-recorded",
            "2026-09-01T00:00:00Z",
        ]
    )
    _piped(
        [
            str(state_path),
            "--decision",
            "ordinary tick",
            "--at",
            "2026-09-02T00:00:00Z",
        ]
    )
    reread = _piped([str(state_path), "--last-triage"])
    assert "last triaged: 2026-09-01T00:00:00Z" in reread.stdout


def test_cli_refuses_triage_recorded_in_a_reading_mode(tmp_path):
    result = _piped(
        [
            str(tmp_path / "state.json"),
            "--read",
            "--triage-recorded",
            "2026-09-02T22:10:00Z",
        ]
    )
    assert result.returncode != 0
    assert "only recorded with --decision" in result.stdout


def test_cli_triage_recorded_needs_decision():
    """Negative control for the reading-mode refusal above: --triage-recorded
    with no --decision and no reading-mode flag at all is a different failure
    (argparse's own required group), never a silent no-op."""
    result = _piped(
        ["/nonexistent/state.json", "--triage-recorded", "2026-09-02T22:10:00Z"]
    )
    assert result.returncode != 0
