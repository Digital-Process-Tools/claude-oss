"""#1750: a prior tick's own `declined-for-cause` on a maintainer-policy question
must not be re-decided by a later tick's own judgment.

Observed on claude-oss, 2026-09-26: one tick's `oss:tick-dispatch` declined issue
#784 for cause -- a milestones-policy question needing a maintainer decision. The
next tick, with no memory of that call and nothing on the issue's own GitHub state
recording it either, decided for itself that making the call was fine and
dispatched a developer lane to write the answer into `.oss.json`.

There is no code path to unit-test here -- the defect is an LLM session's own
judgment overriding a prior one's, not a function returning the wrong value. The
fix is the loop's own governing prose, injected into the exact spawn that makes
this call (`agents/tick-dispatch.md`) via the jit-context rule that already
matches it. This file pins that the doctrine exists and says what it must say,
the same way `tests/test_content_invariants.py` pins loop prose elsewhere.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

RULE_PATH = (
    REPO_ROOT
    / ".claude"
    / "jit-context"
    / "paths"
    / "00-manual"
    / "issue-design-question-not-dispatchable.md"
)


def _text():
    assert RULE_PATH.exists(), "the design-question jit rule must exist at {0}".format(
        RULE_PATH
    )
    return RULE_PATH.read_text(encoding="utf-8")


def test_the_rule_still_matches_the_files_that_make_this_call():
    """Positive control: the fix is only reachable at all if the rule's own
    `match` frontmatter still covers `agents/tick-dispatch.md` -- the file
    that actually renders the dispatch decision every tick."""
    text = _text()
    frontmatter = text.split("---", 2)[1]
    assert "tick-dispatch" in frontmatter, frontmatter
    assert "dispatch" in frontmatter, frontmatter
    assert "recon" in frontmatter, frontmatter


def test_a_prior_decline_binds_a_later_tick_until_a_maintainer_signal_clears_it():
    """#1750's own fix: the rule must say, in as many words, that a later tick
    reaching the issue fresh may not conclude on its own that a previously
    identified maintainer/policy question is now fine to decide."""
    text = _text()
    assert "1750" in text, text
    assert re.search(r"maintainer-authored signal", text), text
    assert re.search(
        r"[Nn]othing here licenses a tick to conclude.*on its own judgment alone",
        text,
        re.DOTALL,
    ), text


def test_the_own_reasoning_being_sound_is_explicitly_not_enough():
    """The exact failure mode quoted in #1750 ('I made that call myself this
    tick... low-stakes and reversible') is a sound-sounding judgment call --
    the rule has to name that this is not the same as a maintainer's own
    signal, or the fix does not close the gap that let it happen."""
    text = _text()
    assert "reversible" in text, text
    assert re.search(r"is not that signal", text), text
