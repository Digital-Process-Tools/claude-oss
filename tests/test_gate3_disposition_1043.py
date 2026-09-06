"""Gate 3's own disposition, computed rather than judged from prose -- #1043.

`skills/manager/phases/release.md` and `commands/release.md` both say a
round-one `findings` verdict stops the tag, full stop -- the round-two
carry-forward rule (a non-blocking finding may ship) applies only to round
two. Observed on `Digital-Process-Tools/claude-jit-context` v0.8.0: a
releaser tagged and published over a round-one `findings` verdict on the
grounds that "no blocking finding, so nothing was on the release's critical
path" -- which is round two's own disposition rule, applied one round
early. The prose already said the right thing and was still misread, so
this makes the decision a function instead of a paragraph a releaser has
to re-derive under narrative pressure while it also wants to finish.

Every negative assertion here (a case that must not proceed) carries its
positive control (the neighbouring case that must) in the same fixture.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "gate3_disposition.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import spawn_guard  # noqa: E402
import gate3_disposition  # noqa: E402


def test_round_one_findings_with_no_blocking_row_still_stops_the_tag():
    """This is the exact incident: round one, findings, nothing blocking."""
    verdict = gate3_disposition.decide(
        round_number=1, verdict="findings", has_blocking=False
    )
    assert verdict["disposition"] == "stop-tag"


def test_round_one_findings_with_a_blocking_row_stops_the_tag():
    verdict = gate3_disposition.decide(
        round_number=1, verdict="findings", has_blocking=True
    )
    assert verdict["disposition"] == "stop-tag"


def test_positive_control_round_one_clean_proceeds():
    """Positive control: a genuinely clean round one must still let the tag
    proceed, so the fix above is not simply refusing every round one."""
    verdict = gate3_disposition.decide(
        round_number=1, verdict="clean", has_blocking=False
    )
    assert verdict["disposition"] == "proceed"


def test_round_two_findings_with_no_blocking_row_may_carry_forward():
    verdict = gate3_disposition.decide(
        round_number=2, verdict="findings", has_blocking=False
    )
    assert verdict["disposition"] == "carry-forward-and-proceed"


def test_round_two_findings_with_a_blocking_row_stops_the_tag():
    """Negative-with-control pair with the test above: round two does NOT
    always proceed -- a blocking row stops it in either round."""
    verdict = gate3_disposition.decide(
        round_number=2, verdict="findings", has_blocking=True
    )
    assert verdict["disposition"] == "stop-tag"


def test_round_two_clean_proceeds():
    verdict = gate3_disposition.decide(
        round_number=2, verdict="clean", has_blocking=False
    )
    assert verdict["disposition"] == "proceed"


def test_could_not_run_stops_the_tag_regardless_of_round():
    for round_number in (1, 2):
        verdict = gate3_disposition.decide(
            round_number=round_number, verdict="could-not-run", has_blocking=False
        )
        assert verdict["disposition"] == "stop-tag"


def test_unrecognised_verdict_is_could_not_decide_not_a_silent_proceed():
    verdict = gate3_disposition.decide(
        round_number=1, verdict="mostly clean", has_blocking=False
    )
    assert verdict["disposition"] == "could-not-decide"
    assert verdict["disposition"] != "proceed"


def test_unrecognised_round_is_could_not_decide():
    verdict = gate3_disposition.decide(
        round_number=3, verdict="clean", has_blocking=False
    )
    assert verdict["disposition"] == "could-not-decide"


def test_round_one_and_round_two_findings_do_not_render_identically_when_unblocked():
    """The whole bug in one assertion: identical verdict and blocking state,
    different round, must give different dispositions."""
    round_one = gate3_disposition.decide(
        round_number=1, verdict="findings", has_blocking=False
    )
    round_two = gate3_disposition.decide(
        round_number=2, verdict="findings", has_blocking=False
    )
    assert round_one["disposition"] != round_two["disposition"]


def _run(args):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), *args],
        subject="gate3_disposition.py's CLI verdict and exit code",
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_reports_stop_tag_for_the_incident_shape():
    result = _run(["--round", "1", "--verdict", "findings", "--blocking", "no"])
    assert "stop-tag" in result.stdout
    assert result.returncode == gate3_disposition.EXIT_STOP_TAG


def test_cli_reports_proceed_for_clean():
    result = _run(["--round", "1", "--verdict", "clean", "--blocking", "no"])
    assert "proceed" in result.stdout
    assert result.returncode == gate3_disposition.EXIT_PROCEED


def test_cli_exit_codes_are_distinct():
    stop_tag = _run(["--round", "1", "--verdict", "findings", "--blocking", "no"])
    proceed = _run(["--round", "1", "--verdict", "clean", "--blocking", "no"])
    carry = _run(["--round", "2", "--verdict", "findings", "--blocking", "no"])
    could_not_decide = _run(
        ["--round", "1", "--verdict", "mystery", "--blocking", "no"]
    )
    codes = {
        stop_tag.returncode,
        proceed.returncode,
        carry.returncode,
        could_not_decide.returncode,
    }
    assert len(codes) == 4, (
        stop_tag.returncode,
        proceed.returncode,
        carry.returncode,
        could_not_decide.returncode,
    )
