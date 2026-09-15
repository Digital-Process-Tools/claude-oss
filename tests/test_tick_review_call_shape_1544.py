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

A second, distinct defect was found in the maintainer's own review of this file's first version:
every flag it documented was real, but the call's own *semantics* were not what the file's
surrounding prose claimed. ``pr_green.py``'s own contract is "scan in order, stop at the first
one that is not pending" (its own ``--help`` description); ``scan()`` returns the first
non-pending entry among the numbers it is given and never reads the rest, and ``--wait``'s own
``wait_for_first_actionable`` returns only when every named number is still pending, or the
first one that is not. A single call given several pull request numbers can therefore resolve at
most one of them and says nothing about the others, even when they have already gone green or
red. The file's first version documented one call over the whole batch (``NUM [NUM...]``) as
though it verdicted every named pull request -- flags all real, semantics wrong. The checks below
pin the fixed shape (one call per pull request) against ``pr_green.py``'s own real behaviour,
not just its flag spellings.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pr_green  # noqa: E402

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


# ------------------------------------------------------ semantics, not spellings


def _num_placeholder_count(line):
    """How many pull-request-number placeholders one documented call names.

    ``pr_green.py``'s own contract resolves at most one named pull request per
    call, so a documented line naming more than one (``NUM [NUM...]``, or two
    bare ``NUM``s) claims a verdict the call cannot deliver.
    """
    return len(re.findall(r"\bNUM\b", line))


def test_documented_call_never_names_more_than_one_pull_request_per_call():
    """The semantic half of #1530's class: every flag can be real and the call
    can still be wrong, if the surrounding prose asks it to verdict a batch a
    single invocation cannot cover (found in this maintainer's own review of
    #1544 step 2's first version)."""
    for line in _documented_pr_green_lines():
        count = _num_placeholder_count(line)
        assert count <= 1, (
            "agents/tick-review.md documents a pr_green.py call naming {0} pull "
            "request placeholders in one line -- pr_green.py's own scan() stops "
            "at the first non-pending entry and never reads the rest, and "
            "wait_for_first_actionable returns on the first actionable one or "
            "reports every name pending, so one call cannot verdict a batch. "
            "Line: {1!r}".format(count, line)
        )


def test_the_placeholder_count_check_would_have_caught_the_original_bug():
    """Positive control: the exact shape this file's first version documented
    (one call, several numbers) must fail the check above, or it is not
    checking anything."""
    bad_line = (
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_green.py" NUM [NUM...] '
        "--wait --timeout N"
    )
    assert _num_placeholder_count(bad_line) > 1, (
        "fixture construction failed: the pre-fix line no longer trips the "
        "placeholder count, so the control proves nothing"
    )


def _fake_gh_run(responses):
    """One ``(returncode, stdout, stderr)`` per expected ``gh`` call, in call
    order -- the same shape ``tests/test_pr_green_1086.py`` uses for
    ``pr_green.scan``'s own tests, reproduced narrowly here so this file does
    not depend on importing another test module."""
    it = iter(responses)

    def run(cmd, **kwargs):
        rc, out, err = next(it)
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    return run


def _rollup_json(number, branch, sha, rows):
    import json

    return json.dumps(
        {
            "number": number,
            "headRefName": branch,
            "headRefOid": sha,
            "state": "OPEN",
            "statusCheckRollup": rows,
        }
    )


def _row(name, workflow, status="COMPLETED", conclusion="SUCCESS"):
    return {
        "name": name,
        "workflowName": workflow,
        "status": status,
        "conclusion": conclusion,
    }


def test_one_scan_call_cannot_verdict_two_named_pull_requests():
    """The behavioural half, not just a wording check: two pull requests,
    already-resolved states (one red, one green) -- ``pr_green.scan`` still
    returns exactly one entry and never reads the second, proving the
    "one call per pull request" fix in agents/tick-review.md's own step 1 is
    not optional phrasing but the only way to get a verdict for each."""
    red_rows = [_row("tests", "tests", conclusion="FAILURE")]
    run = _fake_gh_run(
        [
            (0, _rollup_json(101, "fix/101", "a", red_rows), ""),
        ]
    )
    entry = pr_green.scan([101, 102], "gh", run, workflows_dir=None)
    assert entry is not None
    assert entry["pr"] == 101
    assert entry["state"] == pr_green.STATE_RED
    # PR 102 (already green, per the fixture design) was never read at all --
    # a single call with two numbers produced exactly one verdict, not two.


def test_the_two_pr_fixture_actually_has_a_second_pr_that_would_differ():
    """Positive control for the test above: if PR 102 were read, it would
    report green, not red -- proving the missing second call is a real gap
    in coverage rather than two PRs that happen to agree."""
    green_rows = [_row("tests", "tests")]
    run = _fake_gh_run([(0, _rollup_json(102, "fix/102", "b", green_rows), "")])
    entry = pr_green.read_pr(102, "gh", run, workflows_dir=None)
    assert entry["state"] == pr_green.STATE_GREEN
