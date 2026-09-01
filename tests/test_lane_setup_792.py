"""#792: `held_from_live_lanes`'s route-3 prune wrapped `os.remove` in a bare
`except OSError: pass` and appended to `stale_pruned` regardless, so a removal
that genuinely failed (permission denied, a concurrent writer holding the
file open on a platform that locks it) printed the identical "released" line
as one that actually succeeded -- and the next `--derive-held` re-read a
record it had already been told was gone.

`FileNotFoundError` really is success here ("another reader already pruned
it"), and must stay folded into `stale_pruned`. Every other `OSError` is a
failed release and must land in a separate list the record is demonstrably
still on disk for -- never both, and never silently dropped.
"""

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import lane_setup  # noqa: E402


def _write_record(worktree_root, issue, files=None, branch=None, age_seconds=0):
    root = lane_setup.lane_registry_dir(worktree_root)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "{0}.json".format(issue))
    payload = {
        "issue": issue,
        "branch": branch if branch is not None else "fix/{0}".format(issue),
        "path": None,
        "recorded_at": time.time() - age_seconds,
        "pid": 1,
    }
    if files is not None:
        payload["files"] = files
    with open(path, "w") as fh:
        json.dump(payload, fh)
    return path


def _real_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    done = subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip() or done.returncode))
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], env=env, check=True)
    (repo / "README.md").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "x"], env=env, check=True)
    return repo


def _confirm_directory_write_denied(directory):
    """A permission fixture is a measurement, not a given -- root ignores the
    mode bit and some filesystems ignore it too. Confirm the deny by
    attempting the exact operation the code under test performs (removing a
    file inside the directory), not by trusting a platform's error code from
    a table."""
    probe = os.path.join(directory, "_deny_probe")
    with open(probe, "w") as fh:
        fh.write("x")
    os.chmod(directory, 0o500)
    try:
        os.remove(probe)
    except OSError:
        return True
    else:
        return False
    finally:
        os.chmod(directory, 0o700)
        if os.path.exists(probe):
            os.remove(probe)


def test_held_from_live_lanes_still_prunes_on_a_successful_removal(tmp_path):
    """Must-fire control, restated from #734/#771: a branch genuinely created
    then deleted is still pruned promptly, counted in stale_pruned, and the
    record is actually gone from disk -- #792 must not regress this."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/694"], check=True)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(worktree_root, 694, files=["commands/tick.md"], branch="fix/694")

    first = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert first["state"] == "resolved"

    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/694"], check=True)

    result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert not os.path.exists(record_path)
    assert result["stale_pruned"] == [{"issue": 694, "branch": "fix/694"}]
    assert result.get("prune_failed", []) == []


def test_held_from_live_lanes_reports_a_failed_prune_separately(tmp_path):
    """The reproduction: the removal itself fails (permission denied), and the
    record must not be reported as released -- it is demonstrably still on
    disk. It must land in a distinct list, never silently folded into
    stale_pruned."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/42"], check=True)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(worktree_root, 42, files=["a.py"], branch="fix/42")

    first = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert first["state"] == "resolved"

    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/42"], check=True)

    root = lane_setup.lane_registry_dir(worktree_root)
    if not _confirm_directory_write_denied(root):
        pytest.skip("this platform/filesystem does not deny a write via the directory mode bit")

    os.chmod(root, 0o500)
    try:
        result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    finally:
        os.chmod(root, 0o700)

    assert os.path.exists(record_path), "a failed removal must leave the record on disk"
    assert result["stale_pruned"] == []
    assert result.get("prune_failed", []) == [
        item for item in result.get("prune_failed", []) if item["issue"] == 42
    ]
    assert len(result.get("prune_failed", [])) == 1
    assert result["prune_failed"][0]["issue"] == 42
    assert result["prune_failed"][0]["branch"] == "fix/42"
    assert result["prune_failed"][0]["detail"]


def test_held_from_live_lanes_treats_filenotfounderror_as_success_not_failure(tmp_path):
    """FileNotFoundError really is success here -- "another reader already
    pruned it" -- and must stay folded into stale_pruned, never routed into
    the failure list alongside a genuine permission error."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/7"], check=True)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(worktree_root, 7, files=["a.py"], branch="fix/7")

    first = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert first["state"] == "resolved"
    with open(record_path) as fh:
        confirmed_data = json.load(fh)
    assert confirmed_data.get("branch_confirmed_created") is True

    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/7"], check=True)

    # Simulate a sibling reader having already pruned the record between this
    # call's listdir and its own os.remove: patch os.remove itself, since the
    # record has to still be readable by open()/json.load() (with the branch
    # already confirmed created above) right up to the moment this call's own
    # removal races the sibling's.
    real_remove = os.remove

    def _fake_remove(path):
        if path.endswith("7.json"):
            raise FileNotFoundError(2, "No such file or directory")
        return real_remove(path)

    import lane_setup as _ls
    orig = _ls.os.remove
    _ls.os.remove = _fake_remove
    try:
        result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    finally:
        _ls.os.remove = orig

    assert result["stale_pruned"] == [{"issue": 7, "branch": "fix/7"}]
    assert result.get("prune_failed", []) == []


def _minimal_payload(repo, derived_held, lane_patterns):
    return {
        "issue": 792,
        "repo": str(repo),
        "config": {"state": "ok", "problems": []},
        "base": {
            "state": "resolved", "remote": "origin", "ref": "origin/main",
            "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "detail": "",
        },
        "branch": {
            "state": "resolved", "pattern": "fix/{issue}", "name": "fix/792",
            "detail": "", "exists_local": False, "exists_remote": False,
        },
        "worktree": {"state": "resolved", "root": "/tmp", "path": "/tmp/792", "detail": "", "exists": False},
        "board": {"state": "ok", "lines": []},
        "lanes": None,
        "lane": lane_setup.lane_report(repo, lane_patterns, None, derived_held=derived_held),
    }


def test_receipt_names_a_failed_prune_so_it_is_never_read_as_a_release(tmp_path):
    """The text receipt -- what a maintainer or a dispatched agent actually
    reads -- must say a prune failed, and must not use the "released" line
    for it."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("x\n")
    derived_held = {
        "state": "resolved",
        "held": {},
        "lanes": {
            "stale_pruned": [],
            "prune_failed": [{"issue": 42, "branch": "fix/42", "detail": "PermissionError: [Errno 13] denied"}],
        },
        "detail": "",
    }
    payload = _minimal_payload(tmp_path, derived_held, ["scripts/free.py"])
    text = lane_setup.receipt(payload)
    assert "could NOT be released" in text
    assert "lane #42 (fix/42)" in text
    assert "stale record(s) released" not in text


def test_receipt_says_nothing_about_a_failed_prune_when_none_happened(tmp_path):
    """Control: the new failure line must not appear on an ordinary, clean
    derivation with nothing to report."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("x\n")
    derived_held = {
        "state": "resolved",
        "held": {},
        "lanes": {"stale_pruned": [], "prune_failed": []},
        "detail": "",
    }
    payload = _minimal_payload(tmp_path, derived_held, ["scripts/free.py"])
    text = lane_setup.receipt(payload)
    assert "could NOT be released" not in text
