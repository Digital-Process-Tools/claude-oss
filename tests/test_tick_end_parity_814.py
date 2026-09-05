"""#814: `agents/sub-manager.md`'s report-back trigger and `commands/tick.md`'s
"What ends a tick" section can drift into disagreeing about whether dispatching
a lane, by itself, ends a sub-manager's tick -- and the drift is invisible to a
check that only asks whether each document mentions the right words, because
both documents can independently pass a per-document floor while contradicting
each other. Modeled on `tests/test_write_route_fact_parity_673.py`: compare a
named fact pairwise between the two documents, plus a findable-in-both control
and must-fire controls proving the comparison can actually fail.

Observed 2026-09-02 (the issue's own account): a sub-manager dispatched three
lanes and wrote its handback at that moment, following
`agents/sub-manager.md:115`'s literal "your tick is done -- dispatched,
blocked, or could not even start" -- while `commands/tick.md`'s "What ends a
tick" section says the opposite, that "Work started" does not end a tick and
"the tick continues". Three branches were left committed locally with no
remote ref and no open pull request.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_content_invariants import _collapse  # noqa: E402
import tick_handback  # noqa: E402

SUB_MANAGER_MD = REPO_ROOT / "agents" / "sub-manager.md"
# #1037: "What ends a tick" moved out of commands/tick.md into its own phase file.
TICK_MD = REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md"


#: The TICK-ENDS vocabulary, measured from `tick_handback.py`'s own
#: _KNOWN_TICK_ENDS tuple rather than retyped -- the issue explicitly asks
#: for this rather than a hand-copied list going stale beside the module
#: that enforces it. #896 broadened _TICK_ENDS's own compiled pattern to
#: an any-token capture (validated separately against _KNOWN_TICK_ENDS
#: afterwards) so that an unrecognised value is distinguishable from a
#: missing line rather than silently failing to match at all -- which
#: means the vocabulary can no longer be read out of the pattern's own
#: source text at all, and _KNOWN_TICK_ENDS is exactly the tuple this
#: parity check wants, already named and already the single source of
#: truth tick_handback.py itself validates against.
def _tick_ends_vocabulary():
    return frozenset(tick_handback._KNOWN_TICK_ENDS)


#: "Work started" bullet in commands/tick.md's "What ends a tick" section: does
#: it say the tick continues (dispatch alone does not end it) or does it say
#: dispatching itself closes the tick out?
_WORK_STARTED_BULLET_RE = re.compile(r"Work started[^-]*—\s*(.*?)(?=- \*\*Blocked\*\*)")


def _tick_md_dispatch_ends_tick(text):
    m = _WORK_STARTED_BULLET_RE.search(text)
    if not m:
        return None
    body = m.group(1)
    if "tick continues" in body:
        return False
    if "ends the tick" in body:
        return True
    return None


#: The sub-manager's own report-back trigger sentence: "When your tick is
#: done -- <list> -- write your final message". Before the fix this list
#: literally read "dispatched, blocked, or could not even start", naming
#: dispatch as itself sufficient to report a finished tick.
_REPORT_TRIGGER_RE = re.compile(
    r"[Ww]hen your tick is done\s*--\s*(.*?)\s*--\s*write your final message"
)


def _sub_manager_dispatch_ends_tick(text):
    """True only if "dispatched" appears as a bare, standalone item in the
    comma-separated list of things that end a tick -- not merely present
    somewhere in a longer clause qualifying it (e.g. "every lane dispatched
    this tick pushed ... or blocked"), which would false-positive on the
    fixed wording too."""
    m = _REPORT_TRIGGER_RE.search(text)
    if not m:
        return None
    items = re.split(r",|\bor\b", m.group(1))
    stripped = [item.strip().strip(".") for item in items]
    return "dispatched" in stripped


FACT_EXTRACTORS = {
    "dispatching alone ends the tick": (
        _sub_manager_dispatch_ends_tick,
        _tick_md_dispatch_ends_tick,
    ),
}


def test_sub_manager_and_tick_md_agree_that_dispatch_alone_does_not_end_a_tick():
    sub = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    tick = _collapse(TICK_MD.read_text(encoding="utf-8"))
    disagreements = {}
    for name, (sub_fn, tick_fn) in FACT_EXTRACTORS.items():
        sub_value = sub_fn(sub)
        tick_value = tick_fn(tick)
        if sub_value != tick_value:
            disagreements[name] = (sub_value, tick_value)
    assert not disagreements, (
        "agents/sub-manager.md and commands/tick.md disagree about when a "
        "tick ends (#814): {}".format(disagreements)
    )
    # And the agreed answer must be the correct one -- both documents could
    # agree on "yes, dispatch ends the tick" and both be wrong.
    sub_value = _sub_manager_dispatch_ends_tick(sub)
    assert sub_value is False, (
        "agents/sub-manager.md must not claim dispatching a lane, by itself, "
        "ends a tick (#814); got {!r}".format(sub_value)
    )


def test_the_facts_are_findable_in_both_documents():
    sub = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    tick = _collapse(TICK_MD.read_text(encoding="utf-8"))
    for name, (sub_fn, tick_fn) in FACT_EXTRACTORS.items():
        assert sub_fn(sub) is not None, (
            "agents/sub-manager.md does not state: {}".format(name)
        )
        assert tick_fn(tick) is not None, "commands/tick.md does not state: {}".format(
            name
        )


def test_sub_manager_ticks_ends_vocabulary_matches_tick_handback_py():
    sub = _collapse(SUB_MANAGER_MD.read_text(encoding="utf-8"))
    vocab = _tick_ends_vocabulary()
    assert vocab == frozenset({"work-started", "blocked", "nothing-left"}), vocab
    for word in vocab:
        assert word in sub, (
            "agents/sub-manager.md's TICK-ENDS gloss does not name {!r}, a "
            "value tick_handback.py actually accepts".format(word)
        )


# --- must-fire controls: prove the parity check can actually fail ----------

_TICK_MD_SNIPPET = (
    "- **Work started** — something was delegated in this tick. Name what and "
    "where it is running. The tick continues; do not arm a wakeup and wait on "
    "it. - **Blocked** — every remaining open item named individually."
)


def test_the_parity_check_fires_on_the_buggy_wording():
    """Must-fire: the exact wording #814 filed against -- 'dispatched' listed
    as itself sufficient for 'your tick is done'."""
    buggy = (
        "When your tick is done -- dispatched, blocked, or could not even "
        "start -- write your final message in exactly this shape"
    )
    assert _sub_manager_dispatch_ends_tick(buggy) is True
    assert _tick_md_dispatch_ends_tick(_TICK_MD_SNIPPET) is False
    assert _sub_manager_dispatch_ends_tick(buggy) != _tick_md_dispatch_ends_tick(
        _TICK_MD_SNIPPET
    )


def test_the_facts_are_findable_in_the_control_snippets():
    buggy = (
        "When your tick is done -- dispatched, blocked, or could not even "
        "start -- write your final message in exactly this shape"
    )
    assert _sub_manager_dispatch_ends_tick(buggy) is not None
    assert _tick_md_dispatch_ends_tick(_TICK_MD_SNIPPET) is not None
