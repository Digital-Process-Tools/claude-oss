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

import dispatch_rank as _dispatch_rank  # noqa: E402
from test_content_invariants import _collapse  # noqa: E402

SUB_MANAGER_MD = REPO_ROOT / "agents" / "sub-manager.md"
TICK_MD = REPO_ROOT / "commands" / "tick.md"

#: The short-lane reasons, read from `dispatch_rank.SHORT_REASONS` rather than
#: retyped (#918, found by review on PR #921). This tuple used to be a hardcoded
#: three, and its own comment called `dispatch_rank` "the actual source of truth"
#: while comparing neither document to it -- it checked the two prose files
#: against *each other*, so both naming the same stale three passed as fully
#: compliant. #918 added a fourth word to the vocabulary and this guard went on
#: reporting parity, which is a guard measuring the wrong pair rather than one
#: that failed to run. Two copies agreeing proves nothing about whether either is
#: right; pin the source, not the parity.
SHORT_REASONS = tuple(_dispatch_rank.SHORT_REASONS)


#: "default" alone is a false positive waiting to happen: `commands/tick.md`
#: says "default branch" roughly a dozen times, none of them about lane fill
#: (found by review -- the bare substring check reported this fact present in
#: a pre-#867 copy of the file that never stated the #867 sentence at all).
#: Anchored on the actual shared phrasing instead -- "default" and "ceiling"
#: within a handful of words of each other, either order -- which is what
#: both documents' own "three is the default, not the ceiling" sentences
#: look like and what "default branch" never does.
_DEFAULT_NOT_CEILING_RE = re.compile(
    r"default\W+(?:\S+\s+){0,8}ceiling|ceiling\W+(?:\S+\s+){0,8}default"
)


def _has_fill_facts(text):
    """#867: never-four ceiling, three as default (not ceiling), and all three
    short-lane reasons named. Returns a tuple so a partial match is visible in
    a failed assertion rather than folding into one boolean.
    """
    return (
        "never four" in text or "never 4" in text,
        bool(_DEFAULT_NOT_CEILING_RE.search(text)),
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


def test_negative_control_a_missing_reason_is_caught():
    """The positive control's negative half: strip one fact from a copy of the
    text and the same extractor must report it missing, so a green result
    above is not a check that never fires.
    """
    text = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    stripped = text.replace("board-exhausted", "")
    never_four, has_default, has_reasons = _has_fill_facts(stripped)
    assert not has_reasons, "stripping a reason word should make the check fail"


def test_negative_control_a_missing_never_four_is_caught():
    """Every sub-fact needs its own negative control (found by review): a
    single passing extractor for one of three facts does not establish the
    other two are discriminating rather than trivially true.
    """
    text = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    stripped = text.replace("never four", "").replace("never 4", "")
    never_four, has_default, has_reasons = _has_fill_facts(stripped)
    assert not never_four, "stripping the never-four phrase should make the check fail"


def test_negative_control_a_missing_default_not_ceiling_is_caught():
    """The bare-substring version of this extractor could not fail this test
    at all: `commands/tick.md` says "default branch" a dozen times, so
    stripping the one #867 sentence would have left the fact reading `True`
    regardless (found by review, see `_DEFAULT_NOT_CEILING_RE`'s own note).
    """
    text = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    stripped = text.replace(
        "The default is three, not the ceiling", "Three issues is fine"
    )
    never_four, has_default, has_reasons = _has_fill_facts(stripped)
    assert not has_default, "stripping the default/ceiling sentence should make the check fail"
