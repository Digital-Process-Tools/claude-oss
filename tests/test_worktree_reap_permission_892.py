"""#892: `_bash_wildcard_allow_detail` (added by #886) is, as its own name
says, allow-side only. A **deny** rule shaped like the same bare wildcard --
`deny: ["Bash(git *)"]` -- is caught by neither the original substring test
nor #886's helper, so it still renders `absent`, the state that means "nobody
granted this". That direction is worse than #886's own gap: a repository that
deliberately denied the op via this wildcard is told the same thing as a
repository that granted nothing, and a reader acting on `absent` adds a rule
against the owner's own explicit prohibition.

This fix gives the deny-side ambiguity its own state, `cannot-tell-whether-
forbidden`, rather than folding it into the allow-side `cannot-tell-whether-
covered` -- see the reasoning in `worktree_remove_permission_state`'s own
docstring for why the two directions are kept apart. `_bash_wildcard_deny_
detail` is the deny-side sibling of #886's own `_bash_wildcard_allow_detail`,
scoped to the bare-wildcard shape only (`Bash(git *)`), matching what #892's
own issue and test shape ask for -- not the `name:*` command-level prefix
shape, which is #895's own, separate finding.

Same fixture shape #886 established: the exact, literal deny spelling must
still read `denied` (positive control -- the fix must not disturb behaviour
the substring test already handled correctly); a bare-wildcard deny for the
same command head must not read `absent` (the fix itself); and a wildcard
deny for an unrelated command head (`Bash(npm *)`) must leave a genuine
`absent` alone (negative control -- #886's own first-draft bug, on the allow
side, was exactly this: an unscoped wildcard scan that flagged any Bash
wildcard entry regardless of which command it named)."""

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


def test_exact_deny_spelling_still_reads_denied(tmp_path):
    """Positive control: the literal substring test already handles this
    spelling, and this fix must not disturb it."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(git worktree remove:*)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "denied"


def test_covering_wildcard_deny_does_not_read_absent(tmp_path):
    """The issue's own repro: a `Bash(git *)` DENY entry covers `git worktree
    remove` under Claude Code's own matcher (same measurement #886 already
    took), and must not render as `absent` -- the state that means nobody
    granted this, when in fact the operation was deliberately forbidden."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(git *)"],
    )
    state, detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-forbidden"
    assert detail


def test_genuinely_nothing_configured_still_reads_absent(tmp_path):
    """Negative control paired with the wildcard-deny case above: a test
    asserting only the wildcard case would also pass if every settings file
    read the same way."""
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_unrelated_wildcard_deny_does_not_read_cannot_tell(tmp_path):
    """A wildcard deny for an unrelated command cannot cover a `git` op under
    any wildcard semantics -- `Bash(npm *)` never becomes `git worktree
    remove`. Flagging it anyway would turn a genuine `absent` into a false
    `cannot-tell-whether-forbidden`. This is the deny-side regression guard
    for #886's own first-draft overbreadth bug on the allow side."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(npm *)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_check_reports_warn_and_does_not_suggest_adding_a_forbidden_rule(
    tmp_path, capsys
):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(git *)"],
    )
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "forbid" in out
    assert "NOT a suggestion" in out
    doctor.FINDINGS.clear()


def test_covering_prefix_wildcard_deny_does_not_read_absent(tmp_path):
    """Self-review finding: `oss:auditor`'s and the `Explore` reviewer's spawn
    against this lane's own first draft both caught this independently --
    `_bash_wildcard_deny_detail`'s first version only matched the bare
    `Bash(git *)` shape, so the command-name-level prefix shape
    (`Bash(git:*)`, #895's own shape) still rendered `absent` on the deny
    side, reproducing the exact defect #892 was filed to fix, one spelling
    over. Same fixture shape as the bare-wildcard case above."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(git:*)"],
    )
    state, detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-forbidden"
    assert detail


def test_unrelated_prefix_wildcard_deny_does_not_read_cannot_tell(tmp_path):
    """Negative control paired with the prefix-deny case above: `Bash(npm:*)`
    cannot cover a `git` op under any prefix semantics."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(npm:*)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


# --------------------------------------------------------- branch delete, sibling


def test_branch_delete_covering_wildcard_deny_does_not_read_absent(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(git *)"],
    )
    state, detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-forbidden"
    assert detail
