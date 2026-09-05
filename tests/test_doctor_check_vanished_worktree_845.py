"""#845: `check_vanished_worktrees` is the loud detector filed in place of a
fix -- see `scripts/doctor_check_vanished_worktree.py`'s own docstring for why
no fix was written. This is the doctor-line test the same way
`test_trap_curate_905.py` tests `check_trap_queue`'s own line: the count only
reaches a maintainer through `doctor` and nowhere else that runs unprompted,
so the line is the whole forcing function and is tested rather than assumed --
tested in the state that matters most, the one where a worktree really is gone.
"""

import contextlib
import io
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import lane_setup  # noqa: E402


def _write_record(worktree_root, issue, path, branch=None, age_seconds=0):
    root = lane_setup.lane_registry_dir(str(worktree_root))
    import os

    os.makedirs(root, exist_ok=True)
    record_path = os.path.join(root, "{0}.json".format(issue))
    payload = {
        "issue": issue,
        "branch": branch if branch is not None else "fix/{0}".format(issue),
        "path": path,
        "recorded_at": time.time() - age_seconds,
        "files": ["scripts/x.py"],
    }
    with open(record_path, "w") as fh:
        json.dump(payload, fh)
    return record_path


def _doctor_line(project_dir, config):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor.check_vanished_worktrees(str(project_dir), config)
    return buf.getvalue().strip()


def test_doctor_reports_a_genuine_skip_as_warn_not_ok_when_worktree_root_is_unknown(
    tmp_path,
):
    """Found by this lane's own auditor round (#845): a run that never called
    `detect_vanished_worktrees` at all (no derivable worktree_root -- the
    ordinary state for a fresh install or a config-less tree) used to print
    `OK ... not checked`, indistinguishable from a check that ran and found
    nothing. `doctor.py`'s own convention (`unmeasured`'s docstring, and the
    sibling `worktree_root` check two lines earlier in `main()`) is that a
    genuine skip is WARN, never OK -- OK is reserved for a check that
    actually ran and came back clean."""
    line = _doctor_line(tmp_path, {})
    assert line.startswith("WARN "), line
    assert "not checked" in line


def test_doctor_reports_ok_when_nothing_is_live(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    line = _doctor_line(tmp_path, {"worktree_root": str(root)})
    assert line.startswith("OK "), line


def test_doctor_reports_ok_when_the_live_worktree_is_present(tmp_path):
    root = tmp_path / "wt"
    lane_dir = root / "845"
    lane_dir.mkdir(parents=True)
    _write_record(root, 845, str(lane_dir))
    line = _doctor_line(tmp_path, {"worktree_root": str(root)})
    assert line.startswith("OK "), line
    assert "none" in line


def test_doctor_warns_when_a_live_worktree_has_vanished(tmp_path):
    """The #845 shape itself: a live record, no worktree on disk."""
    root = tmp_path / "wt"
    lane_dir = root / "845"
    lane_dir.mkdir(parents=True)
    _write_record(root, 845, str(lane_dir))
    lane_dir.rmdir()
    line = _doctor_line(tmp_path, {"worktree_root": str(root)})
    assert line.startswith("WARN "), line
    assert "#845" in line
    assert "reflog" in line
