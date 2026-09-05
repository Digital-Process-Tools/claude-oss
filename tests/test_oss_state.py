"""The tick state file.

The skill says: written every tick, read first every tick, entries short. It also says
the handoff is not the repo -- the file records what was *believed* when it was written,
which is why every entry carries its own timestamp and why nothing here re-derives.

Timestamps are passed in, never taken from the clock inside these functions. A function
that reads the clock cannot be tested for what it writes, and this file is evidence.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

STAMP = "2026-08-12T17:00:00Z"


def test_reading_a_missing_file_returns_empty_not_an_error(tmp_path):
    """First tick in a repo is the common case, not an exception."""
    assert oss_state.read(tmp_path / ".max" / "oss-watch.json") == []


def test_reading_a_corrupt_file_raises_rather_than_silently_resetting(tmp_path):
    """Silently starting fresh would destroy the history it exists to keep, and the
    tick that did it would look identical to a first tick.
    """
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(oss_state.StateError):
        oss_state.read(path)


def test_append_creates_the_file_and_its_parent(tmp_path):
    path = tmp_path / ".max" / "oss-watch.json"
    oss_state.append(path, STAMP, "triaged 4 issues", detail={"issues": [1, 2, 3, 4]})
    assert path.is_file()
    assert len(oss_state.read(path)) == 1


def test_entries_accumulate_newest_last(tmp_path):
    path = tmp_path / "state.json"
    oss_state.append(path, "2026-08-12T10:00:00Z", "first")
    oss_state.append(path, "2026-08-12T11:00:00Z", "second")
    entries = oss_state.read(path)
    assert [e["decision"] for e in entries] == ["first", "second"]


def test_every_entry_carries_its_stamp_and_decision(tmp_path):
    path = tmp_path / "state.json"
    oss_state.append(path, STAMP, "merged #12", detail={"pr": 12})
    entry = oss_state.read(path)[0]
    assert entry["at"] == STAMP
    assert entry["decision"] == "merged #12"
    assert entry["detail"] == {"pr": 12}


def test_a_decision_is_required(tmp_path):
    """An entry with no decision is a tick that recorded that it happened and nothing
    about what it decided -- which is worse than no entry, because it reads as history.
    """
    with pytest.raises(oss_state.StateError):
        oss_state.append(tmp_path / "state.json", STAMP, "")


def test_a_decision_is_kept_short(tmp_path):
    """Reasoning that only matters to the PR belongs in the PR body. The cap is a
    refusal, not a truncation: truncating would silently lose the half that mattered.
    """
    with pytest.raises(oss_state.StateError):
        oss_state.append(
            tmp_path / "state.json", STAMP, "x" * (oss_state.MAX_DECISION + 1)
        )


def test_last_returns_the_most_recent_entry(tmp_path):
    path = tmp_path / "state.json"
    oss_state.append(path, "2026-08-12T10:00:00Z", "first")
    oss_state.append(path, "2026-08-12T11:00:00Z", "second")
    assert oss_state.last(path)["decision"] == "second"


def test_last_on_an_empty_history_is_none_not_an_error(tmp_path):
    assert oss_state.last(tmp_path / "state.json") is None


def test_the_file_stays_valid_json_a_human_can_read(tmp_path):
    path = tmp_path / "state.json"
    oss_state.append(path, STAMP, "filed #9")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_append_refuses_a_detail_that_is_not_serialisable(tmp_path):
    """Failing at write time keeps the file valid. Discovering it at read time means
    the tick that broke it is already over.
    """
    with pytest.raises(oss_state.StateError):
        oss_state.append(
            tmp_path / "state.json", STAMP, "ok", detail={"fn": lambda: None}
        )


def test_a_failed_append_leaves_the_previous_history_intact(tmp_path):
    path = tmp_path / "state.json"
    oss_state.append(path, STAMP, "first")
    with pytest.raises(oss_state.StateError):
        oss_state.append(path, STAMP, "second", detail={"fn": lambda: None})
    assert [e["decision"] for e in oss_state.read(path)] == ["first"]
