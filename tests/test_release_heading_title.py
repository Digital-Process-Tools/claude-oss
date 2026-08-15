"""`render()` hardcoded `## [x.y.z] - YYYY-MM-DD`, so a repository whose release
headings carry a title had to fork an owned file to keep them (#170).

The default is right -- it is Keep a Changelog's own shape -- and it stays. What
was missing is that the shape be *expressible*, since this script is the only
writer of CHANGELOG.md in every repository that vendors it.

Three states, not two, on both halves:

* the flag: absent (read the convention out of the file), `--title ''` (a
  decision to cut this one plain, recorded as one), `--title 'text'`.
* the file: its newest release heading is titled, dated, or bare.

Every "must not fire" case below sits beside a "must fire" one built by the same
helper. A fold that refuses and a harness that never ran the script leave the
identical CHANGELOG.md behind, so each refusal is paired with an accept in the
same fixture.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

OK = 0
SKIPPED = 1
REFUSED = 2

EM = "—"

#: The plain convention: the newest release heading is `[x.y.z] - date`.
DATED = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
"""

#: The titled convention, the shape #170 was filed about. Same file otherwise.
TITLED = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.1.0] {em} A rule that disarmed itself after one refusal

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
""".format(em=EM)

#: A bare heading: neither dated nor titled. Not a title convention, and the
#: separator-stripping must not read one into it.
BARE = """# Changelog

## [Unreleased]

## [0.1.0]

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
"""

#: No release heading at all. There is no convention to read, which is the
#: third state and must be said rather than defaulted through.
FIRST = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

[Unreleased]: https://github.com/o/r/commits/HEAD
"""


def _repo(tmp_path, changelog_text, name="repo"):
    """A synthetic repo holding the real script and one valid fragment."""
    root = tmp_path / name
    (root / ".oss").mkdir(parents=True)
    (root / ".git").mkdir()
    script_path = root / ".oss" / "assemble_changelog.py"
    shutil.copy(SCRIPT, script_path)
    fragments = root / "changelog.d"
    fragments.mkdir()
    (fragments / "170.added.md").write_text(
        "- A release heading can carry a title (#170).\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
    return root, script_path


def _run(root, script_path, *args):
    env = dict(os.environ)
    # The receipt quotes the heading, and the heading may hold an em dash. What
    # a console does with that byte is `test_receipt_encoding.py`'s subject, not
    # this file's -- pinned here so a failure below is about the heading.
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", env=env,
    )


def _fold(root, script_path, *extra, version="0.2.0"):
    return _run(root, script_path, "--version", version, "--date", "2026-08-14",
                "--dir", "changelog.d", "--changelog", "CHANGELOG.md", *extra)


def _changelog(root):
    return (root / "CHANGELOG.md").read_text(encoding="utf-8")


def _heading_line(root, version="0.2.0"):
    """The one `## [version]` line the fold wrote, or None."""
    for line in _changelog(root).splitlines():
        if line.startswith("## [{0}]".format(version)):
            return line
    return None


def _untouched(root, before):
    """The refusal's other half: nothing written, nothing consumed."""
    return (_changelog(root) == before
            and (root / "changelog.d" / "170.added.md").exists())


# --------------------------------------------------------------------------
# the flag reaches the heading
# --------------------------------------------------------------------------

def test_a_title_reaches_the_release_heading(tmp_path):
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path, "--title", "The heading says why")
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == OK, result.stdout + result.stderr
    assert _heading_line(root) == (
        "## [0.2.0] - 2026-08-14 {0} The heading says why".format(EM))


def test_without_the_flag_the_default_heading_is_byte_identical(tmp_path):
    """The must-not-fire half of the same fixture. The default is Keep a
    Changelog's shape and #170 is not an argument against it."""
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr
    assert _heading_line(root) == "## [0.2.0] - 2026-08-14"


def test_a_non_ascii_title_survives_the_round_trip(tmp_path):
    """argv, the render, the re-parse and the write are four encodings deep."""
    root, script_path = _repo(tmp_path, DATED)
    title = "Une règle qui s'est désarmée"
    result = _fold(root, script_path, "--title", title)
    assert result.returncode == OK, result.stdout + result.stderr
    assert _heading_line(root) == "## [0.2.0] - 2026-08-14 {0} {1}".format(EM, title)


# --------------------------------------------------------------------------
# absent, empty, and given are three states
# --------------------------------------------------------------------------

def test_a_titled_history_refuses_a_fold_that_was_given_no_title(tmp_path):
    """The quiet direction #170 is about: the fold succeeds and writes a
    heading, just a plainer one than the four above it, and nobody reviewing a
    release diff for the version bump notices."""
    root, script_path = _repo(tmp_path, TITLED)
    before = _changelog(root)
    result = _fold(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "refused" in result.stdout
    assert "--title" in result.stdout
    assert _untouched(root, before), "refused and wrote anyway"


def test_the_same_titled_history_folds_when_a_title_is_given(tmp_path):
    """The must-fire half: the refusal above is about the missing title and
    not about the fixture being unfoldable."""
    root, script_path = _repo(tmp_path, TITLED)
    result = _fold(root, script_path, "--title", "A second thing worth naming")
    assert result.returncode == OK, result.stdout + result.stderr
    assert _heading_line(root) == (
        "## [0.2.0] - 2026-08-14 {0} A second thing worth naming".format(EM))


def test_an_empty_title_is_a_decision_and_cuts_plain(tmp_path):
    """`--title ''` against the same titled history. Absent means nobody
    decided and is refused; empty means somebody did, and the receipt records
    it rather than letting it read as the default path."""
    root, script_path = _repo(tmp_path, TITLED)
    result = _fold(root, script_path, "--title", "")
    assert result.returncode == OK, result.stdout + result.stderr
    assert _heading_line(root) == "## [0.2.0] - 2026-08-14"
    assert "deliberately untitled" in result.stdout, result.stdout


def test_a_dated_history_does_not_demand_a_title(tmp_path):
    """The false-positive control. Every repository that has never used a
    title folds exactly as it did before #170."""
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr


def test_a_bare_history_does_not_demand_a_title(tmp_path):
    """`## [0.1.0]` is neither dated nor titled. Reading a title into it would
    be the separator-stripping matching its own leftovers."""
    root, script_path = _repo(tmp_path, BARE)
    result = _fold(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr
    assert _heading_line(root) == "## [0.2.0] - 2026-08-14"


def test_no_release_heading_says_the_convention_could_not_be_read(tmp_path):
    """The third state on the file's side. A first release has no heading to
    read a convention from, and that is not the same as reading one and
    finding it plain."""
    root, script_path = _repo(tmp_path, FIRST)
    result = _fold(root, script_path, version="0.1.0")
    assert result.returncode == OK, result.stdout + result.stderr
    assert "no release heading" in result.stdout, result.stdout


# --------------------------------------------------------------------------
# a heading is one line
# --------------------------------------------------------------------------

def test_a_title_holding_a_newline_is_refused(tmp_path):
    root, script_path = _repo(tmp_path, DATED)
    before = _changelog(root)
    result = _fold(root, script_path, "--title", "One line\nand a second")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    # This script's own refusal, not argparse's. Before `--title` existed,
    # argparse rejected the unknown flag with the same exit 2 and the flag name
    # in its usage text -- so an assertion on either alone passes against a
    # build that has none of this.
    assert result.stdout.startswith("assemble    : refused"), (
        result.stdout + result.stderr)
    assert _untouched(root, before), "refused and wrote anyway"


def test_the_same_title_without_the_newline_is_accepted(tmp_path):
    """The must-fire half, same fixture: it is the newline that is refused."""
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path, "--title", "One line and a second")
    assert result.returncode == OK, result.stdout + result.stderr


# --------------------------------------------------------------------------
# the flag is read by the fold and by nothing else
# --------------------------------------------------------------------------

def test_the_read_only_modes_refuse_a_title_rather_than_ignoring_it(tmp_path):
    """Same argument as `--untagged`: silently accepted where it is never
    consulted, a title that never applied is indistinguishable from one that
    did -- and here the difference is the heading a release ships with."""
    for mode in ("--check", "--check-links", "--count"):
        root, script_path = _repo(tmp_path, DATED, name="repo" + mode)
        result = _run(root, script_path, mode, "--title", "x",
                      "--dir", "changelog.d", "--changelog", "CHANGELOG.md")
        assert result.returncode == REFUSED, mode + ": " + result.stdout + result.stderr
        # Same reason as above: argparse's unknown-option error is also exit 2
        # and also names the flag.
        assert result.stdout.startswith("assemble    : refused"), (
            mode + ": " + result.stdout + result.stderr)
        assert "--title" in result.stdout, mode


def test_the_read_only_modes_still_run_without_one(tmp_path):
    """The must-fire half: the refusal above is about `--title` and not about
    the mode or the fixture."""
    for mode in ("--check", "--check-links", "--count"):
        root, script_path = _repo(tmp_path, DATED, name="ok" + mode)
        result = _run(root, script_path, mode,
                      "--dir", "changelog.d", "--changelog", "CHANGELOG.md")
        assert result.returncode == OK, mode + ": " + result.stdout + result.stderr


# --------------------------------------------------------------------------
# the parse side agrees
# --------------------------------------------------------------------------

def test_the_link_ref_audit_still_finds_a_titled_version(tmp_path):
    """`--check-links` reads release headings back. A title changes the
    heading text and must not change which version is read out of it."""
    root, script_path = _repo(tmp_path, DATED)
    assert _fold(root, script_path, "--title", "A title").returncode == OK

    clean = _run(root, script_path, "--check-links",
                 "--changelog", "CHANGELOG.md", "--dir", "changelog.d")
    assert clean.returncode == OK, clean.stdout + clean.stderr

    # The must-fire half: delete the ref the fold wrote for the titled heading
    # and the audit has to name that version. An audit that had stopped seeing
    # the heading would report clean here too.
    text = _changelog(root)
    kept = [line for line in text.splitlines()
            if not line.startswith("[0.2.0]:")]
    (root / "CHANGELOG.md").write_text("\n".join(kept) + "\n", encoding="utf-8")
    broken = _run(root, script_path, "--check-links",
                  "--changelog", "CHANGELOG.md", "--dir", "changelog.d")
    assert broken.returncode == REFUSED, broken.stdout + broken.stderr
    assert "0.2.0" in broken.stdout, broken.stdout


def test_a_second_fold_still_sees_the_titled_section(tmp_path):
    """The duplicate-section guard matches on `[{version}]`, which a title
    follows rather than replaces. If it stopped matching, a release could be
    assembled twice."""
    root, script_path = _repo(tmp_path, DATED)
    assert _fold(root, script_path, "--title", "A title").returncode == OK
    (root / "changelog.d" / "171.fixed.md").write_text(
        "- Another entry (#171).\n", encoding="utf-8")
    again = _fold(root, script_path, "--title", "A title")
    assert again.returncode == REFUSED, again.stdout + again.stderr
    assert "already has" in again.stdout, again.stdout


# --------------------------------------------------------------------------
# the receipt describes the heading that was written
# --------------------------------------------------------------------------

def test_the_dry_run_receipt_quotes_the_titled_heading(tmp_path):
    """The dry run's summary formatted `## [{version}] - {date}` itself, which
    is the second source of truth for what a heading may look like that #170
    asks the fix to not grow. It has to quote what `render` emitted."""
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path, "--dry-run", "--title", "Quoted back")
    assert result.returncode == OK, result.stdout + result.stderr
    assert "## [0.2.0] - 2026-08-14 {0} Quoted back".format(EM) in result.stdout, (
        result.stdout)


def test_the_dry_run_receipt_quotes_the_plain_heading_when_there_is_no_title(tmp_path):
    """The must-not-fire half: the quote is the heading, not the title."""
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path, "--dry-run")
    assert result.returncode == OK, result.stdout + result.stderr
    summary = result.stdout.splitlines()[0]
    assert "## [0.2.0] - 2026-08-14" in summary, result.stdout
    assert EM not in summary, result.stdout

def test_the_receipt_for_a_real_fold_quotes_the_titled_heading(tmp_path):
    """The dry run was not the only place composing the heading a second time.

    The `ok` summary on the write path did it too, and that is the worse of
    the two: it is the only thing that reports the mutation, printed after
    CHANGELOG.md was rewritten and the fragments deleted. It named a heading
    that is not in the file it had just written, and a maintainer reading the
    receipt instead of the diff -- which is what a receipt is for -- would have
    seen the plain heading and concluded `--title` had been ignored.
    """
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path, "--title", "Quoted on the write path")
    assert result.returncode == OK, result.stdout + result.stderr
    summary = result.stdout.splitlines()[0]
    assert "## [0.2.0] - 2026-08-14 {0} Quoted on the write path".format(EM) in summary, (
        result.stdout)
    # And it is the heading that is on disk, which is the claim the summary is
    # making.
    assert _heading_line(root) in summary


def test_the_receipt_for_a_real_fold_quotes_the_plain_heading(tmp_path):
    """The must-not-fire half, same fixture: the summary quotes the heading,
    not the title, so an untitled fold's receipt is unchanged."""
    root, script_path = _repo(tmp_path, DATED)
    result = _fold(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr
    summary = result.stdout.splitlines()[0]
    assert "## [0.2.0] - 2026-08-14" in summary, result.stdout
    assert EM not in summary, result.stdout
