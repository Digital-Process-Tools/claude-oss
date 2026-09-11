"""#1430: `SNAPSHOT_ARTIFACT_RE` excludes any status line whose path matches
the generic before-snapshot naming convention, at ANY depth -- not anchored
to the specific snapshot file the caller actually passed to `compare`
(`--before <path>`, or the `own_snapshot_path` kwarg on the Python API).

An unrelated file a lane genuinely creates that happens to also match the
naming convention (e.g. `src/anything-before-snapshot.json`, a fixture or
scratch file with no relation to this module's own bookkeeping artifact) is
therefore invisible to the mutation detector even though it is a real,
reportable mutation.

The fix anchors the exclusion to the caller-supplied snapshot path when one
is known (the ordinary CLI shape, `compare --before <path>`), falling back
to the old, unanchored pattern match only when no such path is available
(reading the before-snapshot from stdin, or a direct Python caller that
built the dicts by hand without saying where the snapshot itself lives) --
so every existing caller (`tests/test_tree_snapshot_own_artifact_1330.py`,
which calls `compare(before, after)` with no path at all) keeps its current
behaviour unchanged.
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
    (repo / "tracked.txt").write_text("original content")
    subprocess.run(["git", "-C", str(repo), "add", "."], env=env, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "initial"],
        env=env,
        check=True,
    )
    return repo


def test_an_unrelated_file_matching_the_naming_convention_is_reported_when_anchored(
    tmp_path,
):
    """Must-fire: when the caller names its own snapshot path, a DIFFERENT
    file that happens to match the generic naming convention (a fixture or
    scratch file, not the snapshot the caller actually took) must still be
    reported as a mutation rather than silently absorbed by the pattern.
    """
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "src").mkdir()
    (repo / "src" / "anything-before-snapshot.json").write_text("{}")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(
        before, after, own_snapshot_path="1430-before-snapshot.json"
    )
    assert verdict["state"] == "mutated", verdict
    assert any("anything-before-snapshot.json" in line for line in verdict["added"]), (
        verdict
    )


def test_a_different_directory_with_the_same_basename_is_not_falsely_excluded(
    tmp_path,
):
    """Self-review finding (#1430, both spawned reviewers found this
    independently): the first anchoring attempt matched on a shared
    BASENAME alone whenever `own_snapshot_path` was a bare filename with no
    directory component (the ordinary case -- see #1330's own convention
    of writing the before-snapshot inside the worktree it snapshots). That
    silently re-admits the exact ambiguity the anchoring fix exists to
    remove: a real, unrelated file at a DIFFERENT path that happens to
    share the caller's own snapshot basename must still be reported.
    """
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "important").mkdir()
    (repo / "important" / "1430-before-snapshot.json").write_text("{}")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(
        before, after, own_snapshot_path="1430-before-snapshot.json"
    )
    assert verdict["state"] == "mutated", verdict
    assert any(
        "important/1430-before-snapshot.json" in line for line in verdict["added"]
    ), verdict


def test_the_actual_snapshot_file_is_still_excluded_when_anchored(tmp_path):
    """Must-not-fire, same fixture shape: the snapshot the caller actually
    named must still be excluded when anchored, exactly as it was under the
    old unanchored pattern match.
    """
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "1430-before-snapshot.json").write_text("{}")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(
        before, after, own_snapshot_path="1430-before-snapshot.json"
    )
    assert verdict["state"] == "clean", verdict


def test_unanchored_compare_keeps_its_old_unrelated_pattern_match_behaviour(tmp_path):
    """Existing callers that never pass a path (`tests/test_tree_snapshot_
    own_artifact_1330.py`'s own tests) must be unaffected: with no anchor,
    the generic pattern match is the fallback, unchanged.
    """
    repo = _real_git_repo(tmp_path)
    before = tree_snapshot.snapshot(str(repo))
    (repo / "1330-before-snapshot.json").write_text("{}")
    after = tree_snapshot.snapshot(str(repo))

    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "clean", verdict


def test_cli_compare_anchors_the_exclusion_to_the_before_flag(tmp_path):
    """The CLI's `compare --before <path>` shape must pass that path through
    to `compare()` as the anchor -- an unrelated file elsewhere in the tree
    that matches the naming convention must be reported as mutated even
    though the CLI ran, not just the Python API."""
    repo = _real_git_repo(tmp_path)
    before_path = repo / "1430-before-snapshot.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "tree_snapshot.py"),
            "snapshot",
            "--root",
            str(repo),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    before_path.write_text(result.stdout)

    (repo / "src").mkdir()
    (repo / "src" / "anything-before-snapshot.json").write_text("{}")

    done = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "tree_snapshot.py"),
            "compare",
            "--before",
            str(before_path),
            "--root",
            str(repo),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "VERDICT: mutated" in done.stdout, done.stdout
    assert "anything-before-snapshot.json" in done.stdout, done.stdout
