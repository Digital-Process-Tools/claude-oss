"""#373: `worktree_occupancy` rendered three states -- `already exists` / `free` /
`unknown` -- and the third was unreachable for the case it exists for. `os.path.exists`
swallows `OSError`, so an unreadable parent came back `False` and printed `[free]`: a
confident absence, in a receipt a maintainer pastes into a developer brief.

The settling fact was inside the same release delta. `doctor._dir_state` (#363, landed
as `be36015`) answers `unreadable` on the identical path in the identical run, so two
scripts in one repository disagreed about one input and the wrong one was the one whose
output gets pasted.

**The judgement call the issue leaves open, and the answer taken here.** `_dir_state`
was not moved to a module both files import. It lives in `scripts/doctor.py`, has four
call sites there and its own tests, and lifting it is a refactor with a blast radius
well past this lane -- the coordinator's brief said to solve locally rather than
refactor unreviewed if so. Instead `worktree_occupancy` grew the same *mechanism*
(`stat()` in a try, the two absence subclasses caught ahead of the general `OSError`
arm) while keeping its own narrower question: it asks "is anything there", not "is this
a directory", so this is a sibling rather than a second copy of the same classifier.

What keeps the two from drifting is not the prose above but
`test_the_two_classifiers_agree_on_the_same_path` below, which runs both on one fixture
and fails if either changes its mind. That is the second-measurement mechanism CLAUDE.md
asks for rather than a test that states the same claim twice.

The deny is never assumed. Every case attempts the exact operation the code under test
performs and skips loudly, carrying the platform and what went untested, when the
platform did not produce it -- root ignores the mode bit, some filesystems ignore it,
and Windows' `os.chmod` on a directory toggles a read-only attribute that does not stop
a traversal.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _deny(parent, child):
    """Make `child` unstattable by removing traversal on `parent`, and confirm it took.

    Returns the exception the real operation raised, or None when the platform did not
    produce the condition. Never asserts on an errno from a table: the question is
    whether *this* run can reach the case at all, and only attempting it answers that.
    """
    try:
        os.chmod(str(parent), 0o000)
    except OSError:
        return None
    try:
        os.stat(str(child))
    except OSError as exc:
        return exc
    return None


def _restore(parent):
    try:
        os.chmod(str(parent), 0o755)
    except OSError:
        pass


@pytest.fixture
def denied(tmp_path):
    """A child under a parent that cannot be traversed, or a loud skip."""
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    child.mkdir()
    exc = _deny(parent, child)
    if exc is None:
        _restore(parent)
        pytest.skip(
            "this platform did not produce an unreadable parent: os.stat on the child "
            "succeeded after chmod 000 (running as root, a filesystem that ignores the "
            "mode bit, or Windows, where chmod on a directory toggles a read-only "
            "attribute that does not stop traversal). UNTESTED here: that "
            "worktree_occupancy answers unknown rather than free when it cannot look. "
            "platform={}".format(sys.platform)
        )
    try:
        yield child, exc
    finally:
        _restore(parent)


# ------------------------------------------------------- the two must-fire controls


def test_an_existing_path_is_true(tmp_path):
    """Control: `already exists` still resolves. A guard that answered `unknown` for
    everything would pass the silence assertion below and fail here.
    """
    here = tmp_path / "here"
    here.mkdir()
    assert lane_setup.worktree_occupancy(str(here)) is True


def test_an_absent_path_is_false(tmp_path):
    """Control: `free` still resolves, and genuine absence must not fold into
    `unknown`. #363's own self-review records breaking exactly this while fixing the
    unreadable case, so it is pinned rather than assumed.
    """
    assert lane_setup.worktree_occupancy(str(tmp_path / "nope")) is False


def test_a_path_under_a_file_is_false(tmp_path):
    """`NotADirectoryError` is ordinary absence, not an unreadable parent -- the other
    half of the same distinction, and the one whose exception type differs.
    """
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    assert lane_setup.worktree_occupancy(str(afile / "under")) is False


def test_no_path_is_unknown():
    """The one route to `unknown` that already worked."""
    assert lane_setup.worktree_occupancy("") is None
    assert lane_setup.worktree_occupancy(None) is None


# --------------------------------------------------------------- the defect itself


def test_an_unreadable_parent_is_unknown_not_free(denied):
    child, exc = denied
    verdict = lane_setup.worktree_occupancy(str(child))
    assert verdict is None, (
        "could not look, and answered {!r} instead of unknown; the real operation "
        "raised {}: {}".format(verdict, type(exc).__name__, exc)
    )


def test_the_receipt_says_unknown_not_free(denied):
    """The harm is the rendered word, not the return value. `[free]` is the sentence a
    maintainer pastes into a brief.
    """
    child, _ = denied
    payload = {
        "issue": 373,
        "repo": ".",
        "config": {"state": "ok", "problems": []},
        "base": {
            "state": "could-not-resolve",
            "remote": "origin",
            "ref": None,
            "sha": None,
            "detail": "x",
        },
        "branch": {
            "state": "unknown",
            "pattern": None,
            "name": None,
            "detail": "x",
            "exists_local": None,
            "exists_remote": None,
        },
        "worktree": {
            "state": "resolved",
            "root": str(child.parent),
            "path": str(child),
            "detail": "",
            "exists": lane_setup.worktree_occupancy(str(child)),
        },
        "board": {"state": "could-not-run", "lines": [], "detail": "x"},
    }
    row = [
        ln
        for ln in lane_setup.receipt(payload).splitlines()
        if ln.startswith("worktree  :")
    ]
    assert len(row) == 1, row
    assert row[0].endswith("[unknown]"), row[0]
    assert "[free]" not in row[0], row[0]


def test_the_two_classifiers_agree_on_the_same_path(denied):
    """The drift guard, and the reason `_dir_state` was not copied.

    `doctor._dir_state` answers a different question -- dir / absent / unreadable --
    but the third state is the same fact about the same path. If either side later
    changes its mind about an unreadable parent, this fails; a test asserting each one
    separately against a fixed expectation would state the same claim twice and pass
    whenever both were wrong together.
    """
    doctor = pytest.importorskip("doctor")
    child, _ = denied
    state, detail = doctor._dir_state(child)
    assert state == "unreadable", (state, detail)
    assert lane_setup.worktree_occupancy(str(child)) is None


def test_the_two_classifiers_agree_that_a_readable_path_is_readable(tmp_path):
    """Must-fire control for the agreement test: both must also agree when there is
    nothing wrong, or the pair could agree only by both being broken.
    """
    doctor = pytest.importorskip("doctor")
    here = tmp_path / "here"
    here.mkdir()
    assert doctor._dir_state(here)[0] == "dir"
    assert lane_setup.worktree_occupancy(str(here)) is True
