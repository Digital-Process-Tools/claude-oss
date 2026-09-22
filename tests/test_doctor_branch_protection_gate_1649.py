"""#1649: `on-default`'s write-then-commit path never checked branch protection.

`agents/doctor.md`'s `on-default` disposition told a doctor spawn to write an owned-file
repair and `git commit` it straight onto the default branch, unconditionally, and called
the result `repaired`. On a repo whose default branch is protected
(`required_pull_request_reviews`, or an active ruleset), that commit cannot land except
through a bypass push -- the exact push claude-jit-context's own v0.10.0 release used the
day before this was filed. `repaired: ... (committed <sha>)` on a branch the commit cannot
reach without a bypass is the absence-rendered-as-clean shape this plugin is named after,
one level up: a repair that landed nowhere renders identically to a repair that worked.

**#1687 superseded the fix this file originally pinned.** The original fix made
`branch_protection_state` a WRITE GATE: `not-protected` allowed a write-then-commit
straight onto the default branch, and `protected`/`could-not-tell` refused to write at
all. #1687 found BOTH outcomes still wrong -- a repair the loop makes to somebody's
repository should land on a branch and go through a pull request like any other change,
never straight onto the default branch even when unprotected, and never refused outright
just because the default happens to be protected. #1687's own second and third comments
(read in full before touching this file again) found a further wrinkle: some owned files
are untracked or gitignored (`.oss/statusline.py`, `outbound/README.md`,
`trap.d/README.md` on this repo), and cutting a branch and a pull request for one of those
produces an empty diff -- so the real fix is a prior tracked/untracked/cannot-tell split,
not a uniform branch-for-everything rule.

The current contract, pinned below: `agents/doctor.md` must first determine whether the
path being repaired is tracked by git. An untracked or ignored path is written in the
clone directly, no branch, no commit, `branch_protection_state` not consulted. A tracked
path is written in a fresh worktree on a deterministic `doctor/<check-slug>` branch cut
from the default branch's tip, committed there -- never in the clone -- with
`branch_protection_state` folded into the report as INFORMATION rather than as a gate,
since the branch always needs a pull request to land regardless of protection state. A
path whose tracked state cannot be determined reports `could-not-repair`.

This is a content-pin test over agents/doctor.md's own prose (the same class as
tests/test_recon_call_shape_1586.py) -- it cannot prove a spawn obeys its brief, only that
the brief still says what it must.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_MD = REPO_ROOT / "agents" / "doctor.md"
DOCTOR_CMD_MD = REPO_ROOT / "commands" / "doctor.md"
RUN_MD = REPO_ROOT / "commands" / "run.md"


def _text():
    return DOCTOR_MD.read_text(encoding="utf-8")


def _disposition_block():
    """Disposition 1's own text, from its own numbered item to the next
    top-level numbered item ('2. **Not this repo's') -- so a claim can be
    checked as belonging to THIS disposition rather than appearing anywhere
    in the file."""
    text = _text()
    match = re.search(
        r"1\. \*\*Ours to repair.*?(?=\n2\. \*\*Not this repo)", text, re.DOTALL
    )
    assert match, "could not locate disposition 1 as its own block -- fixture broken"
    return match.group(0)


def test_checks_whether_the_path_is_tracked_before_writing():
    block = _disposition_block()
    assert "tracked by git" in block, (
        "disposition 1 never says it checks whether the repair path is tracked by git "
        "before writing (#1687)"
    )
    assert "git check-ignore" in block and "git ls-files" in block, (
        "disposition 1 names checking whether a path is tracked but gives no runnable "
        "git check-ignore/git ls-files invocation (#1687)"
    )


def test_untracked_case_never_writes_a_commit_and_names_no_sha():
    block = _disposition_block()
    match = re.search(
        r"\*\*Untracked or ignored\*\*.*?(?=\n   - \*\*Tracked)", block, re.DOTALL
    )
    assert match, "the untracked-or-ignored bullet is not its own block (#1687)"
    untracked = match.group(0)
    assert "No worktree, no branch, no commit" in untracked
    assert "branch_protection_state" in untracked and "not consulted" in untracked
    assert "untracked -- no commit" in untracked


def test_tracked_case_cuts_a_worktree_branch_and_never_writes_in_the_clone():
    block = _disposition_block()
    match = re.search(r"\*\*Tracked\*\*.*?(?=\n   - \*\*Cannot tell)", block, re.DOTALL)
    assert match, "the tracked bullet is not its own block (#1687)"
    tracked = match.group(0)
    assert "worktree_root" in tracked
    assert "doctor/<check-slug>" in tracked
    assert "never in the clone" in tracked
    assert "never `git push`" in tracked and "never a pull request" in tracked


def test_branch_protection_state_is_informational_not_a_write_gate():
    """#1687's own reversal of #1649's design: `protected` must no longer stop
    the write. It is still CALLED and folded into the report, but the write
    happens regardless."""
    block = _disposition_block()
    match = re.search(r"\*\*Tracked\*\*.*?(?=\n   - \*\*Cannot tell)", block, re.DOTALL)
    assert match, "the tracked bullet is not its own block (#1687)"
    tracked = match.group(0)
    assert "branch_protection_state" in tracked
    assert "never as a reason to skip the write" in tracked, (
        "the tracked-case bullet names branch_protection_state but does not say it is "
        "informational rather than gating (#1687)"
    )


def test_cannot_tell_case_reports_could_not_repair():
    block = _disposition_block()
    assert re.search(
        r"\*\*Cannot tell\*\*.{0,400}could-not-repair", block, re.DOTALL
    ), (
        "the cannot-tell case does not route to could-not-repair within disposition 1's "
        "own text (#1687)"
    )


def test_clone_head_state_no_longer_gates_the_write_decision():
    block = _disposition_block()
    assert "no longer gates this decision" in block, (
        "disposition 1 does not say clone_head_state stopped gating the write decision "
        "(#1687 collapses the on-default/on-other/could-not-tell split for this purpose)"
    )


def test_doctor_cmd_md_vocabulary_line_names_could_not_repair():
    """commands/doctor.md relays the chase agent's report in a fixed vocabulary list
    -- a reviewer found the first draft left this stale at three states after the
    fix added a fourth."""
    text = DOCTOR_CMD_MD.read_text(encoding="utf-8")
    assert "could-not-repair:" in text, (
        "commands/doctor.md's relay instructions still enumerate only "
        "repaired:/not-ours:/could-not-tell:, missing the could-not-repair: "
        "outcome (#1649)"
    )


def test_run_md_vocabulary_line_names_could_not_repair():
    text = RUN_MD.read_text(encoding="utf-8")
    assert "could-not-repair:" in text, (
        "commands/run.md's relay instructions still enumerate only "
        "repaired:/not-ours:/could-not-tell:, missing the could-not-repair: "
        "outcome (#1649)"
    )
