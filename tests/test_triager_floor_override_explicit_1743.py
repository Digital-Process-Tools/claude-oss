"""#1743: `agents/triager.md` states a priority floor for an unranked
finding (`priority-low`, #1310/#1695) but never says whether that floor is
a mandate or a default an agent may override. Two real issues (#1740 at
`priority-high`, #1630 at `priority-medium`) were left at an elevated
priority by a prior triage sweep despite being unranked, with no stated
reason distinguishing a deliberate severity override from the floor simply
having gone unapplied -- exactly the ambiguity the sweep flagged as needing
a maintainer decision rather than another labelling pass.

The fix: the floor paragraph now states explicitly that it is a default,
not a mandate -- an agent may override it when it judges the real severity
warrants a higher priority, but only by stating the override AS an
override, with the reason, rather than silently applying a higher priority
that reads like an ordinary judgment call.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAGER = REPO_ROOT / "agents" / "triager.md"


def _flatten(text):
    return " ".join(text.lower().split())


def _unmet(text, anchors):
    folded = _flatten(text)
    return [anchor for anchor in anchors if anchor not in folded]


FLOOR_OVERRIDE_ANCHORS = [
    "default, not a mandate",
    "override",
    "priority-low",
]


def test_triager_states_the_floor_is_a_default_not_a_mandate():
    """Without this, #1740 and #1630 are each individually defensible under
    the existing 'rank it your way' license, but the document never says
    that license applies to the priority floor specifically, so a reader
    cannot tell an override from a floor that was never applied."""
    text = TRIAGER.read_text(encoding="utf-8")
    assert not _unmet(text, FLOOR_OVERRIDE_ANCHORS)


def test_the_override_check_fires_on_the_prior_floor_paragraph():
    """The document as it stood before #1743: the floor paragraph states
    the duty ('apply priority-low') with no mention of an override at all
    -- a positive control showing the anchors above are absent from the
    un-fixed text."""
    prior_floor_paragraph = (
        "**Say so if an issue fits none of them** rather than forcing it "
        "into the nearest row -- the class that does not exist yet is "
        "where the worst finding lands. **Priority still gets the same "
        "floor lane has below (#1310, #1695):** apply `priority-low` so "
        "no issue is left unlabelled -- `select_issues_rank`'s own "
        "`_band()` already treats a missing label this way (#826). Report "
        "the unranked class as a finding for filing rather than letting "
        "the fallback speak for itself: a `priority-low` applied because "
        "nothing fit must stay **distinguishable in your report** from "
        "one applied because the issue really is low, or the fallback "
        "quietly becomes a judgment."
    )
    missing = _unmet(prior_floor_paragraph, FLOOR_OVERRIDE_ANCHORS)
    assert missing, (
        "the floor-override check passes against the document's prior "
        "floor paragraph, which never states an override rule: {}".format(missing)
    )
