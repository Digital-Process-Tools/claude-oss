"""#1649: `on-default`'s write-then-commit path never checked branch protection.

`agents/doctor.md`'s `on-default` disposition told a doctor spawn to write an owned-file
repair and `git commit` it straight onto the default branch, unconditionally, and called
the result `repaired`. On a repo whose default branch is protected
(`required_pull_request_reviews`, or an active ruleset), that commit cannot land except
through a bypass push -- the exact push claude-jit-context's own v0.10.0 release used the
day before this was filed. `repaired: ... (committed <sha>)` on a branch the commit cannot
reach without a bypass is the absence-rendered-as-clean shape this plugin is named after,
one level up: a repair that landed nowhere renders identically to a repair that worked.

Worse, the diagnostic already runs `check_branch_protection` (scripts/
doctor_check_branch_protection.py) as part of the SAME `doctor.sh --findings` pass a
doctor spawn runs first -- but that check reports `OK` when the branch IS protected, and
`--findings` mode suppresses OK lines by design (#1455). So a doctor spawn that only reads
its own findings-only output will never see the one line that would have told it to stop.

The fix: `on-default` must call `doctor_check_branch_protection.branch_protection_state`
directly (never inferring it from the findings-only run) before writing anything, and must
never write-then-commit when that call answers anything other than `not-protected`.

This is a content-pin test over agents/doctor.md's own prose (the same class as
tests/test_recon_call_shape_1586.py) -- it cannot prove a spawn obeys its brief, only that
the brief still says what it must.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_MD = REPO_ROOT / "agents" / "doctor.md"


def _text():
    return DOCTOR_MD.read_text(encoding="utf-8")


def test_on_default_names_branch_protection_state_before_writing():
    text = _text()
    assert "branch_protection_state" in text, (
        "agents/doctor.md's on-default clause never names "
        "doctor_check_branch_protection.branch_protection_state -- a spawn reading only "
        "this file has no instruction to check protection before writing (#1649)"
    )


def test_on_default_names_a_could_not_repair_outcome_for_a_protected_branch():
    text = _text()
    assert re.search(r"could-not-repair", text), (
        "agents/doctor.md names no could-not-repair outcome for a protected default "
        "branch -- without it, on-default has nowhere to route a protected-branch "
        "answer except the old unconditional write-then-commit path (#1649)"
    )


def test_findings_only_suppression_of_the_ok_case_is_called_out():
    text = _text()
    assert "--findings" in text and ("suppress" in text.lower() or "1455" in text), (
        "agents/doctor.md's branch-protection instruction never explains why the "
        "spawn's own findings-only run cannot be trusted to reveal a protected branch "
        "(check_branch_protection reports OK, and --findings suppresses OK lines, #1455) "
        "-- without that, a future edit could reasonably assume the findings run alone "
        "is enough and revert to reading it (#1649)"
    )
