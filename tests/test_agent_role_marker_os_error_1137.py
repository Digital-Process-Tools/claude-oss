"""A real write/unlink failure must not read as "not a git repository" (#1137).

#1137 was filed for a harness-level classifier that intermittently denies an
`oss_state.py`/`agent_role.py` call before the process is ever launched --
that half is not fixable from inside either script, and is documented as such
in `skills/manager/phases/tick-order.md` rather than coded around here.

But investigating it surfaced a second, genuinely fixable instance of the
same defect class one level down, inside `agent_role.py` itself, once the
process IS running: `write_role_marker` and `clear_role_marker` both catch
`OSError` and return the identical `False` they already return for "root is
not inside a git repository" (write) or "no marker was there" (clear). The
CLI then printed a message naming the git-repository cause unconditionally
for every `False` -- so a real disk-write or unlink failure inside a
perfectly valid repository (permissions, a full disk, a read-only mount) was
reported with a cause that was not the one that happened.

The fix keeps `write_role_marker`/`clear_role_marker`'s own bool contracts
unchanged -- every existing caller and test keeps working exactly as before
-- and adds `_write_role_marker_detail`/`_clear_role_marker_detail`, which
the CLI alone reads, to tell the causes apart.

Per this repository's own working rule (`test-fixture-pitfalls.md`), the
denial fixture is a measurement, not a given: each test attempts the real
operation the code under test performs and skips, naming what went
untested, if this platform cannot be made to fail it. The positive control
lives in each fixture too: an ordinary write/clear in the same repository
must still succeed, so a broken classifier that always answered `os-error`
could not pass either half.
"""

import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import agent_role  # noqa: E402
import spawn_guard  # noqa: E402


def _init_repo(path):
    subject = (
        "the role marker, in a git repository this fixture never finished creating"
    )
    spawn_guard.run(
        ["git", "init", "-q", str(path)], subject=subject, check=True, timeout=30
    )
    spawn_guard.run(
        ["git", "-C", str(path), "config", "user.email", "t@example.com"],
        subject=subject,
        check=True,
        timeout=30,
    )
    spawn_guard.run(
        ["git", "-C", str(path), "config", "user.name", "t"],
        subject=subject,
        check=True,
        timeout=30,
    )
    (path / "README.md").write_text("x", encoding="utf-8")
    spawn_guard.run(
        ["git", "-C", str(path), "add", "-A"], subject=subject, check=True, timeout=30
    )
    spawn_guard.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "init"],
        subject=subject,
        check=True,
        timeout=30,
    )


def test_write_os_error_is_not_reported_as_not_a_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    # Positive control: an ordinary write in a real git repository succeeds
    # and is reported `ok` -- a broken classifier that always answered
    # `os-error` could not pass this half.
    state, exc = agent_role._write_role_marker_detail("sub-manager", root=str(repo))
    assert state == agent_role._MARKER_OK
    assert exc is None
    assert agent_role.write_role_marker("sub-manager", root=str(repo)) is True
    agent_role.clear_role_marker(root=str(repo))

    # Now measure whether this platform can actually be made to fail the
    # write itself: force the marker path to be a directory, so
    # `path.write_text` is what fails, not `_marker_path` returning `None`.
    marker_path = agent_role._marker_path(root=str(repo))
    marker_path.mkdir()
    try:
        try:
            marker_path.write_text("x", encoding="utf-8")
        except OSError:
            pass
        else:
            pytest.skip(
                "writing a file over an existing directory did not raise "
                "OSError on this platform, so this construction cannot "
                "produce a real write failure here. UNTESTED here: whether "
                "_write_role_marker_detail's os-error state is "
                "distinguished from its not-a-repo state."
            )

        state, exc = agent_role._write_role_marker_detail("sub-manager", root=str(repo))
        assert state == agent_role._MARKER_OS_ERROR, (
            "a write that failed for a real OSError inside a valid git "
            "repository must not be reported the same as 'not inside a "
            "git repository'; got {!r}".format(state)
        )
        assert isinstance(exc, OSError)
        assert agent_role.write_role_marker("sub-manager", root=str(repo)) is False
    finally:
        marker_path.rmdir()


def test_clear_os_error_is_not_reported_as_nothing_to_clear(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    agent_role.write_role_marker("sub-manager", root=str(repo))

    # Positive control: an ordinary clear of a real marker succeeds and is
    # reported `cleared`.
    state, exc = agent_role._clear_role_marker_detail(root=str(repo))
    assert state == agent_role._MARKER_CLEARED
    assert exc is None
    agent_role.write_role_marker("sub-manager", root=str(repo))

    marker_path = agent_role._marker_path(root=str(repo))
    git_dir = marker_path.parent
    original_mode = git_dir.stat().st_mode
    git_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x, no write: block unlink
    denied = False
    try:
        try:
            marker_path.unlink()
        except OSError:
            denied = True
        else:
            # The platform allowed the unlink anyway (root, or a
            # filesystem/OS that ignores this mode for deletion) --
            # nothing left to test here.
            pass

        if not denied:
            git_dir.chmod(original_mode)
            pytest.skip(
                "removing write permission from the git directory did not "
                "block unlinking the marker on this platform (root, or a "
                "permissive filesystem/OS), so this construction cannot "
                "produce a real removal failure here. UNTESTED here: "
                "whether _clear_role_marker_detail's os-error state is "
                "distinguished from its absent state."
            )

        state, exc = agent_role._clear_role_marker_detail(root=str(repo))
        assert state == agent_role._MARKER_OS_ERROR, (
            "a removal that failed for a real OSError, of a marker that "
            "genuinely exists, must not be reported the same as 'nothing "
            "to clear'; got {!r}".format(state)
        )
        assert isinstance(exc, OSError)
        assert agent_role.clear_role_marker(root=str(repo)) is False
    finally:
        git_dir.chmod(original_mode)
        if marker_path.is_file():
            marker_path.unlink()
