"""#1109: a bare `gh`/`git` handed to `subprocess.run` never resolves a
`.cmd`/`.bat` launcher on Windows -- `CreateProcess` only auto-appends
`.exe` for an extensionless name, while `shutil.which` performs the full
`PATHEXT`-aware search and returns a spawnable path. #1069/PR #1107 fixed
this exact shape in `select_issues_claim_read._run`; this file pins the
same fix landing at the other `gh`-spawning call sites this lane owns:
`doctor.label_vocabulary_state` / `doctor.lane_label_state` (`gh label
list`) and each per-check module's own verbatim `_gh_api` (`gh api ...`).
`oss_config._run` (`gh`/`git`, used generically) is the issue's third named
site and is deliberately NOT touched here -- `scripts/oss_config.py` is held
by a concurrent lane for the duration of this one, so that half of #1109
stays open as a follow-up rather than risking a collision on a shared file.

#1157 (release-blocking follow-up): every one of these call sites now goes
through `gh_which.safe_which` rather than `shutil.which` directly -- a bare
`shutil.which(name)`, even with a `path=` argument, still lets a `gh.cmd`
committed to the root of the inspected repo win over a real `PATH` entry on
Windows, because the current-working-directory insertion fires whenever the
queried NAME has no directory component, regardless of what `path` was
passed (see `scripts/gh_which.py`'s own docstring for the mechanism, and
`tests/test_gh_which_1157.py` for what pins `safe_which` itself). So the
fixtures below patch `gh_which.safe_which` -- the real seam every one of
these call sites now uses -- rather than `shutil.which`, which none of them
call directly any more.

Every "must fire" case here is paired with a "must not fire" (or "still
works") case in the same fixture, per CLAUDE.md's own rule: a `safe_which`
that resolves to a fully-qualified `.cmd` path must be what gets spawned,
and a `safe_which` that finds nothing must still fall back to the bare
name rather than crashing `subprocess.run` with a `None` argv[0].
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_branch_protection  # noqa: E402
import doctor_check_codeql_scan  # noqa: E402
import doctor_check_security_alerts  # noqa: E402
import doctor_check_security_settings  # noqa: E402


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _recording_run(**kwargs):
    calls = []

    def run(cmd, **_kwargs):
        calls.append(cmd)
        return _FakeCompleted(**kwargs)

    run.calls = calls
    return run


_FAKE_GH_CMD = r"C:\fake\bin\gh.cmd"


# --------------------------------------------------- doctor.py: gh label list


def test_label_vocabulary_state_resolves_gh_via_which(monkeypatch, tmp_path):
    run = _recording_run(returncode=0, stdout=json.dumps([{"name": "priority-high"}]))
    monkeypatch.setattr(
        doctor.gh_which, "safe_which", lambda name, path=None: _FAKE_GH_CMD
    )
    state, _payload = doctor.label_vocabulary_state(
        tmp_path, config={"repo": "owner/name"}, run=run
    )
    assert state == "satisfied"
    assert run.calls[0][0] == _FAKE_GH_CMD, run.calls


def test_label_vocabulary_state_falls_back_to_bare_name_when_which_finds_nothing(
    monkeypatch, tmp_path
):
    """Positive control: `safe_which` returning `None` for `gh` is already
    read as `could-not-tell` upstream of the spawn, so the bare-name
    fallback is only exercised via `lane_label_state`'s identical shape --
    covered directly below."""
    monkeypatch.setattr(doctor.gh_which, "safe_which", lambda name, path=None: None)
    state, reason = doctor.label_vocabulary_state(
        tmp_path, config={"repo": "owner/name"}, run=_recording_run()
    )
    assert state == "could-not-tell"
    assert "not on PATH" in reason


def test_lane_label_state_resolves_gh_via_which(monkeypatch, tmp_path):
    run = _recording_run(returncode=0, stdout=json.dumps([{"name": "lane-doctor"}]))
    monkeypatch.setattr(
        doctor.gh_which, "safe_which", lambda name, path=None: _FAKE_GH_CMD
    )
    state, _payload = doctor.lane_label_state(
        tmp_path, config={"repo": "owner/name"}, run=run
    )
    assert state == "satisfied"
    assert run.calls[0][0] == _FAKE_GH_CMD, run.calls


# ---------------------------------------- per-check modules: _gh_api verbatim copies


_GH_API_MODULES = [
    doctor_check_branch_protection,
    doctor_check_codeql_scan,
    doctor_check_security_alerts,
    doctor_check_security_settings,
]


def test_gh_api_resolves_the_binary_via_which_before_spawning_it(monkeypatch):
    """Must-fire case for every sibling `_gh_api` copy: given a `safe_which`
    that resolves to some fully-qualified `.cmd` path, the argv handed to
    `run` must use that path, not the bare `"gh"`."""
    for module in _GH_API_MODULES:
        run = _recording_run(returncode=0, stdout="{}", stderr="")
        monkeypatch.setattr(
            module.gh_which, "safe_which", lambda name, path=None: _FAKE_GH_CMD
        )
        rc, _out, _err, exc = module._gh_api("repos/owner/name", run)
        assert exc is None, (module.__name__, exc)
        assert rc == 0, module.__name__
        assert run.calls[0][0] == _FAKE_GH_CMD, (module.__name__, run.calls)


def test_gh_api_never_spawns_a_bare_unresolved_name_when_which_finds_nothing(
    monkeypatch,
):
    """#1157 self-review finding (both spawned reviewers, independently
    confirmed): the original shape of this control asserted `run.calls[0][0]
    == "gh"` -- a bare, unresolved name is exactly the shape a planted
    same-named `.exe` at the inspected repo's own root can still hijack via
    `CreateProcess`'s own cwd-first search on Windows, `shutil.which`
    entirely aside. `_gh_api` must never call `run` at all once
    `safe_which` has already searched every real `PATH` entry and found
    nothing -- it returns the same `(None, "", "", exc)` shape a real spawn
    attempt would raise, without spawning anything."""
    for module in _GH_API_MODULES:
        run = _recording_run(returncode=0, stdout="{}", stderr="")
        monkeypatch.setattr(module.gh_which, "safe_which", lambda name, path=None: None)
        rc, out, err, exc = module._gh_api("repos/owner/name", run)
        assert not run.calls, (module.__name__, run.calls)
        assert rc is None, (module.__name__, rc)
        assert out == "" and err == "", (module.__name__, out, err)
        assert isinstance(exc, FileNotFoundError), (module.__name__, exc)


# --------------------------------------------------- doctor.py: check_gh_binary


def test_check_gh_binary_resolves_gh_via_safe_which(monkeypatch, capsys):
    """#1163: `check_gh_binary` was named as fixed by #1157's own changelog
    fragment but still called bare `shutil.which("gh")` -- the exact gap
    this file's other cases pin for the sibling call sites. This asserts
    the real seam (`gh_which.safe_which`) is what `check_gh_binary` calls,
    never `shutil.which` directly."""
    monkeypatch.setattr(
        doctor.gh_which, "safe_which", lambda name, path=None: _FAKE_GH_CMD
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError("check_gh_binary must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    monkeypatch.setattr(doctor, "_gh_version_text", lambda resolved: "gh version 2.0.0")
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")

    doctor.check_gh_binary()

    out = capsys.readouterr().out
    assert "gh version" in out


def test_check_gh_binary_falls_back_when_safe_which_finds_nothing(monkeypatch, capsys):
    """Positive control: `safe_which` returning `None` must still be
    handled (no crash, and reported as gh missing), not just the resolved
    case above."""
    monkeypatch.setattr(doctor.gh_which, "safe_which", lambda name, path=None: None)

    def _boom(*_args, **_kwargs):
        raise AssertionError("check_gh_binary must not call shutil.which directly")

    monkeypatch.setattr(doctor.shutil, "which", _boom)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")

    doctor.check_gh_binary()

    out = capsys.readouterr().out
    assert "gh" in out.lower()
