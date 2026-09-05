"""#1024 -- a report from a developer lane's self-review claimed
`tree_snapshot.py`, invoked with no `--root` from inside a worktree, had
resolved its root to a *different, sibling* live worktree of the same repo
(landed on by some unstated heuristic), producing a false `mutated` verdict.

Investigated directly against this repository's own real worktrees
(`claude-oss-wt/1024` and `claude-oss-wt/1029`, siblings sharing one
`.git`) rather than the synthetic independent repos
`test_tree_snapshot_cwd_root_971.py` uses: `snapshot` reads
`Path(root).resolve()`, which is always the invoking process's actual cwd
(or an explicit `--root`) -- there is no glob/mtime-based "most recently
touched worktree" guess anywhere in this module. And `compare`'s default
root, since #971, is the *recorded* root from the before-snapshot, not the
live cwd at compare time -- so even a `compare` call made from a sibling
worktree's cwd re-snapshots the worktree the `snapshot` call actually
looked at.

This test pins that: real `git worktree add` siblings, a `compare` whose
cwd sits in the *other* sibling, and both a "nothing changed" and a "one
file really changed" case. No mechanism reproducing the reported false
positive was found; see the #1024 report for the full writeup. This is a
regression pin against real worktree siblings, not a red-then-green fix --
the incident's own hypothesis (a cross-worktree resolution heuristic) does
not exist in the code, so there was no bug to turn from red to green.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tree_snapshot.py"


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(args, cwd, check=True, env=None):
    result = subprocess.run(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=env or _git_env(),
    )
    if check and result.returncode != 0:
        raise AssertionError(
            "{0} failed ({1}): {2}".format(args, result.returncode, result.stderr)
        )
    return result


def _run_cli(args, cwd=None, stdin=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        cwd=cwd,
        input=stdin,
    )


@pytest.fixture
def sibling_worktrees(tmp_path):
    """A real main checkout plus a real `git worktree add` sibling of it --
    the actual shape #1024's incident describes, not two unrelated repos."""
    env = _git_env()
    main = tmp_path / "main"
    main.mkdir()
    done = _run(["git", "init", "--quiet", "."], cwd=main, check=False, env=env)
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip()))
    _run(["git", "config", "user.email", "t@example.com"], cwd=main, env=env)
    _run(["git", "config", "user.name", "t"], cwd=main, env=env)
    (main / "tracked.txt").write_text("original\n")
    _run(["git", "add", "."], cwd=main, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=main, env=env)

    sibling = tmp_path / "sibling"
    _run(
        ["git", "worktree", "add", "-b", "sibling-branch", str(sibling)],
        cwd=main,
        env=env,
    )
    return main, sibling


def test_compare_from_a_sibling_worktrees_cwd_still_reports_clean(sibling_worktrees):
    """`snapshot` taken in `main`; `compare` invoked with cwd sitting in the
    *sibling* worktree of the same repo, no `--root` passed to either call
    -- exactly the shape #1024's incident describes. Nothing in `main`
    changed, so this must report `clean`, never a false `mutated`."""
    main, sibling = sibling_worktrees
    before = _run_cli(["snapshot"], cwd=str(main)).stdout

    done = _run_cli(["compare", "--before", "-"], cwd=str(sibling), stdin=before)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "VERDICT: clean" in done.stdout, done.stdout + done.stderr


def test_compare_from_a_sibling_worktrees_cwd_still_reports_a_real_mutation(
    sibling_worktrees,
):
    """Positive control: `main` genuinely changes after the snapshot. A
    `compare` call made from the sibling's cwd must still catch it -- the
    cwd reset must not swallow a real mutation either."""
    main, sibling = sibling_worktrees
    before = _run_cli(["snapshot"], cwd=str(main)).stdout

    (main / "scratch_left_behind.txt").write_text("oops\n")

    done = _run_cli(["compare", "--before", "-"], cwd=str(sibling), stdin=before)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "VERDICT: mutated" in done.stdout, done.stdout + done.stderr
    assert "scratch_left_behind.txt" in done.stdout
