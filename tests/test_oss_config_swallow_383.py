"""#383: `scripts/oss_config.py` was excluded from the swallow-class census
twice (2026-08-22, 2026-08-25) because an open lane held it both times --
"a coverage gap, not a clean result", per the issue's own thread. This is
that pass, taken first while nothing holds it.

`resolve_config_path` prints a VERDICT (`here` / `clone` / `missing` /
`unsearchable`), the shape CLAUDE.md's own swallow-class distinction says
must classify in three states rather than filter silently -- `Path.is_file()`
and `Path.is_dir()` swallow `OSError` internally (measured directly for
`EACCES`/`EPERM` on this repo's own 3.9/3.11/3.13 in `doctor.py`'s
`_safe_is_file`), so a bare `.is_file()` on a permission-denied path used to
render a real "cannot be checked" as a confident "missing", with a "run
/oss:setup to write it" remedy attached that cannot fix a file that already
exists.

Every "must fire" case (a real, chmod-based permission-denied fixture) is
paired with a "must not fire" control in the same test, per this repo's own
convention that a fix reporting everything as unreadable would pass the
must-fire half and still be wrong. The chmod fixture self-skips, naming what
went untested, on a platform whose permission model does not honour it (root,
some filesystems, Windows).
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402


# --------------------------------------------------------------------------
# _stat_kind -- the classifier itself, unit-level, no filesystem permission
# fixture needed: a fake Path-like stand-in controls exactly which exception
# `.stat()` raises.
# --------------------------------------------------------------------------


class _FakeStat:
    def __init__(self, exc=None, is_dir=False):
        self._exc = exc
        self._is_dir = is_dir

    def stat(self):
        if self._exc is not None:
            raise self._exc
        return os.stat_result(
            (0o40000 if self._is_dir else 0o100000, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        )


def test_stat_kind_reports_dir():
    kind, reason = oss_config._stat_kind(_FakeStat(is_dir=True))
    assert (kind, reason) == ("dir", None)


def test_stat_kind_reports_file():
    kind, reason = oss_config._stat_kind(_FakeStat(is_dir=False))
    assert (kind, reason) == ("file", None)


def test_stat_kind_reports_absent_for_file_not_found():
    kind, reason = oss_config._stat_kind(_FakeStat(exc=FileNotFoundError()))
    assert (kind, reason) == (None, "absent")


def test_stat_kind_reports_absent_for_not_a_directory():
    kind, reason = oss_config._stat_kind(_FakeStat(exc=NotADirectoryError()))
    assert (kind, reason) == (None, "absent")


def test_stat_kind_reports_unreadable_for_permission_denied():
    """Must-fire: the case the whole file is about -- a permission error must
    NOT be folded into "absent" the way `Path.is_file()`'s own internal
    swallow would."""
    kind, reason = oss_config._stat_kind(_FakeStat(exc=PermissionError(13, "denied")))
    assert (kind, reason) == (None, "unreadable")


# --------------------------------------------------------------------------
# resolve_config_path -- real chmod-based reproduction against `here`, the
# first and cheapest of the three sites this module renders a verdict from
# (no git subprocess reached at all for this branch).
# --------------------------------------------------------------------------


def test_resolve_config_path_reports_unsearchable_not_missing_when_here_is_unreadable(
    tmp_path,
):
    """Must-fire: `.oss.json` sits inside a directory this process cannot
    read. Measured directly on this machine's own 3.13 install (Python's own
    `is_file()` docstring warns it "returns False if [...] another error
    occurs" but the implementation actually re-raises `PermissionError` here
    rather than swallowing it): before the fix, `here.is_file()` propagated
    an unhandled `PermissionError` straight out of `resolve_config_path`,
    crashing every caller instead of reporting a verdict. `doctor.py`'s own
    `_safe_is_file` records that at least one interpreter this repo supports
    (3.14, measured there) swallows the SAME raise to a bare `False`
    instead -- the opposite failure, a confident `missing` with a "run
    /oss:setup to write it" remedy that cannot fix a file that already
    exists. `_stat_kind` closes both: an explicit `unsearchable` verdict
    either way, on every interpreter."""
    denied = tmp_path / "denied"
    denied.mkdir()
    (denied / oss_config.CONFIG_NAME).write_text("{}", encoding="utf-8")
    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether resolve_config_path swallows on this platform".format(exc)
        )
    try:
        if os.access(str(denied / oss_config.CONFIG_NAME), os.R_OK):
            pytest.skip(
                "this process can still read inside a 0o000 directory "
                "(root, or a filesystem without POSIX modes); what went "
                "untested is whether resolve_config_path swallows on this "
                "platform"
            )
        resolved, origin, detail = oss_config.resolve_config_path(
            oss_config.CONFIG_NAME, start=str(denied)
        )
    finally:
        os.chmod(str(denied), 0o755)

    assert origin == "unsearchable", (origin, detail)
    assert resolved is None
    assert "could not be checked" in detail, detail
    assert "Run /oss:setup" not in detail, detail


def test_resolve_config_path_still_reports_missing_for_a_genuinely_absent_here(
    tmp_path,
):
    """Positive control, same fixture shape, no chmod: a genuinely absent
    (and fully readable) `.oss.json` must NOT be reported as unsearchable
    for the "here could not be checked" reason -- proving the must-fire case
    above is actually measuring the permission swallow and not some other
    effect of the rewrite."""
    readable = tmp_path / "readable"
    readable.mkdir()
    _resolved, _origin, detail = oss_config.resolve_config_path(
        oss_config.CONFIG_NAME, start=str(readable)
    )
    assert "could not be checked" not in detail, detail


# --------------------------------------------------------------------------
# ensure_worktree_root -- the three ordinary states, unaffected by the
# rewrite (regression coverage; the permission-denied case already routed
# to "blocked" through `mkdir`'s own OSError before this change too, so it
# is not a reproduction of a behaviour change the way the test above is).
# --------------------------------------------------------------------------


def test_ensure_worktree_root_unset_present_blocked_created(tmp_path):
    assert oss_config.ensure_worktree_root({}) == "unset"

    present = tmp_path / "present"
    present.mkdir()
    assert oss_config.ensure_worktree_root({"worktree_root": str(present)}) == "present"

    blocked = tmp_path / "blocked"
    blocked.write_text("x", encoding="utf-8")
    assert oss_config.ensure_worktree_root({"worktree_root": str(blocked)}) == "blocked"

    created = tmp_path / "created"
    assert oss_config.ensure_worktree_root({"worktree_root": str(created)}) == "created"
    assert created.is_dir()
