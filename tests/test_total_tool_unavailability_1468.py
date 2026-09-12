"""#1468 -- a nested `oss:developer` lane reported the `Agent` tool totally
unavailable in its own session (neither `Explore` nor `oss:auditor` could be
spawned, the tool refused or absent regardless of `subagent_type`), while the
dispatching sub-manager's own `Agent` tool worked the whole time -- so this is
specific to the nested (agent-spawned-by-agent) context, not a whole-install
outage.

`agents/developer/review-return.md`'s own "When the spawn itself fails"
section already documented one failure mode before this change: a
`subagent_type` that does not resolve, fixed by re-dispatching once to
`general-purpose` (#81). It said nothing about the Agent tool being
unreachable outright -- a materially different failure, because the
`general-purpose` fallback is not a remedy for it (the same unavailability
defeats every name equally) and the schema already has a different, correct
state for it (`not-checked` with `review.spawn_error`, wired by #1383/#1445)
that a lane following only the #81 clause would never reach.

This mirrors `tests/test_spawn_error_documented_1383.py`'s shape (the
narrowest testable claim for a doc-only fix over this brief) and
`tests/test_developer_brief_duties.py`'s PRIOR-control shape (an anchor must
not already match the pre-change wording, or the guard has no teeth).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import developer_docs  # noqa: E402

# The pre-change spine and phase file, exactly as they stood at the base this
# change was written against (f0cf758, tag v0.33.1) -- read once here rather
# than trusted from memory, so a stale PRIOR string cannot pass the red-before
# check vacuously.
PRIOR_REVIEW_RETURN = REPO_ROOT.joinpath("agents", "developer", "review-return.md")
PRIOR_SPINE = REPO_ROOT.joinpath("agents", "developer.md")


def _flat(text):
    return " ".join(text.lower().split())


def _prior_review_return():
    import subprocess

    out = subprocess.run(
        ["git", "show", "f0cf758:agents/developer/review-return.md"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def _prior_spine():
    import subprocess

    out = subprocess.run(
        ["git", "show", "f0cf758:agents/developer.md"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


# The anchors the fix has to state, not their exact wording:
TOTAL_UNAVAILABILITY_POLICY = [
    "total unavailability",
    "not a remedy for it",
    "report `not-checked` per",
    "review.spawn_error",
    "not worth spending a turn on",
]


def test_the_developer_brief_documents_total_tool_unavailability():
    flat = _flat(developer_docs.text(REPO_ROOT))
    missing = [a for a in TOTAL_UNAVAILABILITY_POLICY if a not in flat]
    assert missing == [], missing


def test_the_anchors_were_red_against_the_pre_change_review_return():
    """Must-not-fire half: an anchor already present before this change is an
    anchor with no teeth."""
    prior = _flat(_prior_review_return())
    matched = [a for a in TOTAL_UNAVAILABILITY_POLICY if a in prior]
    assert matched == [], f"toothless anchors, already on disk: {matched}"


def test_the_pre_change_document_still_only_names_one_failure_mode():
    """Positive control for the test above: PRIOR must be readable and must
    contain the ORIGINAL failure mode's own language, so a blank or truncated
    PRIOR does not silently pass every 'must not match' assertion."""
    prior = _flat(_prior_review_return())
    assert "a spawn that errors because the name does not resolve" in prior
    assert "could not run" in prior


def test_total_unavailability_is_distinguished_from_name_resolution_failure():
    """The two failure modes must not collapse into the same instruction --
    the whole point of #1468 is that re-dispatching to general-purpose is a
    remedy for one and not the other."""
    text = _flat(developer_docs.text(REPO_ROOT))
    assert "does not resolve" in text  # #81, still present
    assert "totally unavailable" in text or "total unavailability" in text


def test_the_spine_points_at_both_failure_modes_before_the_phase_file():
    """agents/developer.md is read from turn one; the pointer sentence to
    review-return.md has to name both failure modes so a lane knows the
    phase file distinguishes them, per the same reasoning
    tests/test_the_developer_brief_names_the_classifier (392) applies to
    scripts/review_return.py."""
    spine = _flat(
        REPO_ROOT.joinpath("agents", "developer.md").read_text(encoding="utf-8")
    )
    assert "1468" in spine or "totally unavailable" in spine


def test_the_spine_anchor_was_red_against_the_pre_change_spine():
    prior_spine = _flat(_prior_spine())
    assert "totally unavailable" not in prior_spine
    assert "1468" not in prior_spine
