"""#609: does any allow entry name ``supertool`` in one of its real spellings?

Every agent here is denied Read/Grep/Glob (CLAUDE.md) -- every read goes through
supertool via Bash -- so unlike the merge permission (needed roughly once a tick),
this one is needed on the very first tool call a session makes. Same shape as
`doctor_check_merge_permission.py`'s check: a file read, not a probe of the
harness, with three non-boolean states plus the caveat wording carried over
verbatim (#609's own request).

Every "must not fire" case here is paired with a "must fire" case in the same
fixture shape, per CLAUDE.md's rule that a negative assertion needs a positive
control.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _settings(path, allow=None, deny=None):
    permissions = {}
    if allow is not None:
        permissions["allow"] = allow
    if deny is not None:
        permissions["deny"] = deny
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"permissions": permissions}), encoding="utf-8")
    return path


def _isolated_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def test_supertool_permission_state_absent_when_no_settings_exist(tmp_path):
    """Negative control: nothing to read, nothing that names supertool."""
    state, _detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "absent"


def test_supertool_permission_state_present_for_bare_spelling(tmp_path):
    """Positive control, paired with the absent test above: the bare
    ``Bash(supertool:*)`` spelling this repo's own local settings carry."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool:*)"],
    )
    state, _detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "present"


def test_supertool_permission_state_present_for_relative_spelling(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool:*)"],
    )
    state, _detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "present"


def test_supertool_permission_state_present_for_absolute_path_spelling(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(/Users/floriandavid/Documents/claude-oss/supertool:*)"],
    )
    state, _detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "present"


def test_supertool_permission_state_present_for_a_windows_absolute_path_spelling(tmp_path):
    """#609 audit finding: the absolute-path spelling has to match a Windows-native
    path (backslash separators, drive letter) too, not only a POSIX one -- a
    Windows contributor's own settings.local.json is written with backslashes,
    never with forward slashes."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=[r"Bash(C:\Users\name\claude-oss\supertool:*)"],
    )
    state, _detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "present"


def test_supertool_permission_state_present_for_an_absolute_path_with_a_space(tmp_path):
    """#609 audit finding: a space in the path -- the ordinary shape of a Windows
    account-name home directory this repo's own CLAUDE.md already documents --
    must not defeat the match either."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(/Users/flor ian/claude-oss/supertool:*)"],
    )
    state, _detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "present"


def test_supertool_permission_state_absent_for_a_one_off_test_file_entry(tmp_path):
    """A pytest-path allow entry mentioning "supertool" only in a test file's
    name must not be read as granting the call -- it grants running one pytest
    invocation, not invoking supertool at all."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(python3 -m pytest tests/test_supertool_entry_point_unreadable_341.py -q)"],
    )
    state, _detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "absent"


def test_supertool_permission_state_denied_wins_over_an_allow(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool:*)"],
        deny=["Bash(./supertool:*)"],
    )
    state, detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "denied"
    assert "deny" in detail


def test_supertool_permission_state_unknown_when_settings_are_malformed(tmp_path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    state, detail = doctor.supertool_permission_state(tmp_path, home=_isolated_home(tmp_path))
    assert state == "unknown"
    assert str(path) in detail


def test_check_supertool_permission_ok_does_not_promise_the_call_is_permitted(tmp_path, capsys):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool:*)"],
    )
    doctor.check_supertool_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert out.startswith("OK ")
    assert "not a probe" in out
    assert doctor.FINDINGS[-1][0] == "OK"


def test_check_supertool_permission_warns_and_names_the_remedy(tmp_path, capsys):
    """Negative control paired with the OK test above: no entry at all names the
    gap rather than staying silent about it."""
    doctor.check_supertool_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert ".claude/settings.json" in out


def test_check_supertool_permission_reports_a_deny_rule(tmp_path, capsys):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(supertool:*)"],
    )
    doctor.check_supertool_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "deny rule" in out


def test_check_supertool_permission_says_it_could_not_look(tmp_path, capsys):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    doctor.check_supertool_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not" in out
    assert "no rule" not in out
