"""#1048: the third instance of the observed recurrence -- "State recorded.
Waiting for the background CI poll now -- will act as soon as #923/#924
clear or if a failure shows up." -- is a header-less promise to resume, the
exact class `_RESUME_PROMISE` (#941) exists to name, but its own phrasing
("will act as soon as ... clear") does not match any of #941's four
sub-patterns: it is not "pick ... back up", not "will resume/continue",
and "as soon as #923/#924 clear" is not "once CI"/"when CI ... resolves".

This is a positive control, paired with a negative one below, for the
narrower fix within #1048's scope: broadening the pattern so the *reason*
this classifies with names the actual defect (as #941 already does for the
first two instances) rather than falling back to the generic "no header"
text -- the same defect #941 fixed, recurring on a phrasing #941's own
pattern did not anticipate.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import tick_handback  # noqa: E402


def test_the_observed_third_instance_names_the_promise_defect():
    verdict = tick_handback.classify(
        "State recorded. Waiting for the background CI poll now -- will "
        "act as soon as #923/#924 clear or if a failure shows up."
    )
    assert verdict["state"] == "could-not-classify"
    assert "TICK: paused" in verdict["reason"], verdict["reason"]


def test_a_plain_no_header_message_with_no_promise_still_gets_the_generic_reason():
    """Must-not-fire control: the widened pattern must not swallow the
    ordinary header-less case #941's own control already covers."""
    verdict = tick_handback.classify(
        "I looked at the board and dispatched two lanes, everything is fine."
    )
    assert verdict["state"] == "could-not-classify"
    assert "no TICK: header found" in verdict["reason"]
    assert "paused" not in verdict["reason"]


def test_ordinary_will_act_prose_does_not_trigger_the_promise_reason():
    """Must-not-fire control, found in self-review: an earlier draft of this
    fix added a bare `act` to the will-verb alternation, wide enough to fire
    on ordinary present-tense prose unrelated to a resumption promise ("the
    loop will act on this important issue next time"). The third observed
    instance's own wording ("will act as soon as ... clear") is still
    caught by the "as soon as ... clear" and "waiting for ... CI" branches
    added alongside it, so the bare `act` branch bought nothing and was
    removed."""
    verdict = tick_handback.classify(
        "The loop will act on this important issue next time it ticks."
    )
    assert verdict["state"] == "could-not-classify"
    assert "no TICK: header found" in verdict["reason"]
    assert "paused" not in verdict["reason"]
