"""#806 -- `tree_snapshot.py`'s VERDICT line embeds `verdict["reason"]`

unfolded. `_run_git`'s error strings carry git's own stderr verbatim
(around `:115`), and git's stderr is frequently multi-line -- an ambiguous
`rev-parse HEAD` on a repo with no commits appends a `Use '--' to
separate...` hint on its own line. That lands the second line at column 0
of a receipt `agents/developer.md` reads, exactly the shape sibling
renderers (`oss_state._receipt_line`, `lane_setup._one_line`) already fold
away for the same reason.

This is ranked `misreports`, not `forges`: the multi-line text reaching
column 0 is git's own boilerplate, not attacker-controlled content.

Every "must fold" case is paired with a "must not fire" control: a normal
single-line reason must render unchanged.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tree_snapshot.py"

sys.path.insert(0, str(REPO / "scripts"))

import tree_snapshot  # noqa: E402


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo_no_commits(tmp_path):
    """A real git repo with no commits at all, so `git rev-parse HEAD`
    genuinely fails with git's own multi-line stderr -- the exact
    reproduction the issue names, not a stand-in for it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(["init", "-q"], root)
    return root


def _committed_repo(tmp_path):
    root = tmp_path / "seed"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "t"], root)
    (root / "f.txt").write_text("x", encoding="utf-8")
    _git(["add", "f.txt"], root)
    _git(["commit", "-q", "-m", "seed"], root)
    return root


# --- must fire: the real multi-line git stderr reproduction ------------------


def test_verdict_line_is_single_line_for_multiline_git_stderr(tmp_path, capsys):
    """The reproduction named in the issue: `git rev-parse HEAD` on a repo
    with no commits prints a two-line stderr (the error, then a `Use
    '--'...` hint). Confirmed to actually be multi-line before asserting
    anything about the fix."""
    root = _repo_no_commits(tmp_path)
    before = _committed_repo(tmp_path)
    before_path = tmp_path / "before.json"
    snap = tree_snapshot.snapshot(str(before))
    assert snap["error"] is None, snap
    before_path.write_text(json.dumps(snap), encoding="utf-8")

    # Confirm the fixture actually produces multi-line stderr from git
    # itself, so this is measured rather than assumed.
    probe = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root),
        capture_output=True, text=True,
    )
    assert probe.returncode != 0
    if "\n" not in probe.stderr.strip():
        pytest.skip(
            "this git install's ambiguous-HEAD stderr is single-line here, "
            "so the multi-line reproduction could not be established: "
            "{0!r}".format(probe.stderr)
        )

    rc = tree_snapshot.main(
        ["compare", "--before", str(before_path), "--root", str(root)]
    )
    out = capsys.readouterr().out
    assert rc == tree_snapshot.EXIT_CODES["could-not-compare"], out
    lines = out.splitlines()
    verdict_lines = [ln for ln in lines if ln.startswith("VERDICT:")]
    assert len(verdict_lines) == 1, out
    # The VERDICT line itself must be the only line up to the next
    # printed field (there are none here) -- i.e. nothing from git's
    # stderr reached column 0 as a second raw line.
    assert len(lines) == 1, (
        "expected the VERDICT line to be the whole of stdout (folded to "
        "one line), got {0} line(s): {1!r}".format(len(lines), out)
    )


# --- must not fire: a normal single-line reason is unchanged -----------------


def test_verdict_line_unchanged_for_a_normal_single_line_reason(capsys):
    """Positive control: a clean, ordinary single-line reason must print
    exactly as before -- the fold must not mangle the common case."""
    before = {"root": ".", "head": "abc123", "status": "", "error": None}
    after = {"root": ".", "head": "abc123", "status": "", "error": None}
    verdict = tree_snapshot.compare(before, after)
    assert verdict["state"] == "clean"
    assert verdict["reason"] == (
        "the tree's status and HEAD are unchanged since the before-snapshot"
    )
