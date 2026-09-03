"""#895: found by the v0.20.0 release audit round two. #886's fix
(`9a3a554`) added `cannot-tell-whether-covered` for a bare-wildcard grant
(`Bash(git *)`), but excludes the documented `name:*` prefix spelling
(`Bash(git:*)`) by two independent tests -- `PREFIX_SUFFIX not in e`, and
`_entry_command_head("Bash(git:*)")` returning `"git:*"`, which never equals
`"git"`. `Bash(git:*)` is the documented command-name-level prefix form and
DOES cover `git worktree remove` (same breadth as `Bash(git *)`), so a
repository granting it was told `absent` -- byte-identical to a repository
that granted nothing -- and sent to add a redundant rule.

This module's own docstring at the time of filing named this exact gap as
"a distinct, unfiled gap" -- this is that filing, fixed with a new helper,
`_entry_prefix_wildcard_head`, that recognises only the bare-command-name
prefix shape (`Bash(git:*)`) and not the op-specific one (`Bash(git worktree
remove:*)`, already `present` via the literal substring test) or a sibling
op's own prefix grant (`Bash(git branch -D:*)`, which must stay `absent` for
this op -- #886 already tests that boundary and this file does not repeat it).

Reuses the existing `cannot-tell-whether-covered` state rather than minting a
new one: like #886's original bare-wildcard gap, this is an allow-side
ambiguity ("might already be covered"), the same direction #886 already
named that state for -- see `worktree_remove_permission_state`'s docstring
for why the deny-side gap (#892) gets a state of its own instead.

Must-fire and must-not-fire cases in the same fixture, per the issue's own
required test shape: `Bash(git:*)` must not read `absent` for worktree-remove;
`Bash(npm:*)` (the negative control, an unrelated command head) must stay
`absent`."""

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


def test_prefix_grant_does_not_read_absent(tmp_path):
    """The issue's own repro (row C in its measured table): a `Bash(git:*)`
    allow entry is the documented command-name-level prefix grant and covers
    `git worktree remove` exactly as broadly as `Bash(git *)` does. It must
    not render `absent`."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(git:*)"],
    )
    state, detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-covered"
    assert detail


def test_unrelated_prefix_grant_stays_absent(tmp_path):
    """Negative control paired with the case above (row B's shape, prefix
    form): `Bash(npm:*)` cannot cover a `git` op under any prefix semantics,
    and flagging it anyway would turn a genuine `absent` into a false
    `cannot-tell-whether-covered` -- the same overbreadth bug #886's own
    first draft had, one spelling over."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(npm:*)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_genuinely_nothing_configured_still_reads_absent(tmp_path):
    """Row E of the issue's own table: nothing declared at all must still
    read `absent`, identical to the finding row it is contrasted against."""
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_op_specific_prefix_spelling_still_reads_present(tmp_path):
    """Row D of the issue's own table: `Bash(git worktree remove:*)` is
    unaffected -- the literal substring test already handles it, and this fix
    must not disturb that."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git worktree remove:*)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "present"


def test_sibling_op_prefix_spelling_stays_absent_for_this_op(tmp_path):
    """`Bash(git branch -D:*)` is a documented op-specific prefix grant for
    the *other* op -- its content before `:*` contains a space, so
    `_entry_prefix_wildcard_head` must not treat it as the bare
    command-name-level shape this fix targets. It must stay `absent` for
    worktree-remove (#886 already guards this boundary for the bare-wildcard
    case; this is the same boundary for the prefix case)."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git branch -D:*)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_check_reports_warn_and_does_not_suggest_a_redundant_rule(tmp_path, capsys):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(git:*)"],
    )
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "cannot" in out
    doctor.FINDINGS.clear()


# --------------------------------------------------------- branch delete, sibling


def test_branch_delete_prefix_grant_does_not_read_absent(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(git:*)"],
    )
    state, detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-covered"
    assert detail
