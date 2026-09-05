"""#245 step 3: the "What comes back, and opening the pull request" section of SKILL.md,
loaded unconditionally on every tick, moves to a jit-context rule that fires only when a
`gh-pr-create` command is about to run -- the same shape #245 step 1 (#859) used for the
merge gates, keyed on `gh-pr-merge`.

`scripts/oss_rules.py` is the one place the `01-oss` layer is declared -- `install()`
deletes and rewrites the layer on every run, so a rule added only to the tracked copy under
`.claude/jit-context/` is discarded by the next `/oss:scaffold --apply` and never reaches a
managed repository (#702). So the new rule has to exist in `oss_rules.RULES["tools"]`, be
indexed by `index_rows()`, and be tracked byte-identically under
`.claude/jit-context/tools/01-oss/`.

Per the `claude-jit-context:vocabulary` skill, a rule that ships without a demonstration that
it fires is the inert-layer bug #144 already shipped once -- so this file also drives the
real installed hook, both directions, using the same `jit_hook_harness` module
`test_jit_agent_dispatch.py` and `test_merge_gate_jit_rule_245.py` already use for that
purpose.
"""

import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import jit_hook_harness  # noqa: E402
import oss_rules  # noqa: E402

PR_CREATE_GATE = "pr-create-gate.md"

#: A realistic pull-request-open command, the exact shape
#: skills/manager/phases/handback.md tells the loop to type.
REALISTIC_PR_CREATE_COMMAND = "supertool 'gh-pr-create:@/tmp/pr-payload.toml'"

#: Must-not-fire control: an ordinary Bash call that has nothing to do with opening a
#: pull request.
UNRELATED_COMMAND = "git status"


def _rule_body():
    return oss_rules.RULES.get("tools", {}).get(PR_CREATE_GATE)


# --- 1. the rule exists in the generator, keyed correctly ---------------------------


def test_the_generator_ships_a_pr_create_gate_tools_rule():
    body = _rule_body()
    assert body, "oss_rules.RULES['tools'] carries no {}".format(PR_CREATE_GATE)
    assert oss_rules._field(body, "tool") == "Bash", (
        "the pr-create-gate rule is not keyed on the Bash tool"
    )


def test_the_pr_create_gate_match_actually_matches_a_realistic_gh_pr_create_command():
    """The trigger has to be exercised against the literal command string the loop
    types, not just declared -- a `match:` that looks plausible and never fires is
    exactly #144's inert-layer bug one file over."""
    body = _rule_body()
    match = oss_rules._field(body, "match")
    assert match, "the pr-create-gate rule declares no match:"
    pattern = match[1:] if match.startswith("~") else re.escape(match)
    assert re.search(pattern, REALISTIC_PR_CREATE_COMMAND), (
        "match: {!r} does not fire on {!r}".format(match, REALISTIC_PR_CREATE_COMMAND)
    )
    assert not re.search(pattern, UNRELATED_COMMAND), (
        "match: {!r} fires on an unrelated command {!r} -- too wide".format(
            match, UNRELATED_COMMAND
        )
    )


def test_the_pr_create_gate_rule_is_a_reminder_not_a_block():
    """Blocking every gh-pr-create call outright would refuse opening the pull request
    itself, not just remind of the don't-retype and Closes-#N argument -- that is not
    what #245 asks for."""
    body = _rule_body()
    mode = oss_rules._field(body, "mode") or "remind"
    assert mode == "remind", (
        "the pr-create-gate rule is mode: {!r}, expected remind".format(mode)
    )


def test_the_pr_create_gate_rule_points_at_the_full_argument():
    body = _rule_body()
    assert "skills/manager/phases/handback.md" in body, (
        "the pr-create-gate rule does not point at the phase file carrying the full argument"
    )


# --- 2. it is indexed, and the tracked copy in this repo matches the generator ------


def test_the_pr_create_gate_rule_gets_an_index_row(tmp_path):
    written = oss_rules.install(tmp_path)
    layer = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    rows = (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines()
    named = {row.split("\t")[2] for row in rows if row.strip()}
    assert PR_CREATE_GATE in named, "the pr-create-gate rule was not indexed at all"
    record = layer / PR_CREATE_GATE
    assert record in written


def test_the_tracked_copy_in_this_repo_matches_the_generator():
    tracked = (
        REPO_ROOT
        / ".claude"
        / "jit-context"
        / "tools"
        / oss_rules.LAYER
        / PR_CREATE_GATE
    )
    assert tracked.is_file(), (
        "{} does not exist -- the generator ships the rule but this repository's own "
        "layer, which is what a session actually reads, does not carry it (#702's own "
        "failure mode)".format(tracked)
    )
    on_disk = tracked.read_text(encoding="utf-8")
    body = _rule_body()
    assert on_disk.replace("\r\n", "\n") == body.replace("\r\n", "\n"), (
        "the tracked copy and the generator constant have diverged"
    )


def test_the_tracked_index_carries_the_new_row():
    index = (
        REPO_ROOT
        / ".claude"
        / "jit-context"
        / "tools"
        / oss_rules.LAYER
        / oss_rules.INDEX
    )
    rows = index.read_text(encoding="utf-8").splitlines()
    named = {row.split("\t")[2] for row in rows if row.strip()}
    assert PR_CREATE_GATE in named, "the tracked 00-index.tsv has no row for {}".format(
        PR_CREATE_GATE
    )


# --- 3. proof it fires: drive the real hook, both directions -----------------------


def _driven(tmp_path):
    hook, version, why_not = jit_hook_harness.hook_path()
    if hook is None:
        pytest.skip(
            "{} -- untested: whether the pr-create-gate rule fires against the "
            "installed hook".format(why_not)
        )
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH, so the installed hook could not be driven")
    project = tmp_path / "repo"
    project.mkdir()
    oss_rules.install(project)
    return bash, hook, project, version


def test_the_pr_create_gate_rule_fires_on_a_real_gh_pr_create_command(tmp_path):
    bash, hook, project, version = _driven(tmp_path)
    body = _rule_body()
    title = oss_rules._frontmatter(body)
    # A short, distinctive fragment of the rule's own title -- proof the INJECTED
    # content is this rule and not some other one that happened to fire.
    sentinel = "gh-pr-create: don't retype"
    assert sentinel in title, "test sentinel drifted from the rule's own title"

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        {"tool_name": "Bash", "tool_input": {"command": REALISTIC_PR_CREATE_COMMAND}},
    )
    assert problem is None, problem
    assert sentinel in answer, (
        "{} did not inject the pr-create-gate rule for a realistic gh-pr-create command. "
        "Got: {!r}".format(version, answer[:400])
    )


def test_the_pr_create_gate_rule_does_not_fire_on_an_unrelated_command(tmp_path):
    """Must-not-fire control, without which the assertion above is equally satisfied
    by a rule that injects on every Bash call."""
    bash, hook, project, version = _driven(tmp_path)
    body = _rule_body()
    sentinel = "gh-pr-create: don't retype"

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        {"tool_name": "Bash", "tool_input": {"command": UNRELATED_COMMAND}},
    )
    assert problem is None, problem
    assert sentinel not in answer, (
        "{} injected the pr-create-gate rule for an unrelated command {!r} -- the "
        "match: is too wide. Got: {!r}".format(version, UNRELATED_COMMAND, answer[:400])
    )


# --- 4. SKILL.md's own spine section is trimmed to a pointer -----------------------


def test_skill_md_pull_request_section_is_a_short_pointer():
    text = (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(encoding="utf-8")
    start = text.index("## What comes back, and opening the pull request")
    end = text.index("\n## ", start + 1)
    section = text[start:end]
    assert len(section.splitlines()) <= 12, (
        "SKILL.md's own pull-request section is still {} lines -- #245 asks for a short "
        "pointer now that the gh-pr-create argument lives in the jit-context layer".format(
            len(section.splitlines())
        )
    )
    assert ".claude/jit-context/tools/01-oss/{}".format(PR_CREATE_GATE) in section, (
        "the trimmed section does not name the jit rule that replaces it"
    )
    assert "skills/manager/phases/handback.md" in section, (
        "the trimmed section drops the pointer to the phase file's full argument"
    )


# --- 5. the call this rule now carries a copy of -----------------------------------


#: The same pattern tests/test_agent_report_schema.py uses over the manager loop's own
#: prose: python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report_schema.py" <SOMETHING>
DOCUMENTED_CALL_RE = re.compile(r'report_schema\.py"?\s+(<[^>\n]+>)')


def test_the_rule_documents_the_report_path_and_not_the_payload_path():
    """The rule carries a third copy of the maintainer's one verification call, and a
    copy nothing checks is a copy that drifts.

    `tests/test_agent_report_schema.py` runs the validator against whichever of the two
    files a finished run leaves that the loop's own prose names -- and pins that a call
    aimed at the *payload* exits 1 with a seventeen-line diagnostic about a file with
    nothing wrong with it. That guard reads the manager loop's documents; this rule is
    not one of them, so the same drift here would be caught by nothing. Asserted at the
    level this file can afford: the placeholder names the report, never the payload.
    """
    body = _rule_body()
    placeholders = DOCUMENTED_CALL_RE.findall(body)
    assert placeholders, (
        "the pr-create-gate rule documents no report_schema.py invocation -- either it "
        "stopped carrying the check, or this pattern no longer matches how it writes "
        "it, and a pattern that matched nothing has checked nothing"
    )
    for placeholder in placeholders:
        lowered = placeholder.lower()
        assert "report" in lowered, (
            "the rule documents {} -- a report_schema.py call must name the report "
            "path".format(placeholder)
        )
        assert "payload" not in lowered and "pr_body" not in lowered, (
            "the rule documents {} -- pointed at the payload this call exits 1 on a "
            "correct run, which is the defect the loop's own copy of it pins".format(
                placeholder
            )
        )
