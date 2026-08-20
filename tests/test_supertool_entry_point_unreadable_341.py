"""#341: `supertool_entry_point`'s `./supertool` check used `os.path.lexists`,
which swallows every `OSError`, not only `ENOENT`. A `project_dir` this
process cannot traverse -- an over-long component, a mode-000 ancestor --
made a link nothing could look at read as `absent`, with a remedy attached
telling the reader to create a file that may already be there.

This is the third instance of one defect class in this file: #329 introduced
it in the PATH walk (inherited from `shutil.which`), #333/#340 fixed that
instance with a sixth state (`path-unreadable`), and this is a third check
family carrying the same swallow with its own vocabulary.

## The design decision this issue asks for

`supertool_entry_point` already has an `"unreadable"` state -- returned when
`os.readlink` or the follow-up `os.stat` on the resolved target fails -- and
`check_supertool_entry_point`'s catch-all arm for it already reads correctly
for THIS case too: "could not be read (...) -- so which of
present/absent/wrong-target this repo is in is unknown." So an unreadable
parent reuses that existing state and existing message rather than adding a
seventh name to a vocabulary that already has the right one. `absent` is
never widened to cover it: an absence produced by the tool must not render
as an absence in the world, which is this repository's own defect class.

Two constraints already paid for elsewhere in this file, both honoured here:

* The exception in hand answers why the first question failed -- no
  follow-up `exists()` call (#76).
* A permission fixture is a measurement, not a given -- the real-chmod test
  below confirms the deny by attempting the exact operation the code
  performs and skips naming what went untested when it does not take,
  paired with an injected test that never skips.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _deny_lstat(monkeypatch, denied_dir, exc):
    """Make `os.lstat` raise `exc` for anything under `denied_dir`, and behave
    normally everywhere else. Self-verifying: if this did not take, the link
    check finds nothing under a directory that is genuinely empty and the
    state is `absent`, which fails the assertion below rather than passing
    silently -- the same shape as `_deny_lstat` in
    `tests/test_launcher_path_unreadable_and_platform_remedy_333_330.py`.
    """
    import os as os_module

    real = os_module.lstat
    denied = str(denied_dir)

    def fake(path, *args, **kwargs):
        if str(path).startswith(denied):
            raise exc
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os_module, "lstat", fake)


def test_an_unreadable_project_dir_is_unreadable_not_absent(monkeypatch, tmp_path):
    """The must-fire half. `os.lstat` on `<project_dir>/supertool` raising a
    permission error must not read as `absent` -- that would print a remedy
    telling the reader to link a file that may already be there.
    """
    import errno

    project_dir = tmp_path / "unreadable-project"
    project_dir.mkdir()
    _deny_lstat(monkeypatch, project_dir, PermissionError(errno.EACCES, "Permission denied"))

    state, detail = doctor.supertool_entry_point(str(project_dir))
    assert state == "unreadable", (state, detail)

    doctor.check_supertool_entry_point(str(project_dir))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "unknown" in message, message
    assert "link it by hand" not in message, message


def test_a_genuinely_absent_link_is_still_absent(tmp_path):
    """The must-not-fire control, same fixture shape: an ordinary, readable
    project directory with no `./supertool` must still report `absent` with
    its own remedy -- this is the state the fix must not have widened away.
    """
    project_dir = tmp_path / "ordinary-project"
    project_dir.mkdir()

    state, detail = doctor.supertool_entry_point(str(project_dir))
    assert state == "absent", (state, detail)

    doctor.check_supertool_entry_point(str(project_dir))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "link it by hand" in message, message


def test_own_tree_walk_survives_is_file_raising_permission_error(monkeypatch, tmp_path):
    """PR #359: CI went red on 8 of 14 legs -- Python 3.9/3.10/3.11 on BOTH
    `ubuntu-latest` and `macos-latest`, not a single-OS or single-version
    story. `_own_supertool_tree`'s walk -- which checks `(directory /
    WATCH_CONFIG).is_file()` for every ancestor, starting with `project_dir`
    itself -- RE-RAISED `PermissionError` there instead of treating an
    unreadable directory as "no config here", the safe direction its own
    docstring already claimed but never enforced itself. That crashed
    `supertool_entry_point` before this file's own `os.lstat`-based check
    (added for #341) ever ran, on exactly the input #341's fix is about.

    Measured directly, one command each, on three local interpreters:
    `Path(...).is_file()` against a mode-000 parent raises `PermissionError`
    on 3.9, 3.11 and 3.13, and only swallows it on this repository's local
    3.14. The exact version boundary is not asserted here for that reason --
    3.10 and 3.12 were not directly measured.

    Injected rather than measured by a real chmod, so this is exercised on
    every interpreter regardless of which one happens to be running this
    file. That gap between what a real permission fixture measures and what
    the code under test actually calls is the second half of what this
    regression was: the real-chmod test below confirms `os.lstat` denies on
    `<project_dir>/supertool`, never on `<project_dir>/.supertool.json`,
    which is the `Path.is_file()` call `_own_supertool_tree` reaches FIRST.
    """
    denied = tmp_path / "unreadable-project"
    denied.mkdir()
    target = denied / doctor.WATCH_CONFIG

    real_is_file = Path.is_file

    def fake_is_file(self):
        if self == target:
            raise PermissionError(13, "Permission denied")
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    # Would raise here if the code did nothing -- this is the assertion that
    # makes the test worth having.
    root, core = doctor._own_supertool_tree(str(denied))
    assert (root, core) == (None, None), (root, core)

    state, detail = doctor.supertool_entry_point(str(denied))
    assert state == "absent", (state, detail)


def test_a_real_unreadable_project_dir_reaches_unreadable_not_absent(tmp_path):
    """The same claim without an injection, measured against a real
    filesystem. The deny is confirmed by attempting the exact operation the
    code performs -- `os.lstat` on `<project_dir>/supertool` -- because root
    ignores the mode bit, some filesystems ignore it, and Windows' `os.chmod`
    on a directory sets a read-only attribute that does not stop a listing.
    """
    import os

    denied = tmp_path / "chmod-000"
    denied.mkdir()

    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether a genuinely unreadable project dir reaches `unreadable` "
            "on a real filesystem".format(exc)
        )

    candidate = str(denied / "supertool")
    try:
        try:
            os.lstat(candidate)
        except FileNotFoundError as exc:
            pytest.skip(
                "the mode bit did not deny traversal on this platform/"
                "filesystem: os.lstat answered {} (errno {}), the same "
                "answer an ordinary empty directory gives, so there is "
                "nothing here to classify. What went untested is whether a "
                "genuinely unreadable project dir reaches `unreadable` on a "
                "real filesystem.".format(exc.__class__.__name__, exc.errno)
            )
        except OSError:
            pass
        else:
            pytest.skip(
                "the mode bit did not deny traversal on this platform/"
                "filesystem: os.lstat inside a mode-000 directory succeeded. "
                "What went untested is whether a genuinely unreadable "
                "project dir reaches `unreadable` on a real filesystem."
            )

        state, detail = doctor.supertool_entry_point(str(denied))
        assert state == "unreadable", (state, detail)
    finally:
        os.chmod(str(denied), 0o700)
