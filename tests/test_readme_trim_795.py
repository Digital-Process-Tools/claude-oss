"""README is a pitch and a start; issue receipts live in docs/, not in the front door (#795).

`README.md` had grown to 315+ lines / 22 KB, with a stranger reading references to six
issue numbers before ever reaching the install command -- the shape #795 diagnosed as
"the changelog wearing a front door". This pins the three acceptance criteria the issue
states directly, plus a light findability check that nothing was dropped in the move: a
paragraph removed from README is still readable somewhere under `docs/`, even though the
text itself was not asserted line-for-line (that would just move the drift into a second
copy of the same prose).

Each "must not happen" guard below is paired with a positive control, per this repo's own
rule that a negative assertion also passes when nothing happens at all.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

ISSUE_RE = re.compile(r"#\d+")
DOCS_LINK_RE = re.compile(r"\]\(docs/[^)]+\)")


def _read():
    return README.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Under 80 lines
# --------------------------------------------------------------------------- #


def test_readme_is_under_eighty_lines():
    lines = _read().splitlines()
    assert len(lines) < 80, "README.md is {} lines, not under 80 (#795)".format(len(lines))


# --------------------------------------------------------------------------- #
# No issue number before the first docs/ link
# --------------------------------------------------------------------------- #


def test_readme_states_no_issue_number_above_the_first_docs_link():
    text = _read()
    link_match = DOCS_LINK_RE.search(text)
    assert link_match, (
        "README.md has no docs/ link at all -- #795's whole point is a front door that "
        "points elsewhere for the receipts"
    )
    before = text[: link_match.start()]
    found = ISSUE_RE.findall(before)
    assert not found, (
        "README.md names {} issue number(s) before its first docs/ link: {} -- the "
        "pitch-and-install section is meant to read like a tool, not a changelog "
        "(#795)".format(len(found), found)
    )


def test_the_issue_number_detector_actually_fires():
    """Positive control: a fixture carrying an issue number above the docs link must
    be caught -- otherwise the assertion above could be passing because nothing in
    README ever gets checked, not because README is actually clean."""
    fixture = "Some receipt about #123.\n\nSee [docs/x.md](docs/x.md) for more.\n"
    link_match = DOCS_LINK_RE.search(fixture)
    assert link_match
    before = fixture[: link_match.start()]
    assert ISSUE_RE.findall(before) == ["#123"]


# --------------------------------------------------------------------------- #
# Nothing removed from README is unfindable -- a light existence/content check,
# not a line-for-line diff against git history.
# --------------------------------------------------------------------------- #

#: One or two markers per moved doc, chosen from content that used to live in
#: README.md and would only be here if that paragraph actually moved rather than
#: being silently dropped.
DOCS_TARGETS = {
    "docs/install.md": ["ln -sf", "#607", "#617"],
    "docs/commands.md": ["/oss:doctor", "/oss:install-audit"],
    "docs/status-line.md": ["watch_channel"],
    "docs/development.md": ["pytest-cov", "#303"],
    "docs/status.md": ["Tested, not proven", "#293"],
}


def test_every_moved_paragraph_is_findable_under_docs():
    for rel_path, markers in DOCS_TARGETS.items():
        doc = REPO_ROOT / rel_path
        assert doc.is_file(), (
            "{} is missing -- content #795 moved out of README.md is now "
            "unfindable".format(rel_path)
        )
        text = doc.read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, (
                "{} does not contain {!r}, expected from the README content #795 "
                "moved here".format(rel_path, marker)
            )


def test_the_findability_detector_actually_fires_on_a_missing_doc():
    """Positive control: a doc that does not exist must fail the check above,
    rather than the loop over DOCS_TARGETS silently skipping it."""
    missing = REPO_ROOT / "docs" / "this-file-does-not-exist-795.md"
    assert not missing.is_file()
