"""#1105: traps about this plugin's own review-phase mutation check
(`agents/developer/review.md`'s `tree_snapshot.py` snapshot/compare step), curated
into one jit-context rule and filed here to land in the durable home -- this
plugin's own generated `01-oss` layer, so every managed repository picks it up on
install/update rather than only the one repo where a trap happened to be logged.

Self-review on this same issue found the first draft of the rule stale: it told
every managed repo to chain `snapshot` and `compare` with a same-call `cd`, which
was true before this script's own root-recording fix landed but is not true of the
script as shipped today (`compare` already defaults to the before-snapshot's own
recorded root) -- and it cited bare issue numbers from the tracker the traps were
originally logged in, which resolve to unrelated issues when read from a different
one. The rule below is the corrected version; see `scripts/oss_rules.py`'s own
comment above `TOOLS_TREE_SNAPSHOT` for the full account.

Same shape as `tests/test_merge_gate_jit_rule_245.py`: the rule has to exist in
`oss_rules.RULES["tools"]`, be indexed by `index_rows()`, be tracked byte-identically
under `.claude/jit-context/tools/01-oss/`, and actually fire against the real
installed hook for a realistic `tree_snapshot.py` invocation -- a rule that ships
without a demonstrated fire is the inert-layer bug #144 already shipped once.
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

TREE_SNAPSHOT_RULE = "tree-snapshot-compare.md"

#: The literal shape agents/developer/review.md tells a lane to type.
REALISTIC_SNAPSHOT_COMMAND = (
    'BEFORE=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tree_snapshot.py" snapshot)'
)
REALISTIC_COMPARE_COMMAND = (
    "printf '%s' \"$BEFORE\" | "
    'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tree_snapshot.py" compare --before -'
)

#: Must-not-fire control: an ordinary Bash call with nothing to do with the compare step.
UNRELATED_COMMAND = "git status"


def _rule_body():
    return oss_rules.RULES.get("tools", {}).get(TREE_SNAPSHOT_RULE)


# --- 1. the rule exists in the generator, keyed correctly ---------------------------


def test_the_generator_ships_a_tree_snapshot_tools_rule():
    body = _rule_body()
    assert body, "oss_rules.RULES['tools'] carries no {}".format(TREE_SNAPSHOT_RULE)
    assert oss_rules._field(body, "tool") == "Bash", (
        "the tree-snapshot rule is not keyed on the Bash tool"
    )


def test_the_match_fires_on_both_the_snapshot_and_compare_calls_and_not_on_git_status():
    """Driven against the literal command strings the loop types, not just declared --
    an untested match: is exactly #144's inert-layer bug one file over."""
    body = _rule_body()
    match = oss_rules._field(body, "match")
    assert match, "the tree-snapshot rule declares no match:"
    pattern = match[1:] if match.startswith("~") else re.escape(match)
    assert re.search(pattern, REALISTIC_SNAPSHOT_COMMAND), (
        "match: {!r} does not fire on the snapshot call {!r}".format(
            match, REALISTIC_SNAPSHOT_COMMAND
        )
    )
    assert re.search(pattern, REALISTIC_COMPARE_COMMAND), (
        "match: {!r} does not fire on the compare call {!r}".format(
            match, REALISTIC_COMPARE_COMMAND
        )
    )
    assert not re.search(pattern, UNRELATED_COMMAND), (
        "match: {!r} fires on an unrelated command {!r} -- too wide".format(
            match, UNRELATED_COMMAND
        )
    )


def test_the_rule_is_a_reminder_not_a_block():
    """Blocking the call outright would refuse the diagnostic itself, not just remind
    of its three failure modes -- not what #1105 asks for."""
    body = _rule_body()
    mode = oss_rules._field(body, "mode") or "remind"
    assert mode == "remind", (
        "the tree-snapshot rule is mode: {!r}, expected remind".format(mode)
    )


def test_the_rule_names_no_bare_issue_number():
    """Self-review finding (#1105): none of the sibling `tools` rules
    (merge-gate.md, pr-create-gate.md, supertool-required.md) cite a bare issue
    number in their shipped body -- a number from the repo the traps were
    originally logged in resolves to an unrelated issue when read from a
    different tracker (this repo's own #456 is an unrelated, already-merged PR).
    The rule text stays self-contained instead."""
    body = _rule_body()
    for token in body.split():
        stripped = token.strip("().,:;")
        assert not (stripped.startswith("#") and stripped[1:].isdigit()), (
            "the tree-snapshot rule's body cites a bare issue number ({!r}) -- "
            "none of the shipped 01-oss tools rules do, because the number is "
            "not necessarily this repo's own".format(stripped)
        )


def test_the_rule_covers_all_three_observed_failure_modes():
    """Content-shape check in place of citing issue numbers: the rule still has
    to actually describe all three curated observations, just without numbering
    them."""
    body = _rule_body()
    assert "recorded root" in body and "live cwd" in body, (
        "the rule does not describe the recorded-root-vs-live-cwd mechanism"
    )
    assert "scratchpad" in body, "the rule does not describe the scratchpad hazard"
    assert "index" in body and "HEAD" in body, (
        "the rule does not describe the index/HEAD split incident"
    )


def test_the_rule_states_the_third_verdict_is_not_clean():
    body = _rule_body()
    assert "could-not-compare" in body
    assert "not `clean`" in body or "not clean" in body.replace("**", "")


# --- 2. it is indexed, and the tracked copy in this repo matches the generator ------


def test_the_rule_gets_an_index_row(tmp_path):
    written = oss_rules.install(tmp_path)
    layer = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    rows = (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines()
    named = {row.split("\t")[2] for row in rows if row.strip()}
    assert TREE_SNAPSHOT_RULE in named, "the tree-snapshot rule was not indexed at all"
    record = layer / TREE_SNAPSHOT_RULE
    assert record in written


def test_the_tracked_copy_in_this_repo_matches_the_generator():
    tracked = (
        REPO_ROOT
        / ".claude"
        / "jit-context"
        / "tools"
        / oss_rules.LAYER
        / TREE_SNAPSHOT_RULE
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
    assert TREE_SNAPSHOT_RULE in named, (
        "the tracked 00-index.tsv has no row for {}".format(TREE_SNAPSHOT_RULE)
    )


# --- 3. proof it fires: drive the real hook, both directions -----------------------


def _driven(tmp_path):
    hook, version, why_not = jit_hook_harness.hook_path()
    if hook is None:
        pytest.skip(
            "{} -- untested: whether the tree-snapshot rule fires against the "
            "installed hook".format(why_not)
        )
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH, so the installed hook could not be driven")
    project = tmp_path / "repo"
    project.mkdir()
    oss_rules.install(project)
    return bash, hook, project, version


def test_the_rule_fires_on_a_real_tree_snapshot_command(tmp_path):
    bash, hook, project, version = _driven(tmp_path)
    body = _rule_body()
    title = oss_rules._frontmatter(body)
    # A short, distinctive fragment of the rule's own title -- proof the INJECTED
    # content is this rule and not some other one that happened to fire.
    sentinel = "tree_snapshot compare: the recorded root"
    assert sentinel in title, "test sentinel drifted from the rule's own title"

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        {"tool_name": "Bash", "tool_input": {"command": REALISTIC_COMPARE_COMMAND}},
    )
    assert problem is None, problem
    assert sentinel in answer, (
        "{} did not inject the tree-snapshot rule for a realistic compare command. "
        "Got: {!r}".format(version, answer[:400])
    )


def test_the_rule_does_not_fire_on_an_unrelated_command(tmp_path):
    """Must-not-fire control, without which the assertion above is equally satisfied
    by a rule that injects on every Bash call."""
    bash, hook, project, version = _driven(tmp_path)
    sentinel = "tree_snapshot compare: the recorded root"

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        {"tool_name": "Bash", "tool_input": {"command": UNRELATED_COMMAND}},
    )
    assert problem is None, problem
    assert sentinel not in answer, (
        "{} injected the tree-snapshot rule for an unrelated command {!r} -- the "
        "match: is too wide. Got: {!r}".format(version, UNRELATED_COMMAND, answer[:400])
    )
