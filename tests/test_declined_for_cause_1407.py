"""#1407: `SHORT_REASONS` has no slot for "a real, adjacent, well-formed
candidate was found and named, and the loop declined it anyway for a
substantive judgment reason".

Found running a sub-manager tick over claude-supertool: `select_issues.py`'s
lane-containment group offered a lead issue with two file-adjacent companions,
both correctly declined (speculative proposals depending on an unreleased,
flag-gated feature) -- but neither `board-exhausted`, `no-adjacent`,
`did-not-search` nor `could-not-tell` fits a search that ran, found something,
and rejected it on purpose. The tick had to pick the least-wrong existing
value (`could-not-tell`) and bury the real reason in free prose that never
travelled with the per-lane `--lane-fill` record.

Two halves, and the second is the positive control CLAUDE.md requires beside
any "must not fire" assertion: a refusal that never fires passes a suite by
doing nothing at all.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import select_issues_rank as dispatch_rank  # noqa: E402


def test_declined_for_cause_is_a_declarable_reason():
    """A found-and-declined candidate is a fifth state, not a weaker version
    of any of the other four."""
    assert "declined-for-cause" in dispatch_rank.SHORT_REASONS


def test_declined_for_cause_is_refused_with_no_citation():
    """The claim is checked, the way #871 checks `board-exhausted` against a
    measured count -- a bare reason word with nothing behind it is refused."""
    verdict = dispatch_rank.check_lane([845], short_reason="declined-for-cause")
    assert verdict["state"] != "ok", verdict
    assert verdict["short_reason"] is None, verdict
    assert "declined-for-cause" in (verdict["why"] or "")


def test_declined_for_cause_is_refused_with_a_bare_issue_number():
    """A citation needs more than a bare `#123` -- some reason must be named
    too, or this is indistinguishable from a caller that typed nothing."""
    verdict = dispatch_rank.check_lane(
        [845], short_reason="declined-for-cause", declined="#123"
    )
    assert verdict["state"] != "ok", verdict


def test_declined_for_cause_stands_with_a_real_citation():
    """Positive control: a real citation naming the issue(s) and the reason
    must pass, or the refusal above is satisfied by a function that refuses
    everything."""
    verdict = dispatch_rank.check_lane(
        [845],
        short_reason="declined-for-cause",
        declined="#1200, #1201 -- both depend on an unreleased, flag-gated feature",
    )
    assert verdict["state"] == "ok", verdict
    assert verdict["short_reason"] == "declined-for-cause", verdict


@pytest.mark.parametrize("reason", ["board-exhausted", "no-adjacent", "could-not-tell"])
def test_the_other_four_reasons_are_unaffected_by_the_new_one(reason):
    """Positive control for the whole change: nothing above loosens or
    touches the other reasons' own existing requirements."""
    verdict = dispatch_rank.check_lane([845], short_reason=reason)
    assert verdict["state"] == "ok", verdict
    assert verdict["short_reason"] == reason, verdict


def _import_oss_state():
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import oss_state  # noqa: E402

    return oss_state


def test_lane_fill_refuses_declined_for_cause_with_no_citation():
    """The record-time check mirrors `check_lane`'s own refusal -- a lane
    fill record must not carry a claim `check_lane` itself would refuse."""
    oss_state = _import_oss_state()

    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_fill(
            [{"primary": 845, "count": 1, "reason": "declined-for-cause"}],
            window="this tick",
        )
    assert "declined-for-cause" in str(caught.value)


def test_lane_fill_accepts_declined_for_cause_with_a_real_citation():
    """Positive control: a real citation reaches the state file and travels
    with the per-lane record, closing the gap #1407 was filed against."""
    oss_state = _import_oss_state()

    record = oss_state.lane_fill(
        [
            {
                "primary": 845,
                "count": 1,
                "reason": "declined-for-cause",
                "declined": "#1200, #1201 -- both depend on an unreleased, "
                "flag-gated feature",
            }
        ],
        window="this tick",
    )
    assert record["lanes"][0]["reason"] == "declined-for-cause"
    assert "1200" in record["lanes"][0]["declined"]


def test_lane_fill_refuses_a_citation_for_a_reason_it_does_not_answer():
    """A citation only answers `declined-for-cause`; recording one against
    another reason would be a claim that reason never makes."""
    oss_state = _import_oss_state()

    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_fill(
            [
                {
                    "primary": 845,
                    "count": 1,
                    "reason": "could-not-tell",
                    "declined": "#1200 -- unrelated",
                }
            ],
            window="this tick",
        )
    assert "takes no declined citation" in str(caught.value)


def test_lane_fill_refuses_a_citation_on_a_full_lane():
    """Positive control's mirror: a full lane makes no short-lane claim a
    citation could refute either, the same as the existing count check."""
    oss_state = _import_oss_state()

    with pytest.raises(oss_state.StateError) as caught:
        oss_state.lane_fill(
            [
                {
                    "primary": 845,
                    "count": dispatch_rank.MAX_LANE,
                    "declined": "#1200 -- unrelated",
                }
            ],
            window="this tick",
        )
    assert "makes no claim a citation could refute" in str(caught.value)


def test_cli_lane_fill_argument_parses_the_fifth_field():
    """The CLI's fifth, colon-preserving field reaches `entry['declined']`
    verbatim, including any colons inside the citation itself."""
    oss_state = _import_oss_state()

    entry = oss_state._lane_fill_argument(
        "845:1:declined-for-cause::#1200, #1201 -- see select_issues.py:1678"
    )
    assert entry["declined"] == "#1200, #1201 -- see select_issues.py:1678"
