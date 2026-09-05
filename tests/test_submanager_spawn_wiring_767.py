"""#767: the sub-manager was fully built and nothing spawned it.

#695 shipped the receiving half -- `scripts/tick_handback.py`, `scripts/agent_role.py`,
`agents/sub-manager.md` itself, and five dedicated test files. `commands/tick.md` named
`sub-manager` zero times: nothing anywhere spawned the agent, so the saving #695 was filed
for (a fresh, `/clear`d context every tick instead of one session's context growing
quadratically across ticks) was never realised. This module pins the wiring #767 asked for:
an actual `Agent(subagent_type: "oss:sub-manager", ...)` spawn in `commands/tick.md`, a read
of the handback through `scripts/tick_handback.py` naming all six of its declarable
states (not a narrowed two- or three-way collapse), and the model axis held still across the cutover
(#695's own explicit constraint -- a model change riding the same diff would make #694's
before-and-after measurement meaningless).

Every negative assertion here (`sub-manager` absent, no spawn call, no `model:` override) is
paired with its positive control in the same fixture, per this repo's own rule that a
"must not fire" case is worthless without a "must fire" case beside it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TICK_MD = REPO_ROOT / "commands" / "tick.md"
SUB_MANAGER_MD = REPO_ROOT / "agents" / "sub-manager.md"

#: The exact grep #767's own body ran against the pre-fix tree, reproduced here as a
#: fixture rather than trusted from memory -- this is what "not-matched" looked like.
PRE_FIX_TICK_MD_FIXTURE = """
---
description: Run one maintainer tick — read the board, decide, delegate, review, merge on green.
allowed-tools: Bash, Agent, Skill
---

One pass of the maintainer loop over the repo named in `.oss.json`.

Load the loop itself first — it carries the judgment this command only sequences:

```
Skill(manager)
```

## Order of operations

1. **Read the state file** named by `state_file`, then **`git fetch && git pull --ff-only`**.
"""

_SPAWN_RE = re.compile(r'Agent\(subagent_type:\s*"oss:sub-manager"')
_TICK_HANDBACK_RE = re.compile(r"tick_handback\.py")

#: `could-not-read` is deliberately absent: it is a property of the source the
#: CLI was pointed at, not a state a sub-manager can declare, so a scheduler
#: branching on the handback's own vocabulary has nothing to say about it.
HANDBACK_STATES = (
    "`completed`",
    "`blocked`",
    "`paused`",
    "`could-not-run`",
    "`returned-nothing`",
    "`could-not-classify`",
)


def _spawns_sub_manager(text):
    return bool(_SPAWN_RE.search(text))


def _tick_md_text():
    return TICK_MD.read_text(encoding="utf-8")


def _sub_manager_md_text():
    return SUB_MANAGER_MD.read_text(encoding="utf-8")


def test_tick_md_and_sub_manager_md_exist():
    """A missing file would make every assertion below pass on nothing."""
    assert TICK_MD.is_file(), "commands/tick.md not found"
    assert SUB_MANAGER_MD.is_file(), "agents/sub-manager.md not found"


def test_the_checker_reports_absence_on_the_pre_fix_fixture():
    """Positive control: the exact shape #767 measured (`grep -c sub-manager
    commands/tick.md` -> 0) must still read as absent through this module's own
    checker, or the checker is not measuring what #767 measured.
    """
    assert not _spawns_sub_manager(PRE_FIX_TICK_MD_FIXTURE)
    assert "sub-manager" not in PRE_FIX_TICK_MD_FIXTURE


def test_the_checker_reports_presence_on_a_fixture_that_actually_spawns_it():
    """Negative-control's own control: a fixture that plainly does spawn the
    sub-manager must not also read as absent, or the checker cannot distinguish
    the two cases it exists to distinguish.
    """
    fixture = 'Agent(subagent_type: "oss:sub-manager", run_in_background: false)'
    assert _spawns_sub_manager(fixture)


def test_commands_tick_md_now_spawns_the_sub_manager():
    """The #767 fix itself: commands/tick.md must contain a real spawn, not just
    the word "sub-manager" in prose -- #767's own body distinguished a bare
    string hit (commands/release.md:441-442, prose about withholding) from an
    actual spawn, and found none of the latter anywhere in commands/tick.md.
    """
    assert _spawns_sub_manager(_tick_md_text()), (
        "commands/tick.md does not spawn oss:sub-manager -- #767's own gap is "
        "still open"
    )


def test_commands_tick_md_names_sub_manager_many_times_not_once():
    """A single incidental mention would satisfy a bare `in` check without
    describing how to spawn it, read its handback, or hold the model axis
    still. Require real coverage, not a one-line reference.
    """
    count = _tick_md_text().count("sub-manager")
    assert count >= 10, (
        "commands/tick.md mentions sub-manager only {} times -- too sparse to "
        "be the wiring #767 asked for".format(count)
    )


def test_commands_tick_md_reads_the_handback_through_tick_handback_py():
    """#695/#767: a scheduler must classify a sub-manager's final message with
    the tool built for it, not by reading prose and guessing -- the same
    reasoning agents/developer.md already gives for scripts/review_return.py.
    """
    assert _TICK_HANDBACK_RE.search(_tick_md_text()), (
        "commands/tick.md never calls scripts/tick_handback.py -- a handback "
        "would be read by eye, which is the collapse #695 was filed to prevent"
    )


def test_all_handback_states_are_named_not_collapsed():
    """#695's own constraint: 'the three handback states must not collapse to
    two.' scripts/tick_handback.py actually has six declarable ones (completed,
    blocked, paused, could-not-run, returned-nothing, could-not-classify) once
    returned-nothing and could-not-classify are counted alongside the three
    #695 named and #818's `paused` alongside those -- and a scheduler that only
    branches on some of them silently drops the rest back into a single
    undifferentiated bucket. The count is not written into this test's name any
    more, for the reason #818 demonstrated: the name said `five` while the tuple
    beside it had grown, and a name cannot be checked against anything.
    """
    text = _tick_md_text()
    missing = [state for state in HANDBACK_STATES if state not in text]
    assert not missing, (
        "commands/tick.md does not name these tick_handback.py states, so a "
        "scheduler reading it would collapse them into fewer than "
        "{}: {}".format(len(HANDBACK_STATES), missing)
    )


def test_returned_nothing_is_not_read_as_a_clean_idle_tick():
    """The specific collapse #695 warns about by name: a sub-manager that died
    and one that found nothing to do must not render identically.
    """
    text = _tick_md_text()
    assert "returned-nothing" in text
    idx = text.index("`returned-nothing`")
    window = text[idx:idx + 400]
    assert re.search(r"not read this as an idle, clean tick|must not read as", window), (
        "commands/tick.md's `returned-nothing` entry does not say it must not "
        "be read as a clean, idle tick"
    )


def _spawn_block(text):
    """The fenced code block containing the oss:sub-manager spawn call.

    Scans the whole fence, not just the line the regex matched on -- a
    single-line scan passes today's one-line call and would miss a `model`
    override added on a wrapped continuation line if the call were later
    reformatted to span several lines (review finding, #767's own review
    round). Falls back to the single line when no enclosing fence can be
    found, so this never raises on a match outside a fence.
    """
    match = _SPAWN_RE.search(text)
    if match is None:
        return None
    fence_start = text.rfind("```", 0, match.start())
    fence_end = text.find("```", match.end())
    if fence_start == -1 or fence_end == -1:
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        return text[line_start:line_end if line_end != -1 else len(text)]
    return text[fence_start:fence_end]


def test_the_spawn_call_does_not_override_the_model():
    """#695/#767's explicit constraint: hold the model axis still across the
    cutover, because a model change riding the same diff makes #694's
    before-and-after measurement unable to separate a cheaper context from a
    different model. agents/sub-manager.md pins `model: sonnet` in its own
    frontmatter; the spawn call in commands/tick.md must not pass a `model`
    argument that would override that pin.
    """
    block = _spawn_block(_tick_md_text())
    assert block is not None
    assert "model" not in block, (
        "the oss:sub-manager spawn call's fenced block in commands/tick.md "
        "mentions `model` -- this overrides the agent definition's own "
        "`model: sonnet` pin and breaks #694's before/after measurement: "
        "{!r}".format(block)
    )


def test_the_spawn_block_checker_catches_a_multi_line_override():
    """Positive control for the assertion above: a `model` override wrapped
    onto its own continuation line inside the same fence must still be
    caught, or the widened scan bought nothing over the single-line one it
    replaced.
    """
    fixture = (
        "```\n"
        'Agent(subagent_type: "oss:sub-manager",\n'
        '      model: "opus",\n'
        "      run_in_background: false)\n"
        "```\n"
    )
    block = _spawn_block(fixture)
    assert block is not None
    assert "model" in block


def test_sub_manager_md_model_pin_is_unchanged_by_this_wiring():
    """Control for the assertion above: the pin this wiring must not disturb
    is still there to disturb. A `model` key removed from
    agents/sub-manager.md's own frontmatter would make the "no override on
    the call site" check above vacuous.
    """
    text = _sub_manager_md_text()
    assert re.search(r"(?m)^model:\s*sonnet\s*$", text), (
        "agents/sub-manager.md no longer pins model: sonnet in its frontmatter"
    )


def test_sub_manager_frontmatter_claim_is_now_true():
    """agents/sub-manager.md's own description says 'Spawned by the scheduler
    (`/oss:tick`)'. #767's second comment measured that this was false and
    said the frontmatter sentence and the wiring must land in the same
    commit, or the sentence must change. This ties the two together: if a
    later change removes the spawn from commands/tick.md without touching
    this sentence, this test is what catches the claim going false again.
    """
    claim = "Spawned by the scheduler (/oss:tick)"
    assert claim in _sub_manager_md_text(), (
        "agents/sub-manager.md no longer makes the claim #767 checked -- "
        "update this test if the sentence was deliberately reworded"
    )
    assert _spawns_sub_manager(_tick_md_text()), (
        "agents/sub-manager.md still claims to be spawned by the scheduler, "
        "but commands/tick.md does not spawn it -- the claim is false again"
    )


def test_release_authority_withholding_language_is_unchanged():
    """#767's own scope: tagging and publishing stay with the scheduler until
    the releaser agent (#696) exists. The wiring must not quietly hand
    release authority to the sub-manager -- pin the two sentences that say
    so are still present in both files.
    """
    assert "scripts/agent_role.py" in _tick_md_text()
    assert "never tags, never publishes" in _sub_manager_md_text() or (
        "never tags" in _sub_manager_md_text() and "never publishes" in _sub_manager_md_text()
    )


def test_step_seven_stays_the_scheduler_and_the_stop_doctrine_survives():
    """Step 7 (arm the next tick) is the one step this issue moves off the
    sub-manager and back onto the scheduler, because the sub-manager has no
    ScheduleWakeup tool. Guard that the numbered step is still literally
    named "7. **Arm the next tick" -- tests/test_content_invariants.py's
    stop-doctrine anchors locate this heading by exact regex, and a rename
    or renumbering here would make that check pass on nothing.
    """
    text = _tick_md_text()
    assert re.search(r"(?m)^7\. \*\*Arm the next tick", text), (
        "commands/tick.md's step 7 heading moved or was renumbered -- this "
        "silently defeats tests/test_content_invariants.py's stop-doctrine "
        "anchor, which locates the region by this exact pattern"
    )
    assert "ScheduleWakeup" in text


def test_what_ends_a_tick_heading_still_resolves():
    """Same vacuity guard, for the other stop-doctrine/tick-ending anchor
    region -- tests/test_content_invariants.py locates it by this exact
    heading text.

    #1037: "What ends a tick" moved out of commands/tick.md into its own
    phase file, read by a sub-manager rather than injected into the
    scheduler on every tick.
    """
    tick_order = (
        Path(__file__).resolve().parent.parent
        / "skills" / "manager" / "phases" / "tick-order.md"
    ).read_text(encoding="utf-8")
    assert re.search(r"(?m)^## What ends a tick", tick_order)
