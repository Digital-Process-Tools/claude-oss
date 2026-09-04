"""An off-enum `TICK:` or `TICK-ENDS:` value collapses onto "no line at all"
-- #896.

`_TICK` and `_TICK_ENDS` both used to anchor their regex to the recognised
enum members. A line that *is* present but whose value is not one of them
never matched the pattern at all, so it counted as zero matches -- exactly
the same count an absent line produces -- and the receipt said "no
TICK-ENDS: line" about a message that had one, right above. This module
fixes that by matching any token after the field name, then validating it
against the enum separately, so presence and recognition are two different
questions with two different answers.

Every negative assertion here carries a positive control in the same
fixture, per this repository's own working rule.
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


def test_an_off_enum_tick_ends_value_says_it_was_present_and_unrecognised():
    """The finding itself: TICK-ENDS: is right there, with a value, and the
    reason must say so -- not that no line was found."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: mostly-done\nsome summary text"
    )
    assert verdict["state"] == "could-not-classify"
    assert "no TICK-ENDS" not in verdict["reason"]
    assert "mostly-done" in verdict["reason"]


def test_a_genuinely_absent_tick_ends_line_still_says_no_line():
    """Positive control: the message with the TICK-ENDS: line removed
    entirely must still produce the "no line" reason -- the fix must not
    blur presence and absence in the other direction."""
    verdict = tick_handback.classify(
        "TICK: completed\nsome summary text with no ends field at all"
    )
    assert verdict["state"] == "could-not-classify"
    assert "TICK-ENDS" in verdict["reason"]
    assert "no" in verdict["reason"].lower()


def test_off_enum_tick_ends_recognised_case_still_works():
    """Positive control for the recognised path: an actual enum value is
    still accepted and unaffected by the broadened detection regex."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: work-started\nsome summary text"
    )
    assert verdict["state"] == "completed"
    assert verdict["ends"] == "work-started"


def test_an_off_enum_tick_header_says_it_was_present_and_unrecognised():
    """The identical defect in the TICK: header match itself: a header line
    that names something other than the four recognised states must not
    render as 'no TICK: header found' -- it is there, it just isn't one of
    the four."""
    verdict = tick_handback.classify(
        "TICK: in-progress\nstill working on it, will report back"
    )
    assert verdict["state"] == "could-not-classify"
    assert "no TICK: header found" not in verdict["reason"]
    assert "in-progress" in verdict["reason"]


def test_a_genuinely_missing_tick_header_still_says_no_header():
    """Positive control: a message with no TICK: token anywhere must still
    produce the original 'no header' reason."""
    verdict = tick_handback.classify(
        "Everything looked fine, nothing to report this tick."
    )
    assert verdict["state"] == "could-not-classify"
    assert "no TICK: header found" in verdict["reason"]


def test_off_enum_tick_header_recognised_case_still_works():
    """Positive control: a recognised TICK: value is unaffected."""
    verdict = tick_handback.classify(
        "TICK: blocked\nBLOCKER: waiting on a human\n"
    )
    assert verdict["state"] == "blocked"
    assert verdict["detail"] == "waiting on a human"


def test_cli_reason_for_off_enum_tick_ends_names_the_value():
    result = _run("TICK: completed\nTICK-ENDS: mostly-done\nsome summary\n")
    assert result.returncode == tick_handback.EXIT_CODES["could-not-classify"], (
        result.stdout + result.stderr
    )
    assert "mostly-done" in result.stdout


def test_a_value_with_trailing_markdown_emphasis_is_still_recognised():
    """Regression: the old `\\b`-anchored enum pattern was satisfied by any
    non-word character following the enum word, not only a handful of
    punctuation marks -- so `TICK: completed**` (a bolded value) was
    already recognised as `completed` before #896. The fix must not narrow
    that: it reads the leading run of letters/digits/hyphens and ignores
    whatever markdown or punctuation follows it, exactly like `\\b` did."""
    verdict = tick_handback.classify(
        "TICK: completed**\nTICK-ENDS: work-started\nsome summary text"
    )
    assert verdict["state"] == "completed"
    assert verdict["ends"] == "work-started"


def test_a_bracketed_or_quoted_value_is_still_recognised():
    for wrapped in ("blocked)", 'blocked"', "blocked]"):
        verdict = tick_handback.classify(
            "TICK: {0}\nBLOCKER: waiting on review\n".format(wrapped)
        )
        assert verdict["state"] == "blocked", wrapped


def test_an_unrecognised_tick_value_that_is_not_even_word_shaped_is_folded():
    """Found by this lane's own oss:auditor review: an unrecognised TICK:
    value that does not even start with letters/digits/hyphens (e.g. raw
    ANSI escape bytes a sub-manager's message happened to carry) used to
    reach `verdict["declared"]`, and the CLI's `declared:` line, completely
    unfolded -- every sibling field on this receipt (`quoted`, `detail`,
    the value embedded in `reason`) is folded to printable ASCII, and this
    one was not. A terminal cursor-control sequence in an untrusted
    handback message must not reach the printed receipt raw."""
    verdict = tick_handback.classify(
        "TICK: \x1b[2J\x1b[Hpwned-line\nsome summary text here"
    )
    assert verdict["state"] == "could-not-classify"
    assert "\x1b" not in verdict["declared"]
    assert all(32 <= ord(c) <= 126 for c in verdict["declared"])


def test_cli_declared_line_has_no_raw_escape_bytes():
    result = _run("TICK: \x1b[2J\x1b[Hpwned-line\nsome summary text here\n")
    assert result.returncode == tick_handback.EXIT_CODES["could-not-classify"], (
        result.stdout + result.stderr
    )
    assert "\x1b" not in result.stdout
