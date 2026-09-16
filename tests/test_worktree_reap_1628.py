"""#1628: worktree reaping had a permission check (#787) but nothing that
found reapable trees or reaped them, and the one safety signal that would
have stopped a bad reap -- `git-worktrees`' own "uncommitted work" warning --
was a false positive on 8 of 10 dirty worktrees measured on this repo,
because `notes/` and `reports/` (lane scratch output) were not gitignored.

These tests build real git repositories and real `git worktree add` trees
(`_init_repo`/`_add_worktree` below) rather than mocking every git call, per
CLAUDE.md's rule that a state fixture is a measurement, not a given -- the
commands under test (`git worktree list --porcelain`, `git status
--porcelain`, `git worktree remove --force`, `git branch -D`) are cheap
enough to run for real. Only the tracker (`gh pr list`, via the injected
`gh_bin`/`run` pair) and process occupancy (`list_processes`) are faked --
neither is reachable from a test in this process.

Every "must not fire" case is paired with a "must fire" case in the same
fixture family, per CLAUDE.md's rule that a negative assertion needs a
positive control.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_worktree_reap  # noqa: E402
import worktree_reap  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def _init_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("1", encoding="utf-8")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "initial")


def _add_worktree(clone, path, branch, push_upstream=True):
    """A real `git worktree add`, and -- by default -- a real, pushed
    upstream, matching a real lane's own branch (opening a pull request
    needs a push). `push_upstream=False` models a branch that was never
    pushed at all, the `unpushed_commit_state`-`"no-upstream"` fixture case.
    A throwaway bare remote, not `clone` itself: pushing a branch that is
    checked out in a LINKED WORKTREE of the receiving repo is refused by
    git's own `denyCurrentBranch` protection, which is aware of every
    worktree sharing that repository, not just its primary checkout.
    """
    _git(clone, "worktree", "add", "-q", str(path), "-b", branch)
    if push_upstream:
        remote_dir = path.parent / (path.name + "-remote.git")
        subprocess.run(["git", "init", "-q", "--bare", str(remote_dir)], check=True)
        _git(path, "remote", "add", "origin", str(remote_dir))
        _git(path, "push", "-q", "--set-upstream", "origin", branch)


class _FakeGhRun:
    """Stands in for ``subprocess.run`` ONLY for calls whose first argument
    is the fake gh binary this test hands to `worktree_reap` as `gh_bin` --
    every other call (every real `git` invocation) is passed straight
    through to the real `subprocess.run`. ``pr_states`` maps branch name ->
    GitHub PR ``state`` string (``"MERGED"``/``"OPEN"``/``"CLOSED"``); a
    branch absent from the map renders as "no pull request on record".
    """

    GH_BIN = "FAKE-GH-BINARY"

    def __init__(self, pr_states):
        self.pr_states = pr_states

    def __call__(self, args, **kwargs):
        if args[0] != self.GH_BIN:
            return subprocess.run(args, **kwargs)
        # args: [GH_BIN, "pr", "list", "-R", slug, "--head", branch, ...]
        branch = args[args.index("--head") + 1]
        state = self.pr_states.get(branch)
        rows = (
            []
            if state is None
            else [{"number": 1, "headRefName": branch, "state": state}]
        )
        import json

        class _Result:
            returncode = 0
            stdout = json.dumps(rows).encode("utf-8")
            stderr = b""

        return _Result()


def _unoccupied():
    return []


def _occupied(path):
    return lambda: [("999", str(path))]


def _unknown_occupancy():
    return None


# ------------------------------------------------------------- list_worktrees


def test_list_worktrees_excludes_nothing_and_the_first_entry_is_the_main_tree(
    tmp_path,
):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    state, entries = worktree_reap.list_worktrees(clone)
    assert state == "listed", entries
    assert len(entries) == 2
    assert Path(entries[0]["path"]).resolve() == clone.resolve()
    assert Path(entries[1]["path"]).resolve() == wt.resolve()
    assert entries[1]["branch"] == "fix/1"


def test_list_worktrees_could_not_tell_when_git_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(worktree_reap.gh_which, "safe_which", lambda name: None)
    state, detail = worktree_reap.list_worktrees(tmp_path)
    assert state == "could-not-tell"
    assert "git is not on PATH" in detail


# ------------------------------------------------------------------ dirt_state


def test_dirt_state_clean_tree(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    state, offenders, fragments = worktree_reap.dirt_state(wt)
    assert (state, offenders, fragments) == ("clean", [], [])


def test_dirt_state_artifacts_only_is_not_real_dirt(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    (wt / "notes").mkdir()
    (wt / "notes" / "scratch.md").write_text("x", encoding="utf-8")
    (wt / "reports").mkdir()
    (wt / "reports" / "out.json").write_text("{}", encoding="utf-8")
    state, offenders, fragments = worktree_reap.dirt_state(wt)
    assert state == "artifacts-only", (state, offenders, fragments)
    assert offenders == []


def test_dirt_state_real_dirt_outside_the_allowlist_is_reported_with_its_path(
    tmp_path,
):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    (wt / "scratch.py").write_text("x = 1\n", encoding="utf-8")
    state, offenders, fragments = worktree_reap.dirt_state(wt)
    assert state == "real-dirt", (state, offenders, fragments)
    assert offenders == ["scratch.py"]


def test_dirt_state_collects_trap_fragments_separately_from_offenders(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    (wt / "trap.d").mkdir()
    (wt / "trap.d" / "1.slug.md").write_text("finding", encoding="utf-8")
    state, offenders, fragments = worktree_reap.dirt_state(wt)
    assert state == "artifacts-only", (state, offenders, fragments)
    assert offenders == []
    assert fragments == ["trap.d/1.slug.md"]


# --------------------------------------------------------------- occupant/merge


def test_worktree_occupant_true_when_a_process_cwd_is_inside(tmp_path):
    assert (
        worktree_reap.worktree_occupant(tmp_path, list_processes=_occupied(tmp_path))
        is True
    )


def test_worktree_occupant_false_when_no_process_matches(tmp_path):
    assert (
        worktree_reap.worktree_occupant(tmp_path, list_processes=_unoccupied) is False
    )


def test_worktree_occupant_unknown_when_the_probe_could_not_run(tmp_path):
    assert (
        worktree_reap.worktree_occupant(tmp_path, list_processes=_unknown_occupancy)
        is None
    )


def test_branch_merge_state_merged(monkeypatch):
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, _reason = worktree_reap.branch_merge_state(
        "o/r", "fix/1", run=fake, gh_bin=fake.GH_BIN
    )
    assert state == "merged"


def test_branch_merge_state_not_merged_positive_control(monkeypatch):
    fake = _FakeGhRun({"fix/1": "OPEN"})
    state, _reason = worktree_reap.branch_merge_state(
        "o/r", "fix/1", run=fake, gh_bin=fake.GH_BIN
    )
    assert state == "not-merged"


def test_branch_merge_state_no_pr_on_record_is_not_merged(monkeypatch):
    fake = _FakeGhRun({})
    state, reason = worktree_reap.branch_merge_state(
        "o/r", "fix/never-opened", run=fake, gh_bin=fake.GH_BIN
    )
    assert state == "not-merged"
    assert "no pull request on record" in reason


# --------------------------------------------------------------------- plan_reap


def _config(clone, repo="o/r"):
    return {"clone": str(clone), "repo": repo}


def test_reapable_tree_merged_unoccupied_clean(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert len(plan) == 1
    assert plan[0]["decision"] == "reapable", plan[0]


def test_occupied_tree_is_kept_not_reapable(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_occupied(wt),
    )
    assert state == "planned"
    assert plan[0]["decision"] == "kept", plan[0]
    assert "process" in plan[0]["reason"]


def test_unknown_occupancy_is_kept_could_not_tell_never_reaped(tmp_path):
    """Must-not-fire control paired with the occupied case above: an absent
    occupancy answer must never be treated as "unoccupied"."""
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unknown_occupancy,
    )
    assert state == "planned"
    assert plan[0]["decision"] == "could-not-tell", plan[0]


def test_not_merged_branch_is_kept(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "OPEN"})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert plan[0]["decision"] == "kept", plan[0]
    assert "not merged" in plan[0]["reason"]


def test_real_dirt_outside_allowlist_is_kept_and_names_the_path(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    (wt / "scratch.py").write_text("x = 1\n", encoding="utf-8")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert plan[0]["decision"] == "kept", plan[0]
    assert "scratch.py" in plan[0]["reason"]


def test_main_worktree_is_never_in_the_plan(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    fake = _FakeGhRun({})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert plan == []


# ------------------------------------------------------------------------ reap


def test_unpushed_local_commits_after_a_merged_pr_are_kept_not_reaped(tmp_path):
    """Explore review finding on this diff's own commit: `branch_merge_state`
    reads whether ANY pull request headed at this branch NAME ever reached
    MERGED, and stays true for that name forever; `dirt_state` only sees
    uncommitted changes. Neither alone notices a commit made in the worktree
    AFTER the branch's own PR merged -- clean working tree, merged branch
    name, and still real, unpushed work that `git branch -D` would destroy.
    Must be kept, never reaped, until it is confirmed not ahead of its own
    remote tracking ref."""
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")  # pushes an upstream, per its own default
    # A commit that exists ONLY in the worktree, never reaching that remote.
    (wt / "unpushed.txt").write_text("real work", encoding="utf-8")
    _git(wt, "add", "unpushed.txt")
    _git(wt, "commit", "-q", "-m", "unpushed follow-up")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert plan[0]["decision"] == "kept", plan[0]
    assert "ahead" in plan[0]["reason"]
    assert wt.exists()


def test_no_upstream_at_all_is_kept_not_reaped(tmp_path):
    """Must-not-fire control paired with the ahead case above: a branch with
    NO remote tracking ref configured at all is exactly as unverifiable as
    one with unpushed commits, and must be kept for the same reason -- never
    treated as safe on the strength of an absent upstream."""
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1", push_upstream=False)
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, plan = worktree_reap.plan_reap(
        clone,
        _config(clone),
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert plan[0]["decision"] == "kept", plan[0]
    assert "remote tracking ref" in plan[0]["reason"]


def test_apply_reaps_a_reapable_tree(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, results = worktree_reap.reap(
        clone,
        _config(clone),
        apply=True,
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert results[0]["state"] == "reaped", results[0]
    assert not wt.exists()
    branches = _git(clone, "branch", "--list", "fix/1").stdout
    assert "fix/1" not in branches


def test_a_failed_branch_delete_is_named_not_silently_dropped(tmp_path):
    """Explore review finding: the worktree's own removal is the destructive,
    unrecoverable half of a reap -- a failed FOLLOW-ON `git branch -D` must
    not render as a plain, unqualified "reaped" with no trace that the
    branch survived."""
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})

    real_run = fake.__call__

    def _run_and_fail_branch_delete(args, **kwargs):
        if len(args) >= 2 and args[-3:-1] == ["branch", "-D"]:

            class _Failed:
                returncode = 1
                stdout = b""
                stderr = b"branch is checked out elsewhere"

            return _Failed()
        return real_run(args, **kwargs)

    state, results = worktree_reap.reap(
        clone,
        _config(clone),
        apply=True,
        gh_bin=fake.GH_BIN,
        run=_run_and_fail_branch_delete,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert results[0]["state"] == "reaped", results[0]
    assert not wt.exists()
    assert "NOT deleted" in results[0]["reason"], results[0]


def test_dry_run_does_not_touch_the_tree(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, results = worktree_reap.reap(
        clone,
        _config(clone),
        apply=False,
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert results[0]["state"] == "reapable", results[0]
    assert wt.exists()


def test_stranded_trap_fragment_is_harvested_then_the_tree_is_reaped(tmp_path):
    """#1628's own headline incident: a real trap.d/ fragment sitting in an
    otherwise-reapable tree must be copied into the clone's own trap.d/
    before the tree disappears."""
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    (wt / "trap.d").mkdir()
    (wt / "trap.d" / "1.finding.md").write_text("a real finding", encoding="utf-8")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, results = worktree_reap.reap(
        clone,
        _config(clone),
        apply=True,
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert results[0]["state"] == "reaped", results[0]
    assert results[0]["harvested"] == ["trap.d/1.finding.md"]
    harvested = clone / "trap.d" / "1.finding.md"
    assert harvested.read_text(encoding="utf-8") == "a real finding"
    assert not wt.exists()


def test_a_fragment_that_would_collide_stops_the_reap(tmp_path):
    """Must-not-fire control for the harvest test above: a fragment that
    cannot be safely copied (a same-named one already sits in the clone's
    own trap.d/) must keep the tree, never force the removal around the
    loss."""
    clone = tmp_path / "clone"
    _init_repo(clone)
    (clone / "trap.d").mkdir()
    (clone / "trap.d" / "1.finding.md").write_text("already here", encoding="utf-8")
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    (wt / "trap.d").mkdir()
    (wt / "trap.d" / "1.finding.md").write_text("a DIFFERENT finding", encoding="utf-8")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    state, results = worktree_reap.reap(
        clone,
        _config(clone),
        apply=True,
        gh_bin=fake.GH_BIN,
        run=fake,
        list_processes=_unoccupied,
    )
    assert state == "planned"
    assert results[0]["state"] == "kept", results[0]
    assert wt.exists()
    assert (clone / "trap.d" / "1.finding.md").read_text(
        encoding="utf-8"
    ) == "already here"


# ------------------------------------------------------------ doctor_check_worktree_reap


def test_check_reports_ok_when_nothing_reapable(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "OPEN"})
    config = _config(clone)
    state, detail = doctor_check_worktree_reap.worktree_reap_summary(
        clone, config, run=fake, gh_bin=fake.GH_BIN, list_processes=_unoccupied
    )
    assert state == "ok", (state, detail)


def test_check_reports_a_finding_naming_the_runnable_remedy(tmp_path):
    clone = tmp_path / "clone"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    config = _config(clone)
    state, detail = doctor_check_worktree_reap.worktree_reap_summary(
        clone, config, run=fake, gh_bin=fake.GH_BIN, list_processes=_unoccupied
    )
    assert state == "finding", (state, detail)
    assert detail["reapable"] == 1
    doctor_check_worktree_reap.check_worktree_reap(
        clone, config, run=fake, gh_bin=fake.GH_BIN, list_processes=_unoccupied
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "worktree_reap.py" in message
    assert "--apply" in message


def test_remedy_quotes_a_clone_path_containing_a_space(tmp_path, monkeypatch):
    """Auditor review finding on this diff's own commit: an unquoted path in
    a "run this by hand" remedy breaks on the first space -- common on both
    Windows (`C:\\Users\\Jane Doe\\...`) and macOS (`/Users/Jane Doe/...`)."""
    clone = tmp_path / "clone with space"
    _init_repo(clone)
    wt = tmp_path / "wt1"
    _add_worktree(clone, wt, "fix/1")
    fake = _FakeGhRun({"fix/1": "MERGED"})
    monkeypatch.setattr(doctor, "PLUGIN_ROOT", tmp_path / "plugin root")
    config = _config(clone)
    state, detail = doctor_check_worktree_reap.worktree_reap_summary(
        clone, config, run=fake, gh_bin=fake.GH_BIN, list_processes=_unoccupied
    )
    assert state == "finding", (state, detail)
    remedy = detail["remedy"]
    assert '"{}"'.format(str(clone)) in remedy, remedy
    assert (
        '"{}"'.format(str(tmp_path / "plugin root" / "scripts" / "worktree_reap.py"))
        in remedy
    ), remedy


def test_check_could_not_tell_when_no_clone_configured(tmp_path):
    state, detail = doctor_check_worktree_reap.worktree_reap_summary(tmp_path, {})
    assert state == "could-not-tell", (state, detail)
    doctor_check_worktree_reap.check_worktree_reap(tmp_path, {})
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "UNKNOWN, not clean" in message
