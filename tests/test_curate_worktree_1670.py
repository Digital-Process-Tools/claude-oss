"""#1670: the curate step (`commands/run/curate.md`, run by `oss:scheduler-step`)
worked directly in the primary clone. A tick running concurrently in the same
clone took a `tree_snapshot.py` before/after pair spanning curate's own write
window and reported a mutation it did not cause -- curate had promoted a
trap.d/ fragment into a jit-context rule and deleted the fragment as part of
that promotion, while the clone sat checked out on `curate/<timestamp>`. The
underlying defect, confirmed in the issue's own follow-up comment: two
writers, one working tree, no lock and no notice between them.

`.claude/jit-context/paths/00-manual/run-step-worktree-and-pr-ownership.md`
already named this shape (observed on PR #1575) but was advisory prose only,
shown to an agent's context -- it did not stop the recurrence in #1670.

The fix: `curate.md` now states, in the same explicit shape
`agents/developer.md` uses for a developer lane, that it must cut and work
inside its own worktree (`worktree_root`/`clone` from `.oss.json` and
`.oss.local.json`, branched `curate/<UTC timestamp>` off the default branch)
and never work directly in the primary clone.

Content-invariant checks, the same `_collapse` + substring pattern this
repo's own content-invariant test files already use over prose -- see
`tests/test_content_invariants.py` for the general shape.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE = REPO_ROOT / "commands" / "run" / "curate.md"


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _curate_text():
    return CURATE.read_text(encoding="utf-8")


def test_curate_md_says_never_work_in_the_primary_clone():
    collapsed = _collapse(_curate_text())
    assert re.search(r"never.{0,40}(the )?primary clone", collapsed, re.IGNORECASE), (
        "curate.md does not say to never work in the primary clone -- without "
        "that, a tick running concurrently in the same clone can observe "
        "curate's own writes as an unexplained mutation (#1670)"
    )


def test_curate_md_says_to_cut_a_worktree():
    collapsed = _collapse(_curate_text())
    assert "git worktree add" in collapsed, (
        "curate.md does not give the literal `git worktree add` call -- "
        "without a pinned call shape, a pass is free to reinvent (or skip) "
        "worktree isolation exactly like the developer lane's own recon "
        "call had to be pinned for the same reason (#1586)"
    )


def test_curate_md_worktree_call_uses_worktree_root_and_default_branch():
    collapsed = _collapse(_curate_text())
    assert "worktree_root" in collapsed and "default_branch" in collapsed, (
        "curate.md's worktree instruction does not name worktree_root or "
        "default_branch -- a hardcoded path or branch here is exactly the "
        "kind of repo-specific fact test_content_invariants.py forbids"
    )


def test_curate_md_branch_naming_convention_is_unchanged():
    # Positive control: the pre-#1670 curate/<UTC timestamp> branch-naming
    # convention must survive this change untouched -- the worktree fix
    # reuses that same branch name, it does not replace it.
    collapsed = _collapse(_curate_text())
    assert "curate/<UTC timestamp>" in collapsed, (
        "curate.md lost its own curate/<UTC timestamp> branch-naming "
        "convention -- the worktree fix should reuse it, not replace it"
    )
