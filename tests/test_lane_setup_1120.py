"""#1120: a "dead"/"killed" liveness verdict a scheduler hands a sub-manager is
computed entirely outside this repository (the harness's own agent/task-status
machinery, and/or supertool's `git-worktrees` op) -- `worktree_occupancy` in
`lane_setup_worktree.py` only ever answers "does something sit at this path", never
whether anything is still writing to it. Investigated in full for the issue; no
process-liveness signal exists anywhere in this file set to harden, so this closes
the one gap that genuinely is: no positive, corroborating "is this worktree still
being touched" signal was available to a sub-manager doubting a "dead" verdict
before re-dispatching a second agent into the same tree.

`worktree_last_activity` adds exactly that -- a plain recursive mtime scan, no git
invocation, no prior snapshot required, so it works even the very first time it is
called against a worktree (unlike `tree_snapshot.py`'s before/after comparison,
which this is not a replacement for and does not attempt to duplicate). Three
states, this repository's own convention:

  resolved         at least one file was stat'ed; `mtime` carries the newest.
  empty            the directory exists, the walk completed, and nothing was
                    found -- a freshly created worktree, not a failure.
  could-not-tell   `path` does not exist, is not a directory, or the walk itself
                    could not be completed -- never collapsed into `empty`,
                    which is a confident answer this state is not.

A negative assertion needs a positive control (CLAUDE.md): `empty` is only
trustworthy if a fixture with a real file inside a same-shaped tree comes back
`resolved` instead, so both are asserted here rather than only the "nothing found"
case.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import lane_setup_worktree  # noqa: E402
import spawn_guard  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"
GIT = "git"


def test_resolved_finds_the_newest_mtime_among_several_files(tmp_path):
    older = tmp_path / "older.txt"
    newer = tmp_path / "sub" / "newer.txt"
    newer.parent.mkdir()
    older.write_text("old")
    newer.write_text("new")
    now = time.time()
    os.utime(str(older), (now - 500, now - 500))
    os.utime(str(newer), (now - 5, now - 5))
    # #1140: `sub`'s own mtime is now part of the walk too, and `mkdir()`
    # just above set it to "now" -- backdate it so this test still measures
    # what it says it measures (the newest FILE mtime), rather than
    # incidentally asserting the new subdirectory-mtime behaviour that
    # test_lane_setup_1140.py covers on its own.
    os.utime(str(newer.parent), (now - 5, now - 5))

    result = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert result["state"] == "resolved"
    assert result["mtime"] == pytest.approx(now - 5, abs=2)


def test_empty_directory_is_not_confused_with_could_not_tell(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = lane_setup_worktree.worktree_last_activity(str(empty_dir))

    assert result["state"] == "empty"
    assert result["mtime"] is None


def test_nonexistent_path_is_could_not_tell_not_empty(tmp_path):
    missing = tmp_path / "does-not-exist"

    result = lane_setup_worktree.worktree_last_activity(str(missing))

    assert result["state"] == "could-not-tell"
    assert result["mtime"] is None


def test_a_file_instead_of_a_directory_is_could_not_tell(tmp_path):
    a_file = tmp_path / "not-a-dir"
    a_file.write_text("x")

    result = lane_setup_worktree.worktree_last_activity(str(a_file))

    assert result["state"] == "could-not-tell"


def test_a_falsy_path_is_could_not_tell(tmp_path):
    result = lane_setup_worktree.worktree_last_activity(None)

    assert result["state"] == "could-not-tell"


def test_reruns_a_freshly_rewritten_file_forward_the_new_mtime(tmp_path):
    """The exact #1120 shape: a file is rewritten between two calls -- the
    second call must reflect the real, on-disk mtime the rewrite actually
    produced, not a value memoized from the first call. There is no cache
    anywhere in worktree_last_activity to memoize *from* (each call is a fresh
    stat/walk), so this pins that absence of state directly: force the new
    mtime forward with os.utime (portable across filesystems whose mtime
    resolution is too coarse for two real writes a few milliseconds apart to
    reliably differ), then confirm the second call reports exactly that value
    rather than the first call's now-stale one -- a caching regression is the
    only plausible bug this could still catch."""
    target = tmp_path / "rewritten.sh"
    target.write_text("first")
    os.utime(str(target), (1000, 1000))
    first = lane_setup_worktree.worktree_last_activity(str(tmp_path))
    assert first["state"] == "resolved"
    assert first["mtime"] == pytest.approx(1000, abs=0.01)

    target.write_text("second")
    os.utime(str(target), (2000, 2000))

    second = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert second["state"] == "resolved"
    assert second["mtime"] == pytest.approx(2000, abs=0.01)
    assert second["mtime"] != first["mtime"]


def test_an_empty_commit_in_a_real_worktree_is_invisible_to_the_scan(tmp_path):
    """#1120 self-review found this directly: a git worktree add -cut tree
    carries a .git FILE (a one-line gitdir: pointer), not a directory -- the
    real index/refs/objects for a commit made there live under the MAIN
    clone's own .git/worktrees/<name>/, entirely outside the path this
    function scans. So a commit that touches no working-tree file is
    invisible here. Pinned as a known limitation, not a bug: the docstring
    says so explicitly, and this is the test that keeps that claim honest."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "a.txt").write_text("first")
    _git(origin, "add", "a.txt")
    _git(
        origin,
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "user.name=T",
        "commit",
        "-q",
        "-m",
        "first",
    )
    linked = tmp_path / "linked"
    _git(origin, "worktree", "add", "-q", str(linked), "-b", "feature")
    assert (linked / ".git").is_file(), "a linked worktree's own .git is a file"

    before = lane_setup_worktree.worktree_last_activity(str(linked))
    assert before["state"] == "resolved"

    _git(
        linked,
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "user.name=T",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "empty",
    )

    after = lane_setup_worktree.worktree_last_activity(str(linked))
    assert after["state"] == "resolved"
    assert after["mtime"] == before["mtime"]


# --- CLI: --activity ---------------------------------------------------------


def _env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _git(cwd, *args):
    subprocess.run(
        [GIT] + list(args), cwd=str(cwd), check=True, capture_output=True, env=_env()
    )


def _repo_with_worktree(tmp_path):
    """An `origin` repo plus a clone of it (so the clone carries a real `origin`
    remote and `base` resolves cleanly), plus an already-existing directory at
    the derived worktree path for issue 1120 -- carrying one file, so the walk
    has something to see."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "a.txt").write_text("first")
    _git(origin, "add", "a.txt")
    _git(
        origin,
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "user.name=T",
        "commit",
        "-q",
        "-m",
        "first",
    )
    repo = tmp_path / "work"
    subprocess.run(
        [GIT, "clone", "-q", str(origin), str(repo)],
        check=True,
        capture_output=True,
        env=_env(),
    )
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "T")
    worktree_root = tmp_path / "wt"
    lane_dir = worktree_root / "1120"
    lane_dir.mkdir(parents=True)
    (lane_dir / "b.txt").write_text("live diff")
    (repo / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "example/example",
                "default_branch": "main",
                "clone": str(repo),
                "worktree_root": str(worktree_root),
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": [],
                "changelog_dir": None,
                "docs_targets": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": str(tmp_path / "state.json"),
            }
        )
    )
    return repo


def _run(repo, *extra_args):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), "1120", "--repo", str(repo)] + list(extra_args),
        subject="lane_setup.py --activity",
        capture_output=True,
        text=True,
        env=_env(),
        timeout=60,
    )


def test_cli_activity_renders_a_last_touched_line_for_an_existing_worktree(tmp_path):
    repo = _repo_with_worktree(tmp_path)

    done = _run(repo, "--activity")

    assert done.returncode == 0, done.stderr
    assert "activity: last touched" in done.stdout


def test_cli_without_activity_never_prints_an_activity_line(tmp_path):
    """The positive control for the test above: the same fixture, the same
    already-existing worktree, but without --activity -- nothing about
    activity should appear at all, since it was never asked for."""
    repo = _repo_with_worktree(tmp_path)

    done = _run(repo)

    assert done.returncode == 0, done.stderr
    assert "activity:" not in done.stdout


def test_cli_activity_refuses_alongside_release(tmp_path):
    repo = _repo_with_worktree(tmp_path)

    done = _run(repo, "--activity", "--release")

    assert done.returncode != 0
    assert "--activity" in done.stderr
