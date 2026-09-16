"""An optional `CURATE:` line on a `TICK:` handback -- #1600.

The `^curate/` never-auto-merge gate came off in #1602/#1604: a curate pull
request now merges on green like everything else, in an ordinary tick's own
merge step. #1600 is what that removal leaves exposed -- a curate pull
request merging silently renders identically to one that never ran at all,
which is the same "an absence produced by the tool read as an absence in the
world" defect this repository is named after, one step further down the same
gate #1600's body already measured.

The fix mirrors `COST:` (#1499), the existing precedent for "a free-text line
that rides on the `TICK:` header without affecting which state is chosen":
a missing or duplicated `CURATE:` line folds to the same absent answer
(`curate=None`) rather than promoting either shape to `could-not-classify`,
exactly the way `_find_optional_field` already treats `COST:`.

Every negative assertion here (no `CURATE:` line -> `curate=None`) carries a
positive control in the same fixture (a `CURATE:` line present -> its value
comes back), per this repository's own working rule -- a harness that could
not see a `CURATE:` line and a tick that genuinely had nothing to report
must not render identically to a reader who never checked.
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


def test_no_curate_line_folds_to_none_positive_control_absent():
    """The common case: an ordinary tick that merged nothing curate-authored.
    Absent, not a classification failure -- this is the negative half."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: work-started\nmerged PR #900\n"
    )
    assert verdict["state"] == "completed"
    assert verdict["curate"] is None


def test_a_curate_line_on_a_completed_tick_is_captured():
    """The positive control: a tick that merged a curate PR says so, and the
    line survives classification untouched, the same way COST: does."""
    verdict = tick_handback.classify(
        "TICK: completed\n"
        "TICK-ENDS: work-started\n"
        "CURATE: 5 promoted, 4 merged, 10 declined, 1 deferred\n"
        "merged PR #1593\n"
    )
    assert verdict["state"] == "completed"
    assert verdict["curate"] == "5 promoted, 4 merged, 10 declined, 1 deferred"


def test_curate_line_never_changes_the_declared_state():
    """CURATE: is metadata beside the outcome, not part of what decides it --
    the same guarantee COST: already carries. A CURATE: line on a blocked
    tick must not push it toward completed or could-not-classify."""
    verdict = tick_handback.classify(
        "TICK: blocked\n"
        "BLOCKER: CI red on PR #900\n"
        "CURATE: 5 promoted, 4 merged, 10 declined, 1 deferred\n"
    )
    assert verdict["state"] == "blocked"
    assert verdict["curate"] == "5 promoted, 4 merged, 10 declined, 1 deferred"


def test_a_duplicated_curate_line_folds_to_none_not_could_not_classify():
    """Unlike TICK-ENDS:/BLOCKER:/REASON:, a second CURATE: line must not
    refuse classification -- it folds to the same 'absent' answer a missing
    line gets, per _find_optional_field's own contract (mirrors COST:)."""
    verdict = tick_handback.classify(
        "TICK: completed\n"
        "TICK-ENDS: work-started\n"
        "CURATE: first claim\n"
        "CURATE: a second, contradicting claim\n"
    )
    assert verdict["state"] == "completed"
    assert verdict["curate"] is None


def test_cli_prints_the_curate_line_when_present():
    result = _run(
        "TICK: completed\n"
        "TICK-ENDS: work-started\n"
        "CURATE: 5 promoted, 4 merged, 10 declined, 1 deferred\n"
    )
    assert result.returncode == tick_handback.EXIT_CODES["completed"], (
        result.stdout + result.stderr
    )
    assert "curate: 5 promoted, 4 merged, 10 declined, 1 deferred" in result.stdout


def test_cli_omits_the_curate_line_when_absent():
    result = _run("TICK: completed\nTICK-ENDS: nothing-left\n")
    assert result.returncode == tick_handback.EXIT_CODES["completed"], (
        result.stdout + result.stderr
    )
    assert "curate:" not in result.stdout
