"""#1688: a permission rule the harness itself skips at session start as
invalid -- `Bash(./supertool 'gh-pr-merge:*')`, a trailing single quote after
the `:*` prefix marker -- used to be counted by `_permission_rule_state`'s
substring test exactly the same as a rule the harness actually loaded, so
`merge permission: present` was reported for a rule that grants nothing.

Positive control paired with each negative case, per CLAUDE.md's own rule:
a settings file with only the invalid spelling reads `invalid` (never
`present`), and the same file with a genuinely valid entry alongside it
reads `present` (the invalid one is noise, not a blocker).
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_merge_permission as merge_mod  # noqa: E402
import doctor_check_worktree_reap_permission as reap_mod  # noqa: E402


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


# -------------------------------------------------------- merge_permission_state


def test_only_invalid_entry_reads_invalid_never_present(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool 'gh-pr-merge:*')"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "invalid"
    assert "gh-pr-merge:*" in detail
    assert "Rewrite as" in detail


def test_valid_entry_beside_the_invalid_one_still_reads_present(tmp_path):
    """Positive control's sibling: the invalid entry is noise once a real
    one exists -- the state answers from the entry that actually loads."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=[
            "Bash(supertool 'gh-pr-merge:*')",
            "Bash(./supertool 'gh-pr-merge:*)",
        ],
    )
    state, _detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "present"


def test_check_merge_permission_reports_warn_for_invalid_never_ok(tmp_path, capsys):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool 'gh-pr-merge:*')"],
    )
    doctor.check_merge_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "invalid" in out
    doctor.FINDINGS.clear()


# ---------------------------------------------------- supertool_permission_state


def test_supertool_permission_allow_side_invalid_never_present(tmp_path):
    """`Bash(supertool:*')` matches `SUPERTOOL_ENTRY_RE`'s anchored
    `supertool:` spelling (the regex only checks the start of the entry),
    but its trailing `'` after `:*` is the same misplaced-marker shape
    the merge op check was fixed for -- must not read `present`."""
    _settings(
        tmp_path / ".claude" / "settings.json",
        allow=["Bash(supertool:*')"],
    )
    state, detail = doctor.supertool_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "invalid"
    assert "Rewrite as" in detail


def test_supertool_permission_deny_side_invalid_never_denied(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.json",
        deny=["Bash(supertool:*')"],
    )
    state, detail = doctor.supertool_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "invalid"
    assert "Rewrite as" in detail


# -------------------------------------------------------------- shared helper


def test_entry_prefix_marker_misplaced_true_for_trailing_quote():
    assert merge_mod._entry_prefix_marker_misplaced("Bash(supertool 'gh-pr-merge:*')")


def test_entry_prefix_marker_misplaced_false_for_valid_entry():
    assert not merge_mod._entry_prefix_marker_misplaced(
        "Bash(./supertool 'gh-pr-merge:*)"
    )


def test_entry_prefix_marker_misplaced_false_when_no_marker_at_all():
    assert not merge_mod._entry_prefix_marker_misplaced(
        "Bash(supertool 'gh-pr-merge:1234:squash|force|cleanup')"
    )


def test_entry_prefix_marker_rewrite_drops_the_trailing_quote():
    assert (
        merge_mod._entry_prefix_marker_rewrite("Bash(supertool 'gh-pr-merge:*')")
        == "Bash(supertool 'gh-pr-merge:*)"
    )


# --------------------------------------------------- worktree-reap siblings (#1688 ask 4)


def test_worktree_remove_permission_invalid_entry_reads_invalid(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash('git worktree remove:*')"],
    )
    state, detail = reap_mod.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "invalid"
    assert "Rewrite as" in detail


def test_branch_delete_permission_invalid_entry_reads_invalid(tmp_path):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash('git branch -D:*')"],
    )
    state, detail = reap_mod.branch_delete_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "invalid"
    assert "Rewrite as" in detail


def test_check_worktree_remove_permission_reports_warn_for_invalid(tmp_path, capsys):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash('git worktree remove:*')"],
    )
    doctor.check_worktree_remove_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "invalid" in out
    doctor.FINDINGS.clear()


def test_check_branch_delete_permission_reports_warn_for_invalid(tmp_path, capsys):
    doctor.FINDINGS.clear()
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash('git branch -D:*')"],
    )
    doctor.check_branch_delete_permission(tmp_path, home=_isolated_home(tmp_path))
    out = capsys.readouterr().out
    assert doctor.FINDINGS[-1][0] == "WARN"
    assert "invalid" in out
    doctor.FINDINGS.clear()


# -------------------------------------- the invalid spelling is not documented


def test_invalid_literal_beside_a_covering_wildcard_reads_cannot_tell_whether_covered(
    tmp_path,
):
    """Self-review finding: an invalid literal entry must not hide a
    separate covering wildcard's own, more actionable signal -- the same
    signal `absent` (no literal entry at all) already surfaces for the
    identical wildcard."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool 'gh-pr-merge:*')", "Bash(supertool *)"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-covered"
    assert detail


def test_invalid_literal_beside_a_covering_deny_wildcard_reads_cannot_tell_whether_forbidden(
    tmp_path,
):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool 'gh-pr-merge:*')"],
        deny=["Bash(supertool *)"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-forbidden"
    assert detail


def test_invalid_literal_with_no_covering_wildcard_still_reads_invalid(tmp_path):
    """Positive control: the wildcard fallback must not swallow a genuine
    `invalid` when there is nothing covering it."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(supertool 'gh-pr-merge:*')"],
    )
    state, _detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "invalid"


def test_the_invalid_spelling_is_not_documented_anywhere():
    """#1688's own acceptance criterion: a grep for the invalid trailing-
    quote-after-the-marker shape across scripts/commands/agents/skills/docs
    returns nothing -- a maintainer must never be able to copy the shape
    the harness itself refuses to load."""
    import re

    pattern = re.compile(r":\*'")
    hits = []
    for sub in ("scripts", "commands", "agents", "skills", "docs"):
        d = REPO_ROOT / sub
        if not d.is_dir():
            continue
        for path in d.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(text):
                hits.append(str(path))
    assert hits == []
