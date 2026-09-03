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
