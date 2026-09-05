"""#245 step 1: the merge-gate section of SKILL.md, loaded unconditionally on every tick,
moves to a jit-context rule that fires only when a `gh-pr-merge` command is about to run.

`scripts/oss_rules.py` is the one place the `01-oss` layer is declared -- `install()`
deletes and rewrites the layer on every run, so a rule added only to the tracked copy under
`.claude/jit-context/` is discarded by the next `/oss:scaffold --apply` and never reaches a
managed repository (#702). So the new rule has to exist in `oss_rules.RULES["tools"]`, be
indexed by `index_rows()`, and be tracked byte-identically under
`.claude/jit-context/tools/01-oss/`.

Per the `claude-jit-context:vocabulary` skill, a rule that ships without a demonstration that
it fires is the inert-layer bug #144 already shipped once -- so this file also drives the
real installed hook, both directions, using the same `jit_hook_harness` module
`test_jit_agent_dispatch.py` already uses for that purpose.
"""

import os
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import doctor  # noqa: E402
import jit_hook_harness  # noqa: E402
import oss_rules  # noqa: E402

MERGE_GATE = "merge-gate.md"

#: A realistic merge command, the exact shape skills/manager/phases/merge.md tells the loop
#: to type.
REALISTIC_MERGE_COMMAND = "supertool 'gh-pr-merge:123:squash|force|cleanup'"

#: Must-not-fire control: an ordinary Bash call that has nothing to do with merging.
UNRELATED_COMMAND = "git status"


def _rule_body():
    return oss_rules.RULES.get("tools", {}).get(MERGE_GATE)


# --- 1. the rule exists in the generator, keyed correctly ---------------------------


def test_the_generator_ships_a_merge_gate_tools_rule():
    body = _rule_body()
    assert body, "oss_rules.RULES['tools'] carries no {}".format(MERGE_GATE)
    assert oss_rules._field(body, "tool") == "Bash", (
        "the merge-gate rule is not keyed on the Bash tool"
    )


def test_the_merge_gate_match_actually_matches_a_realistic_gh_pr_merge_command():
    """The trigger has to be exercised against the literal command string the loop
    types, not just declared -- a `match:` that looks plausible and never fires is
    exactly #144's inert-layer bug one file over."""
    body = _rule_body()
    match = oss_rules._field(body, "match")
    assert match, "the merge-gate rule declares no match:"
    pattern = match[1:] if match.startswith("~") else re.escape(match)
    assert re.search(pattern, REALISTIC_MERGE_COMMAND), (
        "match: {!r} does not fire on {!r}".format(match, REALISTIC_MERGE_COMMAND)
    )
    assert not re.search(pattern, UNRELATED_COMMAND), (
        "match: {!r} fires on an unrelated command {!r} -- too wide".format(
            match, UNRELATED_COMMAND
        )
    )


def test_the_merge_gate_rule_is_a_reminder_not_a_block():
    """Blocking every gh-pr-merge call outright would refuse the merge itself, not
    just remind of the gates -- that is not what #245 asks for."""
    body = _rule_body()
    mode = oss_rules._field(body, "mode") or "remind"
    assert mode == "remind", (
        "the merge-gate rule is mode: {!r}, expected remind".format(mode)
    )


def test_the_merge_gate_rule_points_at_the_full_argument():
    body = _rule_body()
    assert "skills/manager/phases/merge.md" in body, (
        "the merge-gate rule does not point at the phase file carrying the full argument"
    )


# --- 2. it is indexed, and the tracked copy in this repo matches the generator ------


def test_the_merge_gate_rule_gets_an_index_row(tmp_path):
    written = oss_rules.install(tmp_path)
    layer = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    rows = (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines()
    named = {row.split("\t")[2] for row in rows if row.strip()}
    assert MERGE_GATE in named, "the merge-gate rule was not indexed at all"
    record = layer / MERGE_GATE
    assert record in written


def test_the_tracked_copy_in_this_repo_matches_the_generator():
    tracked = (
        REPO_ROOT / ".claude" / "jit-context" / "tools" / oss_rules.LAYER / MERGE_GATE
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
    assert MERGE_GATE in named, "the tracked 00-index.tsv has no row for {}".format(
        MERGE_GATE
    )


# --- 3. proof it fires: drive the real hook, both directions -----------------------


def _driven(tmp_path):
    hook, version, why_not = jit_hook_harness.hook_path()
    if hook is None:
        pytest.skip(
            "{} -- untested: whether the merge-gate rule fires against the installed "
            "hook".format(why_not)
        )
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH, so the installed hook could not be driven")
    project = tmp_path / "repo"
    project.mkdir()
    oss_rules.install(project)
    return bash, hook, project, version


def test_the_merge_gate_rule_fires_on_a_real_gh_pr_merge_command(tmp_path):
    bash, hook, project, version = _driven(tmp_path)
    body = _rule_body()
    title = oss_rules._frontmatter(body)
    # A short, distinctive fragment of the rule's own title -- proof the INJECTED
    # content is this rule and not some other one that happened to fire.
    sentinel = "gh-pr-merge: gates, cleanup"
    assert sentinel in title, "test sentinel drifted from the rule's own title"

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        {"tool_name": "Bash", "tool_input": {"command": REALISTIC_MERGE_COMMAND}},
    )
    assert problem is None, problem
    assert sentinel in answer, (
        "{} did not inject the merge-gate rule for a realistic gh-pr-merge command. "
        "Got: {!r}".format(version, answer[:400])
    )


def test_the_merge_gate_rule_does_not_fire_on_an_unrelated_command(tmp_path):
    """Must-not-fire control, without which the assertion above is equally satisfied
    by a rule that injects on every Bash call."""
    bash, hook, project, version = _driven(tmp_path)
    body = _rule_body()
    sentinel = "gh-pr-merge: gates, cleanup"

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        {"tool_name": "Bash", "tool_input": {"command": UNRELATED_COMMAND}},
    )
    assert problem is None, problem
    assert sentinel not in answer, (
        "{} injected the merge-gate rule for an unrelated command {!r} -- the match: "
        "is too wide. Got: {!r}".format(version, UNRELATED_COMMAND, answer[:400])
    )


# --- 4. SKILL.md's own spine section is trimmed to a pointer -----------------------


def test_skill_md_merge_gates_section_is_a_short_pointer():
    text = (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(encoding="utf-8")
    start = text.index("## Merge gates")
    end = text.index("\n## ", start + 1)
    section = text[start:end]
    assert len(section.splitlines()) <= 12, (
        "SKILL.md's own Merge gates section is still {} lines -- #245 asks for a short "
        "pointer now that the gate rules live in the jit-context layer".format(
            len(section.splitlines())
        )
    )
    assert ".claude/jit-context/tools/01-oss/{}".format(MERGE_GATE) in section, (
        "the trimmed section does not name the jit rule that replaces it"
    )
    assert "skills/manager/phases/merge.md" in section, (
        "the trimmed section drops the pointer to the phase file's full argument"
    )
