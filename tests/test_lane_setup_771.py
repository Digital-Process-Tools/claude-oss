"""#771: `_branch_confirmed_gone`'s absence-from-`refs/heads` signal, #734's
own route-3 backstop, means two different things and cannot tell them apart
on its own -- "this branch was merged and cleaned up" and "this branch has
been claimed but not yet cut" both render as `git show-ref` answering "not
found". The loop's own documented dispatch order is `--claim` (writes the
lane's own record) before `git worktree add` (creates the branch), so the
second state is not a misconfiguration or a race to be narrowed: it is the
ordinary, structural window between those two calls, and #734's own route 3
read a bare absence as a positive confirmation of the first state and pruned
on the spot.

Reproduced directly by the maintainer, no misconfiguration anywhere: three
lanes claimed back to back, a sibling's `--derive-held` read between each
claim and its own `git worktree add`, and the registry ended up empty --
every record pruned, none of the three branches ever having existed (the
issue's own comment thread).

The fix: a record's own branch has to be positively *observed present* at
some earlier read before a later "not found" is ever trusted as deletion
(`data["branch_confirmed_created"]`, written by `_mark_branch_confirmed_created`
the first time a corroborating read sees the branch alive). A record whose
branch was never observed alive falls back to the pre-#734, no-`repo`
behaviour -- age alone -- exactly the degrade this mechanism already makes
when `repo` is omitted, and never worse than that.

Every case below that proves a not-yet-cut branch survives also has a
sibling proving a genuinely merged-and-deleted branch (created, observed,
then removed) still gets pruned promptly -- #734's own gain must not be
undone by this fix.
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
    """A repo `git show-ref` will actually answer about, or the test skips --
    the same shape test_lane_setup_734.py's own `_real_git_repo` uses."""
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


# --- _show_ref_code / _branch_confirmed_present: the primitives this fix adds ---


def test_show_ref_code_is_1_for_a_branch_that_was_never_created(tmp_path):
    repo = _real_git_repo(tmp_path)
    assert lane_setup._show_ref_code(repo, "fix/never-existed") == 1


def test_show_ref_code_is_0_for_a_branch_that_exists(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    assert lane_setup._show_ref_code(repo, "fix/1") == 0


def test_show_ref_code_is_neither_0_nor_1_when_git_itself_cannot_answer(tmp_path):
    """Not `None` here -- git itself runs and answers (a real `git` binary
    against a directory that is not a repository exits non-zero, non-one,
    e.g. 128), so this is the "git ran and said something else" case rather
    than the "git could not be launched at all" case `_git` returns `None`
    for. Both `_branch_confirmed_gone` and `_branch_confirmed_present` treat
    anything outside {0, 1} the same way: not confirmed either direction."""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    code = lane_setup._show_ref_code(not_a_repo, "fix/1")
    assert code not in (0, 1)


def test_branch_confirmed_present_is_true_for_a_branch_that_exists(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    assert lane_setup._branch_confirmed_present(repo, "fix/1") is True


def test_branch_confirmed_present_is_false_for_a_branch_that_was_never_created(
    tmp_path,
):
    repo = _real_git_repo(tmp_path)
    assert lane_setup._branch_confirmed_present(repo, "fix/never-existed") is False


def test_branch_confirmed_present_is_false_when_git_itself_cannot_answer(tmp_path):
    """Control: silence must never read as confirmation, in either direction --
    the same posture `_branch_confirmed_gone` already takes."""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    assert lane_setup._branch_confirmed_present(not_a_repo, "fix/1") is False


# --- _mark_branch_confirmed_created: the write side effect -----------------------


def test_mark_branch_confirmed_created_persists_the_flag_and_keeps_the_rest(tmp_path):
    worktree_root = tmp_path / "wt"
    path = _write_record(worktree_root, 1, files=["a.py"], branch="fix/1")
    with open(path) as fh:
        data = json.load(fh)
    lane_setup._mark_branch_confirmed_created(path, data)
    with open(path) as fh:
        after = json.load(fh)
    assert after["branch_confirmed_created"] is True
    assert after["files"] == ["a.py"]
    assert after["issue"] == 1
    assert after["branch"] == "fix/1"


# --- held_from_live_lanes: the reproduction, and the must-fire control ----------


def test_held_from_live_lanes_does_not_prune_a_branch_never_yet_observed_created(
    tmp_path,
):
    """The issue's own reproduction, at its simplest: a record whose branch
    has never been created at all -- the ordinary window between --claim and
    git worktree add -- must not be pruned. A bare "not found" from
    refs/heads is exactly as consistent with "not yet cut" as with "merged
    and deleted", and this function has never observed this branch alive."""
    repo = _real_git_repo(tmp_path)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(
        worktree_root, 771, files=["scripts/lane_setup.py"], branch="fix/771"
    )

    result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert result["state"] == "resolved"
    assert result["held"] == {"scripts/lane_setup.py": ["lane #771"]}
    assert os.path.exists(record_path)
    assert result["stale_pruned"] == []


def test_held_from_live_lanes_survives_repeated_probes_before_any_branch_is_cut(
    tmp_path,
):
    """The maintainer's own reproduction, from the issue's comment thread:
    three lanes claim back to back, a sibling's --derive-held read (via
    held_from_live_lanes) in between each claim and its own git worktree
    add. None of the three branches exists yet at any point in this
    sequence, and none of the three records may be pruned."""
    repo = _real_git_repo(tmp_path)
    worktree_root = tmp_path / "wt"
    issues = (771, 774, 776)
    for n in issues:
        _write_record(
            worktree_root, n, files=["f{0}.py".format(n)], branch="fix/{0}".format(n)
        )
        probe = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
        assert probe["state"] == "resolved"
        assert probe["stale_pruned"] == []

    final = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert final["state"] == "resolved"
    assert sorted(final["held"]) == ["f771.py", "f774.py", "f776.py"]
    assert final["stale_pruned"] == []


def test_held_from_live_lanes_still_prunes_a_branch_genuinely_created_then_deleted(
    tmp_path,
):
    """Must-fire control: #734's own gain is not undone. A branch that really
    was created (observed alive by an earlier read) and is later genuinely
    deleted must still be pruned promptly, on the corroborating read that
    finds it positively gone -- never waiting on the TTL."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/694"], check=True)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(
        worktree_root, 694, files=["commands/tick.md"], branch="fix/694"
    )

    first = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert first["state"] == "resolved"
    assert "commands/tick.md" in first["held"]

    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/694"], check=True)

    result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert result["state"] == "unknown"
    assert result["held"] == {}
    assert not os.path.exists(record_path)
    assert result["stale_pruned"] == [{"issue": 694, "branch": "fix/694"}]


def test_held_from_live_lanes_marks_branch_confirmed_created_as_a_side_effect(tmp_path):
    """The mechanism itself, at the record level: the first read while the
    branch exists must write `branch_confirmed_created: true` to disk."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(worktree_root, 1, files=["a.py"], branch="fix/1")

    lane_setup.held_from_live_lanes(worktree_root, repo=repo)

    with open(record_path) as fh:
        data = json.load(fh)
    assert data.get("branch_confirmed_created") is True


def test_held_from_live_lanes_does_not_mark_a_branch_that_does_not_exist(tmp_path):
    """Control for the write side effect: a branch never observed present
    must never get the flag written for it."""
    repo = _real_git_repo(tmp_path)
    worktree_root = tmp_path / "wt"
    record_path = _write_record(
        worktree_root, 1, files=["a.py"], branch="fix/never-existed"
    )

    lane_setup.held_from_live_lanes(worktree_root, repo=repo)

    with open(record_path) as fh:
        data = json.load(fh)
    assert "branch_confirmed_created" not in data


def test_held_from_live_lanes_without_repo_is_unaffected_by_the_new_field(tmp_path):
    """Backward-compat control: every existing caller that does not pass
    `repo` sees byte-for-byte the pre-#771 behaviour -- age is the only
    signal, whether or not `branch_confirmed_created` happens to be set."""
    worktree_root = tmp_path / "wt"
    _write_record(worktree_root, 3, files=["c.py"], branch="fix/nonexistent-branch-xyz")

    result = lane_setup.held_from_live_lanes(worktree_root)
    assert result["state"] == "resolved"
    assert "c.py" in result["held"]


# --- record_lane: branch_confirmed_created survives a --claim refresh -----------
# Review round: `record_lane` already preserves `files` across a re-`--claim` for
# the same issue (its own docstring calls this an ordinary, supported refresh) but
# did not carry `branch_confirmed_created` forward -- so a lane observed alive,
# re-claimed once, then genuinely merged and deleted silently lost route 3's
# prompt prune and fell back to the 240-minute TTL, reopening the exact #734 gap
# #771 exists to close. This section proves the preserve and its own control (a
# changed branch name must NOT carry an old observation forward).


def test_record_lane_carries_branch_confirmed_created_across_a_reclaim(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    worktree_root = tmp_path / "wt"

    lane_setup.record_lane(worktree_root, 1, "fix/1", "/some/path", files=["a.py"])
    lane_setup.held_from_live_lanes(worktree_root, repo=repo)  # observes branch alive
    record_path = os.path.join(lane_setup.lane_registry_dir(worktree_root), "1.json")
    with open(record_path) as fh:
        assert json.load(fh).get("branch_confirmed_created") is True

    # An ordinary mid-lane re-claim, same issue, same branch.
    lane_setup.record_lane(worktree_root, 1, "fix/1", "/some/path", files=["a.py"])
    with open(record_path) as fh:
        assert json.load(fh).get("branch_confirmed_created") is True

    subprocess.run(["git", "-C", str(repo), "branch", "-D", "fix/1"], check=True)
    result = lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    assert result["state"] == "unknown"
    assert result["held"] == {}
    assert result["stale_pruned"] == [{"issue": 1, "branch": "fix/1"}]


def test_record_lane_does_not_carry_the_flag_forward_when_the_branch_changed(tmp_path):
    """Control: an observation about `fix/1` must never be read as an
    observation about `fix/2` just because the same issue number re-claimed
    under a new branch name."""
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/1"], check=True)
    worktree_root = tmp_path / "wt"

    lane_setup.record_lane(worktree_root, 1, "fix/1", "/some/path", files=["a.py"])
    lane_setup.held_from_live_lanes(worktree_root, repo=repo)
    record_path = os.path.join(lane_setup.lane_registry_dir(worktree_root), "1.json")
    with open(record_path) as fh:
        assert json.load(fh).get("branch_confirmed_created") is True

    # Re-claimed under a different branch name -- fix/2 has never been observed.
    lane_setup.record_lane(worktree_root, 1, "fix/2", "/some/path", files=["a.py"])
    with open(record_path) as fh:
        assert "branch_confirmed_created" not in json.load(fh)


def test_record_lane_first_claim_never_carries_the_flag(tmp_path):
    """Control: a record's very first write has no previous record to read from
    and must not fabricate the flag."""
    worktree_root = tmp_path / "wt"
    lane_setup.record_lane(worktree_root, 1, "fix/1", "/some/path", files=["a.py"])
    record_path = os.path.join(lane_setup.lane_registry_dir(worktree_root), "1.json")
    with open(record_path) as fh:
        assert "branch_confirmed_created" not in json.load(fh)
