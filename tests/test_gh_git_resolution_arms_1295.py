"""#1295's self-review found a real gap: the new resolution logic in
scripts/oss_config.py (`_run`, `_ignore_rule`) and its inlined counterpart in
scripts/statusline.py (`_safe_which`, `_run`) had zero direct unit tests --
only the AST sweep (`tests/test_bare_gh_git_spawn_sweep_1165.py`), which is
presence-based ("does the wrapper body mention something containing
`which`?") and cannot detect a logic bug in the resolution walk itself, or in
the not-on-PATH fallback arm each site gained.

This pins two things the sweep cannot see:

1. `statusline._safe_which` has the same core #1157 property `gh_which.
   safe_which` is pinned against in `tests/test_gh_which_1157.py`: a
   same-named binary planted where an implicit curdir search would find it
   must never be preferred over a real `PATH` entry -- because `statusline.
   py` is vendored standalone (see its own module docstring) and cannot
   import `gh_which`, so its copy of the resolution walk is not exercised by
   that suite at all.
2. Every new `git_bin`/`resolved is None` fallback arm -- `oss_config._run`,
   `oss_config._ignore_rule`, `statusline._run` -- reports absence as a
   distinct, readable state rather than silently returning the same shape a
   real answer would, when `git`/`gh` cannot be resolved at all.
"""

import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gh_which  # noqa: E402
import oss_config  # noqa: E402
import statusline  # noqa: E402


def _make_executable(path):
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


_PINNED_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def _force_windows(monkeypatch):
    """Same reasoning as `test_gh_which_1157.py`'s own helper: a REASONED
    claim about Windows-shaped behaviour (the `sys.platform` check is
    mocked), exercised against real files on whatever platform this suite
    actually runs on."""
    monkeypatch.setattr(statusline.sys, "platform", "win32")
    monkeypatch.setenv("PATHEXT", _PINNED_PATHEXT)


def test_statusline_safe_which_never_prefers_the_cwd_shaped_entry(
    monkeypatch, tmp_path
):
    """Must-fire control, mirroring `gh_which_1157`'s own pin: a same-named
    `git`/`gh` planted in a directory standing in for the process's actual
    cwd (never on the real `PATH`) must never be preferred over the real
    `PATH` entry."""
    _force_windows(monkeypatch)
    cwd_dir = tmp_path / "repo_root"
    real_dir = tmp_path / "usr_local_bin"
    cwd_dir.mkdir()
    real_dir.mkdir()
    malicious = cwd_dir / "git.CMD"
    malicious.write_text("echo malicious\n")
    _make_executable(malicious)
    real = real_dir / "git.CMD"
    real.write_text("echo real git\n")
    _make_executable(real)

    # `cwd_dir` is never put on PATH -- it stands in for "whatever the
    # process's actual working directory happens to be", which
    # `_safe_which` must never consult implicitly.
    monkeypatch.setenv("PATH", str(real_dir))
    resolved = statusline._safe_which("git")

    assert resolved == str(real), resolved
    assert cwd_dir.name not in resolved, resolved


def test_statusline_safe_which_positive_control_still_resolves(monkeypatch, tmp_path):
    """Must-not-fire pairing: when the real `PATH` entry is the only place
    `git.cmd` exists, `_safe_which` must still find it -- proving the prior
    test passes because of the fix, not because nothing ever resolves."""
    _force_windows(monkeypatch)
    real_dir = tmp_path / "usr_local_bin_2"
    real_dir.mkdir()
    real = real_dir / "git.CMD"
    real.write_text("echo real git\n")
    _make_executable(real)

    monkeypatch.setenv("PATH", str(real_dir))
    resolved = statusline._safe_which("git")

    assert resolved == str(real), resolved


def test_statusline_safe_which_agrees_with_gh_which_on_a_real_directory(
    monkeypatch, tmp_path
):
    """The inlined copy and the real `gh_which.safe_which` are two separate
    implementations by construction (statusline.py is vendored standalone
    and cannot import gh_which -- see trap.d/1295.statusline-vendoring-
    blocks-shared-safe-which.md for the drift risk this leaves open). This
    is the cheapest check available today that the two still agree, on a
    real (non-mocked) platform, against the same directory layout and PATH.
    """
    real_dir = tmp_path / "bin"
    real_dir.mkdir()
    target = real_dir / ("git.exe" if sys.platform == "win32" else "git")
    target.write_text("echo real git\n")
    _make_executable(target)

    monkeypatch.setenv("PATH", str(real_dir))
    statusline_answer = statusline._safe_which("git")
    gh_which_answer = gh_which.safe_which("git", path=str(real_dir))

    assert statusline_answer == gh_which_answer == str(target), (
        statusline_answer,
        gh_which_answer,
        str(target),
    )


def test_oss_config_run_reports_not_on_path_distinctly(monkeypatch):
    """`oss_config._run`'s new fallback arm: when `gh_which.safe_which`
    cannot resolve `command[0]` at all, the failure must be a distinct,
    readable state -- never silently folded into the same `(False, "", ...)`
    shape a real exit-code failure produces, and never mistaken for
    success."""
    monkeypatch.setattr(oss_config.gh_which, "safe_which", lambda name: None)

    ok, out, detail = oss_config._run(["git", "status"])

    assert ok is False
    assert out == ""
    assert "not on PATH" in detail
    assert "git" in detail


def test_oss_config_ignore_rule_reports_not_on_path_distinctly(monkeypatch, tmp_path):
    """Same property for `_ignore_rule`'s independent fallback arm (it does
    not go through `_run` -- see the fix commit for why): resolution
    failure must render as `"unknown"`, not silently as `"clear"`."""
    monkeypatch.setattr(oss_config.gh_which, "safe_which", lambda name: None)

    state, detail = oss_config._ignore_rule(str(tmp_path), "some-file")

    assert state == "unknown"
    assert "not on PATH" in detail


def test_statusline_run_returns_none_when_resolution_fails(monkeypatch):
    """`statusline._run`'s new fallback arm: an unresolved `command[0]` must
    return `None`, the same "could not answer" contract every other failure
    branch in this function already uses -- never a value indistinguishable
    from a real, empty answer."""
    monkeypatch.setattr(statusline, "_safe_which", lambda name: None)

    result = statusline._run(["git", "status"])

    assert result is None
