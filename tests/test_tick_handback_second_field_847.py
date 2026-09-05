"""A second `TICK-ENDS:`, `WAIT-DISPATCH:`, `WAIT-OBSERVABLE:`, `BLOCKER:` or
`REASON:` match must refuse the same way a second `TICK:` header already does
-- #847.

`scripts/tick_handback.py`'s `_TICK.finditer` refuses a message carrying two
`TICK:` headers (#706), but every companion field used `.search`, which
silently takes the *first* match with no count check at all. Both the header
pattern and every companion-field pattern accept the same markdown quote/
bullet prefix (`[ \t>*_#]*`), so a quoted line inside a legitimately-pasted
excerpt (the sub-manager explaining what it disregarded, per #828) counts as
a real declaration exactly as readily as an unquoted one.

The issue's own measured repro is the first two tests below: the failing
case, and the positive control proving the sibling TICK: header does refuse.

Every negative assertion here carries a positive control in the same
fixture, per this repository's own working rule -- and the fix taken here
does not distinguish quote context when refusing a second match, the same
way `_TICK` never has: see the module docstring / #847's own report for why.
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


def test_the_issue_own_repro_a_quoted_tick_ends_no_longer_wins():
    """The exact measured repro from #847: a quoted TICK-ENDS: line used to
    win silently over the real, unquoted one below it."""
    verdict = tick_handback.classify(
        "TICK: completed\n> TICK-ENDS: nothing-left\nTICK-ENDS: work-started\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert verdict["state"] != "completed"
    assert "TICK-ENDS" in verdict["reason"]


def test_the_issue_own_control_tick_header_already_refuses():
    """Positive control quoted in the issue: the sibling TICK: header already
    refuses a second match. This must keep passing unchanged."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: work-started\n> TICK: blocked\n"
    )
    assert verdict["state"] == "could-not-classify"


def test_a_single_tick_ends_line_still_classifies_normally():
    """Positive control: nothing about the fix should make an ordinary,
    single-declaration message refuse."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: work-started\nsummary text\n"
    )
    assert verdict["state"] == "completed"
    assert verdict["ends"] == "work-started"


def test_two_unquoted_tick_ends_lines_also_refuse():
    """Not just the quoted case -- two plain, unquoted TICK-ENDS: lines are
    just as undecidable as a quoted one winning, and must refuse too."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: work-started\nTICK-ENDS: nothing-left\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert "TICK-ENDS" in verdict["reason"]


def test_two_blocker_lines_refuse():
    verdict = tick_handback.classify(
        "TICK: blocked\nBLOCKER: first thing\n> BLOCKER: a quoted thing\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert "BLOCKER" in verdict["reason"]


def test_a_single_blocker_line_still_classifies_normally():
    verdict = tick_handback.classify("TICK: blocked\nBLOCKER: a thing\n")
    assert verdict["state"] == "blocked"
    assert verdict["detail"] == "a thing"


def test_two_reason_lines_refuse():
    verdict = tick_handback.classify(
        "TICK: could-not-run\nREASON: spawn refused\n> REASON: quoted excerpt\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert "REASON" in verdict["reason"]


def test_a_single_reason_line_still_classifies_normally():
    verdict = tick_handback.classify("TICK: could-not-run\nREASON: spawn refused\n")
    assert verdict["state"] == "could-not-run"
    assert verdict["detail"] == "spawn refused"


def test_two_wait_dispatch_lines_refuse():
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825 opened\n"
        "> WAIT-DISPATCH: quoted excerpt\n"
        "WAIT-OBSERVABLE: PR #825 checks green\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert "WAIT-DISPATCH" in verdict["reason"]


def test_two_wait_observable_lines_refuse():
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825 opened\n"
        "WAIT-OBSERVABLE: PR #825 checks green\n"
        "> WAIT-OBSERVABLE: quoted excerpt\n"
    )
    assert verdict["state"] == "could-not-classify"
    assert "WAIT-OBSERVABLE" in verdict["reason"]


def test_a_single_pair_of_wait_lines_still_classifies_normally():
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825 opened\n"
        "WAIT-OBSERVABLE: PR #825 checks green\n"
    )
    assert verdict["state"] == "paused"
    assert verdict["wait_dispatch"] == "PR #825 opened"
    assert verdict["wait_observable"] == "PR #825 checks green"


def test_cli_exit_code_on_a_second_tick_ends_is_could_not_classify():
    result = _run(
        "TICK: completed\n> TICK-ENDS: nothing-left\nTICK-ENDS: work-started\n"
    )
    assert result.returncode == tick_handback.EXIT_CODES["could-not-classify"], (
        result.stdout + result.stderr
    )
    assert "VERDICT: could-not-classify" in result.stdout
    assert "TICK-ENDS" in result.stdout
