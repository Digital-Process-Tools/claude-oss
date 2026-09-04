"""#1007: a forced worktree cleanup that overrides `|cleanup`'s own `cannot tell`
refusal must be recorded, with a reason, the same way a short lane fill already
records one (`--lane-fill`). This is the machine-checkable half of the fix --
`cleanup_overrides()` is the single place the rule lives, and the CLI is the
only route into it, so a lane record with no reason is refused before it ever
reaches disk.

Every "must refuse" case is paired with a "must accept" case in the same
fixture -- a refusal-only suite cannot tell a real refusal from a test that
never triggers the code path.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

STAMP = "2026-09-04T12:00:00Z"


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# --------------------------------------------------------- library-level: cleanup_overrides()


def test_an_override_with_no_reason_is_refused():
    """The positive control's negative half: a forced removal with no stated
    reason is exactly the silent override #1007 was filed over."""
    with pytest.raises(oss_state.StateError, match="reason"):
        oss_state.cleanup_overrides([{"worktree": "/tmp/wt/1007"}])


def test_an_override_with_a_reason_is_recorded():
    record = oss_state.cleanup_overrides(
        [{"worktree": "/tmp/wt/1007", "reason": "cannot tell, HEAD unchanged since merge"}]
    )
    assert record[0]["worktree"] == "/tmp/wt/1007"
    assert record[0]["reason"] == "cannot tell, HEAD unchanged since merge"


def test_an_empty_list_is_refused():
    """Call it only when at least one override actually happened -- an empty
    list is a claim nothing supports, not a state worth writing."""
    with pytest.raises(oss_state.StateError):
        oss_state.cleanup_overrides([])


def test_a_blank_worktree_is_refused():
    with pytest.raises(oss_state.StateError, match="worktree"):
        oss_state.cleanup_overrides([{"worktree": "  ", "reason": "cannot tell"}])


def test_multiple_overrides_are_all_recorded():
    record = oss_state.cleanup_overrides(
        [
            {"worktree": "/tmp/wt/1007", "reason": "cannot tell"},
            {"worktree": "/tmp/wt/978", "reason": "cannot tell, quiet under bar"},
        ]
    )
    assert len(record) == 2
    assert record[1]["worktree"] == "/tmp/wt/978"


# ---------------------------------------------------------------------- CLI: argument shape


def test_cli_argument_with_no_equals_is_refused():
    result = _piped(
        [
            "unused-path",
            "--decision",
            "d",
            "--at",
            STAMP,
            "--cleanup-override",
            "/tmp/wt/1007",
        ]
    )
    assert result.returncode != 0
    assert "WORKTREE=REASON" in result.stdout


def test_cli_argument_with_blank_reason_after_equals_is_refused():
    result = _piped(
        [
            "unused-path",
            "--decision",
            "d",
            "--at",
            STAMP,
            "--cleanup-override",
            "/tmp/wt/1007=",
        ]
    )
    assert result.returncode != 0
    assert "WORKTREE=REASON" in result.stdout


# -------------------------------------------------------------------------------- CLI: --decision


def test_cli_records_a_forced_cleanup_override(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision",
            "force-reaped one worktree over a cannot-tell",
            "--at",
            STAMP,
            "--cleanup-override",
            "/tmp/wt/1007=cannot tell, quiet under the 60-minute bar",
        ]
    )
    assert result.returncode == 0, result.stdout
    assert "RECORDED" in result.stdout
    entries = oss_state.read(str(path))
    override = entries[0]["detail"]["cleanup_override"]
    assert override[0]["worktree"] == "/tmp/wt/1007"
    assert override[0]["reason"] == "cannot tell, quiet under the 60-minute bar"


def test_cli_records_multiple_cleanup_overrides_in_one_call(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision",
            "force-reaped two worktrees",
            "--at",
            STAMP,
            "--cleanup-override",
            "/tmp/wt/1007=cannot tell",
            "--cleanup-override",
            "/tmp/wt/978=cannot tell, quiet under bar",
        ]
    )
    assert result.returncode == 0, result.stdout
    entries = oss_state.read(str(path))
    override = entries[0]["detail"]["cleanup_override"]
    assert len(override) == 2
    assert {o["worktree"] for o in override} == {"/tmp/wt/1007", "/tmp/wt/978"}


def test_cli_without_cleanup_override_records_nothing_extra(tmp_path):
    """The positive control's own negative half: an ordinary decision with no
    override must not grow a `cleanup_override` key out of nothing."""
    path = tmp_path / "state.json"
    result = _piped(
        [str(path), "--decision", "ordinary tick, nothing forced", "--at", STAMP]
    )
    assert result.returncode == 0, result.stdout
    entries = oss_state.read(str(path))
    detail = entries[0].get("detail")
    assert not (isinstance(detail, dict) and "cleanup_override" in detail)


def test_cli_refuses_when_detail_already_carries_the_key(tmp_path):
    path = tmp_path / "state.json"
    result = _piped(
        [
            str(path),
            "--decision",
            "d",
            "--at",
            STAMP,
            "--cleanup-override",
            "/tmp/wt/1007=cannot tell",
            "--detail",
            '{"cleanup_override": "already here"}',
        ]
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout
    assert not path.exists()
