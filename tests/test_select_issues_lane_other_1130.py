"""#1130: `lane-other` -- a triaged issue with no owning lane -- must never
render as an untriaged one, and must never be treated as bundleable.

`.oss.json` declares five real lanes; the triager's correct behaviour when
none fits is to apply nothing, which makes an examined-and-refused issue
indistinguishable from one nobody has read. `lane-other` is the positive
statement "triaged, no lane owns its files."

Two things carry the weight, each covered below:

* `_derive_lane_patterns_from_labels` must special-case the configured
  `lane-other` label to `None` -- unknown -- explicitly, never by falling
  through to the "uncovered label" path by accident. A test fails if
  someone later adds a `lane-other` entry to the `.oss.json` mapping and
  the special case stops being what produces the `None`.
* A `lane-other` candidate is dispatched solo, always: never given a
  companion, never offered as one, never padded toward `_GROUP_TARGET`.
  It must come out of grouping as a deliberate group of one with a stated
  `short_reason` -- entering grouping and staying alone -- never landing
  in `ungrouped`, which means "never entered grouping at all".
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
    "lane_other": "lane-other",
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


# --------------------------------------------------------------------- unit: derivation


def test_lane_other_label_is_special_cased_to_none_even_when_mapped():
    """The constraint's own words: an explicit special case, with a test
    that fails if someone later adds a `lane-other` entry to the mapping.
    Building the mapping WITH a `lane-other` key (never produced by
    .oss.json's own validated shape, but nothing stops a hand edit) proves
    the `None` comes from the special case, not from the "uncovered label"
    fallback -- if the special case were deleted and `lane-other` merely
    fell through, this exact mapping would derive a file set instead."""
    mapping = dict(LANE_MAP, **{"lane-other": ["scripts/anything.py"]})
    result = select_issues._derive_lane_patterns_from_labels(
        ["lane-other"], mapping, "lane-other"
    )
    assert result is None


def test_a_lane_label_covered_by_the_mapping_still_derives_normally():
    """Positive control: the derivation still works for a real lane when
    `lane_other_label` is passed alongside it -- the special case must not
    swallow every label, only the configured lane-other one."""
    result = select_issues._derive_lane_patterns_from_labels(
        ["lane-dispatch"], LANE_MAP, "lane-other"
    )
    assert result == LANE_MAP["lane-dispatch"]


# --------------------------------------------------------------- production shape


def test_lane_other_issue_and_a_bundleable_pair_both_present():
    """The production shape: a board carrying one `lane-other` issue AND a
    genuinely bundleable pair. The pair must bundle; the `lane-other` issue
    must come out as a stated singleton, never in `ungrouped`, never as a
    member or lead of the pair's group."""

    def companions(repo, own_issue, claimed, board):
        if own_issue == 2:
            return {
                "state": "candidates",
                "candidates": [{"number": 3, "files": ["scripts/shared.py"]}],
                "undetermined": [],
                "detail": "",
            }
        return {
            "state": "none",
            "candidates": [],
            "undetermined": [],
            "detail": "swept, nothing overlaps",
        }

    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-medium"], lane_patterns=["scripts/shared.py"]),
            _issue(3, ["priority-medium"]),
        ],
    }
    result = select_issues.select(
        payload,
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        suggest_companions=companions,
    )
    assert result["state"] == "candidates"
    groups = result["groups"]["groups"]
    ungrouped = result["groups"]["ungrouped"]

    assert ungrouped == []

    solo = [g for g in groups if [m["number"] for m in g["members"]] == [1]]
    assert len(solo) == 1
    solo_group = solo[0]
    assert solo_group["short_reason"]
    assert "lane-other" in solo_group["short_reason"].lower()

    pair = [g for g in groups if {m["number"] for m in g["members"]} == {2, 3}]
    assert len(pair) == 1
    assert {m["number"] for m in pair[0]["members"]} == {2, 3}


def test_lane_other_issue_is_never_offered_as_a_companion():
    """Symmetric half of the rule, paired with the must-fire test above (the
    genuinely bundleable pair DOES bundle): even when a lead's own
    `suggest_companions` sweep names the `lane-other` issue as an
    overlapping candidate, it must never be pulled in as a member."""

    def companions(repo, own_issue, claimed, board):
        if own_issue == 2:
            return {
                "state": "candidates",
                "candidates": [{"number": 1, "files": ["scripts/shared.py"]}],
                "undetermined": [],
                "detail": "",
            }
        return {
            "state": "none",
            "candidates": [],
            "undetermined": [],
            "detail": "",
        }

    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-medium"], lane_patterns=["scripts/shared.py"]),
        ],
    }
    result = select_issues.select(
        payload,
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        suggest_companions=companions,
    )
    groups = result["groups"]["groups"]
    for group in groups:
        numbers = [m["number"] for m in group["members"]]
        if 1 in numbers:
            assert numbers == [1]


def test_a_lane_other_issue_never_gets_a_companion_itself():
    """Even when the board contains another candidate that WOULD overlap by
    file, a `lane-other` lead never receives a companion -- solo dispatch,
    always. Positive control: without the `lane-other` label, the same
    board shape bundles (see the production-shape test above)."""

    def companions(repo, own_issue, claimed, board):
        return {
            "state": "candidates",
            "candidates": [{"number": 2, "files": ["scripts/shared.py"]}],
            "undetermined": [],
            "detail": "",
        }

    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-medium"]),
        ],
    }
    result = select_issues.select(
        payload,
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        suggest_companions=companions,
    )
    groups = result["groups"]["groups"]
    lead_group = [g for g in groups if g["members"][0]["number"] == 1][0]
    assert len(lead_group["members"]) == 1


def test_lane_other_singleton_is_distinguishable_from_ungrouped():
    """A `lane-other` singleton and a fileless, never-derived candidate must
    render as different states -- the one 'entered grouping and stayed
    alone', the other 'never entered grouping at all'."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-high", "lane-other"]),
            _issue(2, ["priority-medium"]),  # no lane label at all: genuinely unknown
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    ungrouped_numbers = {e["number"] for e in result["groups"]["ungrouped"]}
    assert ungrouped_numbers == {2}
    solo_numbers = {
        m["number"] for g in result["groups"]["groups"] for m in g["members"]
    }
    assert solo_numbers == {1}


def test_solo_is_a_bundling_verdict_not_a_ranking_one():
    """A priority-high `lane-other` issue still outranks a bundleable
    priority-low one -- solo dispatch must not touch the ranking axis."""
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(2, ["priority-low"], lane_patterns=["scripts/shared.py"]),
            _issue(1, ["priority-high", "lane-other"]),
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    numbers_in_rank_order = [c["number"] for c in result["candidates"]]
    assert numbers_in_rank_order[0] == 1
