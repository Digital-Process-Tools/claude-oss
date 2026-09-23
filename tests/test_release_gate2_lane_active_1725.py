"""Gate 2's `lane_active` input, derived rather than read off git-worktrees'
composite `occupied` bit directly -- #1725.

Observed on claude-supertool: the releaser refused at gate 2 with
`blocked-by:N`, reading "review_decision is NONE but a lane process is alive
in this PR's own worktree" for a PR whose worktree held no lane at all -- it
was the `doctor/statusline` branch the scheduler's own doctor repair had just
committed and pushed. `git-worktrees`' own `occupied` verdict ORs together an
index-lock, an in-progress rebase/merge/cherry-pick, a `git worktree lock`, a
write newer than its own activity window, and a process cwd'd inside the
tree, and reports only the composite -- never which probe tripped. For a
`doctor/*` or `curate/*` branch (single-spawn, commit-and-die procedures with
no ongoing multi-turn lane) the write their own commit makes is the only
thing that will ever trip that composite, and it is indistinguishable from a
lane still producing work.

Every negative assertion here (a case that must read as not-active) carries
its positive control (the neighbouring case that must still read as active)
in the same fixture, per this repo's own convention.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import release_gate2  # noqa: E402


def test_doctor_branch_occupied_reads_as_not_active():
    assert release_gate2.derive_lane_active("doctor/statusline", True) is False


def test_curate_branch_occupied_reads_as_not_active():
    assert release_gate2.derive_lane_active("curate/20260101T000000Z", True) is False


def test_positive_control_ordinary_lane_branch_occupied_stays_active():
    """The same `occupied: True` reading, for a branch that is not
    loop-authored, must still read as an active lane -- this fix narrows the
    rule to two named prefixes, it does not disable the signal everywhere."""
    assert release_gate2.derive_lane_active("fix/1725", True) is True


def test_doctor_branch_not_occupied_stays_not_active():
    assert release_gate2.derive_lane_active("doctor/statusline", False) is False


def test_unknown_occupied_passes_through_unchanged_for_a_loop_branch():
    """A reading that was never established must not be overwritten either
    way by the branch-name rule."""
    assert (
        release_gate2.derive_lane_active("doctor/statusline", release_gate2.UNKNOWN)
        == release_gate2.UNKNOWN
    )


def test_none_occupied_passes_through_unchanged_for_a_loop_branch():
    assert release_gate2.derive_lane_active("doctor/statusline", None) is None


def test_is_loop_authored_branch_matches_doctor_and_curate_prefixes():
    assert release_gate2.is_loop_authored_branch("doctor/statusline") is True
    assert release_gate2.is_loop_authored_branch("curate/20260101T000000Z") is True


def test_is_loop_authored_branch_does_not_match_a_prefix_lookalike():
    """`doctorish/x` starts with the four letters `doct` but is not the
    `doctor/` prefix -- a substring match here would be the wrong kind of
    permissive."""
    assert release_gate2.is_loop_authored_branch("doctorish/x") is False
    assert release_gate2.is_loop_authored_branch("fix/doctor-thing") is False


def test_is_loop_authored_branch_handles_none_and_empty():
    assert release_gate2.is_loop_authored_branch(None) is False
    assert release_gate2.is_loop_authored_branch("") is False


# The auditor spawned for this issue's own self-review found the correction
# above was reachable only through a separate, hand-run snippet a release run
# could skip -- so decide()/`_decide_one` now apply derive_lane_active()
# themselves whenever a per-PR `branch` key is present. These tests exercise
# that wiring end to end, through decide(), rather than the bare function.


def test_decide_clears_a_doctor_branch_gate2_used_to_block():
    """The exact incident shape: a doctor/* branch, occupied (lane_active
    True as git-worktrees would report it), no formal review decision. Must
    clear now that `branch` is supplied."""
    verdict = release_gate2.decide(
        [
            {
                "number": 2659,
                "branch": "doctor/statusline",
                "review_decision": None,
                "lane_active": True,
                "latest_review_comment_age_minutes": None,
            }
        ]
    )
    assert verdict["disposition"] == "clear"


def test_decide_positive_control_ordinary_branch_still_blocks():
    """The identical facts, for a branch that is not loop-authored, must
    still block -- the wiring narrows two prefixes, it does not disable the
    signal for everyone."""
    verdict = release_gate2.decide(
        [
            {
                "number": 1725,
                "branch": "fix/1725",
                "review_decision": None,
                "lane_active": True,
                "latest_review_comment_age_minutes": None,
            }
        ]
    )
    assert verdict["disposition"] == "blocked-by:1725"


def test_decide_without_a_branch_key_preserves_pre_1725_behaviour():
    """Omitting `branch` entirely (the pre-#1725 payload shape) must behave
    exactly as it did before this fix -- lane_active trusted as given."""
    verdict = release_gate2.decide(
        [
            {
                "number": 2659,
                "review_decision": None,
                "lane_active": True,
                "latest_review_comment_age_minutes": None,
            }
        ]
    )
    assert verdict["disposition"] == "blocked-by:2659"
