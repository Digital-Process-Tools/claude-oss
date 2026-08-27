"""The pull-request field, broken down by what CI says about each one (#508).

`1PR` answered "how many" and nothing about which. One open pull request that is green,
one that is red and one still running are three situations, and a single number renders
them identically -- the defect class this repository is named after, in the field a
maintainer looks at most often.

Two rules the assertions below exist to hold:

**Every group renders, including the ones at zero.** A group that vanishes at zero makes
the reader subtract to find what is missing, and `0x` -- nothing red -- and `0...` --
nothing on the way -- are among the more useful things this line can say.

**A rollup that is not a pass and not a pending is unknown, never green.** GitHub's
rollup has states that are neither: a cancelled or neutral run is not a success, and
folding it into the green group is how a status line comes to report a board that is
fine. Each mapping below is paired with a must-fire control in the same shape, so an
assertion that something is not counted green cannot pass against a counter that counts
nothing at all.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


#: A pull request whose every leg has this conclusion. `_rows` builds the shape `gh pr
#: list --json statusCheckRollup` returns -- a list of legs per pull request, not a
#: precomputed rollup. The precomputed one exists (`statusCheckRollupState`) and the first
#: version of this code asked for it; `gh 2.50.0`, the version on the machine this was
#: written on, answers `Unknown JSON field` and the whole field went `?`. The legs are what
#: both versions carry, and computing the rollup here is also what makes the mapping below
#: this repository's decision rather than the forge's.
def _legs(*conclusions):
    return [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": value}
            for value in conclusions]


def _rows(*states):
    """One pull request per state named, each with a single leg carrying it."""
    rows = []
    for index, state in enumerate(states):
        rows.append({"number": index, "statusCheckRollup": _legs(state)})
    return rows


# ---------------------------------------------------------------------- counting


def test_each_conclusion_lands_in_its_own_group():
    counts = statusline.check_rollup_counts(_rows("SUCCESS", "FAILURE", "TIMED_OUT"), 3)
    assert counts == {"green": 1, "red": 2, "running": 0, "unknown": 0}


def test_a_leg_that_has_not_finished_is_running():
    rows = [{"number": 1, "statusCheckRollup": [
        {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]}]
    assert statusline.check_rollup_counts(rows, 1)["running"] == 1


def test_a_failure_outranks_a_leg_still_running():
    """A red pull request is red while the rest of the matrix finishes. The rollup this
    replaces made that call upstream; making it here is what puts it under test."""
    rows = [{"number": 1, "statusCheckRollup": [
        {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"},
        {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]}]
    assert statusline.check_rollup_counts(rows, 1) == {
        "green": 0, "red": 1, "running": 0, "unknown": 0
    }


def test_a_deliberate_non_result_is_unknown_never_green():
    """Cancelled, skipped and neutral are none of them passes and none of them pendings --
    the same rule this repository already applies when reading a pull request's checks
    before a merge. A pull request with no checks at all is the same absence."""
    for state in ("CANCELLED", "SKIPPED", "NEUTRAL", "STALE", None, ""):
        counts = statusline.check_rollup_counts(_rows(state), 1)
        assert counts["unknown"] == 1, state
        assert counts["green"] == 0, state
    empty = statusline.check_rollup_counts([{"number": 1, "statusCheckRollup": []}], 1)
    assert empty["unknown"] == 1 and empty["green"] == 0


def test_a_non_result_beside_a_pass_does_not_make_the_pull_request_green():
    rows = [{"number": 1, "statusCheckRollup": _legs("SUCCESS", "CANCELLED")}]
    assert statusline.check_rollup_counts(rows, 1)["unknown"] == 1


def test_a_commit_status_leg_is_read_the_same_way():
    """Not every leg is a CheckRun: an external service posts a StatusContext, which
    carries `state` and no `conclusion`."""
    rows = [{"number": 1, "statusCheckRollup": [
        {"__typename": "StatusContext", "state": "FAILURE"}]}]
    assert statusline.check_rollup_counts(rows, 1)["red"] == 1
    rows = [{"number": 1, "statusCheckRollup": [
        {"__typename": "StatusContext", "state": "PENDING"}]}]
    assert statusline.check_rollup_counts(rows, 1)["running"] == 1


def test_the_must_fire_control_for_that_one():
    assert statusline.check_rollup_counts(_rows("SUCCESS"), 1)["green"] == 1
    assert statusline.check_rollup_counts(
        [{"number": 1, "statusCheckRollup": [
            {"__typename": "StatusContext", "state": "SUCCESS"}]}], 1
    )["green"] == 1


def test_a_pull_request_past_the_page_lands_in_unknown_not_out_of_the_field():
    """The count comes from one API and the rollups from another with a page limit. The
    remainder is not green and it is not nothing: it is a pull request nobody read."""
    counts = statusline.check_rollup_counts(_rows("SUCCESS"), 4)
    assert counts == {"green": 1, "red": 0, "running": 0, "unknown": 3}


def test_more_rows_than_the_total_never_produce_a_negative_group():
    counts = statusline.check_rollup_counts(_rows("SUCCESS", "FAILURE"), 1)
    assert counts["unknown"] == 0
    assert min(counts.values()) >= 0


def test_an_unknown_total_counts_the_rows_it_has_and_invents_no_remainder():
    counts = statusline.check_rollup_counts(_rows("SUCCESS", "FAILURE"), None)
    assert counts == {"green": 1, "red": 1, "running": 0, "unknown": 0}


def test_rows_that_are_not_a_list_are_no_reading_at_all():
    assert statusline.check_rollup_counts(None, 3) is None
    assert statusline.check_rollup_counts("SUCCESS", 3) is None


def test_no_open_pull_requests_is_a_measurement_and_renders_as_zeros():
    assert statusline.check_rollup_counts([], 0) == {
        "green": 0, "red": 0, "running": 0, "unknown": 0
    }


# ------------------------------------------------------------------- the cache


def test_the_cache_carries_the_groups_back_and_a_cache_without_them_says_so():
    board = statusline.board_from_cache(
        {"prs": 2, "issues": 3, "fetched_at": 0,
         "pr_checks": {"green": 1, "red": 1, "running": 0, "unknown": 0}}
    )
    assert board["checks"] == {"green": 1, "red": 1, "running": 0, "unknown": 0}
    assert statusline.board_from_cache({"prs": 2, "issues": 3, "fetched_at": 0})["checks"] is None


def test_a_cache_whose_groups_are_not_whole_numbers_is_not_a_reading():
    board = statusline.board_from_cache(
        {"prs": 2, "issues": 3, "fetched_at": 0, "pr_checks": {"green": "1"}}
    )
    assert board["checks"] is None


# --------------------------------------------------------------------- rendering


def _symbols(ascii_only=True):
    return statusline._symbols(ascii_only)


def test_the_labels_are_lowercase():
    field = statusline._board_field(
        {"prs": 4, "issues": 23,
         "checks": {"green": 2, "red": 1, "running": 1, "unknown": 0}},
        _symbols(),
    )
    assert "pr" in field and "is" in field
    assert "PR" not in field and "IS" not in field


def test_every_group_renders_including_the_ones_at_zero():
    field = statusline._board_field(
        {"prs": 4, "issues": 23,
         "checks": {"green": 2, "red": 1, "running": 1, "unknown": 0}},
        _symbols(),
    )
    assert field == "4pr 2ok 1x 1... 0? . 23is / ?eis"


def test_the_glyphs_are_used_where_the_console_encodes_them():
    field = statusline._board_field(
        {"prs": 4, "issues": 23,
         "checks": {"green": 2, "red": 1, "running": 1, "unknown": 0}},
        _symbols(ascii_only=False),
    )
    assert field == "4pr 2✓ 1✗ 1⋯ 0? · 23is / ?eis"


def test_rollups_nobody_read_render_as_one_unknown_not_as_four_zeros():
    field = statusline._board_field({"prs": 4, "issues": 23, "checks": None}, _symbols())
    assert field == "4pr ? . 23is / ?eis"
    assert "0ok" not in field


def test_a_count_nobody_took_is_unknown_on_the_count_itself():
    field = statusline._board_field({"prs": None, "issues": None, "checks": None}, _symbols())
    assert field == "?pr ? . ?is / ?eis"


def test_the_whole_line_carries_the_groups():
    facts = {
        "model": "Opus",
        "percent": 10,
        "repo_name": "oss",
        "branch": "main",
        "board": {"prs": 4, "issues": 23,
                  "checks": {"green": 2, "red": 1, "running": 1, "unknown": 0}},
        "release": {"state": "measured", "since": 4, "typical": 17},
    }
    assert "4pr 2ok 1x 1... 0?" in statusline.render(facts, ascii_only=True)
