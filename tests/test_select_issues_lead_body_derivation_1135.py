"""#1135: grouping computed overlap broad-against-narrow. `select()` built
the LEAD's file set from #1129's `lane-*` label globs -- a whole subsystem
-- while `suggest_companions` built each companion's set from
`_derive_declared_files`: only repo-relative paths named literally, in
backticks, in that issue's own title and body (#851). A lead labelled
`lane-dispatch` therefore claimed all 14 dispatch files and swallowed
anything in that subsystem; two issues sharing only a label rendered
identically to two issues that genuinely share a file.

The fix: give the lead the same narrow, body-declared set companions
already get, and fall back to the label's globs only when the issue's own
title and body name no path at all. Precedence, strict and stated: an
issue's own explicit `lane_patterns`, then paths declared in its body,
then its label's globs, then unknown -- never `[]` at any step.

`lane_patterns_source` grows a fourth value, `"derived-from-body"`, and a
bundled group now says which kind of adjacency joined it -- `"measured"`
when the lead's own claim is narrow (declared or body-derived), or
`"label-derived"` when the lead's claim is the coarse, subsystem-wide
label fallback -- because the group's own precision is bounded by
whichever side of the overlap is coarser, and only the lead can be coarse
here (a companion that survives `suggest_companions` at all always came
from its own narrow body derivation).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402
import select_issues_companions  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
    "lane_other": "lane-other",
}

LANE_MAP = {
    "lane-dispatch": [
        "scripts/select_issues.py",
        "scripts/select_issues_companions.py",
        "scripts/lane_setup.py",
    ],
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


# --------------------------------------------------------------------- unit


def test_derive_declared_patterns_extracts_backtick_paths_from_title_and_body():
    patterns = select_issues_companions._derive_declared_patterns(
        "A bug in select()", "See `scripts/select_issues.py` for the culprit."
    )
    assert patterns == ["scripts/select_issues.py"]


def test_derive_declared_patterns_is_none_when_nothing_path_shaped_is_named():
    assert (
        select_issues_companions._derive_declared_patterns(
            "A vague title", "No paths here, just `could-not-tell`."
        )
        is None
    )


# --------------------------------------------------------------- precedence


def test_a_lead_with_a_body_declared_path_uses_it_over_the_label_derived_set():
    """Positive control is the label-fallback test below: WITH an identical
    label mapping declared, a lead whose body names a path uses that
    narrower set instead, never the label's whole subsystem."""
    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [
            _issue(
                1,
                ["priority-high", "lane-dispatch"],
                body="Only `scripts/select_issues.py` is affected.",
            )
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] == "derived-from-body"


def test_a_lead_whose_body_names_no_path_falls_back_to_the_label_derived_set():
    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [_issue(1, ["priority-high", "lane-dispatch"])],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] == "derived-from-label"


def test_an_explicit_declared_lane_patterns_still_wins_over_a_body_declared_path():
    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [
            _issue(
                1,
                ["priority-high", "lane-dispatch"],
                lane_patterns=["scripts/oss_config.py"],
                body="See `scripts/select_issues.py`.",
            )
        ],
    }
    result = select_issues.select(
        payload, checker=_no_op_checker, resolve_lane=_literal_resolve
    )
    entry = result["candidates"][0]
    assert entry["lane_patterns_source"] == "declared"


# --------------------------------------------------------- group adjacency


def test_a_group_joined_by_a_body_declared_file_is_marked_measured():
    def companions(repo, own_issue, claimed, board):
        if own_issue == 1:
            return {
                "state": "candidates",
                "candidates": [{"number": 2, "files": ["scripts/shared.py"]}],
                "undetermined": [],
                "detail": "",
            }
        return {"state": "none", "candidates": [], "undetermined": [], "detail": ""}

    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(
                1,
                ["priority-high"],
                body="Touches `scripts/shared.py`.",
            ),
            _issue(2, ["priority-medium"]),
        ],
    }
    result = select_issues.select(
        payload,
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        suggest_companions=companions,
    )
    group = result["groups"]["groups"][0]
    assert group["members"][0]["lane_patterns_source"] == "derived-from-body"
    assert group["adjacency"] == "measured"


def test_a_group_joined_only_through_the_lead_label_set_is_marked_label_derived():
    """Positive control is the test above: an otherwise identical shape
    where the LEAD carries no body-declared path at all, so its own claim
    can only be the coarse, subsystem-wide label set -- the group must say
    so, since the group's own precision is bounded by that breadth even
    when the companion's own overlap files are narrow."""

    def companions(repo, own_issue, claimed, board):
        if own_issue == 1:
            return {
                "state": "candidates",
                "candidates": [
                    {"number": 2, "files": ["scripts/select_issues_companions.py"]}
                ],
                "undetermined": [],
                "detail": "",
            }
        return {"state": "none", "candidates": [], "undetermined": [], "detail": ""}

    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [
            _issue(1, ["priority-high", "lane-dispatch"]),
            _issue(2, ["priority-medium"]),
        ],
    }
    result = select_issues.select(
        payload,
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        suggest_companions=companions,
    )
    group = result["groups"]["groups"][0]
    assert group["members"][0]["lane_patterns_source"] == "derived-from-label"
    assert group["adjacency"] == "label-derived"


def test_a_solo_group_never_entered_by_overlap_carries_no_adjacency_claim():
    """A `lane-other` singleton (#1130) and a short group with no overlap at
    all never entered grouping THROUGH an overlap, so there is nothing to
    claim precision about -- `adjacency` stays `None` rather than a guess."""

    def companions(repo, own_issue, claimed, board):
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
            _issue(2, ["priority-medium"], lane_patterns=["scripts/a.py"]),
        ],
    }
    result = select_issues.select(
        payload,
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        suggest_companions=companions,
    )
    for group in result["groups"]["groups"]:
        assert group["adjacency"] is None


# ----------------------------------------------------- production shape


def test_two_pairs_one_measured_one_label_only_are_distinguishable():
    """The production shape #1135 asks for: a board where one pair is
    joined by a genuine body-declared file and another pair shares only a
    lane label -- the two must render differently in the result, not both
    as plain `state: candidates` / `adjacency: None`."""

    def companions(repo, own_issue, claimed, board):
        if own_issue == 1:
            return {
                "state": "candidates",
                "candidates": [{"number": 2, "files": ["scripts/shared.py"]}],
                "undetermined": [],
                "detail": "",
            }
        if own_issue == 3:
            return {
                "state": "candidates",
                "candidates": [
                    {"number": 4, "files": ["scripts/select_issues_companions.py"]}
                ],
                "undetermined": [],
                "detail": "",
            }
        return {"state": "none", "candidates": [], "undetermined": [], "detail": ""}

    declared = dict(DECLARED, lane_patterns=LANE_MAP)
    payload = {
        "declared": declared,
        "issues": [
            _issue(1, ["priority-high"], body="Touches `scripts/shared.py`."),
            _issue(2, ["priority-medium"]),
            _issue(3, ["priority-high", "lane-dispatch"]),
            _issue(4, ["priority-medium"]),
        ],
    }
    result = select_issues.select(
        payload,
        checker=_no_op_checker,
        resolve_lane=_literal_resolve,
        suggest_companions=companions,
    )
    groups_by_lead = {g["members"][0]["number"]: g for g in result["groups"]["groups"]}
    assert groups_by_lead[1]["adjacency"] == "measured"
    assert groups_by_lead[3]["adjacency"] == "label-derived"
    assert groups_by_lead[1]["adjacency"] != groups_by_lead[3]["adjacency"]
