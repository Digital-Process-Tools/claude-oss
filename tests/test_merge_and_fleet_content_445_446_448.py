"""Three related fixes to the two documents the maintainer loop reads at merge and
dispatch time: #445 (the merge call's invocation spelling), #446 (cleanup should
default to `gh-pr-merge`'s own `|cleanup` token rather than raw `gh api -X DELETE`
and `git worktree remove`), and #448 (fleet size is a floor, not only a ceiling).

Each check is a content invariant over `skills/manager/SKILL.md` and, for #446,
`commands/tick.md` -- the same shape `test_manager_op_inventory_claims.py` and
`test_claude_md_currency.py` already use. These are all "must appear" checks
rather than "must not appear" ones: every fix here is additive prose naming a
spelling, a token or a state that was previously absent, so there is no old
wording to assert the absence of. `test_content_invariants.py` and
`test_worktree_ownership_guidance.py` already carry this document's "must not
appear" guards (the raw `git worktree list` command, negative op-inventory
claims); this file does not duplicate them.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "manager" / "SKILL.md"
TICK = REPO_ROOT / "commands" / "tick.md"


def _skill_text():
    return SKILL.read_text(encoding="utf-8")


def _tick_text():
    return TICK.read_text(encoding="utf-8")


def _collapse(text):
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------------------
# #445 -- the merge call's invocation spelling
# ---------------------------------------------------------------------------

def test_the_skill_names_the_bare_supertool_spelling_for_merging():
    text = _skill_text()
    assert "supertool 'gh-pr-merge" in text or 'supertool "gh-pr-merge' in text, (
        "the skill never shows the bare `supertool` spelling for the merge call -- "
        "#445's whole fix is naming which invocation clears the harness classifier"
    )


def test_the_skill_says_not_to_use_the_python3_supertool_py_spelling_for_merging():
    collapsed = _collapse(_skill_text())
    assert "python3 supertool.py" in collapsed, (
        "the skill never mentions the `python3 supertool.py` spelling at all -- "
        "without naming it, the instruction to avoid it for merging cannot be checked"
    )
    assert re.search(
        r"(?:do not|never)\s+use\s+.?python3 supertool\.py", collapsed, re.IGNORECASE
    ) or re.search(
        r"python3 supertool\.py[^.]{0,200}?(?:not|never)\s+(?:for|to)\s+(?:the\s+)?merg",
        collapsed,
        re.IGNORECASE,
    ), (
        "the skill mentions `python3 supertool.py` without saying it must not be used "
        "for the merge call -- #445's classifier trap is that this spelling silently "
        "falls through an allowlist anchored on the bare `supertool` prefix"
    )


def test_the_skill_reads_a_classifier_denial_as_about_the_string_not_the_action():
    collapsed = _collapse(_skill_text())
    assert "Blocked by classifier" in collapsed, (
        "the skill drops the exact denial text -- a reader hitting this message has "
        "nothing to match it against"
    )


# Positive control: the pre-#445 shape names the classifier trap but never the fix.
PRE_445 = (
    "A second mechanism sits in front of all three and is not the same thing: the "
    "harness's own permission handling can deny the call before supertool sees it"
)


def test_pre_445_text_is_still_present_as_context():
    """The trap description #445 builds on was not deleted, only completed."""
    assert PRE_445 in _collapse(_skill_text())


# ---------------------------------------------------------------------------
# #446 -- cleanup defaults to the op's own `|cleanup` token
# ---------------------------------------------------------------------------

def test_the_skill_documents_cleanup_as_the_pipe_cleanup_token():
    assert "|cleanup" in _skill_text(), (
        "the skill never mentions the `|cleanup` token -- #446's whole point is that "
        "`gh-pr-merge` already carries a gated cleanup and the skill routed around it"
    )


def test_the_merge_table_row_carries_the_cleanup_token():
    text = _skill_text()
    row = next((line for line in text.splitlines() if "| Merging |" in line), None)
    assert row is not None, "the op table's Merging row is gone"
    assert "|cleanup" in row, (
        "the op table's Merging row does not carry `|cleanup` -- {}".format(row)
    )


def test_the_skill_names_the_one_idle_tree_condition():
    collapsed = _collapse(_skill_text())
    assert "exactly one idle tree" in collapsed, (
        "the skill never states the one-idle-tree condition -- a fleet-running loop "
        "normally holds several trees, so `|cleanup` silently skips the worktree half "
        "and that has to be named, not left implicit (#446)"
    )
    assert "skipped: reason" in collapsed or "skipped:" in collapsed, (
        "the skill never says the worktree half reports `skipped: reason` when more "
        "than one tree is live -- without it, a skip and a success read the same"
    )


def test_merge_gates_section_mentions_cleanup_token():
    text = _skill_text()
    merge_gates_start = text.index("## Merge gates")
    merge_gates_end = text.index("### The merge is not done when the PR is green")
    section = text[merge_gates_start:merge_gates_end]
    assert "|cleanup" in section, (
        "the Merge gates section does not mention `|cleanup` at all"
    )


def test_positive_control_raw_delete_commands_are_still_documented_as_the_refusal_fallback():
    """Must-fire control: the raw commands are not deleted from the document
    entirely, only demoted -- they are what a maintainer runs for the cases the op
    itself refuses to touch (cross-repo head, unestablished branch, default branch)."""
    collapsed = _collapse(_skill_text())
    assert "gh api -X DELETE" in collapsed, (
        "the raw delete command disappeared entirely -- it is still the documented "
        "fallback for cross-repository heads, unestablished branches and the default "
        "branch, which `|cleanup` deliberately refuses to touch"
    )


def test_tick_md_merge_step_names_cleanup_as_the_ops_own_token():
    collapsed = _collapse(_tick_text())
    assert "|cleanup" in collapsed, (
        "commands/tick.md's merge step still describes cleanup as a second, separate "
        "call rather than pointing at the merge op's own `|cleanup` token (#446)"
    )


# ---------------------------------------------------------------------------
# #448 -- fleet size is a floor, not only a ceiling
# ---------------------------------------------------------------------------

def test_the_fleet_section_states_the_three_floor_states():
    collapsed = _collapse(_skill_text())
    for state in ("filled", "under-filled", "could-not-tell"):
        assert state in collapsed, (
            "the fleet section is missing the `{}` state -- #448 asks for the same "
            "three-state shape every other gate in this loop uses".format(state)
        )


def test_the_fleet_section_says_under_filled_must_never_render_as_filled():
    collapsed = _collapse(_skill_text())
    assert re.search(
        r"could-not-tell[^.]{0,200}?never\s+render\s+as\s+.?filled", collapsed
    ), (
        "the fleet section states the three floor states but never says "
        "`could-not-tell` must not render as `filled` -- that line is the whole "
        "reason #448 wants a third state at all"
    )


def test_the_fleet_section_still_bounds_from_above_too():
    """Positive control: #448 turns the ceiling into a floor, it does not delete the
    ceiling. Two agents in one file is unchanged and load-bearing for the floor."""
    collapsed = _collapse(_skill_text())
    assert "Two agents in one file is reckless at any fleet size" in collapsed


def test_the_fleet_section_names_a_disjoint_lane_as_the_unit_being_counted():
    collapsed = _collapse(_skill_text())
    assert "file-disjoint lane" in collapsed or "file-disjoint area" in collapsed, (
        "the floor language never names the unit it counts -- without it, "
        "`filled`/`under-filled` cannot be told apart from an arbitrary headcount"
    )
