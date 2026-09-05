"""#787: gh-pr-merge's |cleanup falls back, on a refusal, to two hand commands --
`git worktree remove --force <path>` and `git branch -D <branch>` -- and both are
commonly denied by the Claude Code auto-mode classifier by default. Nothing told
a maintainer that before their first merge sent them into it.

Sibling to `doctor_check_merge_permission.py`'s own `check_merge_permission`: two
checks, not one, because the issue's own author observes the two commands are
permitted or denied independently -- a rule granting one says nothing about the
other, so folding them into a single check would either under- or over-report
whichever half it did not carry a state for. Same four states -- `present` /
`denied` / `absent` / `unknown` -- same two-scope read (project then user), same
"count and file, never the text" convention.

Per CLAUDE.md's note that a permission fixture is a measurement, not a given:
these tests do not simulate Claude Code's own classifier (out of process, not
reachable from a test). What they DO measure directly is the thing this check
actually performs -- parsing real `.claude/settings*.json` shapes with real
`allow`/`deny` entries -- via `doctor_check_merge_permission._permission_rule_state`,
the exact function `check_merge_permission` already uses. `denied`/`unknown` are
the two states least likely to be got right, so both get a positive AND a
negative case in the same fixture, not just an assertion that a made-up denied
config renders as denied.
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


# --------------------------------------------------------- worktree remove


def test_worktree_remove_permission_absent_when_nothing_is_configured(tmp_path):
    """Negative control, paired with the present test below."""
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_worktree_remove_permission_present_for_the_documented_spelling(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git worktree remove:*)"],
    )
    state, detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "present"
    assert "allow" in detail


def test_worktree_remove_permission_denied_wins_over_an_allow(tmp_path):
    """Positive control for `denied`, paired with the absent/present tests
    above -- a deny rule must win even when an allow rule for the same command
    also exists, same as the merge-permission check it mirrors."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git worktree remove:*)"],
        deny=["Bash(git worktree remove:*)"],
    )
    state, detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "denied"
    assert "deny" in detail


def test_worktree_remove_permission_unknown_when_settings_are_malformed(tmp_path):
    """Positive control for `unknown`, paired with the absent test above: a file
    that could not be parsed must never render the same as one read cleanly and
    found empty."""
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    state, detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "unknown"
    assert str(path) in detail


def test_worktree_remove_permission_unaffected_by_the_branch_delete_rule(tmp_path):
    """The two checks are independent -- an entry that grants ONLY the branch
    delete op must not be read as granting worktree remove too."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git branch -D:*)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


# --------------------------------------------------------- branch delete


def test_branch_delete_permission_absent_when_nothing_is_configured(tmp_path):
    state, _detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_branch_delete_permission_present_for_the_documented_spelling(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git branch -D:*)"],
    )
    state, detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "present"
    assert "allow" in detail


def test_branch_delete_permission_denied_wins_over_an_allow(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git branch -D:*)"],
        deny=["Bash(git branch -D:*)"],
    )
    state, detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "denied"
    assert "deny" in detail


def test_branch_delete_permission_unknown_when_settings_are_malformed(tmp_path):
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    state, detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "unknown"
    assert str(path) in detail


def test_branch_delete_permission_unaffected_by_the_worktree_remove_rule(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git worktree remove:*)"],
    )
    state, _detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_branch_delete_permission_reads_user_scope_too(tmp_path):
    """Same two-scope read as the merge-permission check it mirrors -- a rule in
    home settings alone must still be found."""
    home = _isolated_home(tmp_path)
    _settings(home / ".claude" / "settings.json", allow=["Bash(git branch -D:*)"])
    state, _detail = doctor.branch_delete_permission_state(tmp_path, home=home)
    assert state == "present"


# --------------------------------------------------------- report lines


def test_check_worktree_remove_permission_reports_ok_and_never_the_entry_text(
    tmp_path, capsys
):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git worktree remove:*)"],
    )
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "OK"
    assert "Bash(git worktree remove:*)" not in out
    doctor.FINDINGS.clear()


def test_check_worktree_remove_permission_warns_and_names_the_remedy(tmp_path, capsys):
    """Negative control paired with the OK test above: nothing configured names
    the gap rather than staying silent."""
    doctor.FINDINGS.clear()
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "git worktree remove" in out
    doctor.FINDINGS.clear()


def test_check_worktree_remove_permission_reports_a_deny_rule(tmp_path, capsys):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(git worktree remove:*)"],
    )
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "deny rule" in out
    doctor.FINDINGS.clear()


def test_check_worktree_remove_permission_says_it_could_not_look(tmp_path, capsys):
    doctor.FINDINGS.clear()
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "could not" in out
    assert "no rule" not in out
    doctor.FINDINGS.clear()


def test_check_branch_delete_permission_reports_ok_and_never_the_entry_text(
    tmp_path, capsys
):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git branch -D:*)"],
    )
    doctor.check_branch_delete_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "OK"
    assert "Bash(git branch -D:*)" not in out
    doctor.FINDINGS.clear()


def test_check_branch_delete_permission_warns_and_names_the_remedy(tmp_path, capsys):
    doctor.FINDINGS.clear()
    doctor.check_branch_delete_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "git branch -D" in out
    doctor.FINDINGS.clear()


def test_check_branch_delete_permission_reports_a_deny_rule(tmp_path, capsys):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(git branch -D:*)"],
    )
    doctor.check_branch_delete_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "deny rule" in out
    doctor.FINDINGS.clear()
