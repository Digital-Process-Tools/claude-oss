"""#1544 step 4: the flags agents/tick-accounting.md documents must be real,
and the limit it states about ending a tick must actually hold.

Same discipline as the other #1544 spawn call-shape tests: every flag named
in prose is checked against `oss_state.py`'s own `--help`, never a hand-kept
list, and the file's central claim -- that it cannot send its own handback --
is checked against `scripts/tick_handback.py`'s real classification target.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import tick_handback  # noqa: E402

OSS_STATE = REPO_ROOT / "scripts" / "oss_state.py"
TICK_ACCOUNTING = REPO_ROOT / "agents" / "tick-accounting.md"


def _text():
    return TICK_ACCOUNTING.read_text(encoding="utf-8")


def _real_help_text():
    result = subprocess.run(
        [sys.executable, str(OSS_STATE), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _documented_flags():
    text = _text()
    return sorted(set(re.findall(r"--[a-z][a-z-]*", text)))


def test_the_file_documents_flags_at_all():
    """Positive control: without this, the check below passes over nothing."""
    assert _documented_flags(), (
        "agents/tick-accounting.md documents no --flag at all -- the check "
        "below would pass vacuously"
    )


def test_every_documented_oss_state_flag_is_one_it_actually_parses():
    """#1530's own class: a flag that reads plausibly but does not exist."""
    help_text = _real_help_text()
    # Flags this file's own prose names as oss_state.py's -- scoped rather
    # than checking every -- in the file, since --framed/--wait/--timeout
    # below belong to tick_handback.py / pr_green.py, not oss_state.py.
    oss_state_flags = (
        "--lane",
        "--lane-window",
        "--lane-dispatch-state",
        "--lane-fill",
        "--lane-fill-window",
        "--cleanup-override",
        "--wait-dispatch",
        "--wait-observable",
        "--check-wait",
        "--filings",
        "--merged-prs",
        "--window",
        "--intake-why",
        "--plugin-identity",
        "--tick-cost-session",
        "--tick-cost-window",
        "--tick-cost-start-ctx",
        "--tick-cost-calls",
        "--tick-cost-context-carried",
        "--tick-cost-first",
        "--tick-cost-why",
        "--decision",
    )
    documented = set(_documented_flags())
    for flag in oss_state_flags:
        assert flag in documented, "expected {0!r} in this file's own text".format(flag)
        assert flag in help_text, (
            "agents/tick-accounting.md documents {0!r}, which oss_state.py's "
            "own --help does not list (#1530's own class of defect)".format(flag)
        )


def test_a_flag_oss_state_py_does_not_have_would_be_caught():
    """Positive control for the check above: a made-up flag must fail it."""
    help_text = _real_help_text()
    assert "--budget" not in help_text, (
        "oss_state.py grew a --budget flag -- pick a different made-up flag "
        "for this control so it still proves the check above can fail"
    )


def test_report_back_names_both_states():
    text = _text()
    for state in ("ACCOUNTING: drafted", "ACCOUNTING: could-not-run"):
        assert state in text, (
            "agents/tick-accounting.md no longer documents the {0!r} report "
            "shape -- a caller reading only this file would not learn to "
            "expect it".format(state)
        )


def test_it_documents_the_validation_call_and_the_frame_terminator():
    """The framed-heredoc call must match commands/tick.md's own framing
    convention (#404's trap: an unframed heredoc lets a quoted terminator
    inside the draft end the stream early)."""
    text = _text()
    assert "tick_handback.py" in text
    assert "--framed" in text
    assert "END OF MESSAGE" in text


def _python3_lines(text=None):
    return [
        line.strip()
        for line in (text if text is not None else _text()).splitlines()
        if line.strip().startswith("python3 ")
    ]


def _writes_or_clears_marker(lines):
    return [line for line in lines if "--write" in line or "--clear" in line]


def test_it_never_writes_or_clears_the_role_marker():
    """Prose describing the caller's own `--write`/`--clear` calls is fine
    and expected (it is how this file explains inheriting the marker); a
    command LINE in this file doing either is not."""
    offenders = _writes_or_clears_marker(_python3_lines())
    assert not offenders, (
        "documented command line writes/clears the marker: {0!r}".format(offenders)
    )


def test_the_marker_check_would_have_caught_a_real_violation():
    """Positive control for the check above (found in the maintainer's own
    review of #1544 step 3's sibling test file, the identical class of gap):
    without this, a predicate over python3-prefixed lines could trivially
    pass forever if it never actually matched anything real, giving false
    confidence in a guarantee nothing here checks."""
    bad_line = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_role.py" --clear --root .'
    offenders = _writes_or_clears_marker(_python3_lines(bad_line))
    assert offenders == [bad_line], (
        "fixture construction failed: the offending line was not caught, so "
        "the control proves nothing"
    )


def _oss_state_call_lines():
    """#1614: a `python3 ...` line that actually names oss_state.py, as
    opposed to the tick_handback.py call line this same file also carries."""
    return [line for line in _python3_lines() if "oss_state.py" in line]


def test_it_documents_a_literal_runnable_oss_state_decision_call():
    """#1614: a bare script name plus a prose list of flags is not enough --
    a spawn told only that costs itself a turn discovering the call shape via
    --help (measured: 73s on this exact file, 2026-09-16). The file must
    carry a literal, copy-pasteable `python3 ... oss_state.py ... --decision
    ...` line, not just the flags named in prose."""
    offenders = _oss_state_call_lines()
    assert offenders, (
        "agents/tick-accounting.md names oss_state.py's --decision flags in "
        "prose but documents no literal, runnable call line for it (#1614)"
    )
    assert any("--decision" in line for line in offenders), (
        "the documented oss_state.py call line(s) do not carry --decision"
    )


def test_a_file_with_no_runnable_call_line_would_fail_the_check_above():
    """Positive control for the check above: prose-only text (the shape this
    file had before #1614) must fail it."""
    prose_only = (
        "Compose and run the tick's one `oss_state.py --decision` call, "
        "folding in every flag your prompt's facts map to: `--lane-fill`, "
        "`--wait-dispatch`."
    )
    offenders = [line for line in _python3_lines(prose_only) if "oss_state.py" in line]
    assert not offenders, (
        "fixture construction failed: prose-only text should document no "
        "literal call line, so the control proves nothing"
    )


def test_tick_handback_classifies_only_the_message_it_is_given():
    """The file's own central claim: `tick_handback.py` has no notion of
    "whose spawn this message came from" -- it classifies text, period, which
    is exactly why a draft has to be pasted by the caller rather than sent by
    this file. `classify` takes the message and nothing about provenance."""
    import inspect

    sig = inspect.signature(tick_handback.classify)
    assert "message" in sig.parameters or len(sig.parameters) == 1, (
        "tick_handback.classify's signature changed shape -- re-check "
        "agents/tick-accounting.md's claim that only message text, never "
        "spawn identity, decides the classification"
    )
