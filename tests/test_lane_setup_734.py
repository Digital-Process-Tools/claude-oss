"""#734: a lane record's liveness is its age, not its state -- nothing consults
whether the pull request it belongs to has actually merged, so a lane the loop
itself merged and read back can still block its own follow-ups for up to the
full four-hour TTL. Three recorded instances, all lanes the loop merged and
read back, 20-90 minutes stale against the TTL (the issue's own comment
thread).

Two independent contributions, and this file closes both -- route 1 and route 3
from the issue's own "What would settle it", left as the maintainer's choice
and taken here on the maintainer's own stated evidence (all three instances are
lanes the loop itself merged):

  route 1  `release_lane` -- an explicit release, called once the loop has
           verified a merge (`state`/`mergedAt`/`mergeCommit` read back). This
           is the fast path: the record is gone the moment the merge step
           says so, never waiting on age at all.

  route 3  a corroborating check inside `held_from_live_lanes` itself, for the
           case route 1's caller never ran (a manual merge, a crash between
           merge and release, an older loop). The loop's own merge cleanup
           runs `git branch -d` on the shared clone (supertool's own
           `gh-pr-merge` help text), and every worktree cut from that clone's
           `worktree_root` can see the shared `refs/heads` namespace without a
           fetch -- so a record whose declared branch is positively confirmed
           gone locally is pruned the same way an expired record already is,
           and is never trusted as still held.

Route 3 is deliberately a corroboration, never a replacement for the TTL: a
record whose branch cannot be positively confirmed gone (no `repo` given, git
unavailable, the branch simply still exists) is kept and judged on age alone,
exactly as before this existed -- so every case that prunes on branch absence
below has a sibling proving an existing branch, or no corroboration at all,
still counts as held in the same fixture.
"""

import json
import os
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
import spawn_guard  # noqa: E402


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


# --- release_lane: the explicit route (route 1) ----------------------------------


def test_release_lane_removes_an_existing_record(tmp_path):
    path = _write_record(tmp_path, 694, files=["commands/tick.md"])
    result = lane_setup.release_lane(tmp_path, 694)
    assert result["state"] == "released"
    assert not os.path.exists(path)


def test_release_lane_not_found_when_no_record_exists(tmp_path):
    """Control: releasing an issue that never claimed (or already expired) is
    not a failure -- there was simply nothing to release."""
    os.makedirs(lane_setup.lane_registry_dir(tmp_path), exist_ok=True)
    result = lane_setup.release_lane(tmp_path, 999)
    assert result["state"] == "not-found"


def test_release_lane_could_not_release_when_worktree_root_is_unknown():
    result = lane_setup.release_lane(None, 694)
    assert result["state"] == "could-not-release"


def test_release_lane_only_removes_the_named_issue(tmp_path):
    """A sibling live record must survive the release of another issue's own."""
    kept = _write_record(tmp_path, 1, files=["a.py"])
    _write_record(tmp_path, 2, files=["b.py"])
    result = lane_setup.release_lane(tmp_path, 2)
    assert result["state"] == "released"
    assert os.path.exists(kept)


# --- CLI: --release reaches the registry -----------------------------------------


def _cli(tmp_path, issue, *extra_args):
    (tmp_path / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "example/example",
                "default_branch": "main",
                "clone": "/tmp/does-not-matter",
                "worktree_root": str(tmp_path / "wt"),
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": [],
                "changelog_dir": None,
                "docs_targets": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": "/tmp/does-not-matter-state.json",
            }
        )
    )
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), str(issue), "--repo", str(tmp_path), "--json"]
        + list(extra_args),
        subject="lane_setup.py --release",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_release_removes_the_record_and_exits_ok(tmp_path):
    """#1069: `--release` now also releases the GitHub assignee in the same
    call (`lane_setup_claim.release_lane_and_assignee`), so `--json` prints
    the combined `{"record": ..., "assignee": ..., "also_released": [...]}`
    payload rather than the bare record -- the exit code still gates on the
    record's own state only, unchanged."""
    worktree_root = tmp_path / "wt"
    _write_record(worktree_root, 694, files=["commands/tick.md"])
    done = _cli(tmp_path, 694, "--release")
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["record"]["state"] == "released"
    assert not os.path.exists(lane_setup.lane_registry_dir(worktree_root) + "/694.json")


def test_cli_release_of_an_unclaimed_issue_still_exits_ok(tmp_path):
    """Control: a merge step that releases an issue this loop never actually
    claimed (no --claim ever ran) must not be treated as an error -- the same
    "nothing to release" answer as the unit-level test above."""
    done = _cli(tmp_path, 999, "--release")
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["record"]["state"] == "not-found"


# --- held_from_live_lanes: route 3, a corroborating local branch check -----------


def _real_git_repo(tmp_path):
    """A repo `git show-ref` will actually answer about, or the test skips --
    the same shape `test_config_scope.py`'s own `_real_git_repo` uses."""
    repo = tmp_path / "repo"
    repo.mkdir()
    done = subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if done.returncode != 0:
        pytest.skip(
            "git init failed here: {0}".format(done.stderr.strip() or done.returncode)
        )
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "t"], env=env, check=True
    )
    (repo / "README.md").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], env=env, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "x"], env=env, check=True
    )
    return repo


def test_held_from_live_lanes_keeps_a_record_whose_branch_still_exists_locally(
    tmp_path,
):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/694"], check=True)
    worktree_root = tmp_path / "wt"
    _write_record(worktree_root, 694, files=["commands/tick.md"], branch="fix/694")

    result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert result["state"] == "resolved"
    assert "commands/tick.md" in result["held"]
    assert result["stale_pruned"] == []


def test_held_from_live_lanes_prunes_a_record_whose_branch_is_confirmed_gone(tmp_path):
    """The issue's own third instance: lane #694 merged, the loop's own cleanup
    ran `git branch -d fix/694`, and the record still claimed
    `commands/tick.md` twenty minutes later against a 240-minute TTL. A
    branch this function has previously observed created, and which is now
    positively confirmed gone, must be excluded from the held set and the
    record itself pruned, not merely aged out later.

    #771 review: the branch is genuinely created, observed by a first read,
    and then deleted here -- unlike the pre-#771 version of this test, which
    simulated "merged and cleaned up" with a branch that was simply never
    created at all. That is exactly the ambiguity #771 is about: this test's
    own sibling in tests/test_lane_setup_771.py proves a branch never
    observed created must NOT be pruned the same way.
    """
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/694"], check=True)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(
        worktree_root, 694, files=["commands/tick.md"], branch="fix/694"
    )
    # A first read while the branch exists -- #771's own precondition for
    # trusting a later absence as deletion rather than "never created".
    first = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert first["state"] == "resolved"
    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/694"], check=True)

    result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert result["state"] == "unknown"
    assert result["held"] == {}
    assert not os.path.exists(record_path)
    assert result["stale_pruned"] == [{"issue": 694, "branch": "fix/694"}]


def test_held_from_live_lanes_stale_branch_prune_does_not_touch_a_live_sibling(
    tmp_path,
):
    """Two records, one prunable and one not -- the held set must keep exactly
    the live one's files, and only the gone branch's record is removed from
    disk. #771 review: both branches are created (and observed by a first
    read) before #2's is deleted -- see the note on the sibling test above."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/2"], check=True)
    worktree_root = tmp_path / "wt"
    live_path = _write_record(worktree_root, 1, files=["a.py"], branch="fix/1")
    gone_path = _write_record(worktree_root, 2, files=["b.py"], branch="fix/2")
    first = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert first["state"] == "resolved"
    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/2"], check=True)

    result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert result["state"] == "resolved"
    assert result["held"] == {"a.py": ["lane #1"]}
    assert os.path.exists(live_path)
    assert not os.path.exists(gone_path)


def test_held_from_live_lanes_without_repo_never_corroborates_branches(tmp_path):
    """Backward-compat control: every existing caller that does not pass `repo`
    (this repo's own suite included) must see byte-for-byte the old behaviour
    -- age is the only signal, and a record naming a branch that plainly does
    not exist as a filesystem concept (no `repo` was ever given to check
    against) is still trusted as held."""
    worktree_root = tmp_path / "wt"
    _write_record(worktree_root, 3, files=["c.py"], branch="fix/nonexistent-branch-xyz")

    result = lane_setup.held_from_live_lanes(worktree_root)
    assert result["state"] == "resolved"
    assert "c.py" in result["held"]


# --- _branch_confirmed_gone: the primitive route 3 is built on -------------------


def test_branch_confirmed_gone_is_false_for_a_branch_that_exists(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    assert lane_setup._branch_confirmed_gone(repo, "fix/1") is False


def test_branch_confirmed_gone_is_true_for_a_branch_that_was_never_created(tmp_path):
    repo = _real_git_repo(tmp_path)
    assert lane_setup._branch_confirmed_gone(repo, "fix/never-existed") is True


def test_branch_confirmed_gone_is_false_when_git_itself_cannot_answer(tmp_path):
    """A repo that is not actually a git repository must never read as
    confirmation that the branch is gone -- silence is not a refusal."""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    assert lane_setup._branch_confirmed_gone(not_a_repo, "fix/1") is False


# --- derive_held_set: `repo` threads through to the corroborating check ----------


def test_derive_held_set_forwards_repo_so_a_merged_lane_stops_blocking(
    tmp_path, monkeypatch
):
    """End to end, the issue's own reproduction shape: a live record for a
    merged-and-cleaned-up lane must not survive into the combined held set
    once `repo` is given, so a sibling lane checking availability against it
    reads `available` rather than `BLOCKED`."""
    real_which = lane_setup.shutil.which
    monkeypatch.setattr(
        lane_setup.shutil,
        "which",
        lambda name: "/usr/bin/gh" if name == "gh" else real_which(name),
    )
    real_run = subprocess.run

    def _fake_run(cmd, *a, **k):
        # Only the `gh pr list` call is faked -- `_git`'s own `show-ref` call
        # (route 3's corroboration) must reach the real `git` binary, or this
        # test could not tell "the branch is gone" from "the check never ran".
        if cmd and "gh" in os.path.basename(str(cmd[0])):
            return subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(lane_setup.subprocess, "run", _fake_run)
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/694"], check=True)
    worktree_root = tmp_path / "wt"
    _write_record(worktree_root, 694, files=["commands/tick.md"], branch="fix/694")
    # #771 review: observe the branch alive once before it is deleted -- see
    # the note on test_held_from_live_lanes_prunes_a_record_whose_branch_is_
    # confirmed_gone above.
    first = lane_setup.derive_held_set("owner/repo", worktree_root, repo=repo)
    assert first["state"] == "resolved"
    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/694"], check=True)

    result = lane_setup.derive_held_set("owner/repo", worktree_root, repo=repo)
    assert result["state"] == "resolved"
    assert "commands/tick.md" not in result["held"]


# --- review round: a stale-branch prune must leave a trace, not just a side ------
# effect -- `compute()`'s own docstring used to claim nothing is written to the
# registry without --claim, and that stopped being true the moment --derive-held
# started pruning OTHER issues' records as a side effect of route 3. The prune
# itself is correct (only ever a positively-confirmed-gone branch); what was
# missing is any way for the caller to see it happened at all.


def test_lane_report_surfaces_which_records_were_pruned(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/694"], check=True)
    worktree_root = tmp_path / "wt"
    _write_record(worktree_root, 694, files=["commands/tick.md"], branch="fix/694")
    # #771 review: observe the branch alive once, then delete it -- see the
    # note on test_held_from_live_lanes_prunes_a_record_whose_branch_is_
    # confirmed_gone above.
    first = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert first["state"] == "resolved"
    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/694"], check=True)
    derived = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    # Wrap in the same shape `derive_held_set` hands `lane_report`.
    derived_held = {
        "state": "resolved",
        "held": derived["held"],
        "lanes": derived,
        "detail": "",
    }

    report = lane_setup.lane_report(
        tmp_path, ["scripts/free.py"], None, derived_held=derived_held
    )
    assert report["held_source"]["stale_pruned"] == [
        {"issue": 694, "branch": "fix/694"}
    ]


def test_lane_report_stale_pruned_is_empty_when_nothing_was_pruned(tmp_path):
    """Control: a clean derivation -- nothing gone, nothing pruned -- must not
    fabricate a prune that never happened."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    worktree_root = tmp_path / "wt"
    _write_record(worktree_root, 1, files=["a.py"], branch="fix/1")
    derived = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    derived_held = {
        "state": "resolved",
        "held": derived["held"],
        "lanes": derived,
        "detail": "",
    }

    report = lane_setup.lane_report(
        tmp_path, ["scripts/free.py"], None, derived_held=derived_held
    )
    assert report["held_source"]["stale_pruned"] == []


def test_receipt_names_a_stale_prune_so_it_is_never_a_silent_write(tmp_path):
    """The text receipt -- what a maintainer or a dispatched agent actually
    reads -- must name a prune too, not only the JSON payload."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("x\n")
    derived_held = {
        "state": "resolved",
        "held": {},
        "lanes": {"stale_pruned": [{"issue": 694, "branch": "fix/694"}]},
        "detail": "",
    }
    payload = _minimal_payload(tmp_path, derived_held, ["scripts/free.py"])
    text = lane_setup.receipt(payload)
    assert "stale record(s) released" in text
    assert "lane #694 (fix/694)" in text


def test_receipt_says_nothing_about_a_prune_when_none_happened(tmp_path):
    """Control: the new line must not appear on an ordinary, clean derivation."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("x\n")
    derived_held = {
        "state": "resolved",
        "held": {},
        "lanes": {"stale_pruned": []},
        "detail": "",
    }
    payload = _minimal_payload(tmp_path, derived_held, ["scripts/free.py"])
    text = lane_setup.receipt(payload)
    assert "stale record(s) released" not in text


def _minimal_payload(repo, derived_held, lane_patterns):
    return {
        "issue": 734,
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
            "name": "fix/734",
            "detail": "",
            "exists_local": False,
            "exists_remote": False,
        },
        "worktree": {
            "state": "resolved",
            "root": "/tmp",
            "path": "/tmp/734",
            "detail": "",
            "exists": False,
        },
        "board": {"state": "ok", "lines": []},
        "lanes": None,
        "lane": lane_setup.lane_report(
            repo, lane_patterns, None, derived_held=derived_held
        ),
    }
