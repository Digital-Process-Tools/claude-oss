"""#1083: `filed_by_loop`'s attach-directive turns on provenance, not on which
call site typed the issue up.

`accounting.md` used to say, unconditionally, "attach it to every issue this
loop files" -- read literally that also tags an issue the maintainer and the
loop decided on together in a session and then asked the loop to write up,
which contradicts two things the same file already says: the intake
numerator counts filings "the loop itself filed" (excluding maintainer
asks), and the dispatch rank function (`select_issues_rank.rank`) reads the
label as settling authorship outright -- a labelled issue is unconditionally
`author: "loop"`. A co-decided issue carrying the label would rank in the
loop's own band instead of the maintainer's.

#1178 found that `dispatch.md` and `tick-order.md` both pointed at
`select_issues.py --board` right after truthfully describing the *default*,
no-flags mode as taking no stdin input at all, while `--board` was a
different, older CLI mode that DID read a board-shaped payload on stdin --
a careful reader who just read "no stdin payload" about the default mode
drew the wrong conclusion at the `--board` call site and got a
`stdin: not valid JSON` failure for their trouble, observed live three
times in one tick. #1178's own fix (PR #1195) documented the exception at
both call sites; #1200 replaced that with the other shape -- `--board` now
fetches its own board too, the same way the default mode does, so there is
no exception left to document. The four tests #1195 added to pin the
documented-exception shape are replaced below by tests pinning its
opposite: no stdin contract left to describe, at either call site or in
the code's own docstring.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

ACCOUNTING = (REPO_ROOT / "skills" / "manager" / "phases" / "accounting.md").read_text(
    encoding="utf-8"
)
DISPATCH = (REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md").read_text(
    encoding="utf-8"
)
TICK_ORDER = (REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md").read_text(
    encoding="utf-8"
)
SELECT_ISSUES = (REPO_ROOT / "scripts" / "select_issues.py").read_text(encoding="utf-8")


def test_the_old_unconditional_attach_sentence_is_gone():
    """The literal old sentence -- "attach it to every issue this loop
    files" with no provenance qualifier -- must not survive the fix. Regexed
    loosely enough to catch a near-identical rewording, not just the exact
    string."""
    assert "attach it to every issue this loop\nfiles" not in ACCOUNTING
    assert "attach it to every issue this loop files" not in ACCOUNTING


def test_attach_directive_turns_on_initiative_not_call_site():
    assert "on its own\ninitiative" in ACCOUNTING or "on its own initiative" in (
        ACCOUNTING.replace("\n", " ")
    )


def test_co_decided_issues_are_explicitly_excluded():
    normalized = ACCOUNTING.replace("\n", " ")
    assert "decided together with the maintainer" in normalized
    assert "even when the loop is the one that types it up and files it" in normalized


def test_provenance_is_per_issue_not_per_session():
    normalized = ACCOUNTING.replace("\n", " ")
    assert "per issue, not per session" in normalized


def test_no_new_label_or_state_is_implied():
    normalized = ACCOUNTING.replace("\n", " ")
    assert "creates no new label and no new state" in normalized


def test_1083_is_cited():
    assert "#1083" in ACCOUNTING


def test_neither_call_site_documents_a_board_stdin_contract_any_more():
    """#1200: `--board` no longer reads stdin at all, so #1178's own fix
    (documenting the exception) has nothing left to document. Neither
    phase file may still claim `--board` reads a board-shaped payload on
    stdin -- that sentence describes code this branch deletes."""
    for name, text in (("dispatch.md", DISPATCH), ("tick-order.md", TICK_ORDER)):
        normalized = text.replace("\n", " ")
        assert "--board" in text, name
        assert "reads a board-shaped payload on stdin" not in normalized, name
        assert "reads the same board shape on stdin" not in normalized, name


def test_select_issues_py_no_longer_reads_stdin_for_board_either():
    """Pins the code fact the prose depends on: `--board` fetches its own
    board now, the identical route the default mode uses, so a future
    change reintroducing a stdin read here fails this test rather than
    leaving the prose stale."""
    assert "still reads its own board-shaped payload on stdin" not in SELECT_ISSUES
    assert "_read_stdin_json" not in SELECT_ISSUES
    assert "fetches its own board too" in SELECT_ISSUES


def test_skill_md_op_table_no_longer_states_the_unconditional_attach_rule():
    """The reviewer's third finding: `skills/manager/SKILL.md`'s own op
    table carried the pre-#1083 unconditional "every time" reading in its
    `Filing` row, directly contradicting accounting.md's new provenance
    directive at a second, equally load-bearing call site."""
    skill_md = (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "label, every time (#762, #798)" not in skill_md
    normalized = skill_md.replace("\n", " ")
    assert "on its own initiative" in normalized
    assert "#1083" in normalized
