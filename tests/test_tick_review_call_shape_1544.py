"""#1544 step 2: the call agents/tick-review.md documents must be a real one.

#1530's own lesson -- ``pr_green.py 1537 --wait --budget 1500`` documented and run with a flag
that does not exist, argparse refusing at exit 2 while a piped notification still read
``completed`` -- is exactly the class of defect a brand-new spawn's own first documented call
can reintroduce silently. This pins that every flag ``agents/tick-review.md`` writes into its
one literal ``pr_green.py`` invocation is a flag ``pr_green.py`` actually parses (checked against
its own ``--help``, never a hand-kept list that could drift from the real parser), and that the
spawn's own three report headers (``REVIEW: reviewed`` / ``pending`` / ``could-not-run``) are all
present -- a caller reading only the file, never running it, must see a shape that matches what
the script underneath it accepts.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PR_GREEN = REPO_ROOT / "scripts" / "pr_green.py"
TICK_REVIEW = REPO_ROOT / "agents" / "tick-review.md"


def _documented_pr_green_lines():
    text = TICK_REVIEW.read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if line.strip().startswith("python3 ") and "pr_green.py" in line
    ]


def test_the_file_documents_a_pr_green_call_at_all():
    """Positive control: without this, the checks below pass over an empty list."""
    lines = _documented_pr_green_lines()
    assert lines, (
        "agents/tick-review.md documents no pr_green.py call at all -- the checks "
        "below would pass vacuously"
    )


def _real_help_text():
    result = subprocess.run(
        [sys.executable, str(PR_GREEN), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_every_documented_flag_is_one_pr_green_py_actually_parses():
    """#1530's own class: a flag that reads plausibly but does not exist."""
    help_text = _real_help_text()
    for line in _documented_pr_green_lines():
        for token in line.split():
            if token.startswith("--"):
                flag = token.split("=", 1)[0]
                assert flag in help_text, (
                    "agents/tick-review.md documents {0!r}, which pr_green.py's own "
                    "--help does not list (#1530's own class of defect). "
                    "Line: {1!r}".format(flag, line)
                )


def test_a_flag_pr_green_py_does_not_have_would_be_caught():
    """Positive control for the check above: a made-up flag must fail it."""
    help_text = _real_help_text()
    assert "--budget" not in help_text, (
        "pr_green.py grew a --budget flag -- pick a different made-up flag for "
        "this control so it still proves the check above can fail"
    )


def test_report_back_names_all_three_states():
    text = TICK_REVIEW.read_text(encoding="utf-8")
    for state in ("REVIEW: reviewed", "REVIEW: pending", "REVIEW: could-not-run"):
        assert state in text, (
            "agents/tick-review.md no longer documents the {0!r} report shape -- a "
            "caller reading only this file would not learn to expect it".format(state)
        )
