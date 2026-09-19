"""Gate 2's own disposition, not re-argued from the same facts every run -- #1681.

Two `oss:releaser` runs on `claude-supertool`, four hours apart, read the
identical open pull request (green, `Review decision: none`, declined by
`oss:tick-merge` for feature scope, untouched for hours) as opposite gate-2
verdicts, with nothing about the PR itself having changed. This pins the
disposition to a function instead: three states -- `clear` / `blocked-by:N` /
`could-not-tell` -- the same shape `gate3_disposition.py` already gives
gate 3.

Every negative assertion here (a case that must not clear) carries its
positive control (the neighbouring case that must) in the same fixture.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "release_gate2.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import spawn_guard  # noqa: E402
import release_gate2  # noqa: E402


def _pr(number, review_decision=None, lane_active=False, age=None):
    return {
        "number": number,
        "review_decision": review_decision,
        "lane_active": lane_active,
        "latest_review_comment_age_minutes": age,
    }


def test_incident_shape_is_clear_not_could_not_tell():
    """The exact incident: NONE decision, no active lane, no recent comment.
    This must clear -- the first run's reading, not the second's -- and must
    do so the same way every time, not depending on how the run narrates
    it."""
    verdict = release_gate2.decide(
        [_pr(2635, review_decision=None, lane_active=False, age=None)]
    )
    assert verdict["disposition"] == "clear"


def test_same_facts_give_the_same_verdict_every_call():
    """Direct regression for the incident: calling decide() twice on the
    identical input must never disagree with itself."""
    prs = [_pr(2635, review_decision=None, lane_active=False, age=None)]
    first = release_gate2.decide(prs)
    second = release_gate2.decide(prs)
    assert first["disposition"] == second["disposition"] == "clear"


def test_tick_merge_decline_for_scope_does_not_change_the_verdict():
    """A PR tick-merge already declined for feature scope reads the same as
    any other untouched backlog PR -- nothing here needs to know why it is
    backlog."""
    declined = release_gate2.decide(
        [_pr(2635, review_decision=None, lane_active=False, age=None)]
    )
    ordinary_backlog = release_gate2.decide(
        [_pr(9999, review_decision=None, lane_active=False, age=None)]
    )
    assert declined["disposition"] == ordinary_backlog["disposition"] == "clear"


def test_changes_requested_blocks():
    verdict = release_gate2.decide([_pr(1, review_decision="CHANGES_REQUESTED")])
    assert verdict["disposition"] == "blocked-by:1"


def test_review_required_blocks():
    verdict = release_gate2.decide([_pr(1, review_decision="REVIEW_REQUIRED")])
    assert verdict["disposition"] == "blocked-by:1"


def test_approved_clears_positive_control_against_changes_requested():
    verdict = release_gate2.decide([_pr(1, review_decision="APPROVED")])
    assert verdict["disposition"] == "clear"


def test_active_lane_blocks_even_with_no_formal_decision():
    verdict = release_gate2.decide(
        [_pr(1, review_decision=None, lane_active=True, age=None)]
    )
    assert verdict["disposition"] == "blocked-by:1"


def test_positive_control_idle_lane_with_no_decision_clears():
    verdict = release_gate2.decide(
        [_pr(1, review_decision=None, lane_active=False, age=None)]
    )
    assert verdict["disposition"] == "clear"


def test_recent_comment_inside_window_blocks():
    verdict = release_gate2.decide(
        [_pr(1, review_decision=None, lane_active=False, age=5)],
        threshold_minutes=30,
    )
    assert verdict["disposition"] == "blocked-by:1"


def test_positive_control_stale_comment_outside_window_clears():
    verdict = release_gate2.decide(
        [_pr(1, review_decision=None, lane_active=False, age=60)],
        threshold_minutes=30,
    )
    assert verdict["disposition"] == "clear"


def test_unknown_lane_active_is_could_not_tell_never_clear():
    """#1681's own repeat of the defect class this repo is named after: an
    unperformed read must never render as a clean read."""
    verdict = release_gate2.decide(
        [_pr(1, review_decision=None, lane_active="unknown", age=None)]
    )
    assert verdict["disposition"] == "could-not-tell"


def test_unknown_comment_age_is_could_not_tell_never_clear():
    verdict = release_gate2.decide(
        [_pr(1, review_decision=None, lane_active=False, age="unknown")]
    )
    assert verdict["disposition"] == "could-not-tell"


def test_unrecognised_review_decision_is_could_not_tell():
    verdict = release_gate2.decide([_pr(1, review_decision="MYSTERY")])
    assert verdict["disposition"] == "could-not-tell"


def test_in_flight_outranks_could_not_tell():
    """A blocking PR must still block even when another open PR in the same
    batch could not be read."""
    verdict = release_gate2.decide(
        [
            _pr(1, review_decision="CHANGES_REQUESTED"),
            _pr(2, review_decision=None, lane_active="unknown", age=None),
        ]
    )
    assert verdict["disposition"] == "blocked-by:1"


def test_empty_pr_list_is_clear():
    verdict = release_gate2.decide([])
    assert verdict["disposition"] == "clear"


def _run(args):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), *args],
        subject="release_gate2.py's CLI verdict and exit code",
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_reports_clear_for_the_incident_shape(tmp_path):
    prs_file = tmp_path / "prs.json"
    prs_file.write_text(
        '[{"number": 2635, "review_decision": null, "lane_active": false, '
        '"latest_review_comment_age_minutes": null}]'
    )
    result = _run(["--prs-json", str(prs_file)])
    assert "clear" in result.stdout
    assert result.returncode == release_gate2.EXIT_CLEAR


def test_cli_reports_blocked_by_and_a_distinct_exit_code(tmp_path):
    prs_file = tmp_path / "prs.json"
    prs_file.write_text('[{"number": 7, "review_decision": "CHANGES_REQUESTED"}]')
    result = _run(["--prs-json", str(prs_file)])
    assert "blocked-by:7" in result.stdout
    assert result.returncode == release_gate2.EXIT_BLOCKED


def test_cli_reports_could_not_tell_and_a_distinct_exit_code(tmp_path):
    prs_file = tmp_path / "prs.json"
    prs_file.write_text(
        '[{"number": 7, "review_decision": null, "lane_active": "unknown"}]'
    )
    result = _run(["--prs-json", str(prs_file)])
    assert "could-not-tell" in result.stdout
    assert result.returncode == release_gate2.EXIT_COULD_NOT_TELL


def test_cli_exit_codes_are_distinct():
    clear = release_gate2._exit_code("clear")
    blocked = release_gate2._exit_code("blocked-by:1")
    could_not_tell = release_gate2._exit_code("could-not-tell")
    assert len({clear, blocked, could_not_tell}) == 3
