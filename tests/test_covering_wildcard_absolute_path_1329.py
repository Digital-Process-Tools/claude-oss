"""#1329 (guard 2): the covering-wildcard scan in `doctor_check_merge_
permission.py` (`SUPERTOOL_COMMAND_HEADS`, shared by `doctor_check_worktree_
reap_permission.py`'s identical `_GIT_COMMAND_HEADS` pattern) recognised two
spellings of a covering wildcard rule -- the bare command (`Bash(supertool
*)`) and the repo-relative form (`Bash(./supertool *)`) -- but missed a third
that `SUPERTOOL_ENTRY_RE` (the narrow, spelling-anchored entry check in the
same module) already recognises: an absolute path ending in one of the
command heads (`Bash(/usr/local/bin/supertool *)`, or the Windows-drive-
lettered equivalent).

Every "must fire" case here is paired with the already-covered "must also
still fire" cases (bare, `./`-relative) per this repo's own convention that a
new positive control does not replace the ones already proving the guard
works at all -- and each is exercised for both the allow-side ('might already
be covered') and deny-side ('might already be forbidden') detail helpers,
since #1329 names both as untested for this third spelling.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_merge_permission as merge_permission  # noqa: E402
import doctor_check_worktree_reap_permission as reap_permission  # noqa: E402


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


# --------------------------------------- _entry_head_covers, the unit itself


def test_entry_head_covers_the_bare_and_relative_spellings_unchanged():
    heads = merge_permission.SUPERTOOL_COMMAND_HEADS
    assert merge_permission._entry_head_covers("supertool", heads)
    assert merge_permission._entry_head_covers("./supertool", heads)


def test_entry_head_covers_an_absolute_posix_path():
    """#1329's own repro: `/usr/local/bin/supertool` names the same launcher
    `supertool` does."""
    heads = merge_permission.SUPERTOOL_COMMAND_HEADS
    assert merge_permission._entry_head_covers("/usr/local/bin/supertool", heads)


def test_entry_head_covers_an_absolute_windows_path():
    heads = merge_permission.SUPERTOOL_COMMAND_HEADS
    assert merge_permission._entry_head_covers(r"C:\tools\supertool", heads)
    assert merge_permission._entry_head_covers("C:/tools/supertool", heads)


def test_entry_head_does_not_cover_an_unrelated_absolute_path():
    """Negative control: an absolute path to a DIFFERENT command must not be
    read as covering `supertool`."""
    heads = merge_permission.SUPERTOOL_COMMAND_HEADS
    assert not merge_permission._entry_head_covers("/usr/local/bin/npm", heads)


def test_entry_head_covers_handles_none():
    """`_entry_command_head` returns `None` for anything not shaped like
    `Bash(...)`; the covers check must not raise on that."""
    heads = merge_permission.SUPERTOOL_COMMAND_HEADS
    assert not merge_permission._entry_head_covers(None, heads)


# ------------------------------------------------ merge_permission_state (allow)


def test_absolute_path_supertool_wildcard_reads_cannot_tell_whether_covered(
    tmp_path,
):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(/usr/local/bin/supertool *)"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-covered"
    assert detail


# ------------------------------------------------- merge_permission_state (deny)


def test_absolute_path_supertool_wildcard_deny_reads_cannot_tell_whether_forbidden(
    tmp_path,
):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(/usr/local/bin/supertool *)"],
    )
    state, detail = doctor.merge_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-forbidden"
    assert detail


# ---------------------------- worktree_remove_permission_state (the git sibling)


def test_absolute_path_git_wildcard_reads_cannot_tell_whether_covered(tmp_path):
    """The identical pattern the issue names in
    `doctor_check_worktree_reap_permission.py` -- an absolute path to `git`
    must be recognised the same way an absolute path to `supertool` now is,
    since both route through the same shared `_entry_head_covers`."""
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        allow=["Bash(/usr/bin/git *)"],
    )
    state, detail = reap_permission.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-covered"
    assert detail


def test_absolute_path_git_wildcard_deny_reads_cannot_tell_whether_forbidden(
    tmp_path,
):
    _settings(
        tmp_path / ".claude" / "settings.local.json",
        deny=["Bash(/usr/bin/git *)"],
    )
    state, detail = reap_permission.worktree_remove_permission_state(
        tmp_path, home=_isolated_home(tmp_path)
    )
    assert state == "cannot-tell-whether-forbidden"
    assert detail
