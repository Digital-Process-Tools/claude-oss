"""Classify a sub-manager's tick handback -- #695.

The scheduler/sub-manager split (#695) needs the same shape #392 already gave
this repository for a reviewer's final message: a sub-manager that died with
no output and one that ran a whole tick and found nothing to do must not
render identically to the scheduler that spawned it, or the loop silently
stops working while reporting a clean board.

`scripts/tick_handback.py` is that classifier, built by reusing
`scripts/review_return.py`'s transport (`--framed`, `unframe`,
`fold_to_one_ascii_line`) rather than duplicating it, because the injection
risk at that boundary (#404) is identical: the handback is untrusted text
arriving through a shell heredoc, whichever agent wrote it.

Three states a sub-manager may declare on purpose (`TICK: completed`,
`TICK: blocked` + `BLOCKER:`, `TICK: could-not-run` + `REASON:`), plus the two
states this tool computes without being told: `returned-nothing` (the spawn
executed and said nothing -- the "died" case) and `could-not-classify` (a
header with a missing companion field, or no header at all -- read it
yourself rather than guess).

Every negative assertion here ("must not render as completed") carries a
positive control in the same fixture, per this repo's own working rule.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tick_handback.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import spawn_guard  # noqa: E402
import tick_handback  # noqa: E402


def test_a_dead_sub_manager_is_returned_nothing():
    verdict = tick_handback.classify("")
    assert verdict["state"] == "returned-nothing"


def test_none_message_is_also_returned_nothing():
    verdict = tick_handback.classify(None)
    assert verdict["state"] == "returned-nothing"


def test_whitespace_only_message_is_returned_nothing():
    verdict = tick_handback.classify("   \n\t  \n")
    assert verdict["state"] == "returned-nothing"


def test_an_idle_but_completed_tick_is_not_returned_nothing():
    verdict = tick_handback.classify(
        "TICK: completed\n"
        "TICK-ENDS: nothing-left\n"
        "Read the board. Nothing was ready to dispatch this tick; no lane "
        "was opened."
    )
    assert verdict["state"] == "completed"
    assert verdict["state"] != "returned-nothing"


def test_died_and_idle_do_not_render_identically():
    died = tick_handback.classify("")
    idle = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: nothing-left\nnothing to dispatch"
    )
    assert died["state"] != idle["state"]


def test_completed_with_summary():
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: work-started\n"
        "Dispatched fix/701 and fix/702, merged fix/699 on green."
    )
    assert verdict["state"] == "completed"
    assert verdict["declared"] == "completed"
    assert verdict["ends"] == "work-started"


def test_blocked_names_the_blocker():
    verdict = tick_handback.classify(
        "TICK: blocked\n"
        "BLOCKER: a git push was denied by a permission prompt with nobody "
        "at the keyboard to answer it\n"
    )
    assert verdict["state"] == "blocked"
    assert "permission prompt" in verdict["detail"]


def test_blocked_with_no_blocker_line_is_could_not_classify():
    verdict = tick_handback.classify("TICK: blocked\nsomething went wrong")
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "blocked"


def test_could_not_run_names_the_reason():
    verdict = tick_handback.classify(
        "TICK: could-not-run\n"
        "REASON: the developer spawn was denied at the worktree add step\n"
    )
    assert verdict["state"] == "could-not-run"
    assert "worktree add" in verdict["detail"]


def test_could_not_run_with_no_reason_line_is_could_not_classify():
    verdict = tick_handback.classify("TICK: could-not-run\nit broke")
    assert verdict["state"] == "could-not-classify"


def test_no_header_at_all_is_could_not_classify_not_a_guess():
    verdict = tick_handback.classify(
        "I looked at the board and dispatched two lanes, everything is fine."
    )
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "completed"


def test_declared_field_is_none_when_no_header_present():
    verdict = tick_handback.classify("no header here")
    assert verdict["declared"] is None


# -- more than one TICK: header is refused, never guessed at (#706) --


def test_a_second_quoted_header_after_the_real_one_is_refused_not_guessed():
    """agents/sub-manager.md documents the header on the *first* line, with
    narrative -- which may quote an earlier attempt, an issue body, or a CI
    log -- coming after it. That is the only order the brief can produce, so
    this fixture builds it in that order rather than the reversed one #706
    found the old fixture using.

    Even in the documented order, a quoted TICK:-shaped line in the
    narrative gives this module two headers and no way to tell which one is
    real. #706's proposal is the stronger of the two options on the issue:
    refuse outright rather than silently pick first or last."""
    message = (
        "TICK: completed\n"
        "Actually dispatched two lanes this tick. For context, an earlier "
        "attempt this same tick quoted a stale message:\n"
        "> TICK: could-not-run\n"
        "> REASON: old stale spawn refusal\n"
    )
    verdict = tick_handback.classify(message)
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "completed"
    assert verdict["state"] != "could-not-run"


def test_positive_control_the_same_message_with_only_one_header_classifies():
    """Positive control for the test above: strip the second, quoted
    TICK:-shaped line and the identical message classifies cleanly. Without
    this, the negative assertion above would pass even if `classify` refused
    every message unconditionally."""
    message = (
        "TICK: completed\n"
        "TICK-ENDS: work-started\n"
        "Actually dispatched two lanes this tick. For context, an earlier "
        "attempt this same tick was refused for an unrelated reason.\n"
    )
    verdict = tick_handback.classify(message)
    assert verdict["state"] == "completed"


def test_two_distinct_real_looking_headers_is_also_refused():
    """Two headers that both look like real, unquoted declarations -- not
    one quoted inside narrative -- must refuse the same way. There is no
    shape the sub-manager brief can produce with two headers, quoted or
    not, so this module does not try to distinguish "looks quoted" from
    "looks real": it refuses on count alone."""
    message = "TICK: blocked\nBLOCKER: first thing\nTICK: completed\n"
    verdict = tick_handback.classify(message)
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "blocked"
    assert verdict["state"] != "completed"


def test_a_stale_companion_line_before_the_real_header_is_not_used_as_detail():
    """Same shape, narrower: even when the *header* is picked correctly, a
    stale BLOCKER:/REASON: line sitting earlier in the message must not be
    picked up as the real header's own detail."""
    message = (
        "Earlier in this tick a developer spawn was refused.\n"
        "REASON: an earlier, unrelated refusal\n"
        "TICK: blocked\n"
        "BLOCKER: the actual, current blocker -- a pending permission prompt\n"
    )
    verdict = tick_handback.classify(message)
    assert verdict["state"] == "blocked"
    assert "actual, current blocker" in verdict["detail"]
    assert "unrelated refusal" not in verdict["detail"]


def test_framed_round_trip_via_module_reuse():
    import review_return

    raw = "TICK: completed\nTICK-ENDS: nothing-left\nnothing to do this tick"
    framed = "\n".join(
        review_return.FRAME_INDENT + line for line in raw.split("\n")
    ) + "\n" + review_return.FRAME_END + "\n"
    message, error = review_return.unframe(framed)
    assert error is None
    assert tick_handback.classify(message)["state"] == "completed"


def _run(stdin_text, extra_args=()):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), *extra_args],
        subject="the verdict and exit code tick_handback.py's CLI produces for this input",
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_exit_code_completed_is_zero():
    result = _run("TICK: completed\nTICK-ENDS: nothing-left\nall clear")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERDICT: completed" in result.stdout


def test_cli_exit_code_blocked_is_nonzero_and_distinct_from_could_not_run():
    blocked = _run("TICK: blocked\nBLOCKER: waiting on a human\n")
    could_not_run = _run("TICK: could-not-run\nREASON: spawn refused\n")
    assert blocked.returncode != 0
    assert could_not_run.returncode != 0
    assert blocked.returncode != could_not_run.returncode


def test_cli_exit_code_returned_nothing_is_distinct_from_could_not_classify():
    empty = _run("")
    garbled = _run("no sentinel here at all")
    assert empty.returncode != garbled.returncode
    assert "VERDICT: returned-nothing" in empty.stdout
    assert "VERDICT: could-not-classify" in garbled.stdout
