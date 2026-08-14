"""A `--changelog` path that does not exist must be answered, not raised.

`assemble()` read the changelog with `Path.read_text()` and nothing above it
established the file was there, so an absent `CHANGELOG.md` surfaced as a raw
`FileNotFoundError` traceback -- the one path in this script that escaped the
three-state receipt discipline every other failure follows. It is also the
state every repo scaffolded by this plugin is in until someone writes the file
by hand, and `--dry-run` raised identically, so the safe way to find out what a
release would do failed the same way.

The exit code alone cannot tell the two apart: an uncaught exception leaves
Python at status 1, which is also `SKIPPED`. Every assertion below therefore
pins the receipt on stdout and the absence of a traceback on stderr, not the
status.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

SKIPPED = 1

PREAMBLE = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.1.0] - 2026-01-01

### Added

- The first release.
"""


def _repo(tmp_path, name="repo", with_changelog=False):
    """A synthetic repo holding the real script and one valid fragment."""
    root = tmp_path / name
    (root / ".oss").mkdir(parents=True)
    (root / ".git").mkdir()
    script_path = root / ".oss" / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    fragments = root / "changelog.d"
    fragments.mkdir()
    (fragments / "35.fixed.md").write_text(
        "- A missing changelog is reported rather than raised (#35).\n",
        encoding="utf-8",
    )
    if with_changelog:
        (root / "CHANGELOG.md").write_text(PREAMBLE, encoding="utf-8")
    return root, script_path


def _run(script_path, cwd, *args):
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _assemble(root, script_path, changelog="CHANGELOG.md", *extra):
    return _run(
        script_path,
        root,
        "--version",
        "0.3.0",
        "--date",
        "2026-08-14",
        "--dir",
        "changelog.d",
        "--changelog",
        changelog,
        *extra,
    )


def test_dry_run_against_a_missing_changelog_reports_rather_than_raises(tmp_path):
    """The sharp one: the read-only mode a maintainer reaches for first."""
    root, script_path = _repo(tmp_path)
    result = _assemble(root, script_path, "CHANGELOG.md", "--dry-run")
    assert "Traceback" not in result.stderr, result.stderr
    assert "FileNotFoundError" not in result.stderr, result.stderr
    assert result.stdout.startswith("assemble    : skipped"), result.stdout
    assert result.returncode == SKIPPED


def test_the_receipt_names_the_file_it_could_not_read(tmp_path):
    # The receipt renders the path the way the platform spells it, so a literal
    # `docs/HISTORY.md` here asserts a POSIX separator and fails all four
    # Windows legs against a script that behaved correctly. `os.path.join` is
    # the same string on POSIX and the native one on Windows, and it still
    # fails if the receipt names no file at all.
    named = os.path.join("docs", "HISTORY.md")
    root, script_path = _repo(tmp_path)
    result = _assemble(root, script_path, "docs/HISTORY.md", "--dry-run")
    assert named in result.stdout, result.stdout


def test_the_receipt_says_the_fragments_were_left_alone(tmp_path):
    """`skipped` is only trustworthy if it also says nothing was consumed --
    the same clause every other skipped path in `assemble` carries."""
    root, script_path = _repo(tmp_path)
    result = _assemble(root, script_path)
    assert "nothing consumed" in result.stdout, result.stdout


def test_the_receipt_says_what_the_file_needs(tmp_path):
    """A missing anchor gets a sentence explaining what it will not guess. The
    missing file is worse off -- the maintainer has to work out that a usable
    changelog needs a prior release heading to insert above -- so the receipt
    states it instead of leaving it to the source."""
    root, script_path = _repo(tmp_path)
    result = _assemble(root, script_path, "CHANGELOG.md", "--dry-run")
    assert "## [Unreleased]" in result.stdout, result.stdout
    assert "## [" in result.stdout and "release heading" in result.stdout, result.stdout


def test_a_real_run_consumes_nothing_and_writes_nothing(tmp_path):
    """Without `--dry-run` the fragment must survive and the file must stay
    absent: a skipped receipt that had already deleted fragments would be a
    lie, and the release would ship with the entries gone."""
    root, script_path = _repo(tmp_path)
    result = _assemble(root, script_path)
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == SKIPPED
    assert (root / "changelog.d" / "35.fixed.md").exists()
    assert not (root / "CHANGELOG.md").exists()


def test_a_changelog_path_that_is_a_directory_is_also_answered(tmp_path):
    """Not `FileNotFoundError` specifically: any refusal by the filesystem to
    hand over the bytes is the same answer -- we could not read it."""
    root, script_path = _repo(tmp_path)
    (root / "CHANGELOG.md").mkdir()
    result = _assemble(root, script_path, "CHANGELOG.md", "--dry-run")
    assert "Traceback" not in result.stderr, result.stderr
    assert result.stdout.startswith("assemble    : skipped"), result.stdout
    assert result.returncode == SKIPPED


def test_a_changelog_that_is_there_still_assembles(tmp_path):
    """The guard must not have bought its receipt by refusing the happy path."""
    root, script_path = _repo(tmp_path, with_changelog=True)
    result = _assemble(root, script_path, "CHANGELOG.md", "--dry-run")
    assert result.stdout.startswith("assemble    : ok"), (
        result.stdout + result.stderr
    )
    assert result.returncode == 0
