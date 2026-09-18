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

The fix: `on-default` must call `branch_protection_state` directly (never inferring it from
the findings-only run) before writing anything, and must never write-then-commit when that
call answers anything other than `not-protected`. A self-review round found the first draft
named the function with no runnable invocation the spawn's Bash-only tool grant could
actually issue (no CLI wrapper exists), and that a naive `import
doctor_check_branch_protection` raises a circular-import error -- fixed by giving a literal,
tested `python3 -c` snippet that imports `doctor` instead (which re-exports the name).

This is a content-pin test over agents/doctor.md's own prose (the same class as
tests/test_recon_call_shape_1586.py) -- it cannot prove a spawn obeys its brief, only that
the brief still says what it must. The anchored-block tests below additionally guard against
the specific weak-test shape a reviewer found in the first draft: three independent
substring/regex checks anywhere in the file, satisfiable by prose that names every token
while routing `protected` to something other than `could-not-repair`.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_MD = REPO_ROOT / "agents" / "doctor.md"
DOCTOR_CMD_MD = REPO_ROOT / "commands" / "doctor.md"
RUN_MD = REPO_ROOT / "commands" / "run.md"


def _text():
    return DOCTOR_MD.read_text(encoding="utf-8")


def _on_default_block():
    """The on-default bullet alone, from its own dash to the next top-level dash
    ('   - `on-other`') -- so a claim can be checked as belonging to THIS disposition
    rather than appearing anywhere in the file."""
    text = _text()
    match = re.search(r"- `on-default` --.*?(?=\n\s{3}- `on-other`)", text, re.DOTALL)
    assert match, (
        "could not locate the on-default bullet as its own block -- fixture broken"
    )
    return match.group(0)


def test_on_default_names_branch_protection_state_before_writing():
    block = _on_default_block()
    assert "branch_protection_state" in block, (
        "the on-default block never names branch_protection_state -- a spawn reading "
        "only this bullet has no instruction to check protection before writing (#1649)"
    )


def _bash_fence(block):
    """The literal ```bash ... ``` fence inside the on-default block -- the actual
    runnable command, as distinct from the prose around it that may reference the
    wrong import form while explaining why it is wrong."""
    match = re.search(r"```bash\n(.*?)\n\s*```", block, re.DOTALL)
    assert match, "on-default block has no ```bash fence -- fixture broken"
    return match.group(1)


def test_on_default_gives_a_runnable_invocation_not_just_a_name():
    """A self-review finding: naming a bare Python function is not itself runnable by
    a spawn granted only Bash -- there must be a literal command to copy."""
    block = _on_default_block()
    assert "python3 -c" in block, (
        "the on-default block names branch_protection_state but gives no runnable "
        "python3 -c invocation a Bash-only spawn could actually issue (#1649)"
    )
    fence = _bash_fence(block)
    assert (
        "import doctor" in fence
        and "import doctor_check_branch_protection" not in fence
    ), (
        "the RUNNABLE invocation (the ```bash fence itself, not the surrounding prose) "
        "must import `doctor` (which re-exports branch_protection_state after "
        "resolving the circular import), never `doctor_check_branch_protection` "
        "directly -- a direct import raises ImportError: cannot import name "
        "'SETTINGS_PAGE_URL' from partially initialized module (#1649, confirmed by "
        "running both forms)"
    )


def test_protected_and_could_not_tell_both_route_to_could_not_repair_within_the_block():
    """Anchored version of the could-not-repair check: both `protected` and
    `could-not-tell` must be routed to could-not-repair INSIDE the on-default block
    itself, not merely present somewhere in the file -- the shape a reviewer showed
    could satisfy three unordered substring checks while still writing-then-committing
    unconditionally."""
    block = _on_default_block()
    assert re.search(r"protected.{0,400}could-not-repair", block, re.DOTALL), (
        "the on-default block does not route a `protected` answer to could-not-repair "
        "within its own text (#1649)"
    )
    assert re.search(r"could-not-tell.{0,600}could-not-repair", block, re.DOTALL), (
        "the on-default block does not route a `could-not-tell` answer to "
        "could-not-repair within its own text (#1649)"
    )


def test_only_not_protected_reaches_write_then_commit():
    """The write-then-commit sentence must be gated on `not-protected` specifically,
    not merely mention it somewhere near the write instruction."""
    block = _on_default_block()
    assert re.search(r"not-protected.{0,80}write", block, re.DOTALL), (
        "the on-default block's write-then-commit instruction is not visibly gated "
        "on printing `not-protected` (#1649)"
    )


def test_findings_only_suppression_of_the_ok_case_is_called_out():
    block = _on_default_block()
    assert "--findings" in block and ("suppress" in block.lower() or "1455" in block), (
        "the on-default block never explains why the spawn's own findings-only run "
        "cannot be trusted to reveal a protected branch (check_branch_protection "
        "reports OK, and --findings suppresses OK lines, #1455) -- without that, a "
        "future edit could reasonably assume the findings run alone is enough and "
        "revert to reading it (#1649)"
    )


def test_doctor_cmd_md_vocabulary_line_names_could_not_repair():
    """commands/doctor.md relays the chase agent's report in a fixed vocabulary list
    -- a reviewer found the first draft left this stale at three states after the
    fix added a fourth."""
    text = DOCTOR_CMD_MD.read_text(encoding="utf-8")
    assert "could-not-repair:" in text, (
        "commands/doctor.md's relay instructions still enumerate only "
        "repaired:/not-ours:/could-not-tell:, missing the new could-not-repair: "
        "outcome (#1649)"
    )


def test_run_md_vocabulary_line_names_could_not_repair():
    text = RUN_MD.read_text(encoding="utf-8")
    assert "could-not-repair:" in text, (
        "commands/run.md's relay instructions still enumerate only "
        "repaired:/not-ours:/could-not-tell:, missing the new could-not-repair: "
        "outcome (#1649)"
    )
