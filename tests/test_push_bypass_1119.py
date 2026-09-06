"""A release-commit push that is silently let through by a branch-protection
bypass must be observable, not indistinguishable from a clean push -- #1119.

`commands/release.md` has the release session commit the changelog fold and
version bumps directly to `main`, then push. On a maintainer account holding
bypass privileges, GitHub's classic branch protection never refuses -- it
records a bypass and lets the push through, announced only in the push's own
stderr:

    remote: Bypassed rule violations for refs/heads/main:
    remote: - 14 of 14 required status checks are expected.

Nothing parsed that line before this fix. This module is the parse: given the
text of a push's own captured output, say whether a bypass happened.

Every negative assertion (a clean push is not reported as bypassed) is paired
with its positive control (a bypassed push IS reported as bypassed) in the
same fixture, per this repo's own rule.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "push_bypass.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import spawn_guard  # noqa: E402
import push_bypass  # noqa: E402

REAL_BYPASS_RECEIPT = (
    "To github.com:Digital-Process-Tools/claude-oss.git\n"
    "remote: Bypassed rule violations for refs/heads/main:\n"
    "remote: - 14 of 14 required status checks are expected.\n"
    "   19c773c..abcdef1  main -> main\n"
)

CLEAN_RECEIPT = (
    "To github.com:Digital-Process-Tools/claude-oss.git\n"
    "   19c773c..abcdef1  main -> main\n"
)


def test_bypassed_receipt_is_detected():
    assert push_bypass.scan(REAL_BYPASS_RECEIPT) == push_bypass.STATE_BYPASSED


def test_positive_control_clean_receipt_is_not_bypassed():
    """Positive control for the assertion above: an ordinary push receipt,
    with no bypass language at all, must classify as clean -- otherwise the
    bypass detector would fire on every push and the finding would be
    worthless."""
    assert push_bypass.scan(CLEAN_RECEIPT) == push_bypass.STATE_CLEAN


def test_empty_receipt_is_could_not_tell_not_clean():
    """An absent receipt (the caller never captured the push's output) must
    never render the same as a clean one -- that is exactly the defect class
    this repo is named after."""
    assert push_bypass.scan("") == push_bypass.STATE_COULD_NOT_TELL
    assert push_bypass.scan(None) == push_bypass.STATE_COULD_NOT_TELL
    assert push_bypass.scan("   \n") == push_bypass.STATE_COULD_NOT_TELL


def test_bypass_language_elsewhere_in_a_longer_receipt_is_still_caught():
    text = "Enumerating objects: 12, done.\n" + REAL_BYPASS_RECEIPT + "Done.\n"
    assert push_bypass.scan(text) == push_bypass.STATE_BYPASSED


def _run(stdin_text, extra_args=()):
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), *extra_args],
        subject="the verdict and exit code push_bypass.py's CLI produces",
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_exit_code_and_stdout_for_bypass():
    result = _run(REAL_BYPASS_RECEIPT)
    assert result.returncode == push_bypass.EXIT_BYPASSED
    assert "bypassed" in result.stdout.lower()


def test_cli_exit_code_and_stdout_for_clean():
    result = _run(CLEAN_RECEIPT)
    assert result.returncode == push_bypass.EXIT_CLEAN
    assert "clean" in result.stdout.lower()


def test_cli_exit_code_for_could_not_tell_is_distinct_from_clean():
    result = _run("")
    assert result.returncode == push_bypass.EXIT_COULD_NOT_TELL
    assert result.returncode != push_bypass.EXIT_CLEAN
    assert "could-not-tell" in result.stdout.lower()


def test_all_three_cli_exit_codes_are_distinct():
    codes = {
        push_bypass.EXIT_CLEAN,
        push_bypass.EXIT_BYPASSED,
        push_bypass.EXIT_COULD_NOT_TELL,
    }
    assert len(codes) == 3
