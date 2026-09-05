"""#1048: a sub-manager closed its handback with a promise to resume itself
three times in one session, and the correction held for exactly one turn out
of three -- "another paragraph asking for it" was already tried twice and
worked once. Two structural pieces close the gap the #941 fix left open,
per its own docstring ("see the prose change in commands/tick.md and
agents/sub-manager.md alongside this diff for the piece of option 2/3 that
does belong in prose" -- a change that had not actually landed):

  1. `agents/sub-manager.md` asks the sub-manager to validate its own draft
     handback through `tick_handback.py` before ending its turn, rather than
     only remembering the rule under narrative pressure.
  2. `commands/tick.md`'s `could-not-classify` handling asks the scheduler to
     re-ask the same sub-manager (via `SendMessage`, the same mechanism a
     `paused` resume already uses) before falling back to a manual read.

Each check is a real-file positive control and a deletion-based negative
control, per this repo's own convention that a "does the file mention X"
predicate must also fail once X's own lines are gone.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUB_MANAGER_MD = REPO_ROOT / "agents" / "sub-manager.md"
TICK_MD = REPO_ROOT / "commands" / "tick.md"


def _text(path):
    return path.read_text(encoding="utf-8")


def _without_lines_matching(text, pattern):
    return "\n".join(
        line for line in text.splitlines() if not re.search(pattern, line)
    )


def test_sub_manager_validates_its_own_draft_before_sending():
    text = _text(SUB_MANAGER_MD)
    assert "tick_handback.py" in text
    assert re.search(r"validate\w* your own draft", text, re.IGNORECASE), (
        "agents/sub-manager.md does not ask the sub-manager to self-check "
        "its draft handback before ending its turn (#1048)"
    )
    assert "#1048" in text


def test_deleting_the_self_validation_lines_removes_the_claim():
    text = _text(SUB_MANAGER_MD)
    stripped = _without_lines_matching(text, r"[Vv]alidate\w* your own draft|#1048")
    assert len(stripped.splitlines()) < len(text.splitlines())
    assert not re.search(r"validate\w* your own draft", stripped, re.IGNORECASE)


def test_tick_md_asks_the_scheduler_to_reask_before_a_manual_read():
    text = _text(TICK_MD)
    assert re.search(r"re-ask", text, re.IGNORECASE), (
        "commands/tick.md's could-not-classify handling does not ask the "
        "scheduler to re-ask the sub-manager before reading the message "
        "itself (#1048)"
    )
    assert "SendMessage" in text
    assert "#1048" in text


def test_deleting_the_reask_lines_removes_the_claim():
    text = _text(TICK_MD)
    stripped = _without_lines_matching(text, r"[Rr]e-ask|#1048")
    assert len(stripped.splitlines()) < len(text.splitlines())
    assert not re.search(r"re-ask", stripped, re.IGNORECASE)


def test_a_silent_file_fails_both_predicates():
    """Must-not-fire control: a file that says nothing about either rule
    must not accidentally satisfy either check."""
    silent = "This document discusses tick dispatch and nothing else."
    assert not re.search(r"validate\w* your own draft", silent, re.IGNORECASE)
    assert not re.search(r"re-ask", silent, re.IGNORECASE)


def test_tick_md_does_not_point_below_at_content_that_moved_out():
    """Found in self-review of #1037: `commands/tick.md` referred to "step 1
    below", "*What ends a tick* below" and "the three states below" -- all
    true when this file held all seven steps, false once #1037 moved steps
    1-6 and "What ends a tick" out to skills/manager/phases/tick-order.md.
    A reader following any "below" pointer into this file now finds
    nothing. Found in two passes: the first two by this lane's own
    self-review auditor spawn, the third ("three states below") by the
    Explore reviewer spawned alongside it, on the same commit."""
    text = _text(TICK_MD)
    assert "step 1 below" not in text
    assert "below names" not in text
    assert "three states below" not in text


def test_dispatch_md_points_at_the_file_the_call_actually_moved_to():
    """Found by the Explore reviewer: dispatch.md's own pointer to "the
    same call and its three states in full" named commands/tick.md, which
    was true before #1037 moved that content to
    skills/manager/phases/tick-order.md and false after."""
    dispatch_md = REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md"
    text = _text(dispatch_md)
    assert "tick-order.md` names the same call and its three" in text
    assert "`commands/tick.md` names the same call and its three" not in text
