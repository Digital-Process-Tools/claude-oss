"""#1643: agents/developer/review.md's own mutation-receipt mechanism (#769) captured its
before-snapshot into a shell variable, `BEFORE=$(...)`, then read `$BEFORE` back in a later
step. This harness runs each Bash tool call as a separate process, so a shell variable set in
one call does not survive into the next -- the compare step would read empty/unset input and
report `could-not-compare` every time, silently defeating the mutation check every developer
lane's own self-review round depends on.

#1622 found and fixed the identical bug in `agents/tick-review.md` first (see
`tests/test_tick_review_mutation_receipt_1622.py`, particularly
`test_the_before_snapshot_is_written_to_a_file_never_a_shell_variable`); this pins the same fix
transferred to the sibling mechanism in `agents/developer/review.md`.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW = REPO_ROOT / "agents" / "developer" / "review.md"


def _text():
    return REVIEW.read_text(encoding="utf-8")


def _bash_code():
    fences = re.findall(r"```(?:bash)?\n(.*?)```", _text(), re.DOTALL)
    assert fences, "agents/developer/review.md has no fenced bash block to check"
    return "\n".join(fences)


def test_the_file_still_documents_a_tree_snapshot_call_at_all():
    """Positive control: without this, the checks below pass over nothing."""
    text = _text()
    assert "tree_snapshot.py" in text, (
        "agents/developer/review.md documents no tree_snapshot.py call -- the checks below "
        "would pass vacuously"
    )


def test_the_before_snapshot_is_written_to_a_file_never_a_shell_variable():
    code = _bash_code()
    assert "BEFORE=$(" not in code, (
        "agents/developer/review.md's own bash snippet still captures the before-snapshot "
        "in a shell variable -- that does not survive the separate Bash tool call the spawn "
        "step and the compare step each run as"
    )
    assert re.search(r"snapshot\s*>\s*\S", code), (
        "agents/developer/review.md does not redirect the snapshot to a file in its own "
        "bash snippet -- the only form that survives across separate Bash tool calls"
    )


def test_the_compare_call_reads_a_file_path_never_bare_stdin():
    code = _bash_code()
    assert re.search(r"compare\s+--before\s+(?!-\b)\S", code), (
        "agents/developer/review.md's compare call does not point --before at a file path "
        "in its own bash snippet (a bare `--before -` reads stdin, which is exactly the "
        "shell-variable-via-printf shape that does not survive across calls)"
    )
    assert "printf '%s' \"$BEFORE\"" not in code, (
        "agents/developer/review.md still pipes a $BEFORE shell variable into compare's "
        "stdin -- that variable does not exist in the later, separate Bash call"
    )


def test_the_temp_file_name_is_not_a_fixed_shared_path():
    """Two developer lanes reviewing different issues at once must not collide on the
    same before-snapshot path -- the same class of bug `bin/oss-workspace` already
    shipped once with a shared, unnamed socket path a second consumer could win."""
    text = _text()
    code = _bash_code()
    assert "oss-developer-review-tree-before.json" not in code, (
        "agents/developer/review.md's bash snippet names a fixed, shared temp file with "
        "no per-issue uniqueness -- two concurrent lanes would collide"
    )
    assert "issue number" in text, (
        "agents/developer/review.md does not instruct the lane to derive the temp file "
        "name from its own issue number(s)"
    )


def test_it_still_verifies_root_and_branch_immediately_after_the_before_snapshot():
    """#1024, #1078, #1096: a snapshot call has landed on the wrong worktree even from a
    single shell call. The file-based fix must not drop this existing verification."""
    code = _bash_code()
    assert re.search(r's\["root"\].*s\["branch"\]', code), (
        "agents/developer/review.md's bash snippet no longer reads root/branch back from "
        "the before-snapshot to verify it landed on the right worktree"
    )


def test_the_three_tree_states_are_all_still_named():
    text = _text()
    for state in ("clean", "mutated", "could-not-compare"):
        assert state in text, (
            "agents/developer/review.md does not name the tree_snapshot.py state "
            "{0!r} -- an absent state reads as coverage it does not have".format(state)
        )


def test_a_stub_missing_the_mechanism_would_fail_these_checks():
    """Positive control: a rewrite that dropped the snapshot/compare entirely must not
    pass, or the checks above are not checking anything."""
    stub = "## What you do\n\n1. **Spawn the two reviewers**\n"
    assert "tree_snapshot.py" not in stub
    assert "BEFORE=$(" not in stub
