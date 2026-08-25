"""A machine without `sh` never runs the update hook, and doctor must not grade
that "OK -- ordinary state" forever (#495).

Found by the v0.12.0 release audit, round 2, platform band, row `misreports`, graded
**reasoned, not observed** -- the auditor was on Darwin, and no CI leg executes a
SessionStart hook. Two instances in the same band:

1. `doctor_check_auto_update.check_auto_update`'s "no receipt" arm reads as the
   ordinary pre-first-run state on every machine, including one that structurally
   can never run the hook: `hooks/hooks.json` invokes the updater via `sh
   "$CLAUDE_PLUGIN_ROOT"/hooks/session-start-update.sh`, and a Windows machine with
   no `sh` on PATH (no Git for Windows, no WSL) can never produce a receipt. That is
   not "nothing established yet" -- it is the permanent state, and the row should
   say so.
2. `doctor_check_statusline._statusline_windows_gap` keyed on `os.name == "nt"`
   alone, so a Windows user whose `statusLine` runs under Git Bash -- where `$VAR`
   syntax works fine -- got warned about a status line that runs correctly.

`CLAUDE.md`'s own rule: a guard over "did this platform distinguish these two
cases" measures, it never infers from a table or a single global. Neither fix here
observes anything about a *different* machine (this test suite cannot; it runs on
whatever CI happens to be); both ask a real, measurable control ON THE MACHINE
DOCTOR IS RUNNING ON right now: is `sh` resolvable via `shutil.which("sh")`? That is
establishable everywhere, including a real Windows-without-git-bash runner, and it
is exactly the dependency both code paths actually have.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import plugin_update  # noqa: E402


def _reset():
    doctor.FINDINGS.clear()


# --------------------------------------------------------- check_auto_update


def test_no_receipt_and_no_sh_on_path_is_a_warn_not_an_ok(tmp_path, monkeypatch):
    """The must-fire half: on a machine where `sh` is not resolvable, the hook
    that would write a receipt can never have run -- this is the permanent
    state, not the ordinary pre-first-run one, and the row must say so."""
    _reset()
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    doctor.check_auto_update(str(tmp_path), sh_available=False)
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "sh" in message and "not resolvable" in message


def test_no_receipt_and_sh_on_path_stays_the_ordinary_ok_495(tmp_path, monkeypatch):
    """The must-not-fire control, same fixture: when `sh` genuinely is
    resolvable (every observed machine so far), this stays the existing
    ordinary pre-first-run OK -- #495 must not regress #480's own coverage."""
    _reset()
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    doctor.check_auto_update(str(tmp_path), sh_available=True)
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "no receipt" in message


def test_sh_available_defaults_to_a_real_measurement(tmp_path, monkeypatch):
    """The parameter is measured by default, not merely reasoned -- confirmed
    against the real, unpatched `shutil.which`, the same shape #487 already
    established for `windows` in `_statusline_windows_gap`."""
    import shutil

    _reset()
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    doctor.check_auto_update(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, _ = doctor.FINDINGS[0]
    expected = "OK" if shutil.which("sh") else "WARN"
    assert state == expected, doctor.FINDINGS


def test_broken_receipt_arm_is_unaffected_by_sh_availability(tmp_path, monkeypatch):
    """The `sh` control only applies to the "nothing was ever written" arm --
    a receipt that exists and is broken (#484) is evidence the hook DID run
    at some point, so `sh` was clearly resolvable then, and that arm must
    keep reporting exactly as #484 established regardless of this."""
    _reset()
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
    monkeypatch.setattr(
        plugin_update, "read_receipt", lambda: plugin_update.ReceiptUnreadable("boom")
    )
    doctor.check_auto_update(str(tmp_path), sh_available=False)
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "could not be read" in message and "boom" in message


# --------------------------------------------------------- _statusline_windows_gap


def test_posix_syntax_on_windows_with_no_sh_available_still_fires():
    """The must-fire half, unchanged from #487: on a Windows machine with no
    POSIX-capable shell resolvable, the gap is real and must still be named."""
    found = doctor._statusline_windows_gap(
        "sh \"$CLAUDE_PROJECT_DIR\"/x.sh", windows=True, sh_available=False
    )
    assert found.startswith("$")


def test_posix_syntax_on_windows_with_sh_available_does_not_fire_495():
    """The must-not-fire control #495 adds: a Windows machine where `sh` IS
    resolvable (Git Bash, WSL's `sh` on PATH, etc.) plausibly runs the
    command under a POSIX-capable shell, so this is not the noise the
    function's own docstring says a diagnostic must not produce about a
    status line that works."""
    found = doctor._statusline_windows_gap(
        "sh \"$CLAUDE_PROJECT_DIR\"/x.sh", windows=True, sh_available=True
    )
    assert found == ""


def test_sh_available_default_is_a_real_measurement_495():
    """Same shape as `windows`'s own default: measured against the real,
    unpatched `shutil.which`, never inferred from `os.name` alone."""
    import shutil

    expected_gap = "" if shutil.which("sh") else "$"
    result = doctor._statusline_windows_gap("echo $HOME", windows=True)
    assert (result != "") == (expected_gap != "")
