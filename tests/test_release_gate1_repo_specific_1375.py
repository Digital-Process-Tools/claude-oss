"""#1375: gate 1 in commands/release.md asserted a fact about ONE managed repos
CI shape (this repo's own reduced-push/full-dispatch matrix, #1246) as though it
were permanent and universal, inside a document every managed repo release
reads identically. commands/release.md already tells the reader to derive
the answer per-repo by grepping .github/workflows/*.yml at release time -- the
offending sentence asserted the answer for one specific repo on top of that,
which is exactly the "fact about one repository living in shared code" defect
CLAUDE.md governing rule forbids.

This guard is deliberately narrow rather than reusing test_content_invariants.py
existing HARDCODED sweep: that sweep _fact_bearing_documents() does not
include commands/*.md at all (#1375 own finding -- no test covered this
file for repo-specific claims), and commands/release.md legitimately mentions
"this repository" and cites #1246 as a worked example elsewhere (the post-push
section, #1266/#1324) without asserting a permanent universal fact -- so a
blanket ban on "this repository" would be too broad. The one sentence banned
here is the one that claims this specific repo IS "one instance of exactly
that shape" as settled fact, rather than something to check.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

RELEASE_MD = REPO_ROOT / "commands" / "release.md"

#: The exact phrase #1375 flags: asserts this repo CI shape as permanent fact
#: rather than something the reader derives at release time.
OFFENDING_PATTERN = re.compile(
    r"this\s+repository\s+is\s+one\s+instance\s+of\s+exactly\s+that\s+shape"
)


def test_release_md_exists():
    assert RELEASE_MD.is_file(), (
        "commands/release.md not found -- the check below would vacuously pass"
    )


def test_gate1_does_not_assert_this_repos_ci_shape_as_permanent_fact():
    text = RELEASE_MD.read_text(encoding="utf-8")
    match = OFFENDING_PATTERN.search(text)
    assert not match, (
        "commands/release.md asserts a repo own CI shape (reduced matrix "
        "on push, full via workflow_dispatch) as a permanent, universal fact "
        "inside a document every managed repo release reads identically. "
        "That is exactly the defect CLAUDE.md governing rule forbids -- a "
        "fact about one repository living in shared (loop) prose. The gate "
        "already instructs the reader to grep .github/workflows/*.yml at "
        "release time to derive the answer per-repo; let that instruction "
        "decide, rather than asserting the answer for one named repo on top "
        "of it. Found: {!r}".format(match.group(0))
    )


#: Gate 1's own paragraph, isolated so the check below cannot be satisfied by
#: the *other* place in the file (the post-push CI-wait section, #1266/#1324)
#: that also mentions workflow_dispatch/inputs -- that text already existed
#: verbatim before this fix and would make the check pass on the pre-fix file
#: too, proving nothing about this diff. Anchored on "does not satisfy this
#: gate", a phrase unique to gate 1.
GATE1_ANCHOR = "does not satisfy this gate"


def _gate1_paragraph(text):
    start = text.index(GATE1_ANCHOR)
    end = text.index("```", start)
    return text[start:end]


def test_gate1_anchor_is_unique_in_the_file():
    """A guard against the anchor itself drifting or being duplicated --
    if it stops being unique, _gate1_paragraph() could silently isolate the
    wrong stretch of text."""
    text = RELEASE_MD.read_text(encoding="utf-8")
    assert text.count(GATE1_ANCHOR) == 1, (
        "expected exactly one occurrence of {!r} in commands/release.md "
        "(gate 1's own paragraph) -- found {}".format(
            GATE1_ANCHOR, text.count(GATE1_ANCHOR)
        )
    )


def test_gate1_still_instructs_deriving_the_shape_per_repo():
    """The fix removes the hardcoded claim, not the underlying instruction --
    gate 1's own paragraph (not merely the file somewhere) must still tell the
    reader to grep the repo's own workflow files at release time rather than
    assume any shape."""
    text = RELEASE_MD.read_text(encoding="utf-8")
    paragraph = _gate1_paragraph(text)
    assert "workflow_dispatch: inputs:" in paragraph, (
        "gate 1's own paragraph no longer instructs looking for a "
        "wider-coverage workflow_dispatch input in .github/workflows/*.yml -- "
        "the per-repo derivation is what should remain in place of the "
        "hardcoded claim"
    )
    assert "never something to assume here" in paragraph or (
        "do not assume" in paragraph or "rather than assume" in paragraph
    ), (
        "gate 1's own paragraph no longer says the shape is a per-repo fact "
        "rather than something to assume -- that framing is what replaces "
        "the removed hardcoded claim"
    )
