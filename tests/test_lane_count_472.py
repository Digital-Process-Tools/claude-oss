"""#472: `lane_count`'s absence detail overclaimed for a registry it could not examine.

`os.path.isdir` (`genericpath.isdir`) swallows `(OSError, ValueError)` unconditionally, so
a registry that exists under an untraversable parent used to answer `False` from that
check and `lane_count` returned the `unknown` `detail` claiming "either nothing has ever
recorded itself here, or nothing is live" -- both false, since a registry with a live
record was right there and merely could not be reached.

The fix probes rather than only rewording: `os.stat` decides which arm runs (the same
move `worktree_occupancy` already made for the identical swallow, #373/#380), so an
untraversable parent is reported as `could-not-run` (a registry may exist here, and it
was not examined) instead of being folded into `unknown` (a registry does not exist
here). `state` was already honestly `unknown` before this fix per the issue; this test
pins the `detail` and the new `could-not-run` `state` together, because a caller in a
hurry only reads one of the two.

The deny is never assumed -- established by attempting the exact operation the code
under test performs (`os.stat` on the registry directory), and skipped loudly, carrying
what went untested, when the platform does not produce it (root, a filesystem that
ignores the mode bit, or Windows, where `chmod` on a directory does not stop traversal).
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _write_record(worktree_root, issue, age_seconds=0):
    root = lane_setup.lane_registry_dir(worktree_root)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "{0}.json".format(issue))
    payload = {
        "issue": issue,
        "branch": "fix/{0}".format(issue),
        "path": None,
        "recorded_at": time.time() - age_seconds,
        "pid": 1,
    }
    with open(path, "w") as fh:
        json.dump(payload, fh)
    return path


def _deny(parent, child):
    """Make `child` unstattable by removing traversal on `parent`, and confirm it took.

    Returns the exception the real operation raised, or None when the platform did not
    produce the condition -- the permission fixture is a measurement, not a given.
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
def denied_registry(tmp_path):
    """A worktree root whose lane registry exists and holds one live record, with the
    root itself made untraversable -- or a loud skip, never an assumed deny.
    """
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    live_path = _write_record(str(worktree_root), 111, age_seconds=60)
    registry_dir = lane_setup.lane_registry_dir(str(worktree_root))
    exc = _deny(worktree_root, registry_dir)
    if exc is None:
        _restore(worktree_root)
        pytest.skip(
            "this platform did not produce an unreadable parent: os.stat on the "
            "registry succeeded after chmod 000 (running as root, a filesystem that "
            "ignores the mode bit, or Windows, where chmod on a directory does not "
            "stop traversal). UNTESTED here: that lane_count reports could-not-run "
            "rather than unknown for a registry it cannot examine. "
            "platform={}".format(sys.platform)
        )
    try:
        yield str(worktree_root), live_path
    finally:
        _restore(worktree_root)


# ------------------------------------------------------- the two must-fire controls


def test_a_live_record_under_a_readable_registry_still_resolves(tmp_path):
    """Control: the ordinary, readable case must still resolve. A guard that answered
    could-not-run for everything would pass the silence assertion below and fail here.
    """
    root = str(tmp_path / "worktrees")
    _write_record(root, 111, age_seconds=60)

    result = lane_setup.lane_count(root)

    assert result["state"] == "resolved"
    assert result["count"] == 1


def test_a_genuinely_absent_registry_still_reports_unknown(tmp_path):
    """Control: genuine absence must not fold into could-not-run either. Paired with
    the denied-registry test below so each `detail` is asserted on its own fixture.
    """
    root = str(tmp_path / "never-written")

    result = lane_setup.lane_count(root)

    assert result["state"] == "unknown"
    assert result["count"] is None
    assert "confirmed zero is not distinguishable" in result["detail"]


# --------------------------------------------------------------------- the defect itself


def test_a_registry_under_a_denied_parent_is_could_not_run_not_unknown(denied_registry):
    root, live_path = denied_registry

    result = lane_setup.lane_count(root)

    assert result["state"] == "could-not-run", (
        "a registry that exists and could not be examined was reported as {0!r} -- "
        "the record at {1} is still on disk".format(result["state"], live_path)
    )
    assert result["count"] is None


def test_the_denied_registry_detail_does_not_claim_a_confirmed_absence(denied_registry):
    """The harm the issue names: the *sentence*, not just the state. A caller in a
    hurry may print only `detail`.
    """
    root, _ = denied_registry

    result = lane_setup.lane_count(root)

    detail = result["detail"]
    assert "nothing has ever recorded" not in detail, detail
    assert "confirmed zero" not in detail, detail
