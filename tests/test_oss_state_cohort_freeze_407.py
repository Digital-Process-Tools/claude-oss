"""A cohort freeze count taken from more than one route (#407).

Freezing a cohort re-counts it right after the label writes that made it. GitHub's
label filter is an index and it lags the writes that feed it, so a filtered query
taken at write+0s can read low while every issue already carries the label -- and a
freeze is the one measurement where being wrong is permanent, because a cohort can
only shrink and no later count corrects it.

The manager skill's own rule bounds *ordering* ("re-count after the last label
write"), never *settling*. `oss_state.cohort_freeze` is the settling half: it takes
more than one route's count and refuses to pick a number when they disagree, because
a lower count is not evidence of a smaller cohort, it is evidence of a stale index.

Every "must report unknown" case below is paired with a "must still answer a number"
case in the same fixture -- an `unknown` that also fires when the routes agree would
not be a fix, it would be a metric that never freezes on anything.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


COHORT = "cohort-6"


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# ------------------------------------------------------------- the control: agreement


def test_two_agreeing_routes_measure_the_count():
    record = oss_state.cohort_freeze(
        COHORT, {"filtered_query": 22, "per_issue_read": 22}
    )
    assert record["state"] == oss_state.COHORT_MEASURED
    assert record["count"] == 22
    assert record["cohort"] == COHORT
    assert record["why"] is None


def test_three_agreeing_routes_still_measure_the_count():
    record = oss_state.cohort_freeze(
        COHORT,
        {"filtered_query": 22, "search_total_count": 22, "per_issue_read": 22},
    )
    assert record["state"] == oss_state.COHORT_MEASURED
    assert record["count"] == 22


# ---------------------------------------------------------- the finding: disagreement


def test_two_disagreeing_routes_report_unknown_not_either_number():
    """The #407 fixture itself: a filtered query reading 19 against a per-issue 22."""
    record = oss_state.cohort_freeze(
        COHORT, {"filtered_query": 19, "per_issue_read": 22}
    )
    assert record["state"] == oss_state.COHORT_UNKNOWN
    assert record["count"] is None
    # Neither number is silently kept as "the" count anywhere on the record.
    assert 19 not in (record.get("count"),)
    assert 22 not in (record.get("count"),)
    assert record["why"] is not None


def test_unknown_never_defaults_to_the_lower_route():
    """A caller reaching for `count or 0` -- or the min of the routes -- must not find
    a number here at all; the routes are only visible under `counts`, not `count`.
    """
    record = oss_state.cohort_freeze(
        COHORT, {"filtered_query": 19, "per_issue_read": 22}
    )
    assert record["count"] is None
    assert record["counts"] == {"filtered_query": 19, "per_issue_read": 22}


def test_three_routes_two_of_which_disagree_is_still_unknown():
    record = oss_state.cohort_freeze(
        COHORT,
        {"filtered_query": 19, "search_total_count": 22, "per_issue_read": 22},
    )
    assert record["state"] == oss_state.COHORT_UNKNOWN
    assert record["count"] is None


# ------------------------------------------------------- a single route is not enough


def test_a_single_counted_route_refuses_to_freeze_on_it_alone():
    record = oss_state.cohort_freeze(
        COHORT,
        {"filtered_query": 19, "search_total_count": None},
        why="only one route answered before the tick moved on",
    )
    assert record["state"] == oss_state.COHORT_COULD_NOT_COUNT
    assert record["count"] is None


def test_a_single_route_without_a_why_raises():
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze(COHORT, {"filtered_query": 19})


def test_no_routes_counted_at_all_also_needs_a_why():
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze(COHORT, {"filtered_query": None, "per_issue_read": None})


# ------------------------------------------------------------------------- refusals


def test_cohort_name_is_required():
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze("", {"filtered_query": 22, "per_issue_read": 22})


def test_counts_must_be_a_non_empty_mapping():
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze(COHORT, {})
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze(COHORT, None)


def test_a_negative_count_is_refused():
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze(COHORT, {"filtered_query": -1, "per_issue_read": 22})


def test_a_non_integer_count_is_refused():
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze(COHORT, {"filtered_query": True, "per_issue_read": 22})
    with pytest.raises(oss_state.StateError):
        oss_state.cohort_freeze(COHORT, {"filtered_query": "22", "per_issue_read": 22})


# --------------------------------------------------------------------------- renderer


def test_cohort_freeze_line_renders_each_state_distinctly():
    measured = oss_state.cohort_freeze(COHORT, {"a": 22, "b": 22})
    unknown = oss_state.cohort_freeze(COHORT, {"a": 19, "b": 22})
    could_not = oss_state.cohort_freeze(COHORT, {"a": 19}, why="only one route answered")

    measured_line = oss_state.cohort_freeze_line(measured)
    unknown_line = oss_state.cohort_freeze_line(unknown)
    could_not_line = oss_state.cohort_freeze_line(could_not)

    assert "22" in measured_line
    assert "unknown" in unknown_line.lower()
    assert "19" not in unknown_line.split("(")[0]  # the headline never states a number
    assert "could not count" in could_not_line.lower() or "could-not-count" in could_not_line.lower()
    # The three renders must be distinguishable from one another.
    assert len({measured_line, unknown_line, could_not_line}) == 3


# --------------------------------------------------------------------------------- CLI


def test_cli_records_a_measured_cohort_freeze(tmp_path):
    state_file = tmp_path / "state.json"
    result = _piped(
        [
            str(state_file),
            "--decision",
            "froze cohort-6 at 22",
            "--at",
            "2026-08-22T00:00:00Z",
            "--cohort",
            COHORT,
            "--cohort-count",
            "filtered_query=22",
            "--cohort-count",
            "per_issue_read=22",
        ]
    )
    assert result.returncode == 0, result.stdout
    assert "RECORDED" in result.stdout
    entries = oss_state.read(str(state_file))
    assert entries[-1]["detail"]["cohort_freeze"]["state"] == oss_state.COHORT_MEASURED
    assert entries[-1]["detail"]["cohort_freeze"]["count"] == 22


def test_cli_disagreeing_routes_records_unknown_not_a_number(tmp_path):
    state_file = tmp_path / "state.json"
    result = _piped(
        [
            str(state_file),
            "--decision",
            "froze cohort-6, routes disagreed",
            "--at",
            "2026-08-22T00:00:00Z",
            "--cohort",
            COHORT,
            "--cohort-count",
            "filtered_query=19",
            "--cohort-count",
            "per_issue_read=22",
        ]
    )
    assert result.returncode == 0, result.stdout
    entries = oss_state.read(str(state_file))
    record = entries[-1]["detail"]["cohort_freeze"]
    assert record["state"] == oss_state.COHORT_UNKNOWN
    assert record["count"] is None
