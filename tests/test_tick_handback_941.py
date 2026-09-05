"""A sub-manager that stops mid-work with no `TICK:` header, promising its
own resumption, is not a shape this tool can classify -- but the reason it
refuses with must name the actual defect, not a generic "no header" note --
#941.

Three options were on the issue and none was chosen there. This module
takes option 3: `TICK: paused` (#818) is already the cheap, correct shape
for "something is in flight, waiting on CI or a poller" -- what a
sub-manager reaches for instead is free prose promising to "pick this back
up" once something resolves, a promise it cannot keep because it dies with
its context the instant it reports back (#695, #767). Option 1 (refuse the
turn at write time) needs a hook in the harness, outside this file's reach,
and is left to a follow-up issue. Option 2 (an automatic scheduler retry)
is a `commands/tick.md` policy question, not a fact this classifier can
derive from one message, so it is not implemented here either -- see the
prose change in commands/tick.md and agents/sub-manager.md alongside this
diff for the piece of option 2/3 that does belong in prose. What this
module can do, and does: recognise the promise-shaped prose and say so,
pointing the reader at the shape that should have been used instead of a
bare "no header" note that gives no hint why the sub-manager thought it had
said something.
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


def test_a_resumption_promise_with_no_header_names_the_defect():
    """The finding itself, reproduced from the issue's own shape: no TICK:
    header, closing with a promise to pick the tick back up once CI
    resolves."""
    verdict = tick_handback.classify(
        "Dispatched fix/900 and pushed. I'll pick this tick back up once "
        "CI resolves and report back then."
    )
    assert verdict["state"] == "could-not-classify"
    assert "paused" in verdict["reason"]
    assert "TICK: paused" in verdict["reason"]


def test_a_plain_no_header_message_with_no_promise_gets_the_generic_reason():
    """Positive control: a message with no header and no resumption
    language must still get the original, generic reason -- the promise
    detection must not swallow the ordinary could-not-classify case."""
    verdict = tick_handback.classify(
        "I looked at the board and dispatched two lanes, everything is fine."
    )
    assert verdict["state"] == "could-not-classify"
    assert "no TICK: header found" in verdict["reason"]
    assert "paused" not in verdict["reason"]


def test_the_correct_paused_shape_still_classifies_cleanly():
    """Positive control: a sub-manager that actually uses TICK: paused
    (the shape #941's fix points a promise-maker towards) is unaffected."""
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: fix/900 pushed, PR #901 open\n"
        "WAIT-OBSERVABLE: checks green or a leg failing on PR #901\n"
    )
    assert verdict["state"] == "paused"
    assert verdict["wait_dispatch"] == "fix/900 pushed, PR #901 open"


def test_a_promise_after_a_real_header_does_not_trigger_the_promise_reason():
    """The promise-detection only fires on the no-header path -- a message
    with a real header goes through the ordinary companion-field logic
    regardless of what its narrative says."""
    verdict = tick_handback.classify(
        "TICK: blocked\nBLOCKER: waiting on a human\n"
        "I'll pick this back up once CI resolves.\n"
    )
    assert verdict["state"] == "blocked"


def test_cli_names_the_promise_pattern_in_the_reason():
    result = _run("Merged fix/899. Will resume once the poller reports back in.")
    assert result.returncode == tick_handback.EXIT_CODES["could-not-classify"], (
        result.stdout + result.stderr
    )
    assert "TICK: paused" in result.stdout
