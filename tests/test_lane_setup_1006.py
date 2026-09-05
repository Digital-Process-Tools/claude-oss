"""#1006: stacking a new lane's branch on another lane's own branch tip, instead
of always deriving `base` from `default_branch`, sidesteps `git-worktrees`'
`cannot tell` collision entirely -- a stacked branch is cut from a ref read
straight out of the shared object database and never touches the worktree a
live agent (or the manager's own merge) might have just written to.

`resolve_stacked_base` is the new primitive (#1006's third candidate fix,
chosen for blast radius: no change to `git-worktrees` itself, so nothing here
needs an upstream filing to land). Three states, same shape as `resolve_base`
elsewhere in this module: `resolved` (found locally -- most likely freshest,
since a sibling worktree cut from the same repo has already advanced it),
`resolved-remote` (found only as a remote-tracking ref, explicitly flagged as
possibly stale), and `could-not-resolve` (neither exists).

Every case that proves a well-formed name resolves has a hostile sibling
proving a dash-prefixed one is refused before reaching git's argv -- the same
guard `resolve_base`'s own #368/#381 tests hold for `default_branch` and
`remote`, applied to the value this function adds.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402

import pytest


def _real_git_repo(tmp_path):
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


def test_resolves_a_local_branch_tip(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/683"], check=True)
    result = lane_setup.resolve_stacked_base(repo, "origin", "fix/683")
    assert result["state"] == "resolved"
    assert result["ref"] == "refs/heads/fix/683"
    assert result["sha"]


def test_control_unresolved_branch_does_not_resolve(tmp_path):
    """Positive control: a branch that was never created must not resolve --
    proves the assertion above is actually discriminating rather than passing
    on a broken harness."""
    repo = _real_git_repo(tmp_path)
    result = lane_setup.resolve_stacked_base(repo, "origin", "fix/never-existed")
    assert result["state"] == "could-not-resolve"


def test_falls_back_to_a_remote_tracking_ref_and_flags_it(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/fix/683", "HEAD"],
        check=True,
    )
    result = lane_setup.resolve_stacked_base(repo, "origin", "fix/683")
    assert result["state"] == "resolved-remote"
    assert result["ref"] == "refs/remotes/origin/fix/683"
    assert result["sha"]
    assert result["detail"]


def test_local_ref_preferred_over_remote_tracking_ref(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/fix/683", "HEAD"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "--allow-empty", "-m", "y"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "branch", "fix/683"], check=True)
    result = lane_setup.resolve_stacked_base(repo, "origin", "fix/683")
    assert result["state"] == "resolved"
    assert result["ref"] == "refs/heads/fix/683"


def test_could_not_resolve_when_neither_ref_exists(tmp_path):
    repo = _real_git_repo(tmp_path)
    result = lane_setup.resolve_stacked_base(repo, "origin", "no-such-branch")
    assert result["state"] == "could-not-resolve"
    assert result["sha"] is None


def test_dash_prefixed_branch_name_is_refused_before_reaching_git(tmp_path):
    """#368/#381's own guard, applied to `stack_on`: a dash-prefixed value must
    never reach git's argv unprefixed. Both `refs/heads/` and
    `refs/remotes/<remote>/` prefixes already protect the position this
    function hands to git -- this pins that a value engineered to look like a
    flag is still refused rather than silently treated as a (nonexistent)
    branch called literally that, and that it is refused loudly rather than
    merely failing to resolve for an unrelated reason."""
    repo = _real_git_repo(tmp_path)
    result = lane_setup.resolve_stacked_base(repo, "origin", "--upload-pack=true")
    assert result["state"] == "could-not-resolve"


def test_non_string_stack_on_does_not_crash(tmp_path):
    repo = _real_git_repo(tmp_path)
    result = lane_setup.resolve_stacked_base(repo, "origin", None)
    assert result["state"] == "could-not-resolve"


def test_empty_stack_on_does_not_crash(tmp_path):
    repo = _real_git_repo(tmp_path)
    result = lane_setup.resolve_stacked_base(repo, "origin", "")
    assert result["state"] == "could-not-resolve"


# --- compute(): --stack-on wired through, base skips default_branch entirely ---


def test_compute_uses_stacked_base_instead_of_default_branch(tmp_path):
    repo = _real_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "branch", "fix/683"], check=True)
    (repo / ".oss.json").write_text(
        '{"repo": "example/example", "default_branch": "does-not-exist-anywhere", '
        '"branch_pattern": "fix/{issue}", "test_command": "pytest", '
        '"version_sites": [], "changelog_dir": null, "docs_targets": [], '
        '"labels": {"priority": [], "lanes": []}}'
    )
    payload = lane_setup.compute(repo, 996, stack_on="fix/683")
    assert payload["base"]["state"] == "resolved"
    assert payload["base"]["ref"] == "refs/heads/fix/683"


# --- receipt(): resolved-stale keeps its own wording, resolved-remote gets its own ---
# (review round: an earlier version of this diff silently renamed the pre-existing
# resolved-stale ("STALE") flag to "NOTE" for every non-resolved base state,
# including the ordinary default_branch path this issue never touched.)


def _minimal_payload(base_payload):
    return dict(
        issue=1006,
        repo=".",
        config={"state": "ok", "problems": []},
        base=base_payload,
        branch={
            "state": "resolved",
            "pattern": "fix/{issue}",
            "name": "fix/1006",
            "exists_local": False,
            "exists_remote": False,
            "detail": "",
        },
        worktree={
            "state": "unknown",
            "root": None,
            "path": None,
            "detail": "",
            "exists": None,
        },
        board={"state": "ok", "lines": [], "detail": ""},
    )


def test_receipt_still_says_stale_for_a_genuinely_stale_default_branch_fetch():
    payload = _minimal_payload(
        {
            "remote": "origin",
            "state": "resolved-stale",
            "ref": "origin/main",
            "sha": "a" * 40,
            "detail": "fetch failed, using the last-known ref: timed out",
        }
    )
    text = lane_setup.receipt(payload)
    base_line = [l for l in text.splitlines() if l.startswith("base")][0]
    assert "STALE" in base_line
    assert "NOTE" not in base_line


def test_receipt_says_note_not_stale_for_a_resolved_remote_stacked_base():
    payload = _minimal_payload(
        {
            "remote": "origin",
            "state": "resolved-remote",
            "ref": "refs/remotes/origin/fix/683",
            "sha": "b" * 40,
            "detail": "found only as a remote-tracking ref",
        }
    )
    text = lane_setup.receipt(payload)
    base_line = [l for l in text.splitlines() if l.startswith("base")][0]
    assert "NOTE" in base_line
    assert "STALE" not in base_line
