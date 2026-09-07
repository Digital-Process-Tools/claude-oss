"""#1134: CLAUDE.md forbade lanes from writing it, on pain of a red CI, over a case the file never
named as an exception -- a lane whose diff pushes a budgeted file past its declared ceiling must
edit this file's own table row (`tests/test_claude_md_budget_table_709.py`,
`tests/test_claude_md_phase_budget_table_725.py`, `tests/test_baseline_matches_disk_1014.py` all
require it), and the "curated by hand" bullet named only two other exceptions. PR #1132 is the
observed instance: a correct, necessary `CLAUDE.md` edit that satisfied neither stated exception.

This does not verify the fix is *sufficient* -- it is a documentation change and cannot be checked
by running the loop through it -- only that the bullet now names a third exception covering that
case, rather than staying silent on the contradiction #1134 filed.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

BULLET_MARKER = "this file is curated by hand"


def _bullet(text):
    """The "curated by hand" bullet's own paragraph, or "" if the marker is absent."""
    start = text.find(BULLET_MARKER)
    if start < 0:
        return ""
    # Back up to the start of the bullet (the preceding "- **").
    bullet_start = text.rfind("\n- ", 0, start)
    rest = text[bullet_start:] if bullet_start >= 0 else text[start:]
    end = rest.find("\n\n", 1)
    return rest if end < 0 else rest[:end]


def test_the_bullet_is_present():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert _bullet(text), (
        "CLAUDE.md carries no 'curated by hand' bullet -- either it was removed, or the marker "
        "string this test keys on drifted"
    )


def test_the_bullet_names_a_third_exception_for_a_forced_budget_rebaseline():
    """#1134: a lane forced into a budgeted-file re-baseline must be a named exception, not left
    to violate either the prose or the tests it cannot simultaneously satisfy.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    bullet = _bullet(text)
    assert bullet, "the 'curated by hand' bullet is missing"
    assert re.search(r"\bthree\s+exceptions\b", bullet, re.IGNORECASE), (
        "the bullet still counts two exceptions -- #1134's third case (a forced budget "
        "re-baseline) is not named"
    )
    assert "#1134" in bullet, (
        "the bullet does not cite #1134, so a reader has no way back to the incident that forced "
        "the third exception"
    )
    assert re.search(r"budget", bullet, re.IGNORECASE), (
        "the bullet's third exception must actually describe the budgeted-file re-baseline case, "
        "not just count to three"
    )
    assert re.search(r"only that file.s own table row", bullet, re.IGNORECASE), (
        "the bullet's third exception must actually scope the licence to the affected table row -- "
        "counting to three and citing #1134 is not the same as narrowing what a lane may touch, "
        "and a cosmetic edit that dropped the scoping clause while keeping the count and citation "
        "would otherwise still satisfy this test"
    )
    assert re.search(
        r"nothing\s+else\s+in\s+`?CLAUDE\.md`?\s+moves", bullet, re.IGNORECASE
    ), (
        "the bullet must say explicitly that nothing else in this file moves for the third "
        "exception's reason alone -- without this clause the exception has no stated ceiling of "
        "its own and could licence an unrelated rider"
    )


def test_the_must_fire_control_fires_on_the_pre_1134_text():
    """Reconstructs the bullet as it read before this fix (two exceptions, no #1134) and proves
    the check above would have failed against it -- otherwise the check could be passing for a
    reason unrelated to this fix.
    """
    before_fix = (
        "\n- **And this file is curated by hand: the loop does not write it.** No lane, "
        "sub-manager, auditor or release session edits `CLAUDE.md` unless editing it was the "
        "thing it was explicitly asked to do. Two exceptions, both an explicit ask rather than "
        "initiative: the release session updating `What is not proven yet`'s marker inside the "
        "release commit, and a change whose subject *is* this file.\n\n"
    )
    bullet = _bullet(before_fix)
    assert bullet, "control text must contain the marker the real extractor keys on"
    assert not re.search(r"\bthree\s+exceptions\b", bullet, re.IGNORECASE), (
        "control text must not already satisfy the 'three exceptions' check"
    )
    assert "#1134" not in bullet, "control text must not already cite #1134"
