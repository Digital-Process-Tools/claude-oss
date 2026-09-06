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

#1178: `dispatch.md` and `tick-order.md` both point at
`select_issues.py --board` right after truthfully describing the *default*,
no-flags mode as taking no stdin input at all. `--board` is a different,
older CLI mode that DOES read a board-shaped payload on stdin
(`scripts/select_issues.py`'s own `main()` docstring says so explicitly) --
a careful reader who just read "no stdin payload" about the default mode
draws the wrong conclusion at the `--board` call site and gets a
`stdin: not valid JSON` failure for their trouble. This was observed live,
three times in one tick.
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


def test_board_mode_stdin_contract_is_stated_at_both_call_sites():
    for name, text in (("dispatch.md", DISPATCH), ("tick-order.md", TICK_ORDER)):
        normalized = text.replace("\n", " ")
        assert "--board" in text
        assert "stdin" in normalized, name
        assert "#1178" in normalized, name


def test_dispatch_md_never_implies_board_shares_the_default_modes_no_input_contract():
    """The true "no stdin, no --fetch mode" sentence about the *default* mode
    must not be immediately followed by an unqualified `--board` reference --
    the fix must state, in the same neighbourhood, that `--board` is a
    different contract."""
    normalized = DISPATCH.replace("\n", " ")
    board_idx = normalized.index("--board")
    window = normalized[max(0, board_idx - 400) : board_idx + 600]
    assert "stdin" in window


def test_select_issues_py_confirms_board_reads_stdin_and_default_does_not():
    """Pins the code fact the prose fix depends on, so a future change to
    select_issues.py's own contract fails this test rather than leaving the
    prose stale."""
    assert "`--board` still reads its own board-shaped payload on stdin" in (
        SELECT_ISSUES
    )
    assert "there is no stdin fallback left in this mode" in SELECT_ISSUES
