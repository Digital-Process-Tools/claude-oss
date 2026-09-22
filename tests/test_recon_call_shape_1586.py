"""#1586: agents/developer.md must document a literal, blocking oss:recon call.

A developer lane's brief stated the ordering rule twice ("spawn recon first, before
you read the tree") but pinned no call shape and never said the spawn must block.
Observed 2026-09-16: a lane spawned recon with the tool's default backgrounding
behaviour, then filled the wait by orienting the tree itself -- reading the three
issues (sanctioned) and also running eighteen tree-touching shell commands of the
kind recon exists to replace. It paid for both: recon's own reads, and the ones it
was sent to save. Nothing in the brief contradicted that reading, because "spawn it
first" is satisfied by having issued the call, backgrounded or not.

The fix mirrors the one place a literal call shape already existed at the time --
``skills/manager/phases/dispatch.md:62`` -- into ``agents/developer.md``, pinning
``run_in_background: false``. A test on the file's own text cannot prove a lane
obeys it (the same limit ``tests/test_agent_grant_is_total.py`` already documents
about itself); what it can do is make sure the literal, correct call shape is still
there in ``agents/developer.md`` to copy.

dispatch.md's own copy was retired by #1691: it lived in a paragraph ("One
dispatcher-side use survives") gating a spawn no live dispatcher can make since
#1544 moved dispatch rendering into ``agents/tick-dispatch.md``, which is granted
no ``Agent`` tool at all. The negative control that used to require dispatch.md's
own copy to persist forever is gone with it -- ``agents/developer.md``'s own copy,
the one an actual lane reads and copies from, is the only one this file still
checks.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVELOPER = REPO_ROOT / "agents" / "developer.md"

RECON_CALL_RE = re.compile(
    r'Agent\(subagent_type:\s*"oss:recon"[^\n]*?run_in_background:\s*false'
)


def _recon_calls(text):
    return RECON_CALL_RE.findall(text)


def test_developer_md_documents_a_blocking_recon_call():
    """Positive control for the fix itself: without this, the checks below would
    have nothing to check and the lane would still have no call shape to copy."""
    text = DEVELOPER.read_text(encoding="utf-8")
    calls = _recon_calls(text)
    assert calls, (
        "agents/developer.md documents no oss:recon Agent(...) call carrying "
        "run_in_background: false -- a lane reading only this file has no call "
        "shape to copy, and nothing stops it from backgrounding the spawn (#1586)"
    )


def test_a_backgrounded_call_would_not_satisfy_the_check():
    """Positive control for the regex itself: a call carrying
    run_in_background: true must not match, or the checks above prove
    nothing about blocking specifically."""
    bad = (
        'Agent(subagent_type: "oss:recon", model: "sonnet", '
        'run_in_background: true, prompt: "...")'
    )
    assert not _recon_calls(bad), (
        "fixture construction failed: a backgrounded call satisfies the "
        "call-shape check, so the check cannot tell blocking from "
        "backgrounded and proves nothing about #1586's own subject"
    )


def test_a_call_missing_run_in_background_would_not_satisfy_the_check():
    """Second positive control: a call naming no run_in_background token at
    all -- the exact shape #1586 observed a lane exploiting -- must not
    match either."""
    bad = 'Agent(subagent_type: "oss:recon", model: "sonnet", prompt: "...")'
    assert not _recon_calls(bad), (
        "fixture construction failed: a call with no run_in_background at "
        "all satisfies the check, so the check would have passed the exact "
        "brief text #1586 reports as the defect"
    )
