"""#487: the status line command this plugin writes uses POSIX `$VAR` shell
expansion, and `doctor.check_statusline` graded it `OK ... wired` by matching the
substring `statusline.py` alone -- true on every platform, whether or not the command
can actually run on the one `doctor` happens to be diagnosing.

This is graded reasoned, not observed (nobody has run a status line on Windows to
confirm the shell that executes it), so the fix stops at what the syntax itself
establishes: `$VAR` is POSIX and `cmd.exe` does not expand it.

`_statusline_windows_gap` takes `windows` as an explicit parameter rather than reading
`os.name` unconditionally, precisely so these tests can drive both branches without
monkeypatching `os.name` -- `pathlib` reads that same global, and patching it breaks
`Path()` construction (measured: it raised `UnsupportedOperation: cannot instantiate
'WindowsPath' on your system` the first time this file tried it).
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import scaffold  # noqa: E402


def _reset():
    doctor.FINDINGS.clear()


def _settings(tmp_path, command):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": command}}),
        encoding="utf-8",
    )
    return settings


# --------------------------------------------------------- the pure syntax detector


def test_the_posix_var_in_our_own_written_command_is_found_on_windows():
    """The must-fire half: the exact command scaffold writes contains `$VAR` syntax,
    and asking with `windows=True` and no POSIX-capable shell resolvable (#495's own
    `sh_available` control) must name it."""
    found = doctor._statusline_windows_gap(
        scaffold.STATUSLINE_COMMAND, windows=True, sh_available=False
    )
    assert found, (
        "expected the POSIX $VAR syntax in scaffold.STATUSLINE_COMMAND to be found"
    )
    assert found.startswith("$")


def test_the_same_command_is_clean_off_windows():
    """The must-not-fire control, same command: on the platform it was written for,
    there is nothing to report."""
    assert (
        doctor._statusline_windows_gap(scaffold.STATUSLINE_COMMAND, windows=False) == ""
    )


def test_a_command_with_no_posix_syntax_is_clean_even_on_windows():
    """A second must-not-fire control: `windows=True` alone must not fire -- only the
    syntax does."""
    assert doctor._statusline_windows_gap("python statusline.py", windows=True) == ""


def test_defaults_to_the_real_os_name_when_windows_is_not_given():
    """The parameter has a default so production code (`check_statusline`) does not
    have to pass it -- confirmed against the real, unpatched `os.name` AND the real,
    unpatched `shutil.which("sh")` (#495): the gap only fires when this real machine
    is Windows AND has no POSIX-capable shell resolvable on it."""
    import os
    import shutil

    windows_here = os.name == "nt"
    sh_here = shutil.which("sh") is not None
    expected_gap = windows_here and not sh_here
    result = doctor._statusline_windows_gap("echo $HOME")
    assert (result != "") == expected_gap


# --------------------------------------------------------- wired through check_statusline


def test_check_statusline_warns_when_the_gap_detector_fires(tmp_path, monkeypatch):
    """Integration: when `_statusline_windows_gap` reports a gap, `check_statusline`
    must WARN rather than the unqualified OK it used to give for any command
    containing the substring `statusline.py`. The WARN also carries a remedy an
    actual reader can act on -- not just the name of the gap -- because the message
    is what a Windows user sees when this fires on the exact command scaffold
    wrote for them, with no other statusLine to fall back to."""
    monkeypatch.setattr(
        doctor, "_statusline_windows_gap", lambda command: "$CLAUDE_PROJECT_DIR"
    )
    _settings(tmp_path, scaffold.STATUSLINE_COMMAND)
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "statusline.py" in message and "$" in message
    assert "%CLAUDE_PROJECT_DIR%" in message, message
    assert "not observed" in message, message


def test_check_statusline_stays_ok_when_the_gap_detector_is_clean(
    tmp_path, monkeypatch
):
    """The must-not-fire control for the integration test above, same fixture."""
    monkeypatch.setattr(doctor, "_statusline_windows_gap", lambda command: "")
    _settings(tmp_path, scaffold.STATUSLINE_COMMAND)
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS


def test_a_third_party_command_also_warns_when_the_gap_fires(tmp_path, monkeypatch):
    """The gap applies to a status line that is not ours too: the finding is about
    whether the command runs here, not about who wrote it."""
    monkeypatch.setattr(
        doctor, "_statusline_windows_gap", lambda command: "$CLAUDE_PROJECT_DIR"
    )
    _settings(tmp_path, 'sh "$CLAUDE_PROJECT_DIR"/mine.sh')
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "not ours" in message
