"""#1044 -- confirm the real live dispatch path composes the companion sweep
against the OPEN BOARD, not against sibling running lanes, and that the bug
shape it reports (three one-issue lanes, real adjacent candidates sitting on
a 31-issue open board, each lane reporting `no-adjacent`) does not reproduce
on current code.

The issue's own framing: `lane_setup.py --against` used to be pointed at the
*other dispatched lanes* (the conflict check) instead of at the *rest of the
open board* (the companion search), so `no-adjacent` was written on the
strength of a measurement that never looked at the board at all. #918/#921
(`select_issues_rank.check_lane(..., adjacent=...)`) already added a
truthfulness check for that exact claim, and #1069/#1145/#1148/#1153 folded
the companion sweep into `select_issues.py`'s own `select()`/`select_fleet()`
so a dispatched lane's own `--lane-fill` reason is derived mechanically from
a real board sweep (`group_state`), never hand-typed from an `--against`
check run against sibling lanes. This file is the fixture the issue itself
asks for: N open issues on a fake board, two of which genuinely land inside
a dispatched lane's own claimed set, run through the REAL,
unmocked `select_issues_companions.suggest_companions` (never a stub -- the
bug was in the wiring, not in that function's own logic, which #851's own
tests already cover on their own).

No production code changes with this fix: every wiring this file exercises
(`select()`'s default `suggest_companions`, `lane_setup.group_short_reason`,
`select_issues_rank.check_lane`'s `adjacent=` truthfulness check) already
existed on `main` before this issue was picked up. This is the confirming
regression test #1044 itself allows for: "if your own reproduction shows the
bug no longer reproduces on current code, say so plainly in the report rather
than inventing a fix for a bug that is gone."
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import lane_setup  # noqa: E402
import select_issues  # noqa: E402
import select_issues_companions  # noqa: E402
import select_issues_rank  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
}


def _issue(number, labels=None, body=None, **extra):
    row = {
        "number": number,
        "labels": labels or [],
        "author_association": "maintainer",
        "body": body or "",
        "title": "issue #{0}".format(number),
    }
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [
        {"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"}
        for n in numbers
    ]


def _board_of_31_open_issues(lead_files):
    """31 open issues -- the exact count #1044's own reproduction names.
    #2 and #3 each declare, in backticks in their own body, a file that
    lands inside the dispatched lane's claimed set (`lead_files`); #4-#30
    each declare a file of their own that overlaps nothing -- board noise a
    truthful sweep must stay clear of, the "must not fire" half of this
    fixture's own pairing."""
    issues = [
        _issue(
            1,
            ["priority-high"],
            lane_patterns=lead_files,
            # Every OTHER issue's own body must declare a real path (#851) --
            # an issue with an empty/undeclared body reads as `undetermined`
            # for whoever else's sweep it is swept into, which would turn
            # this whole board's read into `could-not-tell` rather than the
            # clean `none`/`candidates` split this fixture is testing.
            body="touches `{0}` and `{1}`".format(lead_files[0], lead_files[1]),
        )
    ]
    issues.append(
        _issue(2, ["priority-medium"], body="touches `{0}`".format(lead_files[0]))
    )
    issues.append(
        _issue(3, ["priority-medium"], body="touches `{0}`".format(lead_files[1]))
    )
    for n in range(4, 31):
        issues.append(
            _issue(
                n,
                ["priority-low"],
                body="touches `scripts/unrelated_1044_{0}.py`".format(n),
            )
        )
    return issues


def test_1044_real_board_sweep_finds_the_two_real_adjacent_candidates(tmp_path):
    """Must-fire half: with the REAL, unmocked companion search wired
    through `select()`'s own default, a lead issue's group finds #2 and #3
    as real companions on a 31-issue open board -- the exact adjacency
    #1044 reports the old code never looked for."""
    lead_files = ["scripts/foo_1044_fixture.py", "scripts/bar_1044_fixture.py"]
    payload = {
        "declared": DECLARED,
        "repo": str(tmp_path),
        "issues": _board_of_31_open_issues(lead_files),
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    groups = result["groups"]["groups"]
    lead_group = [g for g in groups if g["members"][0]["number"] == 1][0]
    assert lead_group["state"] == select_issues_companions.STATE_CANDIDATES
    numbers = {m["number"] for m in lead_group["members"]}
    assert {1, 2, 3} <= numbers
    # #918/#1153: a group that genuinely found candidates never translates to
    # the "no-adjacent" word -- that is reserved for a group whose own state
    # is "none" (swept, confirmed clear), never "candidates". This is the
    # mechanical guarantee that stops #1044's bug shape: even a caller who
    # only dispatches the lead alone cannot manufacture a truthful
    # "no-adjacent" fill reason out of a group that found real candidates.
    assert lane_setup.group_short_reason(lead_group["state"]) is None


def test_1044_control_a_genuinely_isolated_lead_on_the_same_board_reports_none(
    tmp_path,
):
    """Must-not-fire half, the positive control for the test above: a SECOND
    lead issue on the exact same 31-issue board, whose own claimed files
    genuinely overlap nothing, reports the real `none` state -- and only
    that state translates to `no-adjacent`. A silence assertion alone would
    also pass if the sweep were simply broken and never ran at all; this
    pairs it with the must-fire case above so a broken harness cannot hide
    behind a fixture that never checked for a real candidate in the first
    place."""
    lead_files = ["scripts/foo_1044_fixture.py", "scripts/bar_1044_fixture.py"]
    issues = _board_of_31_open_issues(lead_files)
    issues.append(
        _issue(
            31,
            ["priority-high"],
            lane_patterns=["scripts/truly_isolated_1044.py"],
            body="touches `scripts/truly_isolated_1044.py`",
        )
    )
    payload = {"declared": DECLARED, "repo": str(tmp_path), "issues": issues}
    result = select_issues.select(payload, checker=_no_op_checker)
    groups = result["groups"]["groups"]
    isolated_group = [g for g in groups if g["members"][0]["number"] == 31][0]
    assert isolated_group["state"] == select_issues_companions.STATE_NONE
    assert lane_setup.group_short_reason(isolated_group["state"]) == "no-adjacent"


def test_1044_no_adjacent_claim_is_refused_when_a_real_candidate_remains():
    """End-to-end: the truthfulness check #918/#921 wired into
    `oss_state.py --decision` (`select_issues_rank.check_lane(...,
    adjacent=...)`) refuses a caller who claims `no-adjacent` while a real
    adjacent candidate count is handed alongside it -- the exact
    reproduction #1044 describes (a claimed `no-adjacent` nothing checked
    against the board) is caught mechanically rather than trusted."""
    check = select_issues_rank.check_lane(range(1), "no-adjacent", adjacent=2)
    assert check["state"] != "ok"
    assert check["state"] == "adjacent-candidate-exists"


def test_1044_control_no_adjacent_is_accepted_when_truthfully_zero():
    """Positive control for the test above: the identical claim, with a real
    zero adjacent count, is accepted -- refusing every `no-adjacent` claim
    regardless of truth would be as wrong as accepting every one blindly."""
    check = select_issues_rank.check_lane(range(1), "no-adjacent", adjacent=0)
    assert check["state"] == "ok"
