"""Guard against bare tracker citations reappearing in the vendored assembler.

`scripts/assemble_changelog.py` ships byte-for-byte into every scaffolded repo as
`.oss/assemble_changelog.py` (see `scaffold._owned_assembler`). A bare `#NNN` in its prose
resolves against whichever tracker the reader is standing in -- this project's issue history
citing itself is invisible to a contributor of a repo we do not own. See issue #24.

This is a content test: the pattern is asserted to match something so a regex that quietly
stopped matching cannot let the check pass by finding nothing.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "scripts" / "assemble_changelog.py"

# A GitHub-style issue/PR reference: '#' immediately followed by 2-5 digits, not itself
# preceded by '{' (which would make it an f-string/`.format()` placeholder interpolating
# the *reader's own* issue number -- those are fine, they never carry our history).
BARE_CITATION_RE = re.compile(r"(?<!\{)#\d{2,5}\b")


def test_source_file_exists():
    assert SOURCE.exists(), "scripts/assemble_changelog.py not found -- did it move?"


def test_regex_matches_something_on_a_known_offender():
    """A pattern that matches nothing has checked nothing."""
    assert BARE_CITATION_RE.search("cite bug (#936) here"), (
        "BARE_CITATION_RE no longer matches a bare issue reference -- fix the pattern before "
        "trusting the assertion below"
    )


def test_no_bare_issue_citations_in_vendored_assembler():
    text = SOURCE.read_text(encoding="utf-8")
    offenders = []
    for match in BARE_CITATION_RE.finditer(text):
        line = text[: match.start()].count("\n") + 1
        offenders.append("{}:{}: {!r}".format(SOURCE.name, line, match.group(0)))
    assert not offenders, (
        "A bare '#NNN' citation resolves against whichever tracker the reader is standing "
        "in once this file is vendored into another repo. State the reason inline instead "
        "of citing our issue number, or use an absolute 'owner/repo#NNN' reference if the "
        "number itself must survive the boundary:\n  " + "\n  ".join(offenders)
    )


def test_no_relative_readme_pointer_in_vendored_assembler():
    """'changelog.d/README.md' assumes the scaffolded repo's copy documents the same
    convention ours does -- a layout assumption, same defect shape as a bare citation.
    """
    text = SOURCE.read_text(encoding="utf-8")
    assert "changelog.d/README.md" not in text, (
        "found a reference to changelog.d/README.md in the vendored assembler -- this "
        "plugin never scaffolds that file, so the pointer may resolve to nothing, or to a "
        "file that documents a different convention, in the repo it is vendored into"
    )
