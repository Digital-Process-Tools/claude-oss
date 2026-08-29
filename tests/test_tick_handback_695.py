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

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tick_handback.py"

sys.path.insert(0, str(REPO / "scripts"))

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
        "Read the board. Nothing was ready to dispatch this tick; no lane "
        "was opened."
    )
    assert verdict["state"] == "completed"
    assert verdict["state"] != "returned-nothing"


def test_died_and_idle_do_not_render_identically():
    died = tick_handback.classify("")
    idle = tick_handback.classify("TICK: completed\nnothing to dispatch")
    assert died["state"] != idle["state"]


def test_completed_with_summary():
    verdict = tick_handback.classify(
        "TICK: completed\nDispatched fix/701 and fix/702, merged fix/699 on green."
    )
    assert verdict["state"] == "completed"
    assert verdict["declared"] == "completed"


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


def test_framed_round_trip_via_module_reuse():
    import review_return

    raw = "TICK: completed\nnothing to do this tick"
    framed = "\n".join(
        review_return.FRAME_INDENT + line for line in raw.split("\n")
    ) + "\n" + review_return.FRAME_END + "\n"
    message, error = review_return.unframe(framed)
    assert error is None
    assert tick_handback.classify(message)["state"] == "completed"


def _run(stdin_text, extra_args=()):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra_args],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_exit_code_completed_is_zero():
    result = _run("TICK: completed\nall clear")
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
