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

**Narrower than the module docstring above first claimed (found by this
lane's own self-review round): the closure is real only for the MECHANICAL
`select()`/`select_fleet()` -> `group_short_reason` -> `compose_lane_fill`
path this file exercises.** `check_lane`'s `adjacent=` truthfulness check
(the third and fourth tests below) is opt-in, not enforced: `oss_state.py`'s
own `--lane-fill PRIMARY:COUNT:REASON` CLI syntax makes the fourth
`CANDIDATES` field optional (`_lane_fill_argument`, `scripts/oss_state.py`),
and `lane_setup.py --claim --short-reason no-adjacent` (a real, documented,
still-reachable escape hatch alongside `--group-state`, for a lane composed
some other way than `select_issues.py`'s own grouping -- see
`skills/manager/phases/dispatch.md`) never threads a measured candidate count
through at all. A caller using `--short-reason` instead of `--group-state`
can still hand-compose a `no-adjacent` claim with zero board verification and
have it recorded as `ok` -- #1044's own bug shape, reproducible today through
that one remaining path. This file's own tests below prove the guard works
*when a count is supplied*; they do not, and cannot, prove every caller
supplies one. See this lane's own pull request / report for the full finding,
filed rather than fixed here because closing it means either the CLI or
`oss_state.py`'s own `lane_fill()` (a file outside this lane's own claimed
set) refusing an unfalsifiable `no-adjacent`/`board-exhausted` claim -- a
design decision, not a one-line fix.
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
    """`select_issues_rank.check_lane(..., adjacent=...)`'s own truthfulness
    check (#918/#921) refuses a caller who claims `no-adjacent` WHILE ALSO
    HANDING IT a real adjacent candidate count -- when the caller supplies
    one. See the two tests below for the gap this leaves: nothing requires
    a caller to supply one in the first place."""
    check = select_issues_rank.check_lane(range(1), "no-adjacent", adjacent=2)
    assert check["state"] != "ok"
    assert check["state"] == "adjacent-candidate-exists"


def test_1044_control_no_adjacent_is_accepted_when_truthfully_zero():
    """Positive control for the test above: the identical claim, with a real
    zero adjacent count, is accepted -- refusing every `no-adjacent` claim
    regardless of truth would be as wrong as accepting every one blindly."""
    check = select_issues_rank.check_lane(range(1), "no-adjacent", adjacent=0)
    assert check["state"] == "ok"


def test_1044_the_short_reason_escape_hatch_still_reproduces_the_bug_shape(tmp_path):
    """**Not closed** -- found by this lane's own self-review round (an
    Explore reviewer spawn), independently confirmed here. The
    truthfulness check above only fires when a caller supplies `adjacent=`.
    `oss_state.py`'s own `--lane-fill PRIMARY:COUNT:REASON[:CANDIDATES]`
    syntax makes the fourth field OPTIONAL (`_lane_fill_argument`), and
    `lane_setup.py --claim --short-reason no-adjacent` -- a real,
    documented, still-reachable path alongside `--group-state`, for a lane
    composed some other way than `select_issues.py`'s own grouping
    (`skills/manager/phases/dispatch.md`) -- never threads a measured
    candidate count through `compose_lane_fill` at all (its own rendered
    token is `PRIMARY:COUNT:REASON`, three fields, always). A caller using
    that path can still hand-compose and record a `no-adjacent` claim with
    ZERO board verification -- #1044's own bug shape, reproducible today.
    This test pins the reproduction so a future fix has a red test to turn
    green; it is not itself the fix, which needs a design decision (does
    `--short-reason no-adjacent`/`board-exhausted` require an attached
    count, or is the escape hatch removed entirely?) in `oss_state.py`, a
    file outside this lane's own claimed set -- filed, not fixed, here."""
    import oss_state

    entries = [{"primary": 1, "count": 1, "reason": "no-adjacent"}]
    result = oss_state.lane_fill(entries, window="demo")
    # This SHOULD be refused (or at minimum should force the caller to
    # measure something), the same way an unfalsifiable `board-exhausted`
    # claim already is when a count contradicts it. Today it is silently
    # accepted -- recorded exactly as if a real sweep had measured zero.
    assert result["state"] == "recorded"
    assert result["lanes"][0]["reason"] == "no-adjacent"


def test_1044_control_the_mechanical_group_state_path_cannot_reproduce_it(tmp_path):
    """Positive control for the test above: the MECHANICAL path this file's
    first two tests exercise cannot manufacture the same false claim,
    because `compose_lane_fill`'s `group_short_reason` only ever derives
    `"no-adjacent"` from a group whose own `state` genuinely is
    `select_issues_companions.STATE_NONE` -- a real, unmocked sweep result,
    never an unverified assertion. The gap is specific to the
    `--short-reason` override, not to the whole mechanism."""
    assert (
        lane_setup.group_short_reason(select_issues_companions.STATE_CANDIDATES) is None
    )
    assert (
        lane_setup.group_short_reason(select_issues_companions.STATE_NONE)
        == "no-adjacent"
    )
