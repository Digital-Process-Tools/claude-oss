"""#1155 -- two threshold routes, read by `next_action.py`'s own `rank()`:
/oss:triage, /oss:curate, each a standing count crossing a per-repo threshold, in three
states (`over`/`under`/`could-not-count`), and gated by a #1064-shaped
receipt so a count stuck `over` does not re-fire on every launch forever.
Used to also cover /oss:release; #1652 removed that route -- see
`workspace_routes.py`'s own module docstring.

Every negative assertion below (a route that must NOT arm) is paired with a
positive control in the same test or its sibling, per this repo's own rule:
a comparator that always answers "no route" would pass every "must not
fire" case trivially.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "workspace_routes.py"

sys.path.insert(0, str(REPO / "scripts"))

import oss_state  # noqa: E402
import workspace_routes  # noqa: E402


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(args, cwd, env=None):
    result = subprocess.run(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=env or _git_env(),
    )
    return result


@pytest.fixture
def repo(tmp_path):
    """A real, minimal git repo with its own trap.d/ and changelog.d/, so
    `curate_count` exercises the real directory rather than a mock."""
    root = tmp_path / "repo"
    root.mkdir()
    env = _git_env()
    done = _run(["git", "init", "--quiet", "."], cwd=root, env=env)
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip()))
    _run(["git", "config", "user.email", "t@example.com"], cwd=root, env=env)
    _run(["git", "config", "user.name", "t"], cwd=root, env=env)
    (root / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, env=env)
    return root


def _write_config(root, extra=None):
    config = {
        "repo": "example/example",
        "changelog_dir": "changelog.d",
    }
    if extra:
        config.update(extra)
    (root / ".oss.json").write_text(json.dumps(config))
    return config


def _fake_run_issues(no_lane=0, no_priority=0, total=None, fail=False):
    """A stand-in for `subprocess.run`, mimicking `gh issue list --json
    number,labels`."""
    total = total if total is not None else max(no_lane, no_priority, 1)
    issues = []
    for i in range(total):
        labels = []
        if i >= no_lane:
            labels.append({"name": "lane-doctor"})
        if i >= no_priority:
            labels.append({"name": "priority-high"})
        issues.append({"number": i, "labels": labels})

    class _Result:
        pass

    def run(command, stdout=None, stderr=None, timeout=None):
        result = _Result()
        if fail:
            result.returncode = 1
            result.stdout = b""
            result.stderr = b"gh: some failure"
        else:
            result.returncode = 0
            result.stdout = json.dumps(issues).encode("utf-8")
            result.stderr = b""
        return result

    return run


# --- curate_count -----------------------------------------------------------


def test_curate_count_counts_real_trap_fragments(repo):
    (repo / "trap.d").mkdir()
    (repo / "trap.d" / "1.a.md").write_text("x\n")
    (repo / "trap.d" / "2.b.md").write_text("x\n")
    count, why = workspace_routes.curate_count(str(repo))
    assert count == 2, why


def test_curate_count_of_an_empty_or_absent_directory_is_zero_not_could_not_count(
    repo,
):
    """Positive control for the negative case below: an absent trap.d/ is a
    real `0`, not `could-not-count`."""
    count, why = workspace_routes.curate_count(str(repo))
    assert count == 0, why


def test_curate_count_unreadable_directory_is_could_not_count(repo, monkeypatch):
    """Negative case: an unreadable trap.d/ must render as `could-not-count`,
    never silently as `0` (this repo's own defect class, #1155's own
    counters included)."""
    import trap_curate

    def _boom(root):
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "boom",
        }

    monkeypatch.setattr(trap_curate, "waiting", _boom)
    count, why = workspace_routes.curate_count(str(repo))
    assert count is None, why


# --- curate_count reads origin/<default_branch>, not whatever is checked
# out (#1476) -----------------------------------------------------------------


@pytest.fixture
def repo_on_main(tmp_path):
    """A real git repo, explicitly on a branch named `main`, with an
    `origin/main` remote-tracking ref pointing at that same clean commit --
    everything #1476's scenario needs to fake a shared checkout without a
    real network fetch."""
    root = tmp_path / "repo"
    root.mkdir()
    env = _git_env()
    done = _run(["git", "init", "--quiet", "."], cwd=root, env=env)
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip()))
    _run(["git", "config", "user.email", "t@example.com"], cwd=root, env=env)
    _run(["git", "config", "user.name", "t"], cwd=root, env=env)
    (root / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=root, env=env)
    _run(["git", "checkout", "--quiet", "-B", "main"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, env=env)
    # Fake `origin/main` without a real remote: a plain ref pointing at the
    # same, trap.d/-free commit -- exactly what a genuinely clean default
    # branch looks like from `git ls-tree`.
    _run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=root,
        env=env,
    )
    return root


def test_curate_count_on_a_stale_branch_reads_origin_default_branch_not_the_checkout(
    repo_on_main,
):
    """The paired 'must not fire' half: the checkout has moved to a feature
    branch cut before origin/main's own clean state, and that feature
    branch's own working tree carries two leftover trap.d/ fragments.
    #1476's own incident: reading the checkout's disk state reported this
    branch's stale fragments as though they belonged to main."""
    root = repo_on_main
    env = _git_env()
    _run(["git", "checkout", "--quiet", "-b", "fix/999"], cwd=root, env=env)
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.a.md").write_text("x\n")
    (root / "trap.d" / "2.b.md").write_text("x\n")
    _run(["git", "add", "trap.d"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "stale fragments"], cwd=root, env=env)

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count == 0, why
    assert "origin/main" in why, why


def test_curate_count_on_a_stale_branch_with_no_fetch_ever_run_says_so(repo_on_main):
    """#1522: `curate_count` reads `origin/<default_branch>` via `git
    ls-tree` and nothing on that path fetches, so a confident count is
    attributed to the default branch with no signal of how fresh that
    remote-tracking ref actually is. `repo_on_main` fakes `origin/main`
    with `git update-ref`, never a real `git fetch` -- no `FETCH_HEAD`
    exists in this checkout at all, which is the honest state for a
    freshly cloned or never-fetched repo. `why` must say so rather than
    silently omitting any freshness signal, exactly as before this fix."""
    root = repo_on_main
    env = _git_env()
    _run(["git", "checkout", "--quiet", "-b", "fix/999"], cwd=root, env=env)

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count == 0, why
    assert "no fetch recorded" in why, why


def test_curate_count_on_a_stale_branch_reports_fetch_age(repo_on_main):
    """Positive control for the case above: once a fetch HAS actually
    happened in this checkout (`FETCH_HEAD` exists), `why` must carry how
    long ago that was, not the same 'no fetch recorded' text the case
    above asserts. #1522's own incident: a curate count read from a
    pre-merge `origin/main` rendered identically to a fresh one -- this is
    the signal that would have told the two apart."""
    root = repo_on_main
    env = _git_env()
    _run(["git", "checkout", "--quiet", "-b", "fix/999"], cwd=root, env=env)
    git_dir = root / ".git"
    (git_dir / "FETCH_HEAD").write_text("deadbeef\tnot-for-merge\t\n")
    old = time.time() - 3661  # a little over an hour ago
    os.utime(str(git_dir / "FETCH_HEAD"), (old, old))

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count == 0, why
    assert "no fetch recorded" not in why, why
    assert "last fetched" in why, why


def test_curate_count_on_a_stale_branch_with_git_dir_lookup_failure_does_not_claim_no_fetch(
    repo_on_main,
):
    """Self-review finding (oss:auditor, #1522): the first version of
    `_fetch_head_age_seconds` collapsed "the git-dir lookup itself
    failed" into the identical `None` -- and identical rendered text --
    as "FETCH_HEAD genuinely does not exist", so a real fetch could have
    happened and this would still have confidently claimed none had. The
    two must render differently: this checkout HAS a real FETCH_HEAD
    (written just below), but a `run` that fails the `rev-parse
    --git-dir` call must never be read as though that FETCH_HEAD did not
    exist."""
    root = repo_on_main
    env = _git_env()
    _run(["git", "checkout", "--quiet", "-b", "fix/999"], cwd=root, env=env)
    (root / ".git" / "FETCH_HEAD").write_text("deadbeef\tnot-for-merge\t\n")

    real_run = subprocess.run

    def _boom(command, *args, **kwargs):
        if "rev-parse" in command and "--git-dir" in command:
            return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"boom")
        return real_run(command, *args, **kwargs)

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}, run=_boom
    )
    assert count == 0, why
    assert "no fetch recorded" not in why, why
    assert "last fetched" not in why, why
    assert "could not be determined" in why, why


def test_curate_count_on_the_default_branch_itself_still_counts_real_fragments(
    repo_on_main,
):
    """Positive control for the case above: the checkout genuinely IS the
    default branch and genuinely has fragments waiting -- this must still
    report them, reading the working tree exactly as before (so a
    just-committed, not-yet-pushed curate run is still visible)."""
    root = repo_on_main
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.a.md").write_text("x\n")
    (root / "trap.d" / "2.b.md").write_text("x\n")

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count == 2, why


def test_curate_count_on_the_default_branch_counts_a_committed_but_not_yet_pushed_fragment(
    repo_on_main,
):
    """The scenario the docstring above actually names, exercised for real
    (#1723 self-review finding, Explore reviewer and oss:auditor
    independently): the first version of the #1723 fix deleted the
    branch-aware working-tree read entirely and replaced it with `origin/
    <default_branch>`'s committed tree unioned with only the UNTRACKED
    files in the clone. A fragment that is `git add`ed or even committed on
    `main` itself, but not yet pushed to `origin/main`, is neither of
    those -- it fell out of the count completely under that version. This
    is the real #1476 guarantee restored: committed locally, never
    pushed, still counted."""
    root = repo_on_main
    env = _git_env()
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.local-only.md").write_text("x\n")
    _run(["git", "add", "trap.d"], cwd=root, env=env)
    _run(
        ["git", "commit", "--quiet", "-m", "local commit, never pushed"],
        cwd=root,
        env=env,
    )
    # origin/main (set by the fixture) still points at the ORIGINAL commit --
    # this one was never pushed there.

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count == 1, why


def test_curate_count_with_no_default_branch_configured_keeps_reading_the_checkout(
    repo,
):
    """Back-compat: a caller that passes no `config` (or one with no
    `default_branch`) gets exactly the original, no-branch-awareness
    behaviour -- unchanged from before #1476."""
    (repo / "trap.d").mkdir()
    (repo / "trap.d" / "1.a.md").write_text("x\n")
    count, why = workspace_routes.curate_count(str(repo), config={})
    assert count == 1, why


def test_curate_count_on_a_stale_branch_with_no_resolvable_origin_ref_is_could_not_count(
    tmp_path,
):
    """Third state: standing on a non-default branch with no `origin/
    <default_branch>` ref to read at all must report `could-not-count`
    (`None`), never silently fall back to the wrong branch's own disk
    state and never a guessed `0`."""
    root = tmp_path / "repo"
    root.mkdir()
    env = _git_env()
    done = _run(["git", "init", "--quiet", "."], cwd=root, env=env)
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip()))
    _run(["git", "config", "user.email", "t@example.com"], cwd=root, env=env)
    _run(["git", "config", "user.name", "t"], cwd=root, env=env)
    (root / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=root, env=env)
    _run(["git", "checkout", "--quiet", "-B", "fix/999"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, env=env)
    # No origin/main ref exists anywhere in this repo.

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count is None, why


def test_curate_count_when_the_untracked_scan_fails_off_branch_is_could_not_count(
    repo_on_main, monkeypatch
):
    """#1723: standing on some OTHER branch, `curate_count` reads the
    clone's own untracked `trap.d/` files (`trap_curate.untracked_fragments`)
    so its answer matches what a curate pass's own setup step copies in. A
    repository this scan genuinely could not read must report
    could-not-count, never silently fall back to the ref-only half as
    though nothing were wrong."""
    root = repo_on_main
    env = _git_env()
    _run(["git", "checkout", "--quiet", "-b", "fix/999"], cwd=root, env=env)
    import trap_curate

    def _boom(root_arg, run=None, git_bin=None, timeout=15):
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "boom",
        }

    monkeypatch.setattr(trap_curate, "untracked_fragments", _boom)
    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count is None, why
    assert "boom" in why, why


def test_curate_count_when_the_working_tree_read_fails_on_branch_is_could_not_count(
    repo_on_main, monkeypatch
):
    """The default-branch counterpart of the case above: standing ON the
    default branch, `curate_count` reads the clone's full working tree
    (`trap_curate.waiting`) rather than `untracked_fragments`. That read
    failing must be `could-not-count` too, never a silent fall back to the
    ref-only half."""
    root = repo_on_main
    import trap_curate

    def _boom(root_arg):
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "boom",
        }

    monkeypatch.setattr(trap_curate, "waiting", _boom)
    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count is None, why
    assert "boom" in why, why


def test_curate_count_when_current_branch_cannot_be_determined_is_could_not_count(
    repo_on_main, monkeypatch
):
    """Self-review finding, restored (Explore reviewer and oss:auditor
    independently, #1723): #1723's own first draft deleted this
    branch-detection call entirely, which is what made the committed-but-
    unpushed regression above possible in the first place. An earlier
    #1476 finding already established the rule this protects: a repository
    whose current branch could not even be determined must not read the
    same as one that is genuinely fine."""
    root = repo_on_main
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.a.md").write_text("x\n")

    def _boom(repo_root, run=None, git_bin=None, timeout=10):
        return None, "rev-parse did not run (boom)"

    monkeypatch.setattr(workspace_routes, "_current_branch", _boom)
    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count is None, why


def test_curate_count_combines_committed_and_untracked_fragments(repo_on_main):
    """#1723's own core fix: a fragment committed at `origin/main` and a
    fragment sitting untracked in the clone's own working tree must both
    count, on whichever branch happens to be checked out -- neither half
    alone is the real backlog `/oss:curate` will actually process once it
    also copies the untracked half in (see the parity test below)."""
    root = repo_on_main
    env = _git_env()
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.committed.md").write_text("x\n")
    _run(["git", "add", "trap.d"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "committed fragment"], cwd=root, env=env)
    _run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=root,
        env=env,
    )
    (root / "trap.d" / "2.stray.md").write_text("y\n")  # untracked, on purpose

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count == 2, why


def test_curate_count_sees_untracked_fragments_regardless_of_checked_out_branch(
    repo_on_main,
):
    """#1723's own observation: an untracked file written straight into the
    clone (`harvest_fragments`, a releaser session) sits there regardless of
    which branch HEAD points to -- untracked-ness is a fact about the
    index, not the checkout. The old on-branch/off-branch split missed this
    stray on a feature branch even though the physical file never moved."""
    root = repo_on_main
    env = _git_env()
    _run(["git", "checkout", "--quiet", "-b", "fix/999"], cwd=root, env=env)
    (root / "trap.d").mkdir()
    (root / "trap.d" / "3.stray.md").write_text("z\n")  # untracked

    count, why = workspace_routes.curate_count(
        str(root), config={"default_branch": "main"}
    )
    assert count == 1, why


def test_waiting_at_ref_does_not_descend_into_a_subdirectory(repo_on_main):
    """Self-review finding (Explore reviewer, #1476): `waiting()` lists
    `trap.d/`'s immediate entries only via `os.listdir`; `waiting_at_ref`
    must count the same shape, not a recursive `git ls-tree -r`, or the
    two readers of the same fact could disagree with nothing about the
    real backlog having changed."""
    import trap_curate

    root = repo_on_main
    env = _git_env()
    (root / "trap.d").mkdir()
    (root / "trap.d" / "sub").mkdir()
    (root / "trap.d" / "1.a.md").write_text("x\n")
    (root / "trap.d" / "sub" / "2.b.md").write_text("y\n")
    _run(["git", "add", "trap.d"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "nested fragment"], cwd=root, env=env)
    _run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=root,
        env=env,
    )

    result = trap_curate.waiting_at_ref(str(root), "origin/main")
    assert result["count"] == 1, result
    assert result["fragments"][0]["name"] == "1.a.md", result


# --- triage_count ------------------------------------------------------------


def test_triage_count_is_the_larger_of_no_lane_and_no_priority():
    run = _fake_run_issues(no_lane=1, no_priority=3, total=5)
    count, why = workspace_routes.triage_count("example/example", "gh", run)
    assert count == 3, why


def test_triage_count_of_a_fully_labelled_board_is_zero():
    """Positive control: every issue carries both labels -- a real `0`."""
    run = _fake_run_issues(no_lane=0, no_priority=0, total=5)
    count, why = workspace_routes.triage_count("example/example", "gh", run)
    assert count == 0, why


def test_triage_count_a_failed_gh_call_is_could_not_count():
    run = _fake_run_issues(fail=True)
    count, why = workspace_routes.triage_count("example/example", "gh", run)
    assert count is None, why


def test_triage_count_with_no_gh_binary_is_could_not_count():
    count, why = workspace_routes.triage_count("example/example", None, subprocess.run)
    assert count is None, why


def _fake_run_issues_with_labels(label_sets):
    """A stand-in for `subprocess.run`, one issue per entry in `label_sets`,
    each entry a list of the label names that issue carries verbatim."""
    issues = [
        {"number": i, "labels": [{"name": name} for name in names]}
        for i, names in enumerate(label_sets)
    ]

    class _Result:
        pass

    def run(command, stdout=None, stderr=None, timeout=None):
        result = _Result()
        result.returncode = 0
        result.stdout = json.dumps(issues).encode("utf-8")
        result.stderr = b""
        return result

    return run


def test_triage_count_honours_config_declared_label_spellings():
    """#1749: a repo whose `.oss.json` spells its priority label
    `priority:high` (colon) rather than `priority-high` (hyphen) must not
    have every issue counted as missing it -- `triage_count` should match
    against what the repo actually declares, the same way
    `statusline._gh_unlabelled_issue_counts` already does."""
    label_sets = [
        ["lane-doctor", "priority:high"],
        ["lane-doctor", "priority:medium"],
        ["priority:low"],  # missing lane
        ["lane-doctor"],  # missing priority
        ["lane-doctor", "priority:high"],
        ["lane-doctor", "priority:high"],
    ]
    run = _fake_run_issues_with_labels(label_sets)
    config = {
        "labels": {
            "priority": ["priority:high", "priority:medium", "priority:low"],
            "lanes": ["lane-doctor"],
        }
    }
    count, why = workspace_routes.triage_count(
        "example/example", "gh", run, config=config
    )
    assert count == 1, why


# --- decide(): thresholds, third state, precedence ---------------------------


def test_route_with_no_configured_threshold_is_not_evaluated(repo):
    config = _write_config(repo)
    armed, results = workspace_routes.decide(str(repo), config, gh=None)
    assert armed is None
    assert results["curate"] == {"configured": False}
    assert results["triage"] == {"configured": False}


def test_route_under_threshold_does_not_arm(repo):
    (repo / "trap.d").mkdir()
    (repo / "trap.d" / "1.a.md").write_text("x\n")
    config = _write_config(repo, {"curate_route_threshold": 5})
    armed, results = workspace_routes.decide(str(repo), config, gh=None)
    assert armed is None
    assert results["curate"]["state"] == "under"


def test_route_over_threshold_arms(repo):
    """Positive control for the assertion above: the same fixture, more
    fragments than the threshold, must arm."""
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    config = _write_config(repo, {"curate_route_threshold": 5})
    armed, results = workspace_routes.decide(str(repo), config, gh=None)
    assert armed == "curate"
    assert results["curate"]["state"] == "over"


def test_an_invalid_threshold_is_could_not_count_not_silently_ignored(repo):
    config = _write_config(repo, {"curate_route_threshold": -1})
    armed, results = workspace_routes.decide(str(repo), config, gh=None)
    assert results["curate"]["state"] == "could-not-count"
    assert results["curate"]["count"] is None
    # could-not-count never arms a route -- an unreadable count is not a
    # green light.
    assert armed is None


def test_precedence_prefers_triage_over_curate(repo, monkeypatch):
    """#1652: ROUTES used to be ("release", "triage", "curate"); with
    `release` removed, triage is now the first, most-blocking entry."""
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    config = _write_config(
        repo,
        {
            "curate_route_threshold": 1,
            "triage_route_threshold": 1,
        },
    )
    run = _fake_run_issues(no_lane=5, no_priority=5, total=5)
    armed, results = workspace_routes.decide(str(repo), config, gh="gh", run=run)
    assert armed == "triage"
    assert results["triage"]["state"] == "over"
    assert results["curate"]["state"] == "over"


def test_precedence_falls_through_to_curate_when_triage_is_under(repo):
    """Positive control for the assertion above: when triage is under its
    own threshold, precedence falls through to curate rather than staying
    stuck on the higher-ranked route."""
    config = _write_config(
        repo,
        {
            "curate_route_threshold": 1,
            "triage_route_threshold": 100,
        },
    )
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    run = _fake_run_issues(no_lane=0, no_priority=0, total=5)
    armed, results = workspace_routes.decide(str(repo), config, gh="gh", run=run)
    assert armed == "curate"


# --- the CLI: not-configured, over, receipt suppression, re-arm -------------


def _run_cli(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def test_cli_prints_route_none_with_no_thresholds_configured(repo):
    _write_config(repo)
    done = _run_cli(["--root", str(repo)])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ROUTE: none" in done.stdout


def test_cli_arms_a_route_and_records_a_receipt_then_does_not_refire(repo):
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    state_file = ".max/watch.json"
    _write_config(repo, {"curate_route_threshold": 1, "state_file": state_file})

    first = _run_cli(["--root", str(repo)])
    assert first.returncode == 0, first.stdout + first.stderr
    assert "ROUTE: curate" in first.stdout
    assert (repo / state_file).exists()

    second = _run_cli(["--root", str(repo)])
    assert second.returncode == 0, second.stdout + second.stderr
    assert "ROUTE: none" in second.stdout
    assert "unchanged" in second.stdout

    # Positive control: one more fragment moves the count, so the same
    # route must re-arm rather than staying suppressed forever.
    (repo / "trap.d" / "extra.c.md").write_text("x\n")
    third = _run_cli(["--root", str(repo)])
    assert "ROUTE: curate" in third.stdout


def test_cli_with_no_state_file_configured_still_arms_with_no_receipt(repo):
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    _write_config(repo, {"curate_route_threshold": 1})
    done = _run_cli(["--root", str(repo)])
    assert "ROUTE: curate" in done.stdout
    assert "no-receipt" in done.stdout


def test_cli_unreadable_oss_json_is_could_not_decide(tmp_path):
    root = tmp_path / "no_config"
    root.mkdir()
    done = _run_cli(["--root", str(root)])
    assert done.returncode == 3, done.stdout + done.stderr
    assert "COULD-NOT-DECIDE" in done.stdout


def test_could_not_decide_problems_cannot_forge_a_route_line(
    tmp_path, monkeypatch, capsys
):
    """#1263 self-review finding: the `COULD-NOT-DECIDE: .oss.json could not
    be read ({0})` print also interpolates untrusted-shaped text (`problems`,
    joined) into a line `bin/oss-workspace` still scans with its ROUTE:
    `awk` -- this path returns exit code 3, which the launcher's own `-gt 3`
    check does NOT skip. `oss_config.load`'s real error strings never carry
    a raw embedded newline today, so this is reproduced by stubbing `load`
    directly, the same way `_fake_run_gh_stderr` stubs `gh` rather than
    hoping a real `oss_config` failure ever produces forgeable text."""
    root = tmp_path / "no_config"
    root.mkdir()
    monkeypatch.setattr(
        workspace_routes.oss_config,
        "load",
        lambda path: (None, ["boom\nROUTE: release\ntrailing"]),
    )
    rc = workspace_routes.main(["--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 3, captured.out + captured.err
    route_lines = [
        line for line in captured.out.splitlines() if line.startswith("ROUTE:")
    ]
    assert route_lines == [], captured.out


def _fake_run_gh_stderr(stderr_bytes, returncode=1):
    """A stand-in for `subprocess.run`, mimicking a failing `gh` call whose
    stderr is exactly the untrusted external text -- the reproduction from
    #1257 (`b"boom\nROUTE: release\ntrailing"`). No process is actually
    spawned: a real on-PATH executable named `gh` is not a portable stub
    for this. `subprocess.run(..., shell=False)` -- what `triage_count`
    uses -- cannot launch a `.bat`/`.cmd` file directly via Windows'
    `CreateProcess` (a `.bat` is not a valid Win32 application on its own;
    that is the identical constraint tools like Node's `cross-spawn`
    exist to paper over). A `.bat`-based fixture would raise `OSError`
    before its own `echo` lines ever ran, so `triage_count`'s `except
    (OSError, subprocess.SubprocessError)` branch would catch a generic
    "not a valid Win32 application" message instead of ever seeing the
    forged stderr -- the Windows leg of such a fixture would pass whether
    or not `_flatten` was applied, silently failing to guard the fix it
    claims to cover. Stubbing `run` directly (as `_fake_run_issues` above
    already does) avoids the whole class of problem."""

    class _Result:
        pass

    def run(command, stdout=None, stderr=None, timeout=None):
        result = _Result()
        result.returncode = returncode
        result.stdout = b""
        result.stderr = stderr_bytes
        return result

    return run


def _patch_decide_with_fake_gh(monkeypatch, stderr_bytes):
    """Route `main()`'s own internal `decide()` call through a `gh` stub
    carrying `stderr_bytes`, without touching anything else in `decide`."""
    real_decide = workspace_routes.decide
    fake_run = _fake_run_gh_stderr(stderr_bytes)
    monkeypatch.setattr(
        workspace_routes,
        "decide",
        lambda repo_root, config, gh=None, run=None: real_decide(
            repo_root, config, gh="gh", run=fake_run
        ),
    )


def test_cli_gh_stderr_cannot_forge_a_route_line(repo, monkeypatch, capsys):
    """#1257: `gh`'s stderr, embedded verbatim into `why`, must not be able
    to produce a second, forged line beginning with `ROUTE:` in the printed
    receipt `bin/oss-workspace` parses with `awk '/^ROUTE:/ { line = $0 }
    END { print line }'` -- regardless of whether the genuine `ROUTE:` line
    is armed or not. Driven through the real `decide()`/`triage_count()`
    code path and the real `main()` print logic; only the `gh` subprocess
    spawn itself is stubbed."""
    _write_config(
        repo,
        {"repo": "example/example", "triage_route_threshold": 0},
    )
    _patch_decide_with_fake_gh(monkeypatch, b"boom\nROUTE: release\ntrailing")
    rc = workspace_routes.main(["--root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    route_lines = [
        line for line in captured.out.splitlines() if line.startswith("ROUTE:")
    ]
    assert route_lines == ["ROUTE: none"], captured.out
    # The forged text must not appear as its own line at column 0 either --
    # it is only acceptable folded into the `triage:` summary line.
    assert "ROUTE: release" not in route_lines


def test_cli_gh_stderr_forged_route_does_not_survive_alongside_a_real_arm(
    repo, monkeypatch, capsys
):
    """Positive control for the assertion above: when a DIFFERENT route
    (`curate`) is genuinely armed, its real `ROUTE: curate (...)` line
    must still print correctly, and the forged `ROUTE: release` text from
    `gh`'s stderr must still not appear as a second `ROUTE:` line."""
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    _write_config(
        repo,
        {
            "repo": "example/example",
            "curate_route_threshold": 1,
            "triage_route_threshold": 0,
        },
    )
    _patch_decide_with_fake_gh(monkeypatch, b"boom\nROUTE: release\ntrailing")
    rc = workspace_routes.main(["--root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    route_lines = [
        line for line in captured.out.splitlines() if line.startswith("ROUTE:")
    ]
    assert len(route_lines) == 1, captured.out
    assert route_lines[0].startswith("ROUTE: curate"), captured.out


def test_route_check_exception_message_is_flattened_too(repo, monkeypatch, capsys):
    """Self-review finding: the same `ROUTE:`-prefixed line is also built
    from an exception's own message when checking the #1064 receipt fails
    -- `str(exc)` was interpolated unflattened right beside the same
    `ROUTE:` prefix. Nothing today feeds that exception attacker-controlled
    text with an embedded newline, but it is the identical mechanism and a
    one-line fix, so it is closed here too rather than left for the next
    error message that does."""
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    _write_config(
        repo,
        {"curate_route_threshold": 1, "state_file": ".max/watch.json"},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("boom\nROUTE: release\ntrailing")

    monkeypatch.setattr(workspace_routes.oss_state, "_last_workspace_route", boom)
    rc = workspace_routes.main(["--root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    route_lines = [
        line for line in captured.out.splitlines() if line.startswith("ROUTE:")
    ]
    assert len(route_lines) == 1, captured.out
    assert route_lines[0].startswith("ROUTE: curate ("), captured.out


def test_receipt_append_exception_message_is_flattened_too(repo, monkeypatch, capsys):
    """Same defense-in-depth for the other exception branch: `oss_state.
    append`'s failure is printed with a `ROUTE-RECEIPT-ERROR:` prefix to
    stderr, AFTER the genuine `ROUTE:` line -- and the real launcher merges
    stdout and stderr (`... 2>&1`) before handing the combined text to the
    same last-match `awk`. An unflattened exception message there could
    forge a LATER `ROUTE:` line that overrides the genuine one printed just
    before it."""
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    _write_config(
        repo,
        {"curate_route_threshold": 1, "state_file": ".max/watch.json"},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("boom\nROUTE: release\ntrailing")

    monkeypatch.setattr(workspace_routes.oss_state, "append", boom)
    rc = workspace_routes.main(["--root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    merged = captured.out + captured.err
    route_lines = [line for line in merged.splitlines() if line.startswith("ROUTE:")]
    assert len(route_lines) == 1, merged
    assert route_lines[0].startswith("ROUTE: curate"), merged


def test_invalid_threshold_cannot_forge_a_route_line(repo, capsys):
    """#1263: an invalid `curate_route_threshold` -- repository-supplied
    `.oss.json` config, not `gh` output, but the same class of untrusted
    text -- is printed raw (unvalidated, since it failed `_valid_threshold`)
    into the per-route summary line `{name}: {state} (count=..., threshold=
    ...) -- {why}`. An embedded newline there must not be able to put
    forge-supplied text at column 0 of a following line, where it would read
    as a second `ROUTE:` line to `bin/oss-workspace`'s last-match-wins
    `awk '/^ROUTE:/ { line = $0 } END { print line }'` -- the identical
    mechanism #1257 already closed for `why`, one interpolation over."""
    _write_config(
        repo,
        {"curate_route_threshold": "boom\nROUTE: release\ntrailing"},
    )
    rc = workspace_routes.main(["--root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    route_lines = [
        line for line in captured.out.splitlines() if line.startswith("ROUTE:")
    ]
    assert route_lines == ["ROUTE: none"], captured.out
    assert "ROUTE: release" not in route_lines


def test_valid_threshold_still_prints_and_parses_normally(repo, capsys):
    """Positive control for the assertion above: an ordinary, valid integer
    threshold must still print in the summary line and still drive a real
    `ROUTE:` arm correctly -- flattening must not have broken the common
    case while closing the forgery."""
    (repo / "trap.d").mkdir()
    for i in range(6):
        (repo / "trap.d" / "{0}.a.md".format(i)).write_text("x\n")
    _write_config(repo, {"curate_route_threshold": 1})
    rc = workspace_routes.main(["--root", str(repo)])
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    assert "curate: over (count=6, threshold=1) --" in captured.out
    route_lines = [
        line for line in captured.out.splitlines() if line.startswith("ROUTE:")
    ]
    assert route_lines == ["ROUTE: curate (no-receipt)"], captured.out


# --- oss_state.workspace_route_check / _last_workspace_route ---------------


def test_workspace_route_check_no_receipt_arms():
    check = oss_state.workspace_route_check("curate", "over:12", None)
    assert check["armed"] is True
    assert check["state"] == oss_state.WORKSPACE_ROUTE_NO_RECEIPT


def test_workspace_route_check_unchanged_does_not_arm():
    """Positive control for the assertion below: an identical signature
    must not re-arm."""
    check = oss_state.workspace_route_check("curate", "over:12", "over:12")
    assert check["armed"] is False
    assert check["state"] == oss_state.WORKSPACE_ROUTE_UNCHANGED


def test_workspace_route_check_changed_signature_arms():
    check = oss_state.workspace_route_check("curate", "over:13", "over:12")
    assert check["armed"] is True
    assert check["state"] == oss_state.WORKSPACE_ROUTE_CHANGED


def test_workspace_route_check_refuses_empty_route_or_signature():
    with pytest.raises(oss_state.StateError):
        oss_state.workspace_route_check("", "over:12", None)
    with pytest.raises(oss_state.StateError):
        oss_state.workspace_route_check("curate", "", None)


def test_last_workspace_route_finds_only_the_named_route(tmp_path):
    path = tmp_path / "state.json"
    oss_state.append(
        path,
        "2026-01-01T00:00:00Z",
        "recorded a #1155 route receipt",
        detail={
            "workspace_route_name": "curate",
            "workspace_route_signature": "over:11",
        },
    )
    oss_state.append(
        path,
        "2026-01-02T00:00:00Z",
        "recorded a #1155 route receipt",
        detail={
            "workspace_route_name": "release",
            "workspace_route_signature": "over:20",
        },
    )
    _entry, curate_sig = oss_state._last_workspace_route(path, "curate")
    assert curate_sig == "over:11"
    _entry, release_sig = oss_state._last_workspace_route(path, "release")
    assert release_sig == "over:20"
    _entry, triage_sig = oss_state._last_workspace_route(path, "triage")
    assert triage_sig is None
