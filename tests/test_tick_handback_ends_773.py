"""`TICK: completed` now requires a `TICK-ENDS:` line naming which of
`skills/manager/SKILL.md`'s *What ends a tick* three states applied --
`work-started`, `blocked` or `nothing-left` -- the same way `TICK: blocked`
already requires `BLOCKER:` and `TICK: could-not-run` already requires
`REASON:` (#773).

Before this, `TICK: completed` needed nothing but a free paragraph, so the
tick-ending state the scheduler's step 7 continue-or-wait decision reads
lived inside that prose or nowhere -- a field the sub-manager *may* fill
gives "had nothing to say" and "never answered" the same rendering. Every
negative assertion here ("an omitted field is refused") is paired with a
positive control in the same fixture, per this repository's own working
rule.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tick_handback.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import spawn_guard  # noqa: E402
import tick_handback  # noqa: E402


def _run(stdin_text, extra_args=()):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), *extra_args],
        subject="the verdict and exit code tick_handback.py's CLI produces for this input",
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_completed_with_no_tick_ends_line_is_could_not_classify():
    """The finding itself: a free paragraph with no TICK-ENDS: line used to
    classify as completed. It must not any more."""
    verdict = tick_handback.classify(
        "TICK: completed\nDispatched fix/701 and merged fix/699 on green."
    )
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "completed"
    assert "TICK-ENDS" in verdict["reason"]


def test_completed_with_a_tick_ends_line_is_the_positive_control():
    """Positive control for the test above: the identical message, with only
    a TICK-ENDS: line added, classifies as completed and carries the
    declared state in `ends`. Without this, the negative assertion above
    would pass even if `classify` refused every completed message."""
    verdict = tick_handback.classify(
        "TICK: completed\n"
        "TICK-ENDS: work-started\n"
        "Dispatched fix/701 and merged fix/699 on green."
    )
    assert verdict["state"] == "completed"
    assert verdict["ends"] == "work-started"


def test_each_of_the_three_tick_ending_states_is_accepted():
    for ends in ("work-started", "blocked", "nothing-left"):
        verdict = tick_handback.classify(
            "TICK: completed\nTICK-ENDS: {0}\nsome summary text".format(ends)
        )
        assert verdict["state"] == "completed", ends
        assert verdict["ends"] == ends, ends


def test_an_unrecognised_tick_ends_value_is_could_not_classify():
    """A misspelled or invented value is not a fourth, silently-accepted
    state -- it is exactly as undecidable as an absent field."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: mostly-done\nsome summary text"
    )
    assert verdict["state"] == "could-not-classify"


def test_tick_ends_is_case_insensitive_like_the_other_headers():
    verdict = tick_handback.classify(
        "TICK: completed\ntick-ends: Nothing-Left\nsome summary text"
    )
    assert verdict["state"] == "completed"
    assert verdict["ends"] == "nothing-left"


def test_the_ends_field_is_none_on_non_completed_states():
    blocked = tick_handback.classify("TICK: blocked\nBLOCKER: a thing\n")
    assert blocked["state"] == "blocked"
    assert blocked["ends"] is None


def test_a_stale_tick_ends_line_before_the_real_header_is_not_used():
    """Same shape as the existing stale-BLOCKER/REASON test: a TICK-ENDS:
    line sitting before the real TICK: completed header (e.g. quoted from
    an earlier attempt in the same message) must not be picked up as this
    header's own field."""
    message = (
        "Earlier this tick a different attempt said:\n"
        "TICK-ENDS: blocked\n"
        "TICK: completed\n"
        "TICK-ENDS: nothing-left\n"
        "the real, current summary\n"
    )
    verdict = tick_handback.classify(message)
    # Two TICK:-shaped headers are not present here (only one 'TICK:' line),
    # so this is not the #706 multi-header refusal -- it tests that the
    # correct TICK-ENDS: (the one after the real header) is the one read.
    assert verdict["state"] == "completed"
    assert verdict["ends"] == "nothing-left"


def test_cli_exit_code_completed_missing_tick_ends_is_could_not_classify():
    result = _run("TICK: completed\nall clear, nothing dispatched")
    assert result.returncode == tick_handback.EXIT_CODES["could-not-classify"], (
        result.stdout + result.stderr
    )
    assert "VERDICT: could-not-classify" in result.stdout
    assert "TICK-ENDS" in result.stdout


def test_cli_prints_the_ends_line_when_present():
    result = _run("TICK: completed\nTICK-ENDS: blocked\nwaiting on three things\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "  ends: blocked" in result.stdout
