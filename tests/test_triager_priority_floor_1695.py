"""#1695: `agents/triager.md` gave lane an explicit floor and fallback but only
invited priority to refuse, so an issue the triager honestly declines to rank
stays permanently unlabelled for priority. `select_issues_rank._band()` already
folds a missing priority label into the `low` band (#826) -- so the fallback the
code takes silently is now stated as a duty here too, mirroring #1310's lane fix,
with the report duty that keeps a genuine refusal distinguishable from a real
low-priority judgment.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAGER = REPO_ROOT / "agents" / "triager.md"


def _flatten(text):
    return " ".join(text.lower().split())


def _unmet(text, anchors):
    folded = _flatten(text)
    return [anchor for anchor in anchors if anchor not in folded]


PRIORITY_FLOOR_ANCHORS = [
    "priority-low",
    "select_issues_rank",
    "distinguishable in your report",
]


def test_triager_carries_the_priority_floor_duty():
    """#1695: without this, `agents/triager.md` states a floor for lane but only
    an invitation to refuse for priority, and the code's own low-band fallback
    then renders identically to a real judgment."""
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), PRIORITY_FLOOR_ANCHORS)


def test_the_priority_floor_check_fires_on_the_prior_priority_paragraph():
    """The document as it stood before #1695: it invites a refusal and states no
    floor and no fallback for priority, unlike the lane paragraph three lines
    below it."""
    prior_priority_paragraph = (
        "**Say so if an issue fits none of them** rather than forcing it into "
        "the nearest row -- the class that does not exist yet is where the "
        "worst finding lands. And if the table did not reach you, say that "
        "instead of labelling from memory: an issue triaged against a taxonomy "
        "you could not read is not a triaged issue, and it is indistinguishable "
        "from one that was."
    )
    missing = _unmet(prior_priority_paragraph, PRIORITY_FLOOR_ANCHORS)
    assert missing, (
        "the priority-floor check passes against the document's prior priority "
        "paragraph, which never states a floor: {}".format(missing)
    )
