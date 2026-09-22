"""Issue #1693: `commands/run/curate.md` cuts a worktree and a branch before
it ever reads what is waiting, but a `none waiting` result ended the pass
with no teardown step anywhere in the file -- so a pass with nothing to
curate still left a worktree behind that `worktree_reap.py`'s own gate would
never reap, since the branch never carries a pull request at all
(`branch_merge_state` reads `not-merged`, "no pull request on record", and
`plan_reap` keeps anything `not-merged` forever).

The fix: `none waiting` now removes the worktree and branch it just cut,
before stopping -- nothing was ever written to it, so nothing is lost.
`could-not-read` is the mirror control: an error worth a human looking at,
so the worktree stays in place rather than being torn down.

Same `_collapse` + substring pattern as `tests/test_curate_worktree_1670.py`.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE = REPO_ROOT / "commands" / "run" / "curate.md"


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _curate_text():
    return CURATE.read_text(encoding="utf-8")


def test_none_waiting_removes_the_worktree_it_just_cut():
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("none waiting` ends the pass")
    assert idx != -1, (
        "curate.md no longer says `none waiting` ends the pass in the "
        "expected sentence shape"
    )
    tail = collapsed[idx : idx + 700]
    assert "git worktree remove" in tail, (
        "`none waiting` does not remove the worktree it just cut -- nothing "
        "was written to it, so leaving it behind strands a tree no reap gate "
        "will ever take (#1693, since a branch with no pull request on "
        "record is kept forever by worktree_reap.py's own gate)"
    )
    assert "git branch -D" in tail, (
        "`none waiting` removes the worktree but not its branch -- a stray "
        "ref left behind (#1693)"
    )


def test_could_not_read_is_the_must_not_fire_control():
    """Positive-control pairing: the error path must NOT be swept into the
    same teardown, since a directory that could not be listed is worth a
    human looking at, not a clean exit to tear down after."""
    collapsed = _collapse(_curate_text())
    idx = collapsed.find("could-not-read")
    assert idx != -1
    # The nearest teardown call must not immediately follow the
    # could-not-read sentence the way it follows none-waiting's.
    tail = collapsed[idx : idx + 200]
    assert "git worktree remove" not in tail, (
        "could-not-read must not be swept into the same immediate teardown "
        "as none-waiting -- an unreadable trap.d/ is worth a human looking "
        "at, not a clean exit"
    )
