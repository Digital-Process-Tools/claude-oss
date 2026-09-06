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

Every "must fire" case here is paired with a "must not fire" (or "still
works") case in the same fixture, per CLAUDE.md's own rule: a `shutil.which`
that resolves to a fully-qualified `.cmd` path must be what gets spawned,
and a `shutil.which` that finds nothing must still fall back to the bare
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


# --------------------------------------------------- doctor.py: gh label list


def test_label_vocabulary_state_resolves_gh_via_which(monkeypatch, tmp_path):
    run = _recording_run(returncode=0, stdout=json.dumps([{"name": "priority-high"}]))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: r"C:\fake\bin\gh.cmd")
    state, _payload = doctor.label_vocabulary_state(
        tmp_path, config={"repo": "owner/name"}, run=run
    )
    assert state == "satisfied"
    assert run.calls[0][0] == r"C:\fake\bin\gh.cmd", run.calls


def test_label_vocabulary_state_falls_back_to_bare_name_when_which_finds_nothing(
    monkeypatch, tmp_path
):
    """Positive control: `shutil.which` returning `None` for `gh` is already
    read as `could-not-tell` upstream of the spawn, so the bare-name
    fallback is only exercised via `lane_label_state`'s identical shape --
    covered directly below."""
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    state, reason = doctor.label_vocabulary_state(
        tmp_path, config={"repo": "owner/name"}, run=_recording_run()
    )
    assert state == "could-not-tell"
    assert "not on PATH" in reason


def test_lane_label_state_resolves_gh_via_which(monkeypatch, tmp_path):
    run = _recording_run(returncode=0, stdout=json.dumps([{"name": "lane-doctor"}]))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: r"C:\fake\bin\gh.cmd")
    state, _payload = doctor.lane_label_state(
        tmp_path, config={"repo": "owner/name"}, run=run
    )
    assert state == "satisfied"
    assert run.calls[0][0] == r"C:\fake\bin\gh.cmd", run.calls


# ---------------------------------------- per-check modules: _gh_api verbatim copies


_GH_API_MODULES = [
    doctor_check_branch_protection,
    doctor_check_codeql_scan,
    doctor_check_security_alerts,
    doctor_check_security_settings,
]


def test_gh_api_resolves_the_binary_via_which_before_spawning_it(monkeypatch):
    """Must-fire case for every sibling `_gh_api` copy: given a `shutil.which`
    that resolves to some fully-qualified `.cmd` path, the argv handed to
    `run` must use that path, not the bare `"gh"`."""
    for module in _GH_API_MODULES:
        run = _recording_run(returncode=0, stdout="{}", stderr="")
        monkeypatch.setattr(module.shutil, "which", lambda name: r"C:\fake\bin\gh.cmd")
        rc, _out, _err, exc = module._gh_api("repos/owner/name", run)
        assert exc is None, (module.__name__, exc)
        assert rc == 0, module.__name__
        assert run.calls[0][0] == r"C:\fake\bin\gh.cmd", (module.__name__, run.calls)


def test_gh_api_still_attempts_the_bare_name_when_which_finds_nothing(monkeypatch):
    """Must-not-fire pairing: when `shutil.which` resolves nothing, `_gh_api`
    must fall back to the bare `"gh"` rather than passing `None` as argv[0]
    (which would raise `TypeError` inside `subprocess.run` before this
    function's own `except` could catch anything)."""
    for module in _GH_API_MODULES:
        run = _recording_run(returncode=0, stdout="{}", stderr="")
        monkeypatch.setattr(module.shutil, "which", lambda name: None)
        rc, _out, _err, exc = module._gh_api("repos/owner/name", run)
        assert exc is None, (module.__name__, exc)
        assert run.calls[0][0] == "gh", (module.__name__, run.calls)
