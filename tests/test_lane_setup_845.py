"""#845: a live lane record whose own worktree directory has vanished mid-run,
caused by no command that lane itself ran, was never noticed by anything in
this codebase -- the reporting agent found out only by rebuilding twice from
`git reflog`. `detect_vanished_worktrees` is the loud detector: it flags a
live registry record whose own `path` is confirmed absent, and it must not
fire on a record whose path genuinely still exists (the positive control) or
on a path this process could not examine at all (unlookable is not absent).
"""

import json
import os
import stat
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _write_record(worktree_root, issue, path, branch=None, age_seconds=0):
    root = lane_setup.lane_registry_dir(str(worktree_root))
    os.makedirs(root, exist_ok=True)
    record_path = os.path.join(root, "{0}.json".format(issue))
    payload = {
        "issue": issue,
        "branch": branch if branch is not None else "fix/{0}".format(issue),
        "path": path,
        "recorded_at": time.time() - age_seconds,
        "files": ["scripts/x.py"],
    }
    with open(record_path, "w") as fh:
        json.dump(payload, fh)
    return record_path


def test_vanished_worktree_is_flagged(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    lane_dir = root / "405"
    lane_dir.mkdir()
    _write_record(root, 405, str(lane_dir))
    # The worktree directory is now removed by something -- the #845 shape --
    # while the registry record still says the lane is live.
    lane_dir.rmdir()

    result = lane_setup.detect_vanished_worktrees(str(root))

    assert result["state"] == "resolved"
    vanished_issues = [v["issue"] for v in result["vanished"]]
    assert 405 in vanished_issues


def test_present_worktree_is_not_flagged(tmp_path):
    """Positive control: a live record whose worktree directory genuinely
    still exists must not be reported as vanished -- a detector that fires on
    every live record regardless of the filesystem would pass the test above
    for the wrong reason."""
    root = tmp_path / "wt"
    root.mkdir()
    lane_dir = root / "406"
    lane_dir.mkdir()
    _write_record(root, 406, str(lane_dir))

    result = lane_setup.detect_vanished_worktrees(str(root))

    assert result["state"] == "resolved"
    vanished_issues = [v["issue"] for v in result["vanished"]]
    assert 406 not in vanished_issues


def test_unlookable_path_is_not_flagged_as_vanished(tmp_path, monkeypatch):
    """A path this process cannot examine ('could not look') is not evidence
    it disappeared -- the same three-state discipline every other absence
    check in this module already applies. If this collapsed to two states,
    an unreadable parent would render as a confident, wrong 'vanished'."""
    root = tmp_path / "wt"
    root.mkdir()
    lane_dir = root / "407"
    lane_dir.mkdir()
    _write_record(root, 407, str(lane_dir))

    monkeypatch.setattr(lane_setup, "worktree_occupancy", lambda path: None)

    result = lane_setup.detect_vanished_worktrees(str(root))

    assert result["state"] == "resolved"
    vanished_issues = [v["issue"] for v in result["vanished"]]
    assert 407 not in vanished_issues


def test_no_registry_is_unknown(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    result = lane_setup.detect_vanished_worktrees(str(root))
    assert result["state"] == "unknown"
    assert result["vanished"] == []


def test_expired_record_is_not_checked(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    lane_dir = root / "408"
    lane_dir.mkdir()
    _write_record(root, 408, str(lane_dir), age_seconds=lane_setup.LANE_RECORD_TTL_SECONDS + 10)
    lane_dir.rmdir()

    result = lane_setup.detect_vanished_worktrees(str(root))

    # The record is expired, so it is not "live" and is excluded entirely --
    # neither flagged as vanished nor counted toward `live`.
    assert result["state"] == "unknown"
    assert result["vanished"] == []


# --- CLI: --check-vanished ---------------------------------------------------

import subprocess  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tests"))
import spawn_guard  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"


def _cli_check_vanished(tmp_path, *extra_args):
    (tmp_path / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "example/example",
                "default_branch": "main",
                "clone": "/tmp/does-not-matter",
                "worktree_root": str(tmp_path / "wt"),
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": [],
                "changelog_dir": None,
                "docs_targets": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": "/tmp/does-not-matter-state.json",
            }
        )
    )
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), "--check-vanished", "--repo", str(tmp_path), "--json"] + list(extra_args),
        subject="lane_setup.py --check-vanished",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_check_vanished_reports_a_missing_worktree_and_exits_nonzero(tmp_path):
    worktree_root = tmp_path / "wt"
    lane_dir = worktree_root / "845"
    lane_dir.mkdir(parents=True)
    _write_record(worktree_root, 845, str(lane_dir))
    lane_dir.rmdir()

    done = _cli_check_vanished(tmp_path)

    payload = json.loads(done.stdout)
    assert payload["state"] == "resolved"
    assert [v["issue"] for v in payload["vanished"]] == [845]
    assert done.returncode == 1, done.stderr


def test_cli_check_vanished_exits_ok_when_nothing_vanished(tmp_path):
    worktree_root = tmp_path / "wt"
    lane_dir = worktree_root / "846"
    lane_dir.mkdir(parents=True)
    _write_record(worktree_root, 846, str(lane_dir))

    done = _cli_check_vanished(tmp_path)

    payload = json.loads(done.stdout)
    assert payload["state"] == "resolved"
    assert payload["vanished"] == []
    assert done.returncode == 0, done.stderr


def test_cli_check_vanished_refuses_alongside_claim(tmp_path):
    done = _cli_check_vanished(tmp_path, "--claim", "--lane", "a.py")
    assert done.returncode != 0
    assert "--check-vanished" in done.stderr
