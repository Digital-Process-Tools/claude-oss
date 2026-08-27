"""The supertool rule body exists twice: the tracked

`.claude/jit-context/tools/01-oss/supertool-required.md`, which this repository's own
sessions read, and `TOOLS_SUPERTOOL` in `scripts/oss_rules.py`, which is what gets
*written into every scaffolded repository*. Nothing used to compare them (#577).
The issue that reported this gap cited `tests/test_content_invariants.py`'s #250
check as covering the pair narrowly; it does not cover it at all -- that check is
about a different pair entirely (`agents/developer.md` and `skills/manager/SKILL.md`)
and never mentions either file here (`grep -n TOOLS_SUPERTOOL tests/test_content_invariants.py`
and `grep -n supertool-required tests/test_content_invariants.py` both return nothing).
So this pair had zero coverage,
not narrow coverage.

#570 is the demonstration this issue was filed over: the `requires:` paragraph went
stale in both copies at once and was corrected in both by hand, which only worked
because one lane happened to hold both files.

The two directions are not symmetric. A stale `.md` here is a rule this repository's own
sessions read. A stale `TOOLS_SUPERTOOL` is a rule written into somebody else's
repository, where nobody here will ever see it.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402

RULE_MD = REPO_ROOT / ".claude" / "jit-context" / "tools" / "01-oss" / "supertool-required.md"


def _normalize(text):
    """Line-ending and trailing-whitespace normalisation only, never a content
    transform. CI runs Windows legs where a checkout can arrive with CRLF, so the two
    copies have to agree in substance rather than in which line-ending convention this
    particular checkout happened to use.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


def _bodies_match(a, b):
    return _normalize(a) == _normalize(b)


# --- the invariant itself -----------------------------------------------------------


def test_tools_supertool_matches_the_tracked_md_body():
    """The two copies of the supertool rule must say the same thing.

    Frontmatter included: measured against the repo at the moment this test was
    written, the two bodies were byte-identical including frontmatter, so there is no
    established reason for `TOOLS_SUPERTOOL` to carry a different `title:`/`match:`/
    etc. than the tracked `.md` -- if that ever becomes intentional, this test is the
    place to carve out the exception, with the reason recorded here.
    """
    md_body = RULE_MD.read_text(encoding="utf-8")
    py_body = oss_rules.TOOLS_SUPERTOOL
    assert _bodies_match(md_body, py_body), (
        "scripts/oss_rules.py's TOOLS_SUPERTOOL and "
        ".claude/jit-context/tools/01-oss/supertool-required.md have diverged -- "
        "TOOLS_SUPERTOOL is what gets written into every scaffolded repository, so a "
        "drift here ships a stale rule nobody in this repository will ever see (#577)"
    )


def test_the_md_file_is_readable_and_substantial():
    """Half of the positive control: a sameness assertion also passes when both
    files are empty or unreadable, so this pins that the file this test reads from is
    neither -- a genuine multi-paragraph rule body, not a placeholder.
    """
    body = RULE_MD.read_text(encoding="utf-8")
    assert len(body) > 1000, "the rule body is suspiciously short: {} bytes".format(len(body))
    assert "supertool" in body


def test_tools_supertool_constant_is_substantial():
    """The other half: `TOOLS_SUPERTOOL` itself is not empty or trivially short."""
    assert len(oss_rules.TOOLS_SUPERTOOL) > 1000
    assert "supertool" in oss_rules.TOOLS_SUPERTOOL


# --- the control pair, driven against synthetic bodies so it does not depend on ------
# --- today's repo state (#577 requires both halves) -----------------------------------


def test_control_an_edit_to_both_copies_the_same_way_still_matches():
    a = "---\ntitle: x\n---\n\nSame body, same rule.\n"
    b = "---\ntitle: x\n---\n\nSame body, same rule.\n"
    assert _bodies_match(a, b)


def test_control_an_edit_to_exactly_one_copy_is_caught():
    a = "---\ntitle: x\n---\n\nSame body, same rule.\n"
    b = "---\ntitle: x\n---\n\nSame body, DIFFERENT rule.\n"
    assert not _bodies_match(a, b)


def test_control_line_ending_and_trailing_whitespace_alone_do_not_count_as_drift():
    """CI runs Windows; a checkout-level CRLF difference must not fail this guard."""
    a = "---\ntitle: x\n---\n\nSame body.  \n"
    b = "---\r\ntitle: x\r\n---\r\n\r\nSame body.\r\n"
    assert _bodies_match(a, b)
