"""A repo cutting its genuine first release has no anchor to insert above.

`_anchor()` finds the newest `## [x.y.z]` heading and puts the new section over
it. A repo that has never released has no such heading, so every scaffolded
repo's v0.1.0 was refused -- correctly for the rule as written, and the
documented way out was to hand-write a release section for a version that never
shipped, i.e. to invent history to satisfy a parser.

Three states, not two, and every "must refuse" case below sits in a file next to
a "must insert" one built by the same helper: an assertion that nothing was
written also passes when the harness never ran the script.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

OK = 0
SKIPPED = 1
REFUSED = 2

#: No release heading, one `## [Unreleased]`, a link-ref block whose
#: `[Unreleased]` cannot be a `compare/v...HEAD` line because there is no
#: previous tag to compare from. This is what `/oss:scaffold` leaves behind.
FIRST = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- An entry someone wrote by hand before fragments existed.

[Unreleased]: https://github.com/o/r/commits/HEAD
"""

#: The positive control: a repo that has released before. The anchor rule must
#: keep applying here, unchanged, and the receipt must not claim a first release.
HAS_RELEASE = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
"""

#: No release heading and no `## [Unreleased]` either: "the top" is a preamble,
#: a blurb, or above the link refs, and the script cannot defend a choice.
NO_UNRELEASED = """# Changelog

All notable changes to this project are documented in this file.

[Unreleased]: https://github.com/o/r/commits/HEAD
"""

#: Two `## [Unreleased]` headings: which one a first release belongs under is a
#: coin toss, and a coin toss is what this script exists to not do.
TWO_UNRELEASED = """# Changelog

## [Unreleased]

### Added

- One.

## [Unreleased]

### Fixed

- Two.

[Unreleased]: https://github.com/o/r/commits/HEAD
"""

#: A first release whose file carries no link-ref block at all. Inserting is
#: still defensible; claiming the refs are fine is not.
NO_LINK_REFS = """# Changelog

## [Unreleased]

### Added

- An entry someone wrote by hand.
"""

#: A first release with a non-release `## ` section below `[Unreleased]`. The
#: release section goes above it and that section must not be folded into the
#: release.
TRAILING_SECTION = """# Changelog

## [Unreleased]

### Added

- An entry someone wrote by hand.

## Notes

Prose that is not a release and must stay below the new section.

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
    (fragments / "41.added.md").write_text(
        "- A genuine first release is cut rather than refused (#41).\n",
        encoding="utf-8",
    )
    if changelog_text is not None:
        (root / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
    return root, script_path


def _assemble(root, script_path, *extra, version="0.1.0"):
    return subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--version",
            version,
            "--date",
            "2026-08-14",
            "--dir",
            "changelog.d",
            "--changelog",
            "CHANGELOG.md",
            *extra,
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def _changelog(root):
    return (root / "CHANGELOG.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# inserted-as-first-release
# --------------------------------------------------------------------------

def test_a_first_release_is_cut_rather_than_refused(tmp_path):
    root, script_path = _repo(tmp_path, FIRST)
    result = _assemble(root, script_path)
    assert "Traceback" not in result.stderr, result.stderr
    assert result.stdout.startswith("assemble    : ok"), result.stdout + result.stderr
    assert result.returncode == OK
    assert "## [0.1.0] - 2026-08-14" in _changelog(root)


def test_the_first_release_lands_directly_below_unreleased(tmp_path):
    """The position has to be one the code can point at, not "the top"."""
    root, script_path = _repo(tmp_path, FIRST)
    _assemble(root, script_path)
    lines = _changelog(root).splitlines()
    unreleased = lines.index("## [Unreleased]")
    release = lines.index("## [0.1.0] - 2026-08-14")
    assert unreleased < release
    # Nothing but blank lines between them: the preamble stays above, the body
    # that was under `[Unreleased]` is folded into the release, not left behind.
    assert not [line for line in lines[unreleased + 1:release] if line.strip()], lines


def test_the_receipt_says_a_first_release_was_detected_not_assumed(tmp_path):
    """`ok` alone cannot tell the maintainer which of the two paths ran."""
    root, script_path = _repo(tmp_path, FIRST)
    result = _assemble(root, script_path)
    assert "first release" in result.stdout, result.stdout
    assert "no `## [x.y.z]`" in result.stdout, result.stdout


def test_the_hand_written_unreleased_entry_is_folded_in(tmp_path):
    """`[Unreleased]` means "goes out next", on a first release too."""
    root, script_path = _repo(tmp_path, FIRST)
    result = _assemble(root, script_path)
    text = _changelog(root)
    assert "An entry someone wrote by hand before fragments existed." in text
    assert "A genuine first release is cut rather than refused (#41)." in text
    assert "folded    1 entry" in result.stdout, result.stdout


def test_the_link_refs_are_written_and_the_receipt_says_so(tmp_path):
    """A first release has no previous tag, so `[Unreleased]` cannot already be
    a compare link -- but the base URL is derivable from the definition that is
    there, and after the cut the file must pass its own `--check-links`."""
    root, script_path = _repo(tmp_path, FIRST)
    result = _assemble(root, script_path)
    text = _changelog(root)
    assert "[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD" in text, text
    assert "[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0" in text, text
    assert "links" in result.stdout and "0.1.0" in result.stdout
    audit = subprocess.run(
        [sys.executable, str(script_path), "--check-links",
         "--changelog", "CHANGELOG.md", "--dir", "changelog.d"],
        cwd=str(root), capture_output=True, text=True,
    )
    assert audit.stdout.startswith("assemble    : ok"), audit.stdout


def test_a_first_release_without_link_refs_still_cuts_and_says_what_it_did(tmp_path):
    """Inserting is defensible with no link-ref block; a silent `links none`
    that reads like "there was nothing to do" is not."""
    root, script_path = _repo(tmp_path, NO_LINK_REFS)
    result = _assemble(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr
    assert "## [0.1.0] - 2026-08-14" in _changelog(root)
    assert "links     none" in result.stdout, result.stdout
    assert "first release" in result.stdout, result.stdout
    assert "0.1.0]:" in result.stdout, result.stdout


def test_a_trailing_section_bounds_the_fold_and_stays_below(tmp_path):
    root, script_path = _repo(tmp_path, TRAILING_SECTION)
    result = _assemble(root, script_path)
    assert result.returncode == OK, result.stdout + result.stderr
    lines = _changelog(root).splitlines()
    assert lines.index("## [0.1.0] - 2026-08-14") < lines.index("## Notes")
    assert "folded    1 entry" in result.stdout, result.stdout


# --------------------------------------------------------------------------
# inserted-at-anchor: the rule that must not have moved
# --------------------------------------------------------------------------

def test_an_existing_release_still_anchors_the_insert(tmp_path):
    root, script_path = _repo(tmp_path, HAS_RELEASE)
    result = _assemble(root, script_path, version="0.2.0")
    assert result.returncode == OK, result.stdout + result.stderr
    lines = _changelog(root).splitlines()
    assert lines.index("## [0.2.0] - 2026-08-14") < lines.index("## [0.1.0] - 2026-01-01")


def test_an_existing_release_is_not_reported_as_a_first_release(tmp_path):
    """The narrow half of the relaxation: the new path must not fire when the
    old rule applies. Without this, "first release" becomes decoration."""
    root, script_path = _repo(tmp_path, HAS_RELEASE)
    result = _assemble(root, script_path, version="0.2.0")
    assert "first release" not in result.stdout, result.stdout
    assert "[Unreleased]: https://github.com/o/r/compare/v0.2.0...HEAD" in _changelog(root)


# --------------------------------------------------------------------------
# refused-with-a-reason
# --------------------------------------------------------------------------

def test_no_unreleased_heading_is_refused_with_what_would_decide_it(tmp_path):
    root, script_path = _repo(tmp_path, NO_UNRELEASED)
    result = _assemble(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert result.stdout.startswith("assemble    : refused"), result.stdout
    assert "## [Unreleased]" in result.stdout, result.stdout
    # The file and the fragment are untouched -- a refusal that consumed the
    # fragment would lose the entry entirely.
    assert _changelog(root) == NO_UNRELEASED
    assert (root / "changelog.d" / "41.added.md").exists()


def test_two_unreleased_headings_are_refused_as_ambiguous(tmp_path):
    root, script_path = _repo(tmp_path, TWO_UNRELEASED)
    result = _assemble(root, script_path)
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "[Unreleased]" in result.stdout, result.stdout
    assert _changelog(root) == TWO_UNRELEASED
    assert (root / "changelog.d" / "41.added.md").exists()
