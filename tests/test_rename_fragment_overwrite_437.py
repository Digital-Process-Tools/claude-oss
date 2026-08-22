"""#437: two findings in scripts/rename_changelog_fragment.py, the file #426

added an hour before this was filed.

Finding 1: `Path.exists()` was the sole overwrite guard on the `--no-git` rename
path (:104), 35 lines ahead of `old_path.rename(new_path)` (:139). CLAUDE.md
records why `exists()` cannot classify: it swallows a version-dependent set of
`OSError`s and answers `False` for a path that could not be stat'd, not only
one that is absent. The fix matches the `os.stat`-and-classify-from-the-
exception-in-hand shape `oss_config._version_evidence` (#396/#413) already
uses in this repo: a destination that exists and one that cannot be stat'd
must not render alike, paired with the control that an absent destination
still renders as free.

Finding 2: `[git, "mv", str(old_path), str(new_path)]` (:119) and
`[git, "add", str(new_path)]` (:147) carry no `--` separator, so a path
component beginning with a dash is parsed by git as an option cluster.
Measured: a directory named `-f` produces "error: unknown switch" for the
leading slash instead of a rename. `parse_fragment_name` forbids a dash in the filename
itself, so only the directory component can carry one.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RENAMER = REPO_ROOT / "scripts" / "rename_changelog_fragment.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from rename_changelog_fragment import OK, REFUSED, rename  # noqa: E402


def _fragment(tmp_path, name, body):
    d = tmp_path / "changelog.d"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


def test_guard_refuses_overwrite_when_destination_exists(tmp_path):
    """Positive control: an ordinary occupied destination must still refuse."""
    old = _fragment(tmp_path, "7.fixed.md", "- source (#7)\n")
    _fragment(tmp_path, "8.fixed.md", "- DESTINATION, someone else's work (#8)\n")

    state, message, new_path = rename(str(old), 8, use_git=False)

    assert state == REFUSED, (state, message)
    assert "already exists" in message
    dest = tmp_path / "changelog.d" / "8.fixed.md"
    assert "DESTINATION" in dest.read_text(encoding="utf-8")


def test_guard_treats_an_absent_destination_as_free(tmp_path):
    """Control: nothing at the destination must still render as free, or a fix
    for the finding below could pass by refusing everything."""
    old = _fragment(tmp_path, "7.fixed.md", "- source (#7)\n")

    state, message, new_path = rename(str(old), 8, use_git=False)

    assert state == OK, (state, message)
    dest = tmp_path / "changelog.d" / "8.fixed.md"
    assert dest.exists()


def test_guard_refuses_when_destination_cannot_be_stat_d(tmp_path):
    """A destination `os.stat` cannot classify -- here, a self-referential
    symlink that raises ELOOP -- must render the same as "occupied", never the
    same as "absent". `Path.exists()` swallows exactly this and answers False,
    which is the defect #437 reports. A permission fixture is a measurement:
    the loop is constructed and then confirmed to actually raise something
    other than FileNotFoundError/NotADirectoryError before it is trusted."""
    old = _fragment(tmp_path, "7.fixed.md", "- source (#7)\n")
    dest = tmp_path / "changelog.d" / "8.fixed.md"
    try:
        os.symlink(str(dest), str(dest))
    except (OSError, NotImplementedError) as exc:
        pytest.skip("platform would not construct a self-referential symlink: {}".format(exc))

    try:
        os.stat(str(dest))
    except (FileNotFoundError, NotADirectoryError):
        pytest.skip("this platform's os.stat resolved the symlink loop as absent")
    except OSError:
        pass
    else:
        pytest.skip("this platform's os.stat resolved the symlink loop without raising")

    state, message, new_path = rename(str(old), 8, use_git=False)

    assert state == REFUSED, (
        "an unstat'able destination must refuse the overwrite, not silently clobber it",
        state,
        message,
    )


def test_git_mv_survives_a_leading_dash_directory(tmp_path):
    """A directory component beginning with `-` must not be parsed by `git mv`
    as an option cluster. `parse_fragment_name` forbids a dash in the filename
    itself, so the directory is the only place one can appear."""
    root = tmp_path
    dashdir = root / "-f"
    dashdir.mkdir()
    old = dashdir / "7.fixed.md"
    old.write_text("- source (#7)\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add fragment"], cwd=str(root), check=True)

    cwd = os.getcwd()
    os.chdir(str(root))
    try:
        state, message, new_path = rename("-f/7.fixed.md", 8, use_git=True)
    finally:
        os.chdir(cwd)

    assert state == OK, (
        "git mv without a -- separator parses a leading-dash path component as "
        "an option cluster instead of renaming",
        state,
        message,
    )
    assert not old.exists()
    assert (dashdir / "8.fixed.md").exists()
