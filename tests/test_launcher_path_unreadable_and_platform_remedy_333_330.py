"""#333 and #330 -- the two gaps left in the launcher check that landed as #329.

#333: `_locate_on_path` walked PATH with `os.path.lexists`, which swallows **every**
`OSError`, not only `ENOENT`. A PATH entry the process cannot traverse was therefore
indistinguishable from one that simply does not hold the file, and the walk continued
silently. If every entry answered that way the caller got exactly the `not on PATH` a
genuinely absent launcher produces -- this repository's named defect class, an absence
produced by the tool read as an absence in the world. The fix is a sixth state,
`path-unreadable`, threaded back through the three functions between the walk and the
report line.

Two constraints this repository has already paid for, and both are honoured here:

* **The exception in hand answers why the first question failed.** No follow-up
  `exists()` -- that is what broke the release gate in #76, and `Path.exists()`
  swallows a different set of errnos on different interpreter versions.
* **A permission fixture is a measurement, not a given.** Root ignores the mode bit,
  some filesystems ignore it, and Windows' `os.chmod` on a directory toggles a
  read-only attribute that does not stop a listing. So the real-chmod test below
  confirms the deny by attempting the exact operation the code performs, and skips
  naming what went untested when it does not take. It is paired with an *injected*
  test that never skips on any platform, so #265 -- a fixture skipping on all four
  Windows legs while rendering green -- is not restated here.

#330: every remedy the check printed was an unconditional POSIX `ln -sf`, on Windows
too, where it is inert. The prior question the issue asks -- is `bin/oss-workspace`
installable on Windows at all -- is answered in `doctor._launcher_remedy`'s docstring:
not by that route. So the Windows arm states that plainly and names the route that
does work, rather than translating a command. Both arms are asserted on every leg
through the `windows=` seam, and the default arm is asserted against the running
platform with no skip, which is the assertion that has to land on a Windows leg.
"""

import errno
import os
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


def _plugin_root(tmp_path, content=b"# the running install\n", version="9.9.9"):
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    entry = root / "bin" / "oss-workspace"
    entry.write_bytes(content)
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        '{"name": "oss", "version": "%s"}' % version, encoding="utf-8"
    )
    return root


def _deny_lstat(monkeypatch, denied_dir, exc):
    """Make `os.lstat` raise `exc` for anything under `denied_dir`, and behave
    normally everywhere else.

    `doctor` calls `os.lstat` by name at call time, so patching the module
    attribute reaches it -- unlike the `io.open` injection in #174, which pathlib
    on 3.10 alone had already bound at import. This injection is self-verifying
    rather than measured-and-skipped: if it did not take, the walk finds nothing
    under a directory that is genuinely empty and the state is `not-resolvable`,
    which is a red on the assertion below, never a silent pass.
    """
    real = os.lstat
    denied = str(denied_dir)

    def fake(path, *args, **kwargs):
        if str(path).startswith(denied):
            raise exc
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", fake)


# --- #333: the sixth state ----------------------------------------------------


def test_a_path_entry_that_cannot_be_read_is_not_not_resolvable(monkeypatch, tmp_path):
    """The must-fire half. An unreadable PATH entry must reach `path-unreadable`
    and must never render as `not-resolvable`, which asserts that nothing on PATH
    is named oss-workspace -- a claim the walk is in no position to make."""
    plugin_root = _plugin_root(tmp_path)
    denied = tmp_path / "denied"
    denied.mkdir()
    _deny_lstat(monkeypatch, denied, PermissionError(errno.EACCES, "Permission denied"))

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(denied)
    )
    assert state == "path-unreadable", (state, detail)
    assert str(denied) in detail, detail
    assert "PermissionError" in detail, detail
    assert str(errno.EACCES) in detail, detail

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(denied))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "not on PATH" not in message, message
    assert "unknown" in message.lower(), message
    assert str(denied) in message, message


def test_a_readable_but_empty_path_entry_is_still_not_resolvable(monkeypatch, tmp_path):
    """The must-not-fire half, in the same shape and through the same injection
    seam. `FileNotFoundError` is absence and must keep producing the old
    `not-resolvable`: a sixth state that fired for every miss would be worse than
    the bug it replaces."""
    plugin_root = _plugin_root(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    _deny_lstat(monkeypatch, empty, FileNotFoundError(errno.ENOENT, "No such file"))

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(empty)
    )
    assert state == "not-resolvable", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(empty))
    assert "not on PATH" in doctor.FINDINGS[-1][1], doctor.FINDINGS[-1]


def test_a_path_entry_that_is_a_regular_file_is_absence_not_unreadability(tmp_path):
    """A PATH entry that is not a directory at all is a real configuration, and
    nothing under it can exist. Whichever of `NotADirectoryError` (POSIX ENOTDIR)
    or `FileNotFoundError` (which is what Windows folds ERROR_PATH_NOT_FOUND onto)
    this platform raises, the answer is absence -- classifying it as unreadable
    would warn about every PATH entry that happens to be a file."""
    plugin_root = _plugin_root(tmp_path)
    not_a_dir = tmp_path / "a-file-on-path"
    not_a_dir.write_text("not a directory", encoding="utf-8")

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(not_a_dir)
    )
    assert state == "not-resolvable", (state, detail)


def test_an_unreadable_entry_does_not_mask_a_launcher_found_later_on_path(
    monkeypatch, tmp_path
):
    """A positive answer stands. An entry that could not be read earlier on PATH
    is not a reason to withhold a launcher that was actually found -- the sixth
    state replaces the *negative* answer only."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n")
    denied = tmp_path / "denied-first"
    denied.mkdir()
    _deny_lstat(monkeypatch, denied, PermissionError(errno.EACCES, "Permission denied"))

    later = tmp_path / "later"
    later.mkdir()
    (later / "oss-workspace").write_bytes(b"same bytes\n")

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root,
        path=os.pathsep.join([str(denied), str(later)]),
    )
    assert state == "matched", (state, detail)


def test_every_unreadable_entry_is_named_not_only_the_first(monkeypatch, tmp_path):
    """Two unreadable entries, both named. A walk that reported only the first
    would understate how much of PATH went unlooked-at."""
    plugin_root = _plugin_root(tmp_path)
    root = tmp_path / "denied"
    root.mkdir()
    first = root / "one"
    first.mkdir()
    second = root / "two"
    second.mkdir()
    _deny_lstat(monkeypatch, root, PermissionError(errno.EACCES, "Permission denied"))

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=os.pathsep.join([str(first), str(second)])
    )
    assert state == "path-unreadable", (state, detail)
    assert str(first) in detail and str(second) in detail, detail


def test_a_real_unreadable_directory_on_path_reaches_the_sixth_state(tmp_path):
    """The same claim without an injection, so the classification is measured
    against a real filesystem rather than against a fake exception.

    The deny is confirmed by attempting the exact operation the code performs --
    `os.lstat` on the candidate -- because root ignores the mode bit, some
    filesystems ignore it, and Windows' `os.chmod` on a directory sets a read-only
    attribute that does not stop a listing. When it does not take, this skips
    naming what went untested; the injected test above covers the same claim on
    every platform and never skips, so no leg is left with nothing asserted here.
    """
    plugin_root = _plugin_root(tmp_path)
    denied = tmp_path / "chmod-000"
    denied.mkdir()
    readable = tmp_path / "readable-control"
    readable.mkdir()

    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is whether a "
            "genuinely unreadable PATH directory reaches path-unreadable on a real "
            "filesystem".format(exc)
        )

    candidate = os.path.join(str(denied), "oss-workspace")
    try:
        try:
            os.lstat(candidate)
        except FileNotFoundError as exc:
            pytest.skip(
                "the mode bit did not deny traversal on this platform/filesystem: "
                "os.lstat answered {} (errno {}), the same answer an ordinary empty "
                "directory gives, so there is nothing here to classify. What went "
                "untested is whether a genuinely unreadable PATH directory reaches "
                "path-unreadable on a real filesystem.".format(
                    exc.__class__.__name__, exc.errno
                )
            )
        except OSError:
            pass
        else:
            pytest.skip(
                "the mode bit did not deny traversal on this platform/filesystem: "
                "os.lstat on a candidate inside a mode-000 directory succeeded. What "
                "went untested is whether a genuinely unreadable PATH directory "
                "reaches path-unreadable on a real filesystem."
            )

        state, detail = doctor.oss_workspace_launcher_state(
            plugin_root=plugin_root,
            path=os.pathsep.join([str(denied), str(readable)]),
        )
        assert state == "path-unreadable", (state, detail)
        assert str(denied) in detail, detail

        # Same fixture, must-not-fire half: the readable sibling alone is absence.
        state, detail = doctor.oss_workspace_launcher_state(
            plugin_root=plugin_root, path=str(readable)
        )
        assert state == "not-resolvable", (state, detail)
    finally:
        os.chmod(str(denied), 0o700)


def test_locate_on_path_returns_the_unreadable_entries_alongside_the_hit(
    monkeypatch, tmp_path
):
    """The walk itself returns two values. Collapsing them into one is the bug --
    this is the same resolution `_workflow_scan` already took for
    `(files, unreadable)` after #124."""
    denied = tmp_path / "denied"
    denied.mkdir()
    _deny_lstat(monkeypatch, denied, PermissionError(errno.EACCES, "Permission denied"))

    found, unreadable = doctor._locate_on_path("oss-workspace", path=str(denied))
    assert found is None
    assert [entry for entry, _exc in unreadable] == [str(denied)]
    assert isinstance(unreadable[0][1], OSError)


# --- #330: the remedy is not a POSIX command everywhere -----------------------


def test_the_posix_remedy_is_unchanged(tmp_path):
    """Must-fire control for the Windows assertions below: without this, a remedy
    function that returned the Windows sentence unconditionally would pass every
    "no ln -sf" test in this file."""
    plugin_root = _plugin_root(tmp_path)
    remedy = doctor._launcher_remedy(plugin_root, windows=False)
    assert "ln -sf" in remedy, remedy
    assert "~/.local/bin/oss-workspace" in remedy, remedy


def test_the_windows_remedy_is_not_a_posix_command(tmp_path):
    """On Windows the answer is not a translated command -- `bin/oss-workspace` is
    a `/bin/sh` script and is not installable by that route there at all -- so the
    line says so and names the route that works."""
    plugin_root = _plugin_root(tmp_path)
    remedy = doctor._launcher_remedy(plugin_root, windows=True)
    assert "ln -sf" not in remedy, remedy
    assert "no one-line install" in remedy, remedy
    assert "Git Bash" in remedy, remedy
    assert "oss-workspace" in remedy, remedy


def test_the_default_remedy_matches_the_platform_actually_running(tmp_path):
    """The assertion that has to land on a Windows CI leg, and it does not skip
    there. On a Windows leg this fails if the POSIX text is printed; on a POSIX leg
    it fails if it is not.

    The Windows arm also pins the **forward-slash rendering** (#340). That is a
    deliberate choice rather than a formatting accident -- the line it appears in
    is a `sh "..."` command a reader pastes into Git Bash -- and this is the only
    place it can be observed, because on POSIX `str(Path)` and `Path.as_posix()`
    are the same string and any such assertion would be vacuous there. So it is
    asserted on the platform that can see it rather than branched into a shape
    that renders green everywhere and checks nothing on one side. What went
    unasserted on POSIX is named rather than left as a gap: nothing on a POSIX leg
    establishes that the Windows arm calls `as_posix()` at all.

    #340 is the second Windows-only failure on this check in one night, and both
    were separator-or-resolution behaviour no POSIX leg can see -- which is why the
    platform claims for this file are graded `reasoned` and CI is what settles them.
    """
    plugin_root = _plugin_root(tmp_path)
    remedy = doctor._launcher_remedy(plugin_root)
    if os.name == "nt":
        assert "ln -sf" not in remedy, remedy
        assert "Git Bash" in remedy, remedy
        assert plugin_root.as_posix() in remedy, remedy
        pasted = remedy.split('sh "')[-1]
        assert "\\" not in pasted, remedy
    else:
        assert "ln -sf" in remedy, remedy
        assert str(plugin_root) in remedy, remedy


@pytest.mark.parametrize(
    "state_name", ["not-resolvable", "unresolved-target", "mismatched"]
)
def test_no_warning_state_prints_a_posix_command_on_windows(tmp_path, state_name):
    """All three remedy-carrying states, both platforms, in one place. The
    `windows=False` half is the must-fire control: it asserts the POSIX text is
    still there, so the Windows half cannot pass on a check that stopped printing a
    remedy altogether."""
    plugin_root = _plugin_root(tmp_path)
    if state_name == "not-resolvable":
        search = tmp_path / "empty"
        search.mkdir()
    elif state_name == "unresolved-target":
        search = tmp_path / "a-directory-named-oss-workspace"
        search.mkdir()
        (search / "oss-workspace").mkdir()
    else:
        search = tmp_path / "different-bytes"
        search.mkdir()
        (search / "oss-workspace").write_bytes(b"different bytes\n")

    doctor.check_oss_workspace_launcher(
        plugin_root=plugin_root, path=str(search), windows=True
    )
    level, windows_message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "ln -sf" not in windows_message, windows_message
    assert "Git Bash" in windows_message, windows_message

    doctor.check_oss_workspace_launcher(
        plugin_root=plugin_root, path=str(search), windows=False
    )
    level, posix_message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "ln -sf" in posix_message, posix_message


def test_the_matched_state_prints_no_remedy_on_either_platform(tmp_path):
    """A remedy in the OK state would be noise on POSIX and a false claim of a
    problem on Windows.

    #617: PATH is built from a symlink onto the plugin's own bin/oss-workspace,
    the way a real `~/.local/bin` install resolves -- not from the plugin's own
    bin directory itself, which `oss_workspace_launcher_state` now excludes from
    the search (see `tests/test_oss_workspace_launcher_289.py`'s #617 tests for
    why: a session's own PATH always carries that directory, so searching it
    proves nothing about what the user's own shell can reach)."""
    plugin_root = _plugin_root(tmp_path)
    local_bin = tmp_path / "local-bin"
    local_bin.mkdir()
    try:
        os.symlink(
            str(plugin_root / "bin" / "oss-workspace"), str(local_bin / "oss-workspace")
        )
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(
            "this platform would not create a symlink ({}); what went untested is "
            "the matched-state-prints-no-remedy arm".format(exc)
        )
    for windows in (True, False):
        doctor.FINDINGS.clear()
        doctor.check_oss_workspace_launcher(
            plugin_root=plugin_root,
            path=str(local_bin),
            windows=windows,
        )
        level, message = doctor.FINDINGS[-1]
        assert level == "OK", (level, message)
        assert "ln -sf" not in message, message
        assert "Git Bash" not in message, message


def test_the_install_line_says_the_command_is_posix_only():
    """#288 kept two README `ln -sf` blocks deliberately identical so #330's caveat would
    reach both audiences. #451 found the duplication itself was the defect -- a second
    copy of the same command, cross-referencing the section it duplicated -- and merged
    them into one. #795 later moved the whole install step, merged block included, out
    of README.md and into docs/install.md. What #330 actually requires survives both
    moves: the one remaining block may not stand as an unconditional instruction."""
    doc = (REPO_ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    marker = 'ln -sf "$PWD/bin/oss-workspace"'
    assert doc.count(marker) == 1, (
        "the documented install line moved, or #451's de-duplication regressed; "
        "this guard names it literally"
    )
    window = doc.split(marker)[1][:700]
    assert "Windows" in window, window
    assert "Git Bash" in window, window
