"""`commands/tick.md` step 3 and `skills/manager/SKILL.md`'s waiting-on-CI
sentence must agree about whether a CI wait counts as work -- #820.

Observed 2026-09-02: a sub-manager mid-tick blocked its own turn on
`gh run watch`, waiting for the default branch to go green before starting
developer lanes it had already selected. Step 3 said "A merged-but-unverified
PR, a red default branch, or an agent whose work is sitting uncommitted all
outrank the next issue. Finishing beats starting." -- three examples that are
all *work*, read naturally as an ordering over everything open, waits
included. `SKILL.md` separately says "Waiting on CI is not a reason to stop
working" and "never wait for [the wakeup]". The two documents were never read
against each other, and the phase split (#725) means a session can hold one
without the other in view.

Following `tests/test_write_route_fact_parity_673.py`'s shape: this is a
per-fact parity check between two documents, not a floor on either one in
isolation. Two copies each individually satisfying a floor can still
contradict each other, which is exactly what a per-document check cannot
see -- the issue's own "test shape" section names this directly.

The shared fact, pasted into both documents verbatim except for
sentence-initial capitalisation (extraction below folds case rather than
require an exact match a legitimate stylistic difference would break): **"a
wait is not an act, and it does not outrank dispatch (#820)"**. `commands/
tick.md` states it where dispatch is decided (step 3); `skills/manager/
SKILL.md` states it beside its "never wait for [the wakeup]" rule. Neither
copy stating it, or the two disagreeing, is the exact drift this issue
reports; both stating it, in agreement, is the fix.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_content_invariants import MANAGER_SKILL  # noqa: E402

# #1037: this content moved out of commands/tick.md into its own phase file.
TICK_MD = REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md"

#: The shared fact, folded to lowercase so a legitimate sentence-initial
#: capital ("A wait is not an act...") is not read as a disagreement with a
#: mid-sentence lowercase copy ("...— a wait is not an act...").
_WAIT_NOT_AN_ACT_RE = re.compile(
    r"a wait is not an act, and it does not outrank dispatch \(#820\)",
    re.IGNORECASE,
)


def _states_wait_is_not_an_act(text):
    return bool(_WAIT_NOT_AN_ACT_RE.search(text))


def test_step_3_and_skill_md_agree_that_a_wait_is_not_work():
    """The parity check itself: both documents must state the same fact
    about a CI wait's priority relative to dispatch, not each be judged
    against a floor of its own."""
    tick_states_it = _states_wait_is_not_an_act(TICK_MD.read_text(encoding="utf-8"))
    skill_states_it = _states_wait_is_not_an_act(
        MANAGER_SKILL.read_text(encoding="utf-8")
    )
    assert tick_states_it and skill_states_it, (
        "commands/tick.md and skills/manager/SKILL.md must both state that a "
        "wait is not an act and does not outrank dispatch (#820) -- tick.md: "
        "{0}, SKILL.md: {1}".format(tick_states_it, skill_states_it)
    )


def test_step_3_specifically_carries_the_fact_not_just_the_document():
    """Narrower than the whole-document check above: the fact must sit in
    step 3 itself, where dispatch is decided, not merely somewhere in the
    2000-line file."""
    text = TICK_MD.read_text(encoding="utf-8")
    step_3_start = text.index("3. **Act on what is open before starting anything new.**")
    step_4_start = text.index("4. **Take the handback")
    step_3_body = text[step_3_start:step_4_start]
    assert _states_wait_is_not_an_act(step_3_body), (
        "the shared fact must live inside step 3's own body, not merely "
        "somewhere in commands/tick.md"
    )


# --- must-fire controls: prove the parity check can actually fail ----------


def test_the_extractor_fires_on_the_real_step_3_wording():
    """Sanity: the exact wording step 3 carries is itself a positive case,
    so the checks above are not passing by accident of a looser regex."""
    sentence = (
        "**A wait is not an act, and it does not outrank dispatch (#820).** "
        "The three examples above are all work."
    )
    assert _states_wait_is_not_an_act(sentence)


def test_the_extractor_does_not_fire_on_the_pre_fix_wording():
    """Must-fire (negative): the wording this issue reports -- three work
    examples with no carve-out for a wait -- must not be read as already
    stating the fact. Guards against a regex loose enough to rubber-stamp
    the pre-fix text."""
    pre_fix = (
        "Act on what is open before starting anything new. A "
        "merged-but-unverified PR, a red default branch, or an agent whose "
        "work is sitting uncommitted all outrank the next issue. Finishing "
        "beats starting."
    )
    assert not _states_wait_is_not_an_act(pre_fix)


def test_the_extractor_would_catch_a_disagreement_if_one_copy_dropped_it():
    """Must-fire (positive): if either document silently lost the sentence
    -- the two-copies-disagree shape this test exists to catch -- the parity
    assertion fails rather than passing on a stale memory of what used to be
    there."""
    with_it = "prose... a wait is not an act, and it does not outrank dispatch (#820). more prose"
    without_it = "prose... waiting on CI is not a reason to stop working. more prose"
    assert _states_wait_is_not_an_act(with_it)
    assert not _states_wait_is_not_an_act(without_it)
