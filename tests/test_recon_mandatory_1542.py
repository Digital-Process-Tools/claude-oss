"""#1542: the lane's recon spawn is unconditional, not a judgement call.

#1535 moved the recon into the developer lane, and `agents/developer.md` made the
spawn conditional on the ground being "unfamiliar". A lane is handed issue numbers
and a worktree path and nothing else, so at the moment it would evaluate that
condition it has read the issue bodies and none of the tree -- the only way to
learn whether the ground is familiar is the orientation pass the recon exists to
replace. Measured on one lane, three issues (#1499): recon 0.7M context tokens,
lane 65.8M against 134.4M for the comparable lane without one.

These checks read the developer brief as a whole (`developer_docs.DeveloperBrief`,
#939) -- prose read by an agent, so what is pinned is what the brief says, never
that any code enforces it. Each negative assertion below is paired with a positive
control in the same test, so "the brief stopped mentioning recon at all" can never
render as "the condition is gone".
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from developer_docs import DeveloperBrief  # noqa: E402

DEVELOPER_MD = DeveloperBrief()  # spine + agents/developer/*.md (#939)


def _flat():
    return " ".join(DEVELOPER_MD.read_text(encoding="utf-8").split())


def test_the_brief_still_tells_the_lane_to_spawn_a_recon():
    """The positive control for both negative assertions below."""
    text = _flat()
    assert "oss:recon" in text, (
        "the developer brief no longer names oss:recon at all -- without this "
        "control, the two checks below would pass vacuously"
    )


def test_the_spawn_is_not_conditional_on_the_lane_judging_the_ground():
    text = _flat()
    assert "oss:recon" in text  # control, re-asserted in the failing test's own fixture
    for conditional in ("when the ground is unfamiliar", "when you spawned one"):
        assert conditional not in text, (
            "the developer brief still makes the recon conditional on a judgement "
            "the lane cannot make before paying the reads the recon replaces "
            "(found: {0!r}) -- #1542".format(conditional)
        )


def _recon_sentence():
    """The one sentence that carries the spawn instruction, not the whole brief.

    Scoping matters: the brief is 43 KB and words like "first" appear all over
    it, so asserting them against `_flat()` passes whether or not the recon
    instruction says anything about ordering -- a check that cannot fail.
    """
    text = _flat()
    marker = "oss:recon"
    start = text.find(marker)
    assert start != -1, "the developer brief no longer names oss:recon"
    opening = text.rfind("**", 0, start)
    end = text.find(". ", start)
    return text[opening if opening != -1 else start : end if end != -1 else len(text)]


def test_the_brief_says_the_recon_comes_first():
    sentence = _recon_sentence()
    assert "oss:recon" in sentence  # control: the scope really did find the spawn
    assert "first" in sentence or "before" in sentence, (
        "the developer brief's own recon sentence does not order the spawn ahead "
        "of the lane's reads of the tree -- a mandate nobody can order is not a "
        "mandate (#1542). Sentence read: {0!r}".format(sentence)
    )


def test_a_refused_agent_tool_still_has_to_be_reported():
    """Mandatory raises the stakes on the third state, so it must survive."""
    text = _flat()
    assert "compliance" in text
    assert "refus" in text, (
        "the developer brief no longer says a refused Agent tool must be reported "
        "under compliance -- a recon that could not run must never render as a lane "
        "that had nothing to orient on"
    )
