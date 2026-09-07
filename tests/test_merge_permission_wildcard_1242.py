"""#1242: `doctor_check_merge_permission.py`'s two checks (`gh-pr-merge`
permission, and the supertool permission itself) never got #886/#895's
wildcard/prefix third-state handling, even though
`doctor_check_worktree_reap_permission.py` already had it. Both checks
rendered `absent` against a settings file that in fact granted (or denied)
the call, via a covering wildcard neither check's own matcher (a literal
substring test for `gh-pr-merge`, an anchored regex for the `supertool:`
spelling) can read.

`gh-pr-merge` and the supertool call itself are both invoked AS a supertool
op (`supertool 'gh-pr-merge:...'`, `./supertool 'op:...'`), so the covering
wildcard head to look for is `supertool` or `./supertool` -- never the op
name itself (`SUPERTOOL_COMMAND_HEADS` in `doctor_check_merge_permission.py`).

Every "must not fire" case here is paired with a "must fire" case in the
same fixture shape, per CLAUDE.md's own rule that a negative assertion needs
a positive control -- the same shape `tests/test_worktree_reap_permission_
886.py` already uses for the sibling check.
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


# --------------------------------------------------------- gh-pr-merge (MERGE_OP)


def test_exact_spelling_still_reads_present_for_merge(tmp_path):
    """Positive control: the literal substring test already handles the
    documented spelling, and this fix must not disturb it."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool:'gh-pr-merge:*')"],
    )
    state, _detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "present"


def test_covering_bare_supertool_wildcard_does_not_read_absent_for_merge(tmp_path):
    """#1242's own repro: a `Bash(supertool *)` allow entry covers
    `gh-pr-merge:...` (invoked as a supertool op) under Claude Code's own
    matcher, and must not render as `absent`."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool *)"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-covered"
    assert detail


def test_covering_relative_supertool_wildcard_does_not_read_absent_for_merge(
    tmp_path,
):
    """#1242's own repro, the `./supertool *` spelling."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(./supertool *)"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-covered"
    assert detail


def test_genuinely_nothing_configured_still_reads_absent_for_merge(tmp_path):
    """Negative control paired with the wildcard case above."""
    state, _detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_unrelated_wildcard_grant_does_not_read_cannot_tell_for_merge(tmp_path):
    """A wildcard grant for an unrelated command (`git`, `npm`) cannot cover
    a supertool op under any wildcard semantics."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(git *)"],
    )
    state, _detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_covering_deny_wildcard_for_merge_is_cannot_tell_whether_forbidden(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(supertool *)"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-forbidden"
    assert detail


def test_check_merge_permission_reports_warn_and_does_not_suggest_a_redundant_rule(
    tmp_path, capsys
):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(supertool *)"],
    )
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "cannot" in out
    doctor.FINDINGS.clear()


# ------------------------------------------------------- supertool call itself


def test_exact_spelling_still_reads_present_for_supertool(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool:*)"],
    )
    state, _detail = doctor.supertool_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "present"


def test_covering_bare_supertool_wildcard_does_not_read_absent_for_supertool(
    tmp_path,
):
    """#1242's own repro, restated exactly from the issue's own settings
    file: `Bash(supertool *)` and `Bash(./supertool *)` in the same file as
    an unrelated `Bash(git *)` -- neither of the two former entries matches
    `SUPERTOOL_ENTRY_RE`'s anchored `supertool:` spelling."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool *)", "Bash(./supertool *)", "Bash(git *)"],
    )
    state, detail = doctor.supertool_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state != "absent"
    assert state == "cannot-tell-whether-covered"
    assert detail


def test_genuinely_nothing_configured_still_reads_absent_for_supertool(tmp_path):
    state, _detail = doctor.supertool_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_unrelated_wildcard_grant_does_not_read_cannot_tell_for_supertool(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(npm *)"],
    )
    state, _detail = doctor.supertool_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "absent"


def test_covering_deny_wildcard_for_supertool_is_cannot_tell_whether_forbidden(
    tmp_path,
):
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(./supertool *)"],
    )
    state, detail = doctor.supertool_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-forbidden"
    assert detail


def test_check_supertool_permission_reports_warn_and_does_not_suggest_a_redundant_rule(
    tmp_path, capsys
):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(supertool *)"],
    )
    doctor.check_supertool_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "cannot" in out
    doctor.FINDINGS.clear()
