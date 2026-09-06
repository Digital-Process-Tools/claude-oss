"""#1096 -- `snapshot()` now records the current branch alongside `root`, so a
lane holding the before-snapshot has a cheap, high-signal way to catch a
wrong-worktree read: a lane already knows its own branch name (its brief
states it), and two sibling lanes on the same repository always sit on
different branches even when their worktree paths look similar at a glance.

This does not claim to have found or fixed the underlying mechanism behind
#1024/#1078/#1096's own reports (repeated investigation found no
cross-worktree resolution heuristic anywhere in this module -- see
`tests/test_tree_snapshot_sibling_worktree_1024.py`'s own docstring). It is a
corroborating field, stated as such in `snapshot()`'s own docstring.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tree_snapshot.py"

sys.path.insert(0, str(REPO / "scripts"))

import tree_snapshot  # noqa: E402


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(args, cwd, env=None):
    return subprocess.run(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=env or _git_env(),
    )


def _real_repo(tmp_path, branch=None):
    env = _git_env()
    root = tmp_path / "repo"
    root.mkdir()
    done = _run(["git", "init", "--quiet", "."], cwd=root, env=env)
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip()))
    _run(["git", "config", "user.email", "t@example.com"], cwd=root, env=env)
    _run(["git", "config", "user.name", "t"], cwd=root, env=env)
    (root / "tracked.txt").write_text("original\n")
    _run(["git", "add", "."], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, env=env)
    if branch:
        _run(["git", "checkout", "--quiet", "-b", branch], cwd=root, env=env)
    return root


def test_snapshot_records_the_current_branch(tmp_path):
    repo = _real_repo(tmp_path, branch="fix/1096")
    snap = tree_snapshot.snapshot(str(repo))
    assert snap["branch"] == "fix/1096", snap


def test_snapshot_distinguishes_sibling_worktrees_by_branch(tmp_path):
    """Positive control for the field's whole purpose: two sibling
    worktrees of the same repo, different branches -- `branch` must differ
    between their two snapshots even though both are otherwise ordinary,
    clean repositories."""
    env = _git_env()
    main = _real_repo(tmp_path, branch="fix/1078")
    sibling = tmp_path / "sibling"
    _run(["git", "worktree", "add", "-b", "fix/1042", str(sibling)], cwd=main, env=env)

    main_snap = tree_snapshot.snapshot(str(main))
    sibling_snap = tree_snapshot.snapshot(str(sibling))

    assert main_snap["branch"] == "fix/1078", main_snap
    assert sibling_snap["branch"] == "fix/1042", sibling_snap
    assert main_snap["branch"] != sibling_snap["branch"]


def test_snapshot_of_a_detached_head_does_not_fail_the_whole_snapshot(tmp_path):
    """A detached HEAD is a real, ordinary git state (a CI checkout, most
    commonly) -- `git rev-parse --abbrev-ref HEAD` answers the literal
    string `HEAD` for it rather than failing, and even if it did fail, the
    snapshot's own `head`/`status` facts (what `compare` actually needs)
    must not be lost over a corroborating field that could not be read."""
    env = _git_env()
    repo = _real_repo(tmp_path)
    head_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo, env=env).stdout.strip()
    _run(["git", "checkout", "--quiet", head_sha], cwd=repo, env=env)

    snap = tree_snapshot.snapshot(str(repo))
    assert snap["error"] is None, snap
    assert snap["head"] == head_sha, snap
    assert snap["branch"] == "HEAD", snap


def test_cli_snapshot_json_carries_the_branch_field(tmp_path):
    repo = _real_repo(tmp_path, branch="fix/1096")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "snapshot"],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    payload = json.loads(done.stdout)
    assert payload["branch"] == "fix/1096", payload
