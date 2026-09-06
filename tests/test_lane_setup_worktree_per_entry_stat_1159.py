"""#1159 -- worktree_last_activity()'s own docstring promises "a partial walk
is reported as `could-not-tell` even when it already found some files" --
but that promise was only kept for the directory-level `os.walk(onerror=...)`
callback. A per-entry `os.lstat` failure inside the walk (a file or
subdirectory that becomes unreadable between `os.walk` listing it and this
function stat'ing it) was silently swallowed (`continue` / `pass`) instead,
so an unreadable *recently touched* entry could return a stale `mtime` under
a confident `resolved` state -- exactly the opposite of the promise.

Paired with a clean-tree positive control in the same fixture, per this
repo's own rule that a negative assertion needs one.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup_worktree  # noqa: E402


def test_an_unreadable_file_forces_could_not_tell_not_a_stale_resolved(
    tmp_path, monkeypatch
):
    older = tmp_path / "older.txt"
    older.write_text("old")
    os.utime(str(older), (1000, 1000))

    poisoned = tmp_path / "poisoned.txt"
    poisoned.write_text("x")

    real_lstat = os.lstat

    def flaky_lstat(path, *a, **kw):
        if os.path.normpath(str(path)) == os.path.normpath(str(poisoned)):
            raise OSError("permission denied (simulated)")
        return real_lstat(path, *a, **kw)

    monkeypatch.setattr(os, "lstat", flaky_lstat)

    result = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert result["state"] == "could-not-tell"
    assert result["mtime"] is None


def test_a_clean_tree_still_resolves_positive_control(tmp_path):
    f = tmp_path / "clean.txt"
    f.write_text("x")
    os.utime(str(f), (5000, 5000))

    result = lane_setup_worktree.worktree_last_activity(str(tmp_path))

    assert result["state"] == "resolved"
    assert result["mtime"] == pytest.approx(5000, abs=0.01)
