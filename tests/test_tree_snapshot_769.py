"""#769 -- a review agent declared read-only wrote into the worktree it was
auditing, twice in one run, by two different agents, leaving no ref movement
and no reflog trace.

`scripts/tree_snapshot.py` is the caller-side receipt the issue's own list of
candidates favours: snapshot before spawning a review agent, snapshot again
after both return, compare. It asks nothing of the spawn and is unaffected by
which agent or which mechanism caused the mutation -- the same
mechanism-independence `review_return.py` (#392) already argues for a
different silent loss in the same review step.

**Every negative assertion here carries a positive control in the same
fixture** (or its sibling test): a comparator that always says `clean` would
pass every "must not fire" case trivially, so each is paired with a fixture
that must produce `mutated`.

The self-cleaning limit is pinned directly, not left as an assumption: a
write that is created and deleted before the after-snapshot runs is, by
construction, invisible to a before/after comparison taken only at the two
ends. `test_selfcleaned_write_is_not_caught_by_design` proves the boundary
this module states rather than promising more than it can deliver.
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


def _real_git_repo(tmp_path):
    """A real, committed git repo -- the same shape
    `test_lane_setup_734.py`'s own `_real_git_repo` uses, skip rather than
    fail if this environment cannot run `git init` at all."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_env()
    done = subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        env=env,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip() or done.returncode))
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], env=env, check=True)
    (repo / "tracked.txt").write_text("original content\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "initial"], env=env, check=True)
    return repo


# --- snapshot(): the primitive -------------------------------------------


def test_snapshot_of_a_clean_repo_carries_no_error(tmp_path):
    repo = _real_git_repo(tmp_path)
    snap = tree_snapshot.snapshot(str(repo))
    assert snap["error"] is None, snap
    assert snap["head"]
    assert snap["status"].strip() == ""


def test_snapshot_of_a_non_git_directory_is_could_not_snapshot(tmp_path):
    """Control for the third state: a directory git has nothing to say about
    must not read as a clean, empty repo."""
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    snap = tree_snapshot.snapshot(str(not_a_repo))
    assert snap["error"] is not None
    assert snap["head"] is None
    assert snap["status"] is None


# --- compare(): must-fire and must-not-fire, paired ------------------------


def test_compare_is_clean_when_nothing_touched_the_tree(tmp_path):
    """Must-not-fire control for every 'mutated' case below."""
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    after = tree_snapshot.snapshot(str(repo))
    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "clean", verdict


def test_compare_catches_a_tracked_file_reverted_in_place(tmp_path):
    """Instance 1's own shape: a reviewer wrote through a symlink and
    reverted a tracked file's content in place, with no commit and no ref
    movement -- exactly what a raw `git checkout <sha> -- <path>` leaves
    behind, and exactly what this module exists to catch."""
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "tracked.txt").write_text("silently reverted by a reviewer\n")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "mutated", verdict
    assert any("tracked.txt" in line for line in verdict["added"]), verdict


def test_compare_catches_an_untracked_scratch_file_left_behind(tmp_path):
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "scratch_diff.txt").write_text("a reviewer's own comparison copy\n")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "mutated", verdict
    assert any("scratch_diff.txt" in line for line in verdict["added"]), verdict


def test_compare_catches_head_moving_with_no_content_change(tmp_path):
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "--allow-empty", "-m", "moved"],
        env=_git_env(), check=True,
    )
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "mutated", verdict
    assert verdict["head_moved"] is True


def test_selfcleaned_write_is_not_caught_by_design(tmp_path):
    """Instance 2's own shape: `oss:auditor` wrote and then deleted an
    untracked scratch file inside the same run. A comparison taken only at
    the two ends cannot see a state that returned to identical in between --
    there is nothing left on disk to name. This is the stated limit in the
    module's own docstring, pinned here so the gap is measured rather than
    assumed true."""
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    scratch = repo / "self_cleaned.txt"
    scratch.write_text("here and gone before anyone compared\n")
    scratch.unlink()
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "clean", verdict


def test_compare_never_reads_a_before_snapshot_error_as_clean(tmp_path):
    """A before-snapshot that itself failed must not silently pass as
    'nothing to compare against' -- this repository's own rule (an absence
    the tool produced must never render as an absence in the world) applied
    to its own tooling."""
    verdict = tree_snapshot.compare(
        {"head": None, "status": None, "error": "git not on PATH"},
        {"head": "abc", "status": "", "error": None},
    )
    assert verdict["state"] == "could-not-compare", verdict


def test_compare_never_reads_an_after_snapshot_error_as_clean(tmp_path):
    verdict = tree_snapshot.compare(
        {"head": "abc", "status": "", "error": None},
        {"head": None, "status": None, "error": "git not on PATH"},
    )
    assert verdict["state"] == "could-not-compare", verdict


# --- CLI: the shape agents/developer.md actually runs -----------------------


def _run_cli(args, cwd=None, stdin=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        cwd=cwd, input=stdin,
    )


def test_cli_snapshot_prints_one_line_of_json(tmp_path):
    repo = _real_git_repo(tmp_path)
    done = _run_cli(["snapshot", "--root", str(repo)])
    assert done.returncode == 0, done.stderr
    assert done.stdout.count("\n") == 1
    payload = json.loads(done.stdout)
    assert payload["error"] is None


def test_cli_compare_clean_exits_zero(tmp_path):
    repo = _real_git_repo(tmp_path)
    before = _run_cli(["snapshot", "--root", str(repo)]).stdout
    done = _run_cli(["compare", "--before", "-", "--root", str(repo)], stdin=before)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "VERDICT: clean" in done.stdout


def test_cli_compare_mutated_exits_one(tmp_path):
    """The exact shape `agents/developer.md` runs: capture a before-snapshot,
    let something touch the tree, compare through stdin."""
    repo = _real_git_repo(tmp_path)
    before = _run_cli(["snapshot", "--root", str(repo)]).stdout
    (repo / "tracked.txt").write_text("reverted\n")
    done = _run_cli(["compare", "--before", "-", "--root", str(repo)], stdin=before)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "VERDICT: mutated" in done.stdout


def test_cli_compare_with_malformed_before_is_could_not_compare_not_clean(tmp_path):
    repo = _real_git_repo(tmp_path)
    done = _run_cli(["compare", "--before", "-", "--root", str(repo)], stdin="not json")
    assert done.returncode == 3, done.stdout + done.stderr
    assert "VERDICT: could-not-compare" in done.stdout
