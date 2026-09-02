"""#804: a regression introduced inside the 0.18.0 delta itself. Before #786,
`record_lane` read the previous record inside a
`try: ... except (OSError, ValueError, AttributeError): previous = None` guard. The
`AttributeError` arm existed for exactly one case: a record file holding valid JSON
that is not an object (a JSON list, most concretely) -- `json.load` succeeds, and
the crash only happens the moment something calls `.get` on the list.

#786's review round hoisted `previous = json.load(fh)` out of that guard, but left
`previous.get("files")` and `previous.get("branch")` outside it too -- so a
list-valued record file now crashes with
`AttributeError: 'list' object has no attribute 'get'` instead of `record_lane`
returning its documented three-state result (`recorded` / `unknown` /
`could-not-write`), the same as every other read failure this function's own
docstring says degrades safely ("best-effort... this call still succeeds and
refreshes the TTL").

Must-fire control: a registry file holding a JSON list for the issue being
claimed. Must-not-fire control: a normal well-formed record file, proving the fix
does not swallow a real error or stop the ordinary preserve-on-refresh behaviour
the docstring describes.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import lane_setup  # noqa: E402


def _registry_path(worktree_root, issue):
    root = lane_setup.lane_registry_dir(worktree_root)
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "{0}.json".format(issue))


def test_list_valued_record_file_no_longer_crashes(tmp_path):
    """Must-fire control: reproduces the exact repro from the issue body --
    a registry file holding a JSON list (not an object) for the issue being
    claimed. Pre-#786 and post-fix both return the same three-state receipt;
    the #786-introduced regression instead raised AttributeError."""
    worktree_root = str(tmp_path)
    record_path = _registry_path(worktree_root, 123)
    with open(record_path, "w") as fh:
        json.dump(["not", "an", "object"], fh)

    result = lane_setup.record_lane(worktree_root, 123, "fix/123", "/tmp/somewhere")

    assert result["state"] == "recorded"
    assert result["path"] == record_path
    with open(record_path) as fh:
        stored = json.load(fh)
    assert stored["issue"] == 123
    assert stored["branch"] == "fix/123"
    # A list-valued previous record carries no recoverable `files` or
    # `branch_confirmed_created` -- the read failed as an AttributeError would
    # have, just without crashing -- so both preserves fall through to their
    # documented safe default.
    assert stored["files"] is None
    assert "branch_confirmed_created" not in stored


def test_well_formed_record_file_still_preserves_files_on_refresh(tmp_path):
    """Must-not-fire control: an ordinary object-valued record file, proving the
    fix does not swallow a real error or break the documented preserve-on-refresh
    behaviour (files=None on this call falls back to the previous record's own
    files list)."""
    worktree_root = str(tmp_path)
    record_path = _registry_path(worktree_root, 456)
    with open(record_path, "w") as fh:
        json.dump(
            {
                "issue": 456,
                "branch": "fix/456",
                "path": "/tmp/somewhere",
                "recorded_at": 0,
                "pid": 1,
                "files": ["a.py", "b.py"],
            },
            fh,
        )

    result = lane_setup.record_lane(worktree_root, 456, "fix/456", "/tmp/somewhere")

    assert result["state"] == "recorded"
    with open(record_path) as fh:
        stored = json.load(fh)
    assert stored["files"] == ["a.py", "b.py"]
