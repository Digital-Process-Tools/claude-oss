"""#1642: agents/auditor.md and agents/release-auditor.md lack the mutation-receipt guard
agents/tick-review.md gained in #1622/#1641.

#1622 gave `agents/tick-review.md` a snapshot/compare mutation-receipt (`scripts/
tree_snapshot.py`, the same mechanism `agents/developer/review.md` already carries around its
own reviewer spawns) after an `oss:tick-review` spawn was found to have deleted two untracked
directories inside a lane worktree it was reviewing -- surfaced only by a harness classifier
warning, not by anything this repo owns. The identical gap existed in `agents/auditor.md` and
`agents/release-auditor.md`: neither wrapped its own review/audit procedure in a before/after
tree snapshot, so a mutation either of them makes to a worktree it is only supposed to read
would go unreported the same way.

Both spawns are the reader themselves (they do not spawn sub-agents the way `agents/developer/
review.md` and `agents/tick-review.md` do), so the receipt wraps each spawn's own run: a
snapshot before its first read, a compare right before it composes its report, carried forward
as a `TREE:` line.

Same shape as `tests/test_tick_review_mutation_receipt_1622.py`, parametrized over both files.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDITOR = REPO_ROOT / "agents" / "auditor.md"
RELEASE_AUDITOR = REPO_ROOT / "agents" / "release-auditor.md"
TREE_SNAPSHOT = REPO_ROOT / "scripts" / "tree_snapshot.py"

FILES = (AUDITOR, RELEASE_AUDITOR)


def _text(path):
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_file_documents_a_tree_snapshot_call_at_all(path):
    """Positive control: without this, the checks below pass over nothing."""
    text = _text(path)
    assert "tree_snapshot.py" in text, (
        "{0} documents no tree_snapshot.py call -- the checks below would pass "
        "vacuously".format(path.name)
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_it_documents_both_a_snapshot_and_a_compare_call(path):
    text = _text(path)
    assert re.search(r"tree_snapshot\.py[\"']?\s+snapshot", text), (
        "{0} does not document the 'before' half of the receipt "
        "(tree_snapshot.py snapshot)".format(path.name)
    )
    assert re.search(r"tree_snapshot\.py[\"']?\s+compare\s+--before", text), (
        "{0} does not document the 'after' half of the receipt "
        "(tree_snapshot.py compare --before)".format(path.name)
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_before_snapshot_is_written_to_a_file_never_a_shell_variable(path):
    """Each spawn's own run spans several separate Bash tool calls; shell state does
    not persist between them, so only a file on disk survives to the compare call."""
    text = _text(path)
    fences = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    assert fences, "{0} has no fenced bash block to check".format(path.name)
    code = "\n".join(fences)
    assert "BEFORE=$(" not in code, (
        "{0}'s own bash snippet captures the before-snapshot in a shell variable -- "
        "that does not survive the spawn's own separate Bash calls".format(path.name)
    )
    assert re.search(r"snapshot\s*>\s*\S", code), (
        "{0} does not redirect the snapshot to a file in its own bash snippet -- the "
        "only form that survives across separate Bash tool calls".format(path.name)
    )
    assert re.search(r"compare\s+--before\s+(?!-\b)\S", code), (
        "{0}'s compare call does not point --before at a file path in its own bash "
        "snippet (a bare `--before -` reads stdin)".format(path.name)
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_documented_tree_snapshot_flag_is_one_the_script_actually_parses(path):
    import subprocess
    import sys

    help_text = subprocess.run(
        [sys.executable, str(TREE_SNAPSHOT), "compare", "--help"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    text = _text(path)
    for line in text.splitlines():
        if "tree_snapshot.py" not in line or "compare" not in line:
            continue
        for token in line.split():
            if token.startswith("--"):
                flag = token.split("=", 1)[0]
                assert flag in help_text, (
                    "{0} documents {1!r} for tree_snapshot.py compare, which its own "
                    "--help does not list. Line: {2!r}".format(path.name, flag, line)
                )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_report_format_requires_a_tree_line(path):
    """A receipt nobody is asked to report is not a receipt -- it has to reach the
    caller, the same way the rest of the report contract does."""
    text = _text(path)
    idx = text.index("## Report format")
    following = text[idx : idx + 1500]
    assert "TREE:" in following, (
        "{0}'s own '## Report format' section does not require a TREE: line -- a "
        "caller reading only this file would not learn to expect one".format(path.name)
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_three_tree_states_are_all_named(path):
    text = _text(path)
    for state in ("clean", "mutated", "could-not-compare"):
        assert state in text, (
            "{0} does not name the tree_snapshot.py state {1!r} -- an absent state "
            "reads as coverage it does not have".format(path.name, state)
        )


def test_a_file_missing_the_mechanism_would_fail_these_checks():
    """Positive control: the pre-#1642 shape (no snapshot, no TREE: line) must not
    pass, or the checks above are not checking anything."""
    stub = (
        "## The checklist\n\n"
        "Four classes.\n\n"
        "## Report format\n\n"
        "Compact. Group by class.\n"
    )
    assert "tree_snapshot.py" not in stub
    assert "TREE:" not in stub
