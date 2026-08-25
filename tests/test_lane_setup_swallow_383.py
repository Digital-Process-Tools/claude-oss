"""#383: the swallow census, `scripts/lane_setup.py`.

Review of the first pass on this issue (a reviewer spawned against this same
diff) found that `resolve_lane`'s `if p.is_file()` glob filter is not the
harmless "filter, may swallow" site the sibling in `assemble_changelog.py`
is. `Path.is_file()` wraps its own `stat()` call in a version-dependent
swallow (CLAUDE.md's own trap; also `doctor._dir_state`'s docstring, which
measured the swallow directly on a local 3.14 install and found `path.stat()`
itself does not swallow there, only the convenience method does). A match
`glob()` found but this process cannot `stat()` -- an entry-level failure,
independent of the directory-traversal permission `glob()` already needed --
used to disappear from `matches` silently instead of reaching the
`except (OSError, ValueError)` a few lines above it, which already exists to
turn an unreadable pattern into a `"refused"` state with a detail. An empty
`matches` after a silent drop reports `"glob-no-match"` -- a printed verdict
`lane_overlap` consumes for the disjointness check #267 exists for -- which
is indistinguishable from the pattern genuinely matching nothing.

The fix asks `p.stat()` directly, which this file's own `_absence_confirmed`
and `worktree_occupancy` already establish does not swallow on any
interpreter this repo has measured, and lets any non-`FileNotFoundError`
`OSError` propagate into the try/except that already surrounds the
comprehension -- no new exception class, no new state, just routing the
version-dependent swallow around the one existing swallow-tolerant caller
that never sees it, and giving it to the one that already refuses instead.

Every "must not fire" case (an entry-level stat failure must not silently
drop out of `matches`) is paired with a "must fire" control in the same
fixture (a genuine non-file match -- a subdirectory -- is still excluded,
and an ordinary readable file is still matched) -- CLAUDE.md's own rule for
a negative assertion.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def test_glob_match_unstatable_entry_is_refused_not_silently_dropped_injected(
    monkeypatch, tmp_path
):
    """Must-fire half, reproducing the swallow itself rather than a raise.

    On this interpreter (measured directly: `Path.stat` raising propagates
    straight through `Path.is_file()` uncaught -- `is_file()` only swallows
    `FileNotFoundError`-class errors here, not `PermissionError`), patching
    `Path.stat` to raise would pass whether or not the fix landed, because
    the *old* code's `p.is_file()` already re-raises on this version and
    the pre-existing `except (OSError, ValueError)` around the whole
    comprehension already catches it -- this platform cannot exercise the
    swallow that way. `doctor._dir_state`'s own docstring records the
    swallow as version-dependent, live only on some interpreters (measured
    there on a local 3.14 install; `path.stat()` itself does not swallow on
    any version this repo has measured). So this patches `Path.is_file`
    directly to *return* `False` for the one real, statable file -- exactly
    what a swallowing interpreter's `is_file()` would do -- while leaving
    `Path.stat` untouched. The buggy code path (`if p.is_file()`) then
    drops the entry silently; the fixed code path (`p.stat()` +
    `stat.S_ISREG`) does not, because it never calls the wrapper this
    patches.
    """
    repo = tmp_path
    (repo / "changelog.d").mkdir()
    target = repo / "changelog.d" / "383.fixed.md"
    target.write_text("- x (#383)\n", encoding="utf-8")

    real_is_file = Path.is_file
    target_str = str(target)

    def fake(self, *a, **kw):
        if str(self) == target_str:
            return False
        return real_is_file(self, *a, **kw)

    monkeypatch.setattr(Path, "is_file", fake)

    result = lane_setup.resolve_lane(repo, ["changelog.d/*.md"])
    entry = result["patterns"][0]
    assert entry["state"] == "glob-resolved", entry
    assert entry["files"] == ["changelog.d/383.fixed.md"], entry


def test_glob_match_subdirectory_is_still_excluded_control(tmp_path):
    """Must-not-fire control, same fixture family: a directory `glob()`
    surfaces alongside real matches is still excluded from `files` --
    the fix must not turn every non-file match into a false `refused`.
    """
    repo = tmp_path
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "sub").mkdir()
    (repo / "changelog.d" / "383.fixed.md").write_text(
        "- x (#383)\n", encoding="utf-8"
    )

    result = lane_setup.resolve_lane(repo, ["changelog.d/*"])
    entry = result["patterns"][0]
    assert entry["state"] == "glob-resolved", entry
    assert entry["files"] == ["changelog.d/383.fixed.md"], entry


def test_glob_pattern_still_resolves_normally_control(tmp_path):
    """Second control: the ordinary readable case, unaffected by the fix."""
    repo = tmp_path
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "383.fixed.md").write_text(
        "- x (#383)\n", encoding="utf-8"
    )

    result = lane_setup.resolve_lane(repo, ["changelog.d/*.md"])
    entry = result["patterns"][0]
    assert entry["state"] == "glob-resolved", entry
    assert entry["files"] == ["changelog.d/383.fixed.md"], entry


def test_glob_match_unstatable_entry_real_chmod(tmp_path):
    """Attempted real-filesystem reproduction of the must-fire case above,
    and it does not take -- reported as a measurement, not a given
    (CLAUDE.md, "a permission fixture is a measurement, not a given").

    `os.chmod`-denying a subdirectory's traversal bit does not isolate
    "`glob()` found the entry but `stat()` cannot reach it": it prevents
    `glob()` from enumerating the entry at all -- `repo.glob()` swallows
    `PermissionError` while it walks, exactly the `Path.rglob` shape
    CLAUDE.md already documents, for `glob("**/...")` too (measured
    directly below). So a denied subdirectory produces `glob-no-match`
    regardless of whether `_match_is_regular_file` is fixed -- the entry
    was never a candidate in the first place, which is a *different*,
    unfixed defect in `repo.glob()`'s own traversal (recorded separately,
    not this test's subject) rather than the entry-level `stat()` swallow
    this file's injected test reproduces. There is no real-filesystem
    construction that separates the two on POSIX: `stat()` on a regular
    file and `glob()`'s enumeration of its parent need the identical
    directory-execute permission, so nothing this test can chmod isolates
    one from the other. What went untested: the entry-level swallow this
    fix addresses, on a real filesystem, on any platform -- it can only be
    observed through a version-dependent interpreter behaviour (the
    injected test), not a permission fixture.
    """
    repo = tmp_path
    changelog_dir = repo / "changelog.d"
    changelog_dir.mkdir()
    sub = changelog_dir / "sub"
    sub.mkdir()
    (sub / "383.fixed.md").write_text("- x (#383)\n", encoding="utf-8")

    try:
        os.chmod(str(sub), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); nothing to measure here "
            "either way".format(exc)
        )
    try:
        if os.access(str(sub / "383.fixed.md"), os.F_OK):
            pytest.skip(
                "this process can still stat under a 0o000 directory "
                "(root, or a filesystem without POSIX modes); nothing to "
                "measure here either way"
            )
        matches = sorted(changelog_dir.glob("**/*.md"))
        assert matches == [], (
            "glob() found the denied subtree after all on this platform -- "
            "the premise this test's docstring is built on does not hold "
            "here: {}".format(matches)
        )
        pytest.skip(
            "confirmed: repo.glob() swallows the denied subdirectory during "
            "its own traversal on this platform, so this construction "
            "cannot isolate the entry-level stat() swallow "
            "_match_is_regular_file fixes -- see this test's docstring; "
            "what went untested is that fix, on a real filesystem"
        )
    finally:
        os.chmod(str(sub), 0o755)
