"""Step 2's board read must not silently cap the issue queue at 50 (#593).

`gh-issues` bare caps at `--limit 50` (`claude-supertool`'s own `DEFAULT_PER_PAGE`).
`commands/tick.md` step 2 used to prescribe that bare call as a literal to copy, and
a literal to copy outranks a reminder to think -- the op's own footer disclosed the
cap on every call and it changed nothing, because nobody reads a footer for a command
they are about to paste verbatim. A repo with 88 open issues read as 50, and the 38
unread issues were structurally invisible to the loop meant to triage them.

`per=100` raises the cap; it does not remove it. So the fix has two parts and this
file checks both: the prescribed literal has to widen the call, and the prose beside
it has to teach the three-state reading -- uncapped, capped-with-a-count-that-is-a-
floor-not-a-total, or genuinely empty -- because a bigger number with no habit change
just moves the same silent failure to a bigger repo.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

TICK_MD = REPO_ROOT / "commands" / "tick.md"

#: The board-read code block itself -- the literal a reader copies. Each op's
#: filter suffix is its own capture group, including gh-prs and gh-branch, so a
#: regression that widens the WRONG op (or widens all four) is distinguishable
#: from one that widens gh-issues -- see test_the_other_three_ops_in_the_block_are_untouched.
BOARD_READ_RE = re.compile(
    r"```bash\s*\n\s*supertool\s+'gh-prs([^']*)'\s+'gh-issues([^']*)'\s+'gh-branch([^']*)'\s+'git-worktrees([^']*)'\s*\n\s*```"
)


def _text():
    return TICK_MD.read_text(encoding="utf-8")


def _flowed():
    return re.sub(r"\s+", " ", _text())


def test_the_board_read_block_still_matches():
    """Positive control: without this, every assertion below is vacuous."""
    assert BOARD_READ_RE.search(_text()), (
        "commands/tick.md step 2 no longer prescribes the board-read literal in "
        "the shape BOARD_READ_RE reads -- either the step was reworded (update the "
        "pattern) or the board read stopped batching these four ops."
    )


def test_gh_issues_is_widened_past_the_silent_default():
    """The literal a reader copies must not be the bare, 50-capped spelling."""
    match = BOARD_READ_RE.search(_text())
    assert match, "board-read block not found (see test above)"
    gh_issues_suffix = match.group(2)
    assert "per=" in gh_issues_suffix, (
        "commands/tick.md step 2 still prescribes bare `gh-issues` with no `per=`, "
        "which caps at 50 (claude-supertool's DEFAULT_PER_PAGE) -- a repo with more "
        "open issues than that reads as 50, silently. #593."
    )
    per_value = re.search(r"per=(\d+)", gh_issues_suffix)
    assert per_value and int(per_value.group(1)) > 50, (
        "the prescribed `per=` must raise the cap above the 50-issue silent default, "
        "not merely restate it."
    )


def test_the_other_three_ops_in_the_block_are_untouched():
    """Negative control: this fix is about `gh-issues`, not a blanket `per=` habit.

    A genuine control, not one guaranteed by the regex's own literals: gh-prs and
    gh-branch each carry their own optional filter-suffix capture group (see
    BOARD_READ_RE), so this fails for real if a future edit widens the wrong op --
    it would still MATCH (unlike relying on the earlier test), and then fail HERE
    with a message that names the actual regression.
    """
    match = BOARD_READ_RE.search(_text())
    assert match, "board-read block not found (see first test)"
    gh_prs_suffix, gh_branch_suffix, worktrees_suffix = (
        match.group(1), match.group(3), match.group(4)
    )
    assert gh_prs_suffix == "" and gh_branch_suffix == "" and worktrees_suffix == "", (
        "gh-prs, gh-branch and git-worktrees must stay bare in the board-read "
        "literal (got suffixes {!r}, {!r}, {!r}) -- this fix targets gh-issues's "
        "own silent cap, not every op in the call.".format(
            gh_prs_suffix, gh_branch_suffix, worktrees_suffix
        )
    )


def test_the_step_teaches_the_cap_is_still_a_cap():
    """`per=100` alone repeats the bug at a bigger number -- prose has to say so.

    The step must name the op's own three-state footer (uncapped / capped-with-a-
    floor / genuinely empty) so a maintainer reading a capped footer treats the
    count as "at least N", never as "the whole backlog" -- the reading #593's board
    silently skipped.
    """
    flowed = _flowed()
    assert "capped at --limit" in flowed, (
        "commands/tick.md step 2 no longer cites the op's own cap-disclosure "
        "wording (capped at --limit N -- more may exist, raise with per=N), so a "
        "reader has nothing telling them a capped footer is not the whole board."
    )
    assert re.search(r"raise\s+`?per=", flowed) or "raise with per=" in flowed, (
        "commands/tick.md step 2 must tell the reader what to do when the footer "
        "reports a cap: raise per= again, not treat the count as final."
    )


def test_a_step_silent_about_the_cap_would_fail():
    """Negative control, pointed at BOTH assertions in the test above, separately.

    `test_the_step_teaches_the_cap_is_still_a_cap` makes two independent claims --
    the cap-disclosure wording is cited, AND the reader is told to raise `per=`
    again. A control that only tries a string missing both proves nothing about
    whether either assertion would catch losing just the other, so this checks
    each half on a step shaped to be missing only that half.
    """
    missing_cap_wording = (
        "2. Read the board, batched into one call:\n\n"
        "   ```bash\n"
        "   supertool 'gh-prs' 'gh-issues:per=100' 'gh-branch' 'git-worktrees'\n"
        "   ```\n"
        "   This widens the cap from 50 to 100; raise per= again if it is still capped.\n"
    )
    flowed = re.sub(r"\s+", " ", missing_cap_wording)
    assert "capped at --limit" not in flowed
    assert re.search(r"raise\s+`?per=", flowed) or "raise with per=" in flowed

    missing_raise_instruction = (
        "2. Read the board, batched into one call:\n\n"
        "   ```bash\n"
        "   supertool 'gh-prs' 'gh-issues:per=100' 'gh-branch' 'git-worktrees'\n"
        "   ```\n"
        "   gh-issues names its population as capped at --limit N when it stopped short.\n"
    )
    flowed = re.sub(r"\s+", " ", missing_raise_instruction)
    assert "capped at --limit" in flowed
    assert not (re.search(r"raise\s+`?per=", flowed) or "raise with per=" in flowed)
