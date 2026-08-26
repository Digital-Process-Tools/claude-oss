"""#566: `CROSS_CUTTING_GUARDS` names test paths that exist only in claude-oss's own
tree. A lane dispatched into a managed repository that does not carry one of those
files was told to run it anyway -- `resolve_lane`'s canonical form never asked
whether the guard test exists in the repository being managed, so "this guard
applies" and "this guard's test file is actually here" were the same claim. They
are not: a managed repo carrying none of the five is the ordinary case, not an
edge one (measured against `claude-supertool` in the issue, four of four absent).

Three candidate designs were weighed in the issue's own order: stat each guard
path in the managed repo (cheapest, keeps the table); move the table into
`.oss.json`; or derive it by grepping the managed repo. The existence check is
what is implemented here -- it is the only one of the three that fits inside this
lane's own file boundary (`scripts/lane_setup.py` and this test file only): the
config route needs a schema change in `scaffold.py`, which #564's lane holds for
this round, and the grep route needs a judgement call about what "a test naming
this trigger path" means that the issue itself does not settle. The existence
check also closes the silent case on its own, which is the whole of what #566
asks for -- the config route's extra power (a managed repo declaring a guard
claude-oss has never heard of) is real but is not what this bug is about.

Every "must fire" case here has a "must not fire" sibling in the same fixture,
per the issue's own control pair: a repository carrying a named guard must still
be told to run it, and a repository carrying none must be told that in as many
words -- never handed a path that collects nothing.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _repo_with_guard(tmp_path, present):
    """A minimal managed repo carrying `agents/developer.md` and, when `present`,
    the content-invariants guard test it should trip."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "developer.md").write_text("x\n")
    if present:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_content_invariants.py").write_text("x\n")
    return tmp_path


# --- backward compatibility: repo=None keeps the old, status-free shape --------


def test_guards_for_files_without_repo_carries_no_status_key():
    """Every existing caller of `guards_for_files` passes no `repo` -- #432's own
    test file among them. That shape must be unchanged: no `status` key at all,
    not a `status` of `None`, so an old caller's `entry["test"]` reads are
    unaffected and nothing new has to be handled by code that predates #566."""
    hits = lane_setup.guards_for_files(["agents/developer.md"])
    assert hits and "status" not in hits[0]


def test_known_guards_without_repo_carries_no_status_key():
    known = lane_setup.known_guards()
    assert known and "status" not in known[0]


# --- control pair: exists vs absent, same fixture shape -------------------------


def test_guard_reports_exists_when_the_managed_repo_carries_it(tmp_path):
    """Must fire: a repository that genuinely carries the guard test must still
    be told to run it -- the positive control for the absent case below."""
    repo = _repo_with_guard(tmp_path, present=True)
    hits = lane_setup.guards_for_files(["agents/developer.md"], repo=repo)
    entry = next(e for e in hits if e["test"] == "tests/test_content_invariants.py")
    assert entry["status"] == "exists"


def test_guard_reports_absent_when_the_managed_repo_lacks_it(tmp_path):
    """Must not silently pass as run: the same trigger, in a repo that does not
    carry the guard test at all -- the four-of-four `claude-supertool` measurement
    in the issue. Never `exists`, and the entry is not dropped."""
    repo = _repo_with_guard(tmp_path, present=False)
    hits = lane_setup.guards_for_files(["agents/developer.md"], repo=repo)
    entry = next(e for e in hits if e["test"] == "tests/test_content_invariants.py")
    assert entry["status"] == "absent"


def test_known_guards_status_mirrors_guards_for_files(tmp_path):
    repo = _repo_with_guard(tmp_path, present=True)
    known = lane_setup.known_guards(repo=repo)
    entry = next(e for e in known if e["test"] == "tests/test_content_invariants.py")
    assert entry["status"] == "exists"
    absent_entry = next(e for e in known if e["test"] == "tests/test_python_floor_410.py")
    assert absent_entry["status"] == "absent"


# --- could-not-tell: a positive control for "nothing looked" --------------------


def test_guard_status_could_not_tell_when_the_repo_cannot_be_examined(tmp_path):
    """The third state, exercised rather than asserted from a table: a directory
    stripped of read/execute permission cannot be listed or stat'ed into, so a
    guard test under it can be neither confirmed present nor confirmed absent.
    Root and some filesystems ignore the mode bit (CLAUDE.md, "a permission
    fixture is a measurement, not a given"), so the deny is confirmed by
    attempting the exact operation before asserting on it, and skipped loudly
    with what went untested when it does not take."""
    repo = _repo_with_guard(tmp_path, present=True)
    blocked_dir = repo / "tests"
    original_mode = blocked_dir.stat().st_mode
    os.chmod(blocked_dir, 0)
    try:
        try:
            os.listdir(blocked_dir)
            deny_confirmed = False
        except PermissionError:
            deny_confirmed = True
        except OSError:
            deny_confirmed = False
        if not deny_confirmed:
            import pytest

            pytest.skip(
                "chmod 0 did not deny listing on this machine/filesystem -- "
                "could-not-tell path untested here"
            )
        hits = lane_setup.guards_for_files(["agents/developer.md"], repo=repo)
        entry = next(e for e in hits if e["test"] == "tests/test_content_invariants.py")
        assert entry["status"] == "could-not-tell"
    finally:
        os.chmod(blocked_dir, original_mode)


# --- lane_report threads repo through, and the receipt says it in words --------


def test_lane_report_threads_repo_into_guard_status(tmp_path):
    repo = _repo_with_guard(tmp_path, present=False)
    report = lane_setup.lane_report(repo, ["agents/developer.md"], None)
    entry = next(
        e for e in report["guards"] if e["test"] == "tests/test_content_invariants.py"
    )
    assert entry["status"] == "absent"


def _minimal_payload(repo, lane_patterns, against_patterns):
    return {
        "issue": 566,
        "repo": str(repo),
        "config": {"state": "ok", "problems": []},
        "base": {
            "state": "resolved",
            "remote": "origin",
            "ref": "origin/main",
            "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "detail": "",
        },
        "branch": {
            "state": "resolved",
            "pattern": "fix/{issue}",
            "name": "fix/566",
            "detail": "",
            "exists_local": False,
            "exists_remote": False,
        },
        "worktree": {
            "state": "resolved",
            "root": "/tmp",
            "path": "/tmp/566",
            "detail": "",
            "exists": False,
        },
        "board": {"state": "ok", "lines": []},
        "lanes": None,
        "lane": lane_setup.lane_report(repo, lane_patterns, against_patterns),
    }


def test_receipt_says_not_in_this_repo_for_an_absent_guard(tmp_path):
    """Must not fire the silent case: a lane in a managed repo lacking the guard
    test reads a sentence saying so, never a bare test path that would collect
    nothing if run."""
    repo = _repo_with_guard(tmp_path, present=False)
    payload = _minimal_payload(repo, ["agents/developer.md"], None)
    text = lane_setup.receipt(payload)
    assert "tests/test_content_invariants.py -- NOT IN THIS REPO" in text


def test_receipt_still_names_a_guard_that_genuinely_exists(tmp_path):
    """Must fire: the control pair's positive half, at the receipt layer this
    time -- a lane in a repo that carries the guard reads exactly the pre-#566
    line, unflagged."""
    repo = _repo_with_guard(tmp_path, present=True)
    payload = _minimal_payload(repo, ["agents/developer.md"], None)
    text = lane_setup.receipt(payload)
    assert "guard   : tests/test_content_invariants.py (" in text
    assert "NOT IN THIS REPO" not in text
