"""Issue #1736: `commands/run/curate.md`'s decline arm had no step checking a

code defect's claim against the code before writing the decline line. #1275
routes a non-blocking finding to `trap.d/` instead of the tracker, and a
fragment describing a one-off code defect (not an agent-facing lesson) is
exactly the shape this pass correctly declines -- so, together, the two
correct rules deleted the bug: nothing at any step ever filed it. Observed on
claude-supertool 2026-09-23: curate declined 12 fragments as "not an
agent-facing lesson"; 10 were live bugs, and only a hand filing by the
scheduler put them on the board.

The fix: before writing a decline line for a code-claim fragment, check the
claim against the code at HEAD. Still true -> file a tracking issue (or find
the existing one) and cite its number in the decline line. Already fixed ->
name the commit or pull request in the decline line instead. Either way the
decline line carries a citation, never a bare "declined -- one-off defect".

Same `_collapse` + substring pattern as `tests/test_curate_pr_no_close_1552.py`
and `tests/test_curate_none_waiting_teardown_1693.py`.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE = REPO_ROOT / "commands" / "run" / "curate.md"


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _curate_text():
    return CURATE.read_text(encoding="utf-8")


def test_decline_of_a_code_defect_checks_against_head():
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("must never be the only record of it")
    assert idx != -1, (
        "curate.md no longer states that a decline of a live code defect "
        "must never be the only record of it (#1736)"
    )
    tail = collapsed[idx : idx + 900]
    assert "check the claim against the code at HEAD" in tail, (
        "the decline arm does not instruct checking a code-defect claim "
        "against the code at HEAD before declining it (#1736)"
    )


def test_decline_of_a_still_live_defect_files_or_cites_an_issue():
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("must never be the only record of it")
    assert idx != -1
    tail = collapsed[idx : idx + 1800]
    assert "file a tracking issue for it" in tail, (
        "curate.md does not say a still-live code defect must be filed "
        "(or an existing issue cited) rather than only declined (#1736)"
    )
    assert "cite that number in the" in tail, (
        "curate.md does not say to cite the filed issue's number in the "
        "decline line itself (#1736)"
    )
    assert "labels.lane_other" in tail and "labels.priority" in tail, (
        "curate.md's decline-time filing omits the lane/priority labels "
        "review.md's own gh-issue-create shape requires -- an issue filed "
        "without them is invisible to dispatch (#1682, #1736)"
    )


def test_decline_of_an_already_fixed_defect_names_the_fix():
    """Positive-control pairing for the check above: a claim that no longer
    holds must not be filed as a new issue -- it must name what already
    fixed it instead."""
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("must never be the only record of it")
    assert idx != -1
    tail = collapsed[idx : idx + 1800]
    assert "name the commit hash or pull request number" in tail, (
        "curate.md does not say an already-fixed claim must name the "
        "commit or pull request that fixed it, rather than being filed "
        "again as a new issue (#1736)"
    )


def test_decline_has_a_third_cannot_tell_state():
    """Positive-control pairing for the two checks above: an agent that
    genuinely cannot tell whether a code-defect claim still holds must not
    be forced to guess at either of the other two outcomes."""
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("must never be the only record of it")
    assert idx != -1
    tail = collapsed[idx : idx + 1800]
    assert "cannot tell" in tail, (
        "curate.md's decline-time check has no third 'cannot tell' state, "
        "forcing a guess between 'still true' and 'already fixed' when "
        "neither is actually known (#1736)"
    )


def test_an_uncited_decline_line_is_self_refused():
    """The promote outcome refuses itself when a rule ships with no firing
    proof; the decline-time citation rule must carry the same enforcement,
    or nothing distinguishes a pass that checked and forgot to cite from a
    pass that never checked at all."""
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("must never be the only record of it")
    assert idx != -1
    tail = collapsed[idx : idx + 2300]
    assert "refused by this pass itself" in tail, (
        "curate.md's decline-time citation rule states no self-refusal "
        "for an uncited decline line, unlike the promote outcome's own "
        "firing-proof refusal (#1736)"
    )


def test_does_not_reopen_1275():
    """A non-blocking finding still skips the tracker at the moment it is
    found -- this fix only changes what happens at the moment curate
    declines to turn an already-routed fragment into a rule."""
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("does not reopen #1275")
    assert idx != -1, (
        "curate.md's new decline-time filing rule does not say it leaves "
        "#1275's own routing (non-blocking findings skip the tracker at "
        "the moment they are found) untouched (#1736)"
    )
