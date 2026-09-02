"""#763: doctor never compared the clone's actual HEAD against `.oss.json`'s
`default_branch` -- a clone left on a merged/stale branch by `gh-pr-merge`'s own
declined cleanup served stale config for two hours of a live tick and doctor's
existing `clone` check (`check_directory`) never noticed, because it only ever
reports the configured path.

Three states, never two: `on-default` / `on-other` / `could-not-tell`, and the
third is load-bearing the same way it is everywhere else in this diagnostic -- a
detached HEAD is not on the default branch and is also not a stale feature
branch, so a run that could not read HEAD at all must not render as either.

These tests build real git repositories (`_init_repo`/`_bare_remote` below)
rather than mocking `subprocess.run`, per CLAUDE.md's rule that a permission or
state fixture is a measurement, not a given -- the `git` commands under test
(`rev-parse`, `rev-list --left-right --count`, `ls-remote`) are cheap enough to
run for real and a mock would only assert that the mock was called correctly.

Every "must not fire" case is paired with a "must fire" case in the same fixture
family, per CLAUDE.md's rule that a negative assertion needs a positive control.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root)] + list(args),
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


def _bare_remote(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    return remote


def _config(default_branch="main", **overrides):
    config = {"default_branch": default_branch}
    config.update(overrides)
    return config


# --------------------------------------------------------------- could-not-tell


def test_could_not_tell_when_git_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    state, detail = doctor.clone_head_state(tmp_path, _config())
    assert state == "could-not-tell"
    assert "git is not on PATH" in detail


def test_could_not_tell_when_default_branch_is_not_configured(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    state, _detail = doctor.clone_head_state(repo, _config(default_branch=None))
    assert state == "could-not-tell"


def test_could_not_tell_when_config_is_none(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    state, _detail = doctor.clone_head_state(repo, None)
    assert state == "could-not-tell"


def test_could_not_tell_on_a_detached_head(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", sha)
    state, detail = doctor.clone_head_state(repo, _config())
    assert state == "could-not-tell"
    assert "detached" in detail


def test_could_not_tell_when_the_directory_is_not_a_git_repo(tmp_path):
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    state, _detail = doctor.clone_head_state(repo, _config())
    assert state == "could-not-tell"


# --------------------------------------------------------------- on-default


def test_on_default_branch_with_no_commits_yet_is_still_on_default(tmp_path):
    """`git rev-parse --abbrev-ref HEAD` fails on an UNBORN branch (a repo with
    no commits yet: "fatal: ambiguous argument 'HEAD': unknown revision") --
    measured while writing this check. A brand-new repo correctly on its default
    branch must not render as `could-not-tell` for that reason; the
    implementation reads `git symbolic-ref --short HEAD` instead, which answers
    with no commits required."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    state, detail = doctor.clone_head_state(root, _config())
    assert state == "on-default"
    assert detail["branch"] == "main"


def test_on_default_branch_up_to_date_is_ok(tmp_path):
    """Positive control for the WARN-on-behind test below: zero behind must not
    itself be WARN-worthy."""
    remote = _bare_remote(tmp_path)
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    state, detail = doctor.clone_head_state(repo, _config())
    assert state == "on-default"
    assert detail["branch"] == "main"
    assert detail["ahead"] == 0
    assert detail["behind"] == 0


def test_on_default_branch_but_behind_is_flagged_in_the_detail(tmp_path):
    """The observed cost (#763) came from being BEHIND, not merely from being on
    a branch -- so `behind > 0` is what the caller WARNs on, never `on-default`
    alone. Paired with the up-to-date positive control above."""
    remote = _bare_remote(tmp_path)
    origin_seed = tmp_path / "seed"
    _init_repo(origin_seed)
    _git(origin_seed, "remote", "add", "origin", str(remote))
    _git(origin_seed, "push", "-q", "-u", "origin", "main")

    repo = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    # The bare remote's own HEAD symref was never updated off its unborn default
    # (created before `main` existed on it), so a plain clone can leave the
    # checkout on that missing ref -- force it onto `main`, tracking origin/main,
    # so the fixture actually exercises "on the default branch, behind".
    _git(repo, "checkout", "-q", "-B", "main", "origin/main")

    # Advance the remote past the clone without pulling.
    (origin_seed / "f.txt").write_text("2", encoding="utf-8")
    _git(origin_seed, "add", "f.txt")
    _git(origin_seed, "commit", "-q", "-m", "second")
    _git(origin_seed, "push", "-q")
    _git(repo, "fetch", "-q", "origin")

    state, detail = doctor.clone_head_state(repo, _config())
    assert state == "on-default"
    assert detail["behind"] == 1
    assert detail["ahead"] == 0


def test_on_default_branch_with_no_upstream_reports_counts_unavailable(tmp_path):
    """No `origin` at all -- a repo that has never been pushed. Still `on-default`
    (the branch question is answered), but the ahead/behind counts cannot be, and
    that has to be said rather than defaulted to 0/0."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    state, detail = doctor.clone_head_state(repo, _config())
    assert state == "on-default"
    assert detail["ahead"] is None
    assert detail["behind"] is None


# --------------------------------------------------------------- on-other


def test_on_other_branch_with_a_live_remote_ref(tmp_path):
    remote = _bare_remote(tmp_path)
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    _git(repo, "checkout", "-q", "-b", "feature/x")
    _git(repo, "push", "-q", "-u", "origin", "feature/x")
    state, detail = doctor.clone_head_state(repo, _config())
    assert state == "on-other"
    assert detail["branch"] == "feature/x"
    assert detail["remote"] == "exists"


def test_on_other_branch_whose_remote_ref_is_gone_is_the_post_merge_signature(tmp_path):
    """Positive control paired with the live-remote test above: a branch whose
    remote ref is gone is `gh-pr-merge`'s own declined-cleanup shape."""
    remote = _bare_remote(tmp_path)
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    _git(repo, "checkout", "-q", "-b", "feature/merged")
    _git(repo, "push", "-q", "-u", "origin", "feature/merged")
    _git(repo, "push", "-q", "origin", "--delete", "feature/merged")
    state, detail = doctor.clone_head_state(repo, _config())
    assert state == "on-other"
    assert detail["branch"] == "feature/merged"
    assert detail["remote"] == "gone"


def test_on_other_branch_with_no_origin_at_all_reports_remote_unknown(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "feature/local-only")
    state, detail = doctor.clone_head_state(repo, _config())
    assert state == "on-other"
    assert detail["remote"] == "unknown"


# --------------------------------------------------------------- report line


def test_check_clone_head_reports_ok_when_up_to_date(tmp_path, capsys):
    remote = _bare_remote(tmp_path)
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    doctor.check_clone_head(repo, _config())
    out = capsys.readouterr().out
    assert out.startswith("OK ")
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_clone_head_warns_when_behind(tmp_path, capsys):
    remote = _bare_remote(tmp_path)
    origin_seed = tmp_path / "seed"
    _init_repo(origin_seed)
    _git(origin_seed, "remote", "add", "origin", str(remote))
    _git(origin_seed, "push", "-q", "-u", "origin", "main")

    repo = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-B", "main", "origin/main")

    (origin_seed / "f.txt").write_text("2", encoding="utf-8")
    _git(origin_seed, "add", "f.txt")
    _git(origin_seed, "commit", "-q", "-m", "second")
    _git(origin_seed, "push", "-q")
    _git(repo, "fetch", "-q", "origin")

    doctor.check_clone_head(repo, _config())
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "behind" in out


def test_check_clone_head_warns_naming_the_branch_when_not_on_default(tmp_path, capsys):
    remote = _bare_remote(tmp_path)
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    _git(repo, "checkout", "-q", "-b", "chore/codeql-actions")
    _git(repo, "push", "-q", "-u", "origin", "chore/codeql-actions")
    _git(repo, "push", "-q", "origin", "--delete", "chore/codeql-actions")
    doctor.check_clone_head(repo, _config())
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "chore/codeql-actions" in out
    assert "very likely" in out


def test_check_clone_head_says_could_not_tell_distinctly(tmp_path, capsys):
    """Negative control: neither the OK nor either WARN wording appears when
    the answer is genuinely unreadable (detached HEAD here)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", sha)
    doctor.check_clone_head(repo, _config())
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not tell" in out
    assert "very likely" not in out
