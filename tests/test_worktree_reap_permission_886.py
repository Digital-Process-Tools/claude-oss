"""#886: `_permission_rule_state`'s substring test cannot see a covering
wildcard. `Bash(git *)` grants `git worktree remove` under Claude Code's own
permission matcher -- measured directly against the installed CLI's own
matching code (`w04`/`wR1` in `cli.js`): a bare, non-`:*` wildcard entry is
turned into a dotall regex (`^git( .*)?$` for `git *`), which does match `git
worktree remove --force <path>`. The substring test `WORKTREE_REMOVE_OP in e`
has no way to know that, so it rendered `absent` -- the state that means
"nobody granted this" -- for a rule that already covers the op.

Both arms in one fixture, per the issue's own test shape: a settings file
whose only relevant entry is the exact, documented `Bash(git worktree
remove:*)` spelling must still read `present` (unaffected by this fix -- the
literal substring test already handles it). A settings file whose only
relevant entry is `Bash(git *)` must NOT read `absent` -- a test asserting
only the wildcard case would also pass if every settings file read the same
way, so the exact-spelling case is the positive control paired with it.

A true `absent` -- nothing configured at all -- is also covered, so this fix
does not turn every unconfigured repo into `cannot-tell-whether-covered`.
And a `:*`-suffixed rule for the *other* op (`git branch -D:*`) must still
read `absent` for worktree-remove, unaffected: the documented prefix-suffix
form is deliberately left alone by this fix (see the module docstring in
`doctor_check_worktree_reap_permission.py`), so this guards against widening
the fix beyond what #886 measured and asked for.
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


def test_exact_spelling_still_reads_present(tmp_path):
    """Positive control: the literal substring test already handles this
    spelling, and this fix must not disturb it."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(git worktree remove:*)"],
    )
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "present"


def test_covering_wildcard_does_not_read_absent(tmp_path):
    """The issue's own repro: a `Bash(git *)` allow entry covers `git worktree
    remove` under Claude Code's own matcher, and must not render as `absent`,
    the state that means nobody granted this."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(supertool:*)", "Bash(./supertool:*)", "Bash(git *)", "Agent"],
    )
    state, detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-covered"
    assert detail


def test_genuinely_nothing_configured_still_reads_absent(tmp_path):
    """Negative control paired with the wildcard case above: a test asserting
    only the wildcard case would also pass if every settings file read the
    same way. Nothing configured at all must still read `absent`."""
    state, _detail = doctor.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_documented_prefix_suffix_for_the_other_op_stays_absent(tmp_path):
    """A `name:*` rule for the sibling op is deliberately left alone by this
    fix (documented prefix syntax, not the bare-wildcard blind spot #886
    measured) -- it must not turn into `cannot-tell-whether-covered` either,
    which would be scope creep beyond what was asked."""
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
        allow=["Bash(git *)"],
    )
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "cannot" in out
    doctor.FINDINGS.clear()


# --------------------------------------------------------- branch delete, sibling


def test_branch_delete_covering_wildcard_does_not_read_absent(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(git *)"],
    )
    state, detail = doctor.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-covered"
    assert detail
