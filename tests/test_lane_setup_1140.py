"""#1140: worktree_last_activity() cannot see a create-then-delete cycle
that leaves no surviving file, because the walk only ever stat'ed files it
found via os.walk(), never a directory's own mtime.

Fixed by folding every SUBdirectory's own mtime into the walk (root
excluded -- see the function's own docstring for why: the root's own mtime
is set the instant `git worktree add` creates it, before any file exists
inside it, and folding that in would flip `empty` for every freshly created
worktree, a wider change #1140 itself defers).

Every must-fire is paired with a must-not-fire in the same fixture, per
this repository's own rule for a negative assertion (CLAUDE.md).
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup_worktree  # noqa: E402


def test_a_create_then_delete_cycle_with_no_surviving_file_is_now_seen(tmp_path):
    """The exact #1140 mechanism: a lock file created and deleted inside a
    subdirectory bumps that subdirectory's own mtime, with nothing left on
    disk for a file-only walk to find. An older, unrelated file survives
    elsewhere in the tree so a walk that never looked at directory mtimes at
    all would report the OLDER file's time instead -- the wrong answer, not
    an absent one, which is what makes this a positive control rather than
    a duplicate of the existing empty/resolved tests."""
    older_survivor = tmp_path / "older.txt"
    older_survivor.write_text("old")
    os.utime(str(older_survivor), (1000, 1000))

    sub = tmp_path / "sub"
    sub.mkdir()
    transient = sub / "lock"
    transient.write_text("x")
    transient.unlink()
    # Force the subdirectory's own mtime forward deterministically, the same
    # way the existing #1120 fixtures force a file's mtime forward rather
    # than trust two real filesystem operations a few milliseconds apart to
    # reliably differ on every platform's mtime resolution.
    os.utime(str(sub), (5000, 5000))

    result = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert result["state"] == "resolved"
    assert result["mtime"] == pytest.approx(5000, abs=0.01)


def test_the_roots_own_mtime_bump_is_still_not_folded_in(tmp_path):
    """Paired negative control for the test above: only a SUBdirectory's own
    mtime is now stat'ed, never the root path's own -- the root's mtime is
    set the instant the worktree is created, before any file exists inside
    it, and folding it in would flip `empty` for every freshly created
    worktree (documented as the still-open half of #1140). Bumping the root
    itself forward past a genuinely newer subdirectory must not move the
    reported mtime."""
    sub = tmp_path / "sub"
    sub.mkdir()
    os.utime(str(sub), (2000, 2000))
    # The root's own mtime is bumped past the subdirectory's, to the far
    # future -- if it were folded in, this would win.
    os.utime(str(tmp_path), (9999999, 9999999))

    result = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert result["state"] == "resolved"
    assert result["mtime"] == pytest.approx(2000, abs=0.01)


def test_empty_directory_with_only_empty_subdirectories_reports_resolved_not_empty(
    tmp_path,
):
    """A directory holding only empty subdirectories now reports `resolved`
    (the subdirectory's own creation mtime), not `empty` -- named as one of
    the two semantics questions #1140's own body raised, and settled here:
    folding SUBdirectory mtimes in necessarily answers this one, since a
    subdirectory's own creation is itself the mtime being folded in."""
    sub = tmp_path / "empty-sub"
    sub.mkdir()

    result = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert result["state"] == "resolved"
    assert result["mtime"] is not None


def test_a_directory_with_no_files_and_no_subdirectories_still_reports_empty(tmp_path):
    """Positive control for the test above, and for the pre-existing
    `test_empty_directory_is_not_confused_with_could_not_tell` in
    test_lane_setup_1120.py: a genuinely bare directory -- no files, no
    subdirectories -- is unaffected by this fix and still reports `empty`."""
    result = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert result["state"] == "empty"
    assert result["mtime"] is None
