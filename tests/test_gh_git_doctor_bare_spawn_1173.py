"""#1173: four more bare gh/git spawns reachable from doctor.py's main() --
`published_versions` (`subprocess.run(["gh", "api", ...])`), `_git_head`,
`_git_ls_files_tracked` and `_origin_slug` (each `subprocess.run(["git",
...])`), gated on a `shutil.which("gh"|"git") is None` check whose result
was then discarded -- the resolved path was never substituted into the
spawned argv. Same class, same fix as #1157/#1163/#1168/#1172: route
through `gh_which.safe_which` and spawn the RESOLVED path, never the bare
literal name.

Every "must fire" case here is paired with a "must not fire" positive
control in the same fixture, per CLAUDE.md's own rule: a `safe_which` that
resolves to a fully-qualified path must be what gets spawned, and a
`safe_which` that finds nothing must still be handled (no spawn at all)
rather than crashing on a `None` argv[0].
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

_FAKE_GIT_CMD = r"C:\fake\bin\git.cmd"
_FAKE_GH_CMD = r"C:\fake\bin\gh.cmd"


class _RecordingSubprocessRun:
    """Records the argv `subprocess.run` was called with and returns a
    canned `CompletedProcess`-like result."""

    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return self


# ------------------------------------------------------- published_versions


def test_published_versions_resolves_gh_via_safe_which(monkeypatch):
    monkeypatch.setattr(
        doctor.gh_which, "safe_which", lambda name, path=None: _FAKE_GH_CMD
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError("published_versions must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(returncode=1)  # non-zero -> no further parsing needed
    monkeypatch.setattr(doctor.subprocess, "run", run)

    doctor.published_versions({"claude-oss": "https://github.com/owner/claude-oss"})

    assert run.calls, "subprocess.run was never called"
    assert run.calls[0][0] == _FAKE_GH_CMD, run.calls


def test_published_versions_skips_when_safe_which_finds_nothing(monkeypatch):
    """Positive control: `safe_which` returning `None` for `gh` must still be
    handled -- no spawn at all, not a crash on a `None` argv[0]."""
    monkeypatch.setattr(doctor.gh_which, "safe_which", lambda name, path=None: None)

    def _boom(*_args, **_kwargs):
        raise AssertionError("published_versions must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(returncode=0)
    monkeypatch.setattr(doctor.subprocess, "run", run)

    result = doctor.published_versions(
        {"claude-oss": "https://github.com/owner/claude-oss"}
    )

    assert not run.calls, run.calls
    assert result == {"claude-oss": None}


# -------------------------------------------------------------- _git_head


def test_git_head_resolves_git_via_safe_which(monkeypatch, tmp_path):
    monkeypatch.setattr(
        doctor.gh_which, "safe_which", lambda name, path=None: _FAKE_GIT_CMD
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError("_git_head must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(returncode=0, stdout="abc1234\n")
    monkeypatch.setattr(doctor.subprocess, "run", run)

    result = doctor._git_head(tmp_path)

    assert run.calls, "subprocess.run was never called"
    assert run.calls[0][0] == _FAKE_GIT_CMD, run.calls
    assert "abc1234" in result


def test_git_head_says_so_when_safe_which_finds_nothing(monkeypatch, tmp_path):
    """Positive control: `safe_which` returning `None` for `git` must still
    be handled -- the named "not on PATH" state, not a spawn attempt."""
    monkeypatch.setattr(doctor.gh_which, "safe_which", lambda name, path=None: None)

    def _boom(*_args, **_kwargs):
        raise AssertionError("_git_head must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(returncode=0)
    monkeypatch.setattr(doctor.subprocess, "run", run)

    result = doctor._git_head(tmp_path)

    assert not run.calls, run.calls
    assert result == "git not on PATH"


# ------------------------------------------------------ _git_ls_files_tracked


def test_git_ls_files_tracked_resolves_git_via_safe_which(monkeypatch, tmp_path):
    monkeypatch.setattr(
        doctor.gh_which, "safe_which", lambda name, path=None: _FAKE_GIT_CMD
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "_git_ls_files_tracked must not call shutil.which directly"
        )

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(returncode=0)

    state, detail = doctor._git_ls_files_tracked(tmp_path, "some/file.py", run=run)

    assert run.calls, "subprocess.run (via the injected run) was never called"
    assert run.calls[0][0] == _FAKE_GIT_CMD, run.calls
    assert state == "tracked"


def test_git_ls_files_tracked_could_not_tell_when_safe_which_finds_nothing(
    monkeypatch, tmp_path
):
    """Positive control: `safe_which` returning `None` for `git` must still
    be handled -- the named `could-not-tell` state, not a spawn attempt."""
    monkeypatch.setattr(doctor.gh_which, "safe_which", lambda name, path=None: None)

    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "_git_ls_files_tracked must not call shutil.which directly"
        )

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(returncode=0)

    state, detail = doctor._git_ls_files_tracked(tmp_path, "some/file.py", run=run)

    assert not run.calls, run.calls
    assert state == "could-not-tell"
    assert "not on PATH" in detail


# ------------------------------------------------------------- _origin_slug


def test_origin_slug_resolves_git_via_safe_which(monkeypatch, tmp_path):
    monkeypatch.setattr(
        doctor.gh_which, "safe_which", lambda name, path=None: _FAKE_GIT_CMD
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError("_origin_slug must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(
        returncode=0, stdout="https://github.com/owner/name.git\n"
    )

    slug, reason = doctor._origin_slug(tmp_path, run=run)

    assert run.calls, "subprocess.run (via the injected run) was never called"
    assert run.calls[0][0] == _FAKE_GIT_CMD, run.calls
    assert slug == "owner/name"
    assert reason is None


def test_origin_slug_says_so_when_safe_which_finds_nothing(monkeypatch, tmp_path):
    """Positive control: `safe_which` returning `None` for `git` must still
    be handled -- a reason naming git as absent, not a spawn attempt."""
    monkeypatch.setattr(doctor.gh_which, "safe_which", lambda name, path=None: None)

    def _boom(*_args, **_kwargs):
        raise AssertionError("_origin_slug must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    run = _RecordingSubprocessRun(returncode=0)

    slug, reason = doctor._origin_slug(tmp_path, run=run)

    assert not run.calls, run.calls
    assert slug is None
    assert "not on PATH" in reason
