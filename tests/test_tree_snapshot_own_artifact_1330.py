"""#1330 -- `compare` counted its own before-snapshot artifact as a mutation.

A lane following `.claude/jit-context/tools/01-oss/tree-snapshot-compare.md`'s
own advice writes the before-snapshot JSON *inside* the worktree it is about
to snapshot (a shared-scratchpad copy can vanish mid-run -- see that rule's
own incident). At `compare` time, that file is by construction an untracked
addition relative to the before-snapshot, since it did not exist when the
before-snapshot was taken. Nothing distinguished it from an unrelated
mutation, so a lane's own bookkeeping artifact was reported as `mutated`
(observed once in practice during PR #1291's own self-review round, per
#1330's own provenance -- `agents/developer/review.md`'s own worked example
keeps the before-snapshot in a shell variable and pipes it via stdin rather
than writing a file, so this shape is one real, observed variant of the
documented workflow rather than the only one).

`compare` now recognises a file matching `tree_snapshot.py`'s own
before-snapshot naming convention (see `tree_snapshot.SNAPSHOT_ARTIFACT_RE`)
and excludes it from the added/removed lines it reports -- never a single
hardcoded literal filename, since the convention is a pattern (any issue
number prefix), not one fixed name.

**Negative assertion paired with a positive control (this repo's own rule):**
`test_compare_excludes_its_own_before_snapshot_artifact` is the "must not
fire" case; `test_compare_still_catches_an_unrelated_untracked_file` is the
"must fire" case in the same shape, so a comparator that always answered
`clean` cannot pass both.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "scripts"))

import tree_snapshot  # noqa: E402


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _real_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_env()
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "t"], env=env, check=True
    )
    (repo / "tracked.txt").write_text("original content\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], env=env, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "initial"],
        env=env,
        check=True,
    )
    return repo


def test_compare_excludes_its_own_before_snapshot_artifact(tmp_path):
    """Must-not-fire: the lane's own before-snapshot JSON, written inside the
    worktree per the jit-context recommendation, must not itself read as a
    mutation."""
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "1330-before-snapshot.json").write_text("{}")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "clean", verdict
    assert verdict["added"] == [], verdict


def test_compare_still_catches_an_unrelated_untracked_file(tmp_path):
    """Must-fire positive control in the same fixture shape: a genuine
    untracked file left behind by a reviewer must still be reported."""
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "scratch-leftover.txt").write_text("oops\n")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "mutated", verdict
    assert any("scratch-leftover.txt" in line for line in verdict["added"]), verdict


def test_compare_excludes_own_artifact_even_alongside_a_real_mutation(tmp_path):
    """The exclusion is per-line, not all-or-nothing: a real mutation next to
    the lane's own snapshot artifact must still surface, with the artifact
    line itself absent from what's reported."""
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "1330-before-snapshot.json").write_text("{}")
    (repo / "scratch-leftover.txt").write_text("oops\n")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "mutated", verdict
    assert any("scratch-leftover.txt" in line for line in verdict["added"]), verdict
    assert not any("1330-before-snapshot.json" in line for line in verdict["added"]), (
        verdict
    )
