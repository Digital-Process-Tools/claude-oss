"""#915: CLAUDE.md's opening must orient the agent reading it, and reach trap.d/.

`CLAUDE.md` is loaded whole by every session and read by nobody else (#904). What it opens with is
the only thing a session is guaranteed to see, so three facts have to be there: who is reading it,
why any of it is written down rather than remembered, and what to do when this session pays for a
lesson of its own.

The third is the one with a cost attached and the only one this file can meaningfully guard. `#905`
shipped `trap.d/` and `/oss:curate`, and `agents/developer.md` tells a *lane* to log a trap -- but a
session that opens `CLAUDE.md` directly is told by nothing else that the directory exists. A
mechanism nobody is invited to use and a mechanism that was never built are the same mechanism from
the outside, which is this repository's own defect class pointed at its own onboarding.

**What this file deliberately does not do is pin prose.** It checks that the invitation and its
permission are reachable in the opening, not that any sentence is phrased a particular way. A guard
that pins wording makes every future edit of the paragraph a test failure, and the paragraph is
exactly the kind of thing that should stay editable.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

#: The opening is everything before the first `## ` heading -- what a reader meets before any
#: section. Anchored at line start, never `find`, because the heading text also appears in prose
#: cross-references further down and a first-occurrence match would silently read the wrong span.
#: That exact defect took four tests red earlier in this repository and is logged in `trap.d/`.
SECTION_MARK = "\n## "


def _opening(text):
    end = text.find(SECTION_MARK)
    return text if end < 0 else text[:end]


#: The opening as it stood before #915: a title and a one-line description. Every assertion below
#: must fail against it, or the assertions are not measuring anything -- a check that passes on the
#: text it was written to reject has not been shown to reject anything.
CONTROL_OPENING = """# claude-oss

The maintainer loop for an open-source repo, as a Claude Code plugin: triage the tracker, decide
what is worth building, delegate it, review hard, merge on green, release.
"""


def _addresses_the_agent(opening):
    lowered = opening.lower()
    return "agent" in lowered and "session" in lowered


def _states_the_blank_session_constraint(opening):
    lowered = opening.lower()
    return "blank" in lowered or "remember" in lowered


def _reaches_the_trap_invitation(opening):
    return "trap.d/" in opening


def _carries_the_permission(opening):
    """#905's finding: the thing that stops a lesson being logged is not the format, it is the
    hesitation about whether it counts. The opening has to answer that, not just name the path."""
    lowered = opening.lower()
    return "do not need to be sure" in lowered or "no decision" in lowered or "decides that" in lowered


CHECKS = (
    ("addresses the agent reading it", _addresses_the_agent),
    ("states why this is written rather than remembered", _states_the_blank_session_constraint),
    ("names trap.d/", _reaches_the_trap_invitation),
    ("gives permission to log without being sure", _carries_the_permission),
)


def test_claude_md_is_readable():
    assert CLAUDE_MD.is_file(), "CLAUDE.md is missing -- every check below would vacuously pass"


@pytest.mark.parametrize("label,check", CHECKS, ids=[c[0] for c in CHECKS])
def test_the_opening_orients_the_session(label, check):
    opening = _opening(CLAUDE_MD.read_text(encoding="utf-8"))
    assert opening.strip(), "CLAUDE.md has no content before its first `## ` heading"
    assert check(opening), (
        "CLAUDE.md's opening no longer {}. It is the only part of this file a session is "
        "guaranteed to read, and trap.d/ is reachable from nowhere else a non-lane session "
        "looks (#915).".format(label)
    )


@pytest.mark.parametrize("label,check", CHECKS, ids=[c[0] for c in CHECKS])
def test_every_check_fails_on_the_pre_915_opening(label, check):
    """Must not fire. Each assertion above is run against the text #915 replaced, and must reject
    it -- otherwise the check passes on anything and the guard above is decoration."""
    assert not check(CONTROL_OPENING), (
        "the {!r} check passes on the pre-#915 opening, so it does not distinguish the fix from "
        "what it replaced".format(label)
    )


def test_the_opening_is_actually_the_opening():
    """The span itself, since every assertion above is scoped by it.

    A `_opening` that returned the whole file would make all four checks pass on any CLAUDE.md
    that mentions trap.d/ anywhere -- including one whose opening says nothing at all.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    opening = _opening(text)
    assert opening.startswith("# claude-oss"), opening[:80]
    assert SECTION_MARK not in opening, "the opening span ran past the first section heading"
    assert len(opening) < len(text), "the opening span swallowed the whole file"
