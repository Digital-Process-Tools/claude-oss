"""#918: `no-adjacent` cannot distinguish a companion search that ran and found
nothing from one that never ran, and nothing checks the claim against the board.

One tick dispatched three single-issue lanes with 31 issues open, each declaring
`no-adjacent`, having only run `lane_setup.py --against` between the three lanes
it had already picked -- the conflict check, not the companion search. Every gate
passed, because `check_lane` verifies the reason's shape, and #871's truth check
was deliberately scoped to `board-exhausted` alone (`dispatch_rank.py`: "``no-
adjacent`` and ``could-not-tell`` are untouched").

Two halves, and the second is the positive control CLAUDE.md requires beside any
"must not fire" assertion: a refusal that never fires passes a suite by doing
nothing at all.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import dispatch_rank  # noqa: E402


def test_did_not_search_is_a_declarable_reason():
    """A search that never ran is a fourth state, not one of the three.

    `no-adjacent` asserts the board was measured and found to have nothing
    adjacent. `could-not-tell` is documented as "adjacency could not be
    computed" -- a computation that was attempted and failed. Neither covers a
    computation nobody started, which is what actually happened, so the tick
    that skipped the search picked the word that reads as having done it.
    """
    assert "did-not-search" in dispatch_rank.SHORT_REASONS


def test_no_adjacent_is_refused_when_an_adjacent_candidate_exists():
    """The claim checked against the board, the way #871 checked the other one.

    `no-adjacent` means zero adjacent candidates, so a single one refutes it --
    a stricter threshold than `board-exhausted`'s `>= MAX_LANE`, and stricter on
    purpose: one adjacent candidate is one issue this lane could have carried.
    """
    verdict = dispatch_rank.check_lane([845], short_reason="no-adjacent", adjacent=1)
    assert verdict["state"] != "ok", verdict
    assert verdict["short_reason"] is None, verdict
    assert "no-adjacent" in (verdict["why"] or "")


def test_no_adjacent_stands_when_the_board_really_has_nothing():
    """Positive control for the refusal above.

    A board measured and found genuinely isolated is the case `no-adjacent`
    exists for, and it must still pass -- otherwise the assertion above is
    satisfied by a function that refuses everything.
    """
    verdict = dispatch_rank.check_lane([845], short_reason="no-adjacent", adjacent=0)
    assert verdict["state"] == "ok", verdict
    assert verdict["short_reason"] == "no-adjacent", verdict


def test_omitting_the_count_leaves_the_old_behaviour_untouched():
    """`adjacent=None` is "the caller named no board", not "the board was empty".

    Same contract #871 gave `candidates`: a caller that did not measure must not
    be silently credited with a measurement, and must not be refused for one it
    never claimed to have.
    """
    verdict = dispatch_rank.check_lane([845], short_reason="no-adjacent")
    assert verdict["state"] == "ok", verdict


@pytest.mark.parametrize("reason", ["board-exhausted", "could-not-tell"])
def test_the_adjacent_count_does_not_leak_into_the_other_reasons(reason):
    """An adjacency count says nothing about board exhaustion or a failed probe.

    The mirror of the sentence `dispatch_rank.py` already carries for
    `candidates`, asserted rather than trusted -- the two counts answer
    different questions and a shared refusal path would conflate them.
    """
    verdict = dispatch_rank.check_lane([845], short_reason=reason, adjacent=3)
    assert verdict["state"] == "ok", verdict
    assert verdict["short_reason"] == reason, verdict


def _state_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[]")
    return path


def test_lane_fill_routes_the_count_to_the_claim_the_word_makes(tmp_path):
    """The fourth `--lane-fill` field means "the count that refutes this claim".

    Which count that is follows from the reason word, so #918 routes rather than
    adding a fifth positional: `no-adjacent:1` must be refused for the adjacency
    reason, not silently checked against `board-exhausted`'s `>= MAX_LANE`
    threshold, which one adjacent candidate would pass.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import oss_state  # noqa: E402

    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_fill(
            [{"primary": 845, "count": 1, "reason": "no-adjacent", "candidates": 1}],
            window="this tick",
        )
    assert "no-adjacent was claimed" in str(caught.value)


def test_lane_fill_still_routes_board_exhausted_to_its_own_threshold(tmp_path):
    """Positive control: the other reason keeps #871's `>= MAX_LANE` threshold.

    One disjoint candidate does not refute `board-exhausted` -- a lane needs
    MAX_LANE of them to be fillable -- so the same `1` that refuses above must
    pass here, or the routing has collapsed the two counts into one rule.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import oss_state  # noqa: E402

    record = oss_state.lane_fill(
        [{"primary": 845, "count": 1, "reason": "board-exhausted", "candidates": 1}],
        window="this tick",
    )
    assert record["lanes"][0]["reason"] == "board-exhausted"


def test_lane_fill_accepts_the_new_reason_word(tmp_path):
    """`did-not-search` reaches the state file, since SHORT_REASONS is shared."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import oss_state  # noqa: E402

    record = oss_state.lane_fill(
        [{"primary": 845, "count": 1, "reason": "did-not-search"}],
        window="this tick",
    )
    assert record["lanes"][0]["reason"] == "did-not-search"


@pytest.mark.parametrize("reason", ["did-not-search", "could-not-tell"])
def test_a_count_is_refused_for_a_reason_no_count_can_refute(reason):
    """Found by review on PR #921: the count was silently dropped, not refused.

    `check_lane` reads `candidates` only for `board-exhausted` and `adjacent`
    only for `no-adjacent`, so a count supplied alongside either of these two
    reached neither parameter and vanished -- the receipt was byte-identical to
    one written by a caller who supplied nothing. A discarded measurement
    rendering as a measurement nobody took is the defect #918 is about, arriving
    in #918's own fix.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import oss_state  # noqa: E402

    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_fill(
            [{"primary": 845, "count": 1, "reason": reason, "candidates": 5}],
            window="this tick",
        )
    assert "takes no count" in str(caught.value)


@pytest.mark.parametrize("reason", ["did-not-search", "could-not-tell"])
def test_those_reasons_still_stand_when_no_count_is_offered(reason):
    """Positive control: refusing the count must not refuse the reason."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import oss_state  # noqa: E402

    record = oss_state.lane_fill(
        [{"primary": 845, "count": 1, "reason": reason}], window="this tick"
    )
    assert record["lanes"][0]["reason"] == reason


def test_a_count_on_a_full_lane_is_refused_rather_than_dropped():
    """Found by review on PR #921's own fix commit -- the same class again.

    `check_lane` returns "ok" for `size == MAX_LANE` before it looks at
    `short_reason` or either count, so a count supplied on a full lane reached
    neither parameter. `lane_fill` had refused a stray *reason* on a full lane
    since #852 and had no twin for the count, which meant the record came back
    byte-identical to one from a caller who measured nothing -- the defect #918
    is about, surviving two rounds of its own fix.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import dispatch_rank  # noqa: E402
    import oss_state  # noqa: E402

    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_fill(
            [{"primary": 845, "count": dispatch_rank.MAX_LANE, "candidates": 5}],
            window="this tick",
        )
    assert "makes no claim a count could refute" in str(caught.value)


def test_a_full_lane_with_no_count_is_still_recorded():
    """Positive control: refusing the stray count must not refuse the lane."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import dispatch_rank  # noqa: E402
    import oss_state  # noqa: E402

    record = oss_state.lane_fill(
        [{"primary": 845, "count": dispatch_rank.MAX_LANE}], window="this tick"
    )
    assert record["lanes"][0] == {
        "primary": 845,
        "count": dispatch_rank.MAX_LANE,
        "reason": None,
    }
