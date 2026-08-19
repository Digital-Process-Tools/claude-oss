"""#289/#288 -- the launcher on PATH, checked against the running plugin.

#289: `~/.local/bin/oss-workspace` is a symlink resolved once, at install time, into a
version-scoped plugin cache directory. Nothing re-points it on a later release, and
nothing checked it -- a stale target that still exists behaves exactly like a current
one. The maintainer's own machine hit this twice: pinned at 0.1.0 for an unknown
span, then re-pointed by hand and stale again one release later, the second time
losing a security fix landed in the very file the symlink names (#324/#323). The
issue's own comment shows why a *path*-only check is not enough: the stale target on
the second occurrence was a git clone pulled mid-release, so its directory read
"0.5.0" while its content matched no tag at all -- a version-segment comparison would
have called that "matched".

#288: a plugin install's `$PWD` is not knowable in advance, so the documented
`ln -sf "$PWD/bin/oss-workspace" ...` line is only correct for someone standing in the
checkout. The plugin's own installed location is knowable at runtime (`PLUGIN_ROOT`,
already used throughout doctor.py) and must never be hardcoded -- that is a fact about
one machine's layout.

So this file tests `doctor.oss_workspace_launcher_state` in five states -- matched,
mismatched, not-resolvable, own-copy-unreadable, unresolved-target -- and that
`check_oss_workspace_launcher` names the *current* install in its remedy line rather
than a path that would be wrong next release.
"""

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
    os.chmod(str(entry), 0o755)
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        '{"name": "oss", "version": "%s"}' % version, encoding="utf-8"
    )
    return root


def _path_entry(tmp_path, name, content):
    """One directory on PATH holding a file called ``oss-workspace``, made
    executable so a POSIX `shutil.which` will actually resolve it -- Windows does
    not gate on the execute bit, so `os.chmod` there is a no-op rather than a lie.
    """
    directory = tmp_path / name
    directory.mkdir()
    target = directory / "oss-workspace"
    target.write_bytes(content)
    os.chmod(str(target), 0o755)
    return str(directory), target


def test_not_resolvable_is_distinct_from_mismatched(tmp_path):
    """PATH carrying no `oss-workspace` at all -- nothing was found to compare, so
    this must not render as a mismatch, which would name a target that does not
    exist."""
    plugin_root = _plugin_root(tmp_path)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(empty)
    )
    assert state == "not-resolvable", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(empty))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "not on PATH" in message, message


def test_matched_by_identity_is_the_positive_control(tmp_path):
    """Positive control for the mismatch tests below: PATH resolving straight to
    the running install's own bin/oss-workspace, with no symlink or copy involved.
    Without this, every "does not warn" assertion could pass on a check that never
    matches anything."""
    plugin_root = _plugin_root(tmp_path)
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(plugin_root / "bin")
    )
    assert state == "matched", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(plugin_root / "bin"))
    assert doctor.FINDINGS[-1][0] == "OK", doctor.FINDINGS[-1]


def test_matched_by_content_a_separate_copy_with_identical_bytes(tmp_path):
    """Two different files, same bytes -- content is the ground truth, not identity
    and not the path shape."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n")
    path_dir, _ = _path_entry(tmp_path, "on-path", b"same bytes\n")
    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)
    assert state == "matched", (state, detail)


def test_mismatched_content_names_both_versions_when_the_shape_is_recognised(tmp_path):
    """The common case: PATH resolves into a `.../oss/<version>/bin/oss-workspace`
    cache layout whose content differs from the running install."""
    plugin_root = _plugin_root(tmp_path, content=b"new content\n", version="0.6.0")
    cache_dir = tmp_path / "cache" / "dpt-plugins" / "oss" / "0.1.0" / "bin"
    cache_dir.mkdir(parents=True)
    target = cache_dir / "oss-workspace"
    target.write_bytes(b"old content\n")
    os.chmod(str(target), 0o755)

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(cache_dir)
    )
    assert state == "mismatched", (state, detail)
    resolved, theirs_version, ours_version = detail
    assert theirs_version == "0.1.0", detail
    assert ours_version == "0.6.0", detail

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(cache_dir))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "0.1.0" in message and "0.6.0" in message, message
    # #288: the remedy must name the running install's own location, not $PWD.
    assert str(plugin_root / "bin" / "oss-workspace") in message, message


def test_mismatched_content_with_an_unrecognised_target_shape_does_not_invent_a_version(
    tmp_path,
):
    """The layout `.../oss/<version>/bin/oss-workspace` is one plugin manager's cache
    convention, not a contract. A target that does not have that shape must still be
    reported by content (mismatched, here), and must say a version could not be read
    from it rather than silently rendering as a clean match -- the failure mode #289's
    own body warns against."""
    plugin_root = _plugin_root(tmp_path, content=b"new content\n")
    flat = tmp_path / "somewhere-else"
    flat.mkdir()
    target = flat / "oss-workspace"
    target.write_bytes(b"old content\n")
    os.chmod(str(target), 0o755)

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=str(flat))
    assert state == "mismatched", (state, detail)
    resolved, theirs_version, ours_version = detail
    assert theirs_version is None, detail

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(flat))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "no recognised" in message or "no known" in message, message


def test_own_copy_unreadable_is_unknown_not_matched_and_not_mismatched(tmp_path):
    """The running install's own bin/oss-workspace could not be read -- so nothing
    was compared, and that must not render as either OK or a skew accusation."""
    plugin_root = _plugin_root(tmp_path)
    # A directory where a file is expected: portable across platforms, no chmod
    # privilege required, and read_bytes() on it always raises OSError.
    (plugin_root / "bin" / "oss-workspace").unlink()
    (plugin_root / "bin" / "oss-workspace").mkdir()
    path_dir, _ = _path_entry(tmp_path, "on-path", b"whatever\n")

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)
    assert state == "own-copy-unreadable", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=path_dir)
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "unknown" in message.lower(), message


def test_unresolved_target_is_unknown_not_matched_and_not_mismatched(tmp_path):
    """The resolved target could not be read. Exercised through the ``resolve``
    testing seam rather than a chmod fixture: `shutil.which` itself refuses a
    directory candidate (`not os.path.isdir(fn)`, CPython's own guard), so a real
    PATH search can never hand this state a directory to fail on -- the seam is
    what makes the branch reachable at all."""
    plugin_root = _plugin_root(tmp_path)
    a_directory = tmp_path / "not-a-file"
    a_directory.mkdir()

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, resolve=lambda: str(a_directory)
    )
    assert state == "unresolved-target", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, resolve=lambda: str(a_directory))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "unknown" in message.lower(), message


def test_version_segment_parses_the_documented_cache_shape():
    resolved = str(
        Path("home", "x", ".claude", "plugins", "cache", "dpt-plugins", "oss", "0.6.0", "bin", "oss-workspace")
    )
    assert doctor._oss_workspace_version_segment(resolved) == "0.6.0"


def test_version_segment_is_none_for_an_unrecognised_shape():
    assert doctor._oss_workspace_version_segment(str(Path("home", "x", "oss-workspace"))) is None
    assert doctor._oss_workspace_version_segment(str(Path("home", "x", "bin", "oss-workspace"))) is None
