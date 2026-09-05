"""#871: a short lane's `board-exhausted` reason is refused for its shape and
never against the board, so a lane dispatched short can claim exhaustion while
35 issues sit open and satisfy every gate. `check_lane` now takes an optional
`candidates` count -- the number of file-disjoint candidates lane_setup.py's
own resolve_lane/lane_overlap found still open -- and refuses `board-exhausted`
when it is at or above the lane cap.

Every refusal is paired with the positive control in the same fixture: a
genuinely short board (few candidates) must still be accepted, or a check that
only ever refuses would also pass a version that refuses every short lane.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import oss_state  # noqa: E402
import select_issues  # noqa: E402
import select_issues_rank as dispatch_rank  # noqa: E402

WINDOW = "lanes dispatched this tick"


# --------------------------------------------------- dispatch_rank.check_lane


def test_board_exhausted_is_accepted_on_a_genuinely_short_board():
    """Positive control: fewer than MAX_LANE candidates remain, so the claim is
    true and must not be refused."""
    answer = dispatch_rank.check_lane([1, 2], "board-exhausted", candidates=1)
    assert answer["state"] == "ok", answer
    assert answer["short_reason"] == "board-exhausted", answer


def test_board_exhausted_is_refused_against_a_full_board():
    """Negative control: three or more file-disjoint candidates remain, so
    'board-exhausted' is false and must be refused rather than recorded."""
    answer = dispatch_rank.check_lane([1, 2], "board-exhausted", candidates=3)
    assert answer["state"] != "ok", answer
    assert "3" in answer["why"], answer


def test_board_exhausted_with_no_candidate_count_is_unverified_but_not_refused():
    """No candidates given at all (the caller named no board) leaves this the
    same shape check_lane always had -- refusing here would demand a
    measurement this function was never handed."""
    answer = dispatch_rank.check_lane([1, 2], "board-exhausted", candidates=None)
    assert answer["state"] == "ok", answer


def test_no_adjacent_is_unaffected_by_candidates():
    """The candidate count only speaks to board-exhausted's own claim -- a
    different reason must not be refused by a count that has nothing to do
    with it."""
    answer = dispatch_rank.check_lane([1, 2], "no-adjacent", candidates=10)
    assert answer["state"] == "ok", answer


def test_candidates_exactly_at_the_cap_refuses():
    """MAX_LANE candidates remaining is enough to fill a full lane -- the
    board was not exhausted at the boundary either."""
    answer = dispatch_rank.check_lane(
        [1, 2], "board-exhausted", candidates=dispatch_rank.MAX_LANE
    )
    assert answer["state"] != "ok", answer


# --------------------------------------------------------------- CLI surface
#
# #1069: `dispatch_rank.py --lane` is gone -- folded into
# `select_issues.py --check-lane`, the entry point for this whole family.


def test_cli_lane_mode_accepts_candidates_flag():
    answer = select_issues.main(
        ["--check-lane", "1", "2", "--short-reason", "board-exhausted", "--candidates", "1"]
    )
    assert answer == 0


def test_cli_lane_mode_refuses_on_candidates_flag(capsys):
    answer = select_issues.main(
        ["--check-lane", "1", "2", "--short-reason", "board-exhausted", "--candidates", "5"]
    )
    assert answer != 0
    out = capsys.readouterr().out
    assert "5" in out


# ------------------------------------------------------- oss_state.lane_fill


def test_lane_fill_records_a_verified_short_reason():
    record = oss_state.lane_fill(
        [{"primary": 871, "count": 1, "reason": "board-exhausted", "candidates": 1}],
        window=WINDOW,
    )
    assert record["state"] == oss_state.LANE_FILL_RECORDED
    assert record["lanes"][0]["reason"] == "board-exhausted"


def test_lane_fill_refuses_an_unsupported_board_exhausted_claim():
    """The strongest of #871's three candidate directions: refuse at the
    state entry, where a lane record already exists to attach the refusal
    to -- unlike #866's advisory check, which had no lane record for a
    declined dispatch to attach to."""
    with pytest.raises(oss_state.StateError, match="board-exhausted"):
        oss_state.lane_fill(
            [
                {
                    "primary": 871,
                    "count": 1,
                    "reason": "board-exhausted",
                    "candidates": 4,
                }
            ],
            window=WINDOW,
        )


def test_lane_fill_cli_argument_parses_the_fourth_field():
    entry = oss_state._lane_fill_argument("871:1:board-exhausted:1")
    assert entry == {
        "primary": 871,
        "count": 1,
        "reason": "board-exhausted",
        "candidates": 1,
    }


# ------------------------------------------------------------------- #953
#
# `lane_fill` used `candidates` to validate the short-lane claim and then
# dropped it from the persisted record -- a `board-exhausted` corroborated
# against a measured 0 candidates and one where no count was ever supplied
# produced byte-identical records. `candidates` is now persisted, present
# only when a caller actually supplied one, so a corroborated claim and an
# uncorroborated one stop rendering identically.


def test_lane_fill_persists_candidates_when_given():
    """MUST-FIRE: a corroborated claim's `candidates` count survives into the
    persisted record, not just into the validation that consumed it."""
    record = oss_state.lane_fill(
        [{"primary": 953, "count": 1, "reason": "board-exhausted", "candidates": 0}],
        window=WINDOW,
    )
    assert record["lanes"][0]["candidates"] == 0


def test_lane_fill_corroborated_and_uncorroborated_records_no_longer_collide():
    """The exact reproduction from the issue: a `board-exhausted` corroborated
    against a measured 0 candidates, and one where no count was ever
    supplied, must produce different records -- both share the same
    `count`/`reason`, so only `candidates` can tell them apart."""
    corroborated = oss_state.lane_fill(
        [{"primary": 1, "count": 1, "reason": "board-exhausted", "candidates": 0}],
        window=WINDOW,
    )
    uncorroborated = oss_state.lane_fill(
        [{"primary": 1, "count": 1, "reason": "board-exhausted"}],
        window=WINDOW,
    )
    assert corroborated["lanes"][0] != uncorroborated["lanes"][0]
    assert "candidates" in corroborated["lanes"][0]
    assert "candidates" not in uncorroborated["lanes"][0]


def test_lane_fill_still_refuses_a_record_candidates_contradicts():
    """MUST-NOT-BREAK: the validation this issue explicitly says already
    works -- a claimed `board-exhausted` refuted by a candidates count that
    proves the board was not exhausted -- must keep refusing."""
    with pytest.raises(oss_state.StateError, match="board-exhausted"):
        oss_state.lane_fill(
            [
                {
                    "primary": 953,
                    "count": 1,
                    "reason": "board-exhausted",
                    "candidates": 3,
                }
            ],
            window=WINDOW,
        )
