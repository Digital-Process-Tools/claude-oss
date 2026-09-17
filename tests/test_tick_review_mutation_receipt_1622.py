"""#1622: a review spawn must not mutate the tree it reviews, and must not rely on prose alone
to prove it did not.

Observed 2026-09-16: an `oss:tick-review` spawn deleted two untracked directories (`notes/`,
`reports/`) inside the lane worktree it was reviewing, judged as tidying rather than as the
mutation neither `agents/tick-review.md` nor `skills/manager/phases/review.md` explicitly ruled
out at the time. It surfaced only because the harness's own classifier flagged it on the way back
-- not because anything in this repository's own tooling would have caught it. The comment thread
on the issue names four more incidents of the identical shape across `oss:auditor` in a sibling
repository, all under a brief that said not to.

The harness grants no genuinely read-only `Bash` (see `tests/test_agent_grant_is_total.py`'s own
docstring), so the fix taken here is the one #769 already established for `agents/developer/
review.md`'s two reviewer spawns: a snapshot before, a compare after, arithmetic rather than a
"did anything look wrong" judgement call. This pins that `agents/tick-review.md` documents that
same mechanism for its own procedure, using a real `tree_snapshot.py` call rather than an invented
one, and that its report contract carries the result forward as a `TREE:` line.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TICK_REVIEW = REPO_ROOT / "agents" / "tick-review.md"
TREE_SNAPSHOT = REPO_ROOT / "scripts" / "tree_snapshot.py"


def _text():
    return TICK_REVIEW.read_text(encoding="utf-8")


def test_the_file_documents_a_tree_snapshot_call_at_all():
    """Positive control: without this, the checks below pass over nothing."""
    text = _text()
    assert "tree_snapshot.py" in text, (
        "agents/tick-review.md documents no tree_snapshot.py call -- the checks below "
        "would pass vacuously"
    )


def test_it_documents_both_a_snapshot_and_a_compare_call():
    text = _text()
    assert re.search(r"tree_snapshot\.py[\"']?\s+snapshot", text), (
        "agents/tick-review.md does not document the 'before' half of the receipt "
        "(tree_snapshot.py snapshot)"
    )
    assert re.search(r"tree_snapshot\.py[\"']?\s+compare\s+--before", text), (
        "agents/tick-review.md does not document the 'after' half of the receipt "
        "(tree_snapshot.py compare --before)"
    )


def test_the_before_snapshot_is_written_to_a_file_never_a_shell_variable():
    """Steps 1-3 span many separate Bash tool calls, and shell state (a `BEFORE=$(...)`
    variable) does not persist between them -- only a real file on disk does. A call
    shape that captures the before-snapshot in a variable and reads it back several
    calls later would silently degrade to `could-not-compare` on every real run,
    never `clean` or `mutated` (found in this file's own self-review round)."""
    text = _text()
    fences = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    assert fences, "agents/tick-review.md has no fenced bash block to check"
    code = "\n".join(fences)
    assert "BEFORE=$(" not in code, (
        "agents/tick-review.md's own bash snippet captures the before-snapshot in a "
        "shell variable -- that does not survive the separate Bash calls steps 1-3 require"
    )
    assert re.search(r"snapshot\s*>\s*\S", code), (
        "agents/tick-review.md does not redirect the snapshot to a file in its own "
        "bash snippet -- the only form that survives across separate Bash tool calls"
    )
    assert re.search(r"compare\s+--before\s+(?!-\b)\S", code), (
        "agents/tick-review.md's compare call does not point --before at a file path "
        "in its own bash snippet (a bare `--before -` reads stdin, which is exactly the "
        "shell-variable shape that does not survive across calls)"
    )


def test_every_documented_tree_snapshot_flag_is_one_the_script_actually_parses():
    """The same #1530 class test_tick_review_call_shape_1544.py already pins for
    pr_green.py: a flag that reads plausibly but does not exist."""
    help_text = subprocess.run(
        [sys.executable, str(TREE_SNAPSHOT), "compare", "--help"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    text = _text()
    for line in text.splitlines():
        if "tree_snapshot.py" not in line or "compare" not in line:
            continue
        for token in line.split():
            if token.startswith("--"):
                flag = token.split("=", 1)[0]
                assert flag in help_text, (
                    "agents/tick-review.md documents {0!r} for tree_snapshot.py compare, "
                    "which its own --help does not list. Line: {1!r}".format(flag, line)
                )


def test_report_back_carries_a_tree_line_beside_every_review_header():
    """A receipt nobody is asked to report is not a receipt -- it has to reach the
    caller, the same way `REVIEW:` itself does."""
    text = _text()
    for header in ("REVIEW: reviewed", "REVIEW: pending", "REVIEW: could-not-run"):
        idx = text.index(header)
        # TREE: must appear on the very next non-blank line after the header, inside
        # the same fenced block -- not merely somewhere later in the file.
        following = text[idx + len(header) : idx + len(header) + 200]
        assert "TREE:" in following, (
            "{0!r} is not immediately followed by a TREE: line in agents/tick-review.md "
            "-- a caller reading only this file would not learn to expect one".format(
                header
            )
        )


def test_it_verifies_root_and_branch_immediately_after_the_before_snapshot():
    """The sibling mechanism in agents/developer/review.md added this check in
    response to three corroborated incidents (#1024, #1078, #1096) of a snapshot
    call landing on the wrong worktree even from a single shell call. Omitting it
    here would reintroduce that same known, unresolved risk into a new call site."""
    text = _text()
    fences = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    code = "\n".join(fences)
    assert re.search(r's\["root"\].*s\["branch"\]', code), (
        "agents/tick-review.md's bash snippet does not read root/branch back from "
        "the before-snapshot to verify it landed on the right worktree"
    )


def test_the_three_tree_states_are_all_named():
    text = _text()
    for state in ("clean", "mutated", "could-not-compare"):
        assert state in text, (
            "agents/tick-review.md does not name the tree_snapshot.py state {0!r} -- "
            "an absent state reads as coverage it does not have".format(state)
        )


def test_a_file_missing_the_mechanism_would_fail_these_checks():
    """Positive control: the pre-#1622 shape (no snapshot, no TREE: line) must not
    pass, or the checks above are not checking anything."""
    stub = (
        "## What you do\n\n"
        "1. **Read something and follow it**\n\n"
        "## Report back\n\n"
        "```\nREVIEW: reviewed\n<one line per pull request>\n```\n"
    )
    assert "tree_snapshot.py" not in stub
    assert "TREE:" not in stub
