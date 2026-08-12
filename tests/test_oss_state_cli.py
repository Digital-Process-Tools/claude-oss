"""The oss_state CLI that /oss:tick invokes."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

STAMP = "2026-08-12T17:00:00Z"


def test_read_on_an_empty_history_prints_an_empty_list(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--read"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_last_on_an_empty_history_says_so_rather_than_printing_null(tmp_path, capsys):
    """`null` on stdout reads like a value. It is the absence of one."""
    assert oss_state._main([str(tmp_path / "state.json"), "--last"]) == 0
    assert "no entries yet" in capsys.readouterr().out


def test_appending_requires_a_timestamp(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--decision", "merged #4"]) == 1
    assert "not read from a clock" in capsys.readouterr().out
    assert not path.exists()


def test_append_writes_and_prints_the_entry(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--decision", "merged #4", "--at", STAMP]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["decision"] == "merged #4"
    assert oss_state.read(path) == [entry]


def test_append_carries_a_json_detail(tmp_path, capsys):
    path = tmp_path / "state.json"
    oss_state._main(
        [str(path), "--decision", "triaged", "--at", STAMP, "--detail", '{"issues": [1, 2]}']
    )
    assert json.loads(capsys.readouterr().out)["detail"] == {"issues": [1, 2]}


def test_a_malformed_detail_is_refused_and_writes_nothing(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--decision", "x", "--at", STAMP, "--detail", "{oops"]) == 1
    assert "not valid JSON" in capsys.readouterr().out
    assert not path.exists()


def test_an_over_long_decision_is_refused_with_the_reason(tmp_path, capsys):
    path = tmp_path / "state.json"
    long_decision = "x" * (oss_state.MAX_DECISION + 1)
    assert oss_state._main([str(path), "--decision", long_decision, "--at", STAMP]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "belongs in the pull request" in out


def test_a_corrupt_state_file_fails_loudly_and_is_not_reset(tmp_path, capsys):
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")
    assert oss_state._main([str(path), "--read"]) == 1
    assert "could not parse" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == "{ not json"
