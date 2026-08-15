"""This repository's own CLAUDE.md: "What is not proven yet" must say what it was measured against.

A test cannot assert that a claim in that section is *true*. What it can assert is that the section
carries a marker naming the release and the commit it was re-derived at, so a reader standing in a
tree can tell at a glance whether the section predates it. Staleness stays a human judgement; being
undated stops being one.

The marker is checked by shape and against `CHANGELOG.md`, never by asking git.
`.github/workflows/tests.yml` checks out at `actions/checkout`'s default depth of 1, so neither a
tag nor a historical sha resolves there: a guard that shelled out to `git cat-file` would pass on a
maintainer's full clone and fail every leg.

What this file cannot do is the reason it is small. It cannot tell a section re-derived this morning
from one whose marker was hand-edited, and it cannot read the tree the marker names. It converts
"stale and silent" into "stale and dated", and nothing further.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

SECTION_HEADING = "## What is not proven yet"

#: `v0.3.0`, in backticks. The backticks are load-bearing: without them, prose mentioning a
#: version in passing reads as a measurement marker.
RELEASE = re.compile(r"`v(\d+\.\d+\.\d+)`")

#: An abbreviated or full commit sha in backticks. A digit is required as well, so that ordinary
#: words spelled entirely from a-f -- `defaced`, `deedeed` -- are not read as commits.
COMMIT = re.compile(r"`([0-9a-f]{7,40})`")


def _section(text):
    """The body of the section, or "" when the heading is absent.

    Returning "" for an absent heading rather than raising is what lets the same function serve
    both the real file and the fabricated controls below.
    """
    start = text.find(SECTION_HEADING)
    if start < 0:
        return ""
    rest = text[start + len(SECTION_HEADING) :]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _releases(body):
    return RELEASE.findall(body)


def _commits(body):
    return [sha for sha in COMMIT.findall(body) if any(ch.isdigit() for ch in sha)]


def test_the_documents_this_file_reads_are_present():
    """Both checks below read a file. Absent, they would pass by finding nothing to disagree with."""
    assert CLAUDE_MD.is_file(), "CLAUDE.md is missing -- every check below would vacuously pass"
    assert CHANGELOG.is_file(), "CHANGELOG.md is missing -- the release check would be unanchored"


def test_the_section_is_present_and_not_empty():
    body = _section(CLAUDE_MD.read_text(encoding="utf-8"))
    assert body.strip(), (
        "CLAUDE.md has no non-empty '{}' section. That section is where this codebase says what it "
        "has not demonstrated; deleting it does not make the claims true.".format(SECTION_HEADING)
    )


def test_the_section_names_the_release_it_was_measured_against():
    body = _section(CLAUDE_MD.read_text(encoding="utf-8"))
    assert _releases(body), (
        "The '{}' section names no release in backticks (`vX.Y.Z`). Without one a reader cannot "
        "tell whether it was re-derived against this tree or inherited from an older one -- and a "
        "section that has gone stale reads exactly like one that was checked this morning."
        .format(SECTION_HEADING)
    )


def test_the_release_the_section_names_is_one_this_repo_actually_cut():
    body = _section(CLAUDE_MD.read_text(encoding="utf-8"))
    changelog = CHANGELOG.read_text(encoding="utf-8")
    missing = [v for v in _releases(body) if "## [{}]".format(v) not in changelog]
    assert not missing, (
        "The section names release(s) with no heading in CHANGELOG.md: {}. A marker naming a "
        "release that was never cut is decoration, not a date.".format(", ".join(missing))
    )


def test_the_section_names_the_commit_it_was_measured_at():
    body = _section(CLAUDE_MD.read_text(encoding="utf-8"))
    assert _commits(body), (
        "The '{}' section names no commit in backticks. The release alone dates it only to the "
        "last tag; the commit is what says how far past the tag the measurement reached."
        .format(SECTION_HEADING)
    )


#: The controls. Both halves live here so that a detector which stopped matching anything is a
#: failure rather than a silent pass -- an assertion that a marker is absent is satisfied just as
#: well by a regex that can no longer see one.
MARKED = (
    SECTION_HEADING
    + "\n\nMeasured at `c6b7bd4`, seventeen merged pull requests after `v0.3.0`.\n"
)
UNMARKED = (
    SECTION_HEADING
    + "\n\nMost of what this plugin claims about a scaffolded repository rests on tests and "
    "scratch runs rather than on a repo somebody maintains through it.\n"
)


def test_the_detectors_see_a_marker_and_see_its_absence():
    marked = _section(MARKED)
    unmarked = _section(UNMARKED)

    assert _releases(marked) == ["0.3.0"], "the release detector stopped matching a marked section"
    assert _commits(marked) == ["c6b7bd4"], "the commit detector stopped matching a marked section"

    assert not _releases(unmarked), "the release detector matched prose carrying no marker"
    assert not _commits(unmarked), "the commit detector matched prose carrying no marker"


def test_an_absent_heading_is_reported_as_empty_rather_than_as_a_match():
    """The other way this file could pass while checking nothing: a renamed heading."""
    assert _section("## Something else\n\nMeasured at `c6b7bd4` after `v0.3.0`.\n") == ""
