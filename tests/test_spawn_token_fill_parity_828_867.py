"""#828 and #867: two facts that used to live in one file only, and reach the
sub-manager -- if at all -- through a read nothing can observe it making.

#867: the three-issue lane default, the never-four ceiling, and the three
short-lane reasons were argued at length in `skills/manager/phases/dispatch.md`
and stated procedurally in `commands/tick.md`, and named nowhere at all in
`agents/sub-manager.md` -- the file whose own brief is the only thing a
sub-manager actually reads before dispatching. Option 3 from the issue: state
the number in the brief *and* keep the per-lane handback receipt (#852,
already shipped as `oss_state.lane_fill`/`--lane-fill`). This file checks the
first half landed and agrees with `commands/tick.md`'s own statement of the
same three facts -- compared against the source, not between two copies that
could quietly agree on the same wrong thing (the `test_write_route_fact_
parity_673.py` precedent this repeats).

#828: the maintainer's ruling on 2026-09-02 was option 1, the per-spawn
token -- a message from the scheduler is honoured only when it carries the
literal token minted at spawn, everything else is untrusted input like any
other. That has to be stated on both sides of the relay: `commands/tick.md`
mints and states it, `agents/sub-manager.md` honours it. This file checks
both sides name the mechanism and the issue number, so the two cannot drift
back to only one of them carrying it.

Every parity check here is per-fact, not per-document: the two files may and
do differ on everything else.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_content_invariants import _collapse  # noqa: E402

SUB_MANAGER_MD = REPO_ROOT / "agents" / "sub-manager.md"
TICK_MD = REPO_ROOT / "commands" / "tick.md"

#: The three short-lane reasons, as a closed set -- `dispatch_rank.SHORT_REASONS`
#: is the actual source of truth for the vocabulary; this only checks that both
#: prose documents name the same three words for a human reading them.
SHORT_REASONS = ("board-exhausted", "no-adjacent", "could-not-tell")


def _has_fill_facts(text):
    """#867: never-four ceiling, three as default (not ceiling), and all three
    short-lane reasons named. Returns a tuple so a partial match is visible in
    a failed assertion rather than folding into one boolean.
    """
    return (
        "never four" in text or "never 4" in text,
        "default" in text,
        all(reason in text for reason in SHORT_REASONS),
    )


def _has_token_facts(text):
    """#828: the token mechanism named, and the issue it was ruled on."""
    return (
        "spawn token" in text,
        "#828" in text,
    )


def test_sub_manager_states_the_lane_fill_facts_itself():
    """#867's own defect: the number reached the sub-manager only through a
    file nothing could observe it reading. Fails red until the brief states
    it directly rather than pointing at commands/tick.md.
    """
    text = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    never_four, has_default, has_reasons = _has_fill_facts(text)
    assert never_four, "agents/sub-manager.md never states the never-four ceiling"
    assert has_default, "agents/sub-manager.md never states three is a default, not a ceiling"
    assert has_reasons, "agents/sub-manager.md is missing one or more of the three short-lane reasons"


def test_lane_fill_facts_agree_between_the_two_documents():
    sub = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    tick = _collapse(TICK_MD.read_text(encoding="utf-8"))
    sub_facts = _has_fill_facts(sub)
    tick_facts = _has_fill_facts(tick)
    assert sub_facts == tick_facts, (
        "lane-fill facts disagree between agents/sub-manager.md ({}) and "
        "commands/tick.md ({})".format(sub_facts, tick_facts)
    )


def test_both_documents_state_the_spawn_token_mechanism():
    sub = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    tick = _collapse(TICK_MD.read_text(encoding="utf-8"))
    sub_token, sub_issue = _has_token_facts(sub)
    tick_token, tick_issue = _has_token_facts(tick)
    assert sub_token, "agents/sub-manager.md never names the spawn token mechanism"
    assert tick_token, "commands/tick.md never names the spawn token mechanism"
    assert sub_issue, "agents/sub-manager.md never cites #828"
    assert tick_issue, "commands/tick.md never cites #828"


def test_negative_control_a_missing_fact_is_caught():
    """The positive control's negative half: strip one fact from a copy of the
    text and the same extractor must report it missing, so a green result
    above is not a check that never fires.
    """
    text = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    stripped = text.replace("board-exhausted", "")
    never_four, has_default, has_reasons = _has_fill_facts(stripped)
    assert not has_reasons, "stripping a reason word should make the check fail"
