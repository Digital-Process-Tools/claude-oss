"""#1129: `select_issues.py` ranks correctly and forms zero lanes on every
real board, because `lane_patterns` -- the per-issue file set `groups`
(#1068) bundles on -- has no producer; not one real issue carries it as a
literal. This derives it, as a fallback only, from an issue's `lane-*`
GitHub label through a mapping declared in `.oss.json`
(`declared["lane_patterns"]`).

Three states, and the third is the point: a lane label covered by a
declared mapping derives that lane's patterns; no lane label, an uncovered
lane label, or no declared mapping at all resolve to **unknown** -- never
to an empty file set (#267's own rule, restated for a derived source
rather than a declared one). Explicit per-issue `lane_patterns` always
wins over a derived one.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
}

LANE_MAP = {
    "lane-dispatch": ["scripts/select_issues_overlap.py"],
    "lane-doctor": ["scripts/doctor.py"],
}


def _issue(number, labels=None, **extra):
    row = {"number": number, "labels": labels or [], "author_association": "maintainer"}
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [
        {"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"}
        for n in numbers
    ]


def _literal_resolve(repo, patterns):
    return {
        "patterns": [
            {"pattern": p, "state": "literal", "files": [p], "detail": ""}
            for p in patterns
        ],
        "files": list(patterns),
    }


# --------------------------------------------------------------------- must-fire


def test_a_lane_label_covered_by_the_mapping_derives_patterns():
    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [_issue(1, ["priority-high", "lane-dispatch"])],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    assert result["state"] == "candidates"
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] == "derived-from-label"
    # A derived file set is real enough to lead its own (short) group --
    # not folded into `ungrouped`'s "declares no files" state.
    assert result["groups"]["ungrouped"] == []
    assert len(result["groups"]["groups"]) == 1


# --------------------------------------------------------------- must-not-fire, paired


def test_no_lane_label_at_all_resolves_unknown_not_an_empty_set():
    """Positive control is the test directly above: WITH the identical
    mapping declared, an issue carrying no lane label at all must still
    resolve unknown -- never a guessed empty file set (#267)."""
    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {"declared": declared, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    assert result["state"] == "candidates"
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] is None
    assert len(result["groups"]["ungrouped"]) == 1
    assert "no files" in result["groups"]["ungrouped"][0]["why"]


def test_a_lane_label_the_mapping_does_not_cover_resolves_unknown():
    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [_issue(1, ["priority-high", "lane-release"])],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] is None
    assert len(result["groups"]["ungrouped"]) == 1


def test_no_mapping_declared_at_all_resolves_unknown_even_with_a_lane_label():
    declared = dict(DECLARED)  # no "lane_patterns" key at all
    payload = {
        "declared": declared,
        "issues": [_issue(1, ["priority-high", "lane-dispatch"])],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] is None
    assert len(result["groups"]["ungrouped"]) == 1


def test_explicit_lane_patterns_always_wins_over_a_derived_one():
    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [
            _issue(
                1,
                ["priority-high", "lane-dispatch"],
                lane_patterns=["scripts/oss_config.py"],
            )
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] == "declared"
    # Not the label-mapped file -- the issue's own explicit one.
    group = result["groups"]["groups"][0]
    assert group["members"][0]["number"] == 1


# ----------------------------------------------------- production shape (#1129)


def test_a_real_board_with_lane_labels_and_no_explicit_lane_patterns_forms_groups():
    """The shape production actually sees: NO issue anywhere in the payload
    carries a literal `lane_patterns` -- only `lane-*` labels -- and real
    file resolution (no injected `resolve_lane`) against this repo's own
    tree. Before #1129 this always produced zero groups; #1129's own
    reproduction, verbatim.
    """
    declared = dict(
        DECLARED,
        lane_patterns={"lane-dispatch": ["scripts/select_issues_overlap.py"]},
    )
    lead = _issue(1, ["priority-high", "lane-dispatch"])
    other = _issue(
        2,
        ["priority-high", "lane-dispatch"],
        title="Fix an overlap edge case",
        body="See `scripts/select_issues_overlap.py` for the bug.",
    )
    payload = {"declared": declared, "issues": [lead, other]}
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    assert result["groups"]["ungrouped"] == []
    assert len(result["groups"]["groups"]) == 1
    numbers = {m["number"] for m in result["groups"]["groups"][0]["members"]}
    assert numbers == {1, 2}
