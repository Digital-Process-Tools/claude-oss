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

One thing it can do, added for #206: fail while a release is *pending*. Until then every check here
was satisfied by `v0.3.0` -- a release this repo really did cut -- for the whole of the 0.4.0 cycle
and into the 0.5.0 one, so the guard could not fail at the boundary it exists to make visible. The
signal it was missing is on disk and needs no git: unfolded fragments in the changelog directory
mean a release is being prepared, and at that moment the newest release the section names must be
the newest release `CHANGELOG.md` records. Between releases there are no fragments and the check
says so rather than passing quietly -- the third state is reported, not inferred.

This deliberately does not check any measurement inside the section. Asserting that the prose agrees
with, say, a `doctor` check states the same claim twice and passes whenever both are wrong together.
"""

import json
import re
from pathlib import Path

import pytest

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


# --- Is a release pending, and is the section current for it? (#206) ------------------------
#
# Everything above is satisfied by any release this repo ever cut, so it stayed green through a
# whole cycle in which the section was never re-derived. What follows keys on the one signal that
# is on disk at the moment it matters and needs neither git nor the network.

#: `## [0.4.0] - 2026-08-15`, and not `## [Unreleased]`.
CHANGELOG_RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)

#: `164.added.md`. The fragment directory also carries a `README.md`, which is not a fragment.
FRAGMENT = re.compile(r"\A\d+\.[a-z]+\.md\Z")


def _version_key(version):
    return tuple(int(part) for part in version.split("."))


def _changelog_releases(text):
    return CHANGELOG_RELEASE.findall(text)


def _fragment_dir():
    """The fragment directory, read from `.oss.json` rather than spelled here.

    A repo fact belongs in the config or is re-derived; a second copy in a test is one more
    place a rename has to reach.  Returns None when the config cannot be read or names no
    directory -- which this file reports as "could not look", never as "nothing pending".
    """
    try:
        config = json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = config.get("changelog_dir")
    if not isinstance(name, str) or not name:
        return None
    return REPO_ROOT / name


def _pending_fragments(directory):
    """(fragments, reason-it-could-not-look). Exactly one of the two is meaningful.

    An unreadable directory must not render as an empty one: "no release is pending" and "I could
    not tell" are the two states this repository is named after confusing.
    """
    if directory is None:
        return None, ".oss.json is unreadable or names no changelog_dir"
    try:
        entries = sorted(p.name for p in directory.iterdir())
    except FileNotFoundError:
        return [], None
    except OSError as exc:
        return None, "{} could not be listed: {}".format(directory, exc)
    return [name for name in entries if FRAGMENT.match(name)], None


def test_the_section_is_current_for_the_release_being_prepared():
    """While fragments are waiting to be folded, the marker must name the newest cut release.

    The failure this catches is #206 exactly: the section was derived against `v0.3.0`, `v0.4.0`
    shipped, a 0.5.0 delta accumulated, and every check above stayed green because `v0.3.0` has a
    heading in `CHANGELOG.md`.

    Between releases there is nothing to key on -- the version being prepared is not on disk, and
    neither is the release commit -- so the check reports that it did not run instead of passing.
    """
    fragments, blocked = _pending_fragments(_fragment_dir())
    if blocked is not None:
        raise AssertionError(
            "could not tell whether a release is pending: {}. Not the same as no release being "
            "pending, and not something to pass over.".format(blocked)
        )
    if not fragments:
        pytest.skip(
            "no unfolded changelog fragments, so no release is being prepared and there is no "
            "version to key the marker to. UNTESTED here: whether the section is current -- it "
            "becomes testable again as soon as the next fragment lands."
        )

    cut = _changelog_releases(CHANGELOG.read_text(encoding="utf-8"))
    assert cut, "CHANGELOG.md records no released version, so the marker cannot be keyed to one"
    newest_cut = max(cut, key=_version_key)

    named = _releases(_section(CLAUDE_MD.read_text(encoding="utf-8")))
    assert named, "the section names no release; see the check above"
    newest_named = max(named, key=_version_key)

    assert newest_named == newest_cut, (
        "{} fragment(s) are waiting to be folded, so a release is being prepared -- but the "
        "newest release the '{}' section names is `v{}`, while `v{}` has already shipped. The "
        "section is a release behind, and its own instruction is to re-derive it at each release "
        "rather than to edit its numbers. Re-run the commands against this tree and write what "
        "they return.".format(len(fragments), SECTION_HEADING, newest_named, newest_cut)
    )


#: Controls for the check above. A stale section and a current one, both fabricated, so a detector
#: that stopped matching anything fails here rather than passing quietly over the real file.
STALE = SECTION_HEADING + "\n\nMeasured at `9aed28e`, after `v0.3.0`.\n"
CURRENT = SECTION_HEADING + "\n\nMeasured at `35abbcf`, after `v0.4.0`, succeeding `v0.3.0`.\n"
CHANGELOG_FIXTURE = "## [Unreleased]\n\n## [0.4.0] - 2026-08-15\n\n## [0.3.0] - 2026-08-15\n"


def test_the_staleness_detector_fires_and_stays_silent_on_a_current_section():
    cut = _changelog_releases(CHANGELOG_FIXTURE)
    assert cut == ["0.4.0", "0.3.0"], "the changelog release detector stopped matching headings"
    newest_cut = max(cut, key=_version_key)

    stale = max(_releases(_section(STALE)), key=_version_key)
    current = max(_releases(_section(CURRENT)), key=_version_key)

    assert stale != newest_cut, "the detector would not have fired on the #206 section"
    assert current == newest_cut, "the detector fires on a section that is current"


def test_a_fragment_is_told_from_the_readme_beside_it():
    """The skip arm is reached by finding no fragments, so what counts as one is load-bearing."""
    assert FRAGMENT.match("206.fixed.md")
    assert not FRAGMENT.match("README.md")
    assert not FRAGMENT.match("206.fixed.md.bak")


def test_an_unreadable_fragment_directory_is_not_read_as_an_empty_one(tmp_path):
    """The third state, established rather than assumed: attempt the listing, skip if it took."""
    blocked_dir = tmp_path / "changelog.d"
    blocked_dir.mkdir()
    (blocked_dir / "1.fixed.md").write_text("x", encoding="utf-8")
    blocked_dir.chmod(0o000)
    try:
        try:
            list(blocked_dir.iterdir())
        except OSError:
            denied = True
        else:
            denied = False
        if not denied:
            pytest.skip(
                "this filesystem/user still lists a 0o000 directory, so the deny could not be "
                "established. UNTESTED here: that an unreadable fragment directory reports "
                "'could not look' rather than 'no release pending'."
            )
        fragments, reason = _pending_fragments(blocked_dir)
        assert fragments is None, "an unreadable directory came back as a list of fragments"
        assert reason and "could not be listed" in reason
    finally:
        blocked_dir.chmod(0o700)


def test_an_absent_fragment_directory_is_no_release_pending_rather_than_an_error(tmp_path):
    """The positive control for the case above: absence is a real answer, and a different one."""
    fragments, reason = _pending_fragments(tmp_path / "nothing-here")
    assert fragments == [], "an absent directory should mean no release is pending"
    assert reason is None
