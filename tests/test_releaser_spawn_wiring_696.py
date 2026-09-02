"""#696: a release has no agent of its own -- it runs inside whatever session
reached it, at that session's accumulated context, with no named performer for
its own gates. This module pins the wiring the fix adds: an actual
`agents/releaser.md` definition, a real `Agent(subagent_type: "oss:releaser",
...)` spawn reachable from `commands/tick.md`'s release-trigger handling, and
the three-state report contract (`released` / `refused` / `could-not-run`)
the issue asks for -- the same shape `scripts/release_delta.py` already uses
for its own narrower question, one level up.

Every negative assertion here (no spawn call, no releaser file, no
`sub-manager` marker written) is paired with its positive control in the same
fixture, per this repo's own rule that a "must not fire" case is worthless
without a "must fire" case beside it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TICK_MD = REPO_ROOT / "commands" / "tick.md"
RELEASE_MD = REPO_ROOT / "commands" / "release.md"
RELEASER_MD = REPO_ROOT / "agents" / "releaser.md"
SUB_MANAGER_MD = REPO_ROOT / "agents" / "sub-manager.md"

#: The exact shape #696's own body measured as absent before the fix: the
#: tick scheduler's release-trigger paragraph names spawning as an option in
#: prose but contains no actual Agent(...) call.
PRE_FIX_TICK_MD_FIXTURE = """
- **`completed`** -- read the `TICK-ENDS:` line first. Read it for a release
  trigger too. If the paragraph says a trigger fired, decide from here
  whether to run `/oss:release` -- in this session or by spawning it --
  never inside the sub-manager that already reported back and is gone.
"""

_SPAWN_RE = re.compile(r'Agent\(subagent_type:\s*"oss:releaser"')

RELEASE_STATES = ("`released`", "`refused`", "`could-not-run`")


def _spawns_releaser(text):
    return bool(_SPAWN_RE.search(text))


def _tick_md_text():
    return TICK_MD.read_text(encoding="utf-8")


def _release_md_text():
    return RELEASE_MD.read_text(encoding="utf-8")


def _releaser_md_text():
    return RELEASER_MD.read_text(encoding="utf-8")


def _sub_manager_md_text():
    return SUB_MANAGER_MD.read_text(encoding="utf-8")


def test_tick_md_and_releaser_md_exist():
    """A missing file would make every assertion below pass on nothing."""
    assert TICK_MD.is_file(), "commands/tick.md not found"
    assert RELEASER_MD.is_file(), "agents/releaser.md not found"


def test_the_checker_reports_absence_on_the_pre_fix_fixture():
    """Positive control: the exact shape #696 was filed against -- a
    release trigger's handling names spawning in prose with no real call --
    must still read as absent through this module's own checker.
    """
    assert not _spawns_releaser(PRE_FIX_TICK_MD_FIXTURE)
    assert "oss:releaser" not in PRE_FIX_TICK_MD_FIXTURE


def test_the_checker_reports_presence_on_a_fixture_that_actually_spawns_it():
    """Negative-control's own control: a fixture that plainly does spawn the
    releaser must not also read as absent.
    """
    fixture = 'Agent(subagent_type: "oss:releaser", run_in_background: false)'
    assert _spawns_releaser(fixture)


def test_commands_tick_md_now_spawns_the_releaser():
    """The #696 fix itself: commands/tick.md's release-trigger handling must
    contain a real spawn, not just prose saying spawning is an option.
    """
    assert _spawns_releaser(_tick_md_text()), (
        "commands/tick.md does not spawn oss:releaser -- #696's own gap is "
        "still open"
    )


def test_releaser_md_frontmatter_names_itself_releaser():
    text = _releaser_md_text()
    assert re.search(r"(?m)^name:\s*releaser\s*$", text), (
        "agents/releaser.md frontmatter does not declare name: releaser, "
        'so subagent_type: "oss:releaser" would resolve to nothing'
    )


def test_releaser_md_is_granted_bash_and_agent():
    """It must be able to run shell (the gates are shell calls) and to spawn
    the release-auditor (gate 3) the way commands/release.md already does.
    """
    text = _releaser_md_text()
    tools_line = re.search(r"(?m)^tools:\s*(.+)$", text)
    assert tools_line, "agents/releaser.md has no tools: frontmatter line"
    tools = tools_line.group(1)
    assert "Bash" in tools
    assert "Agent" in tools


def test_releaser_md_declares_all_three_report_states():
    text = _releaser_md_text()
    missing = [state for state in RELEASE_STATES if state.strip("`") not in text]
    assert not missing, (
        "agents/releaser.md does not name all three report states asked "
        "for by #696: {}".format(missing)
    )


def test_releaser_md_never_writes_the_sub_manager_role_marker():
    """agent_role.py's SUB_MANAGER denylist is the code-level refusal that
    stops release_publish.py from publishing on a sub-manager's behalf. If
    the releaser ever wrote that same marker, it would refuse its own
    publish call -- the opposite of what it exists to do. Checked as an
    actual invocation (the shape agents/sub-manager.md's own first-step
    code fence uses), not a bare substring -- a sentence telling the
    releaser NOT to run it legitimately contains the same words.
    """
    text = _releaser_md_text()
    for fence in re.findall(r"```(?:bash)?\n(.*?)```", text, re.DOTALL):
        assert not re.search(r"agent_role\.py.*--write\s+sub-manager", fence), (
            "agents/releaser.md contains a fenced invocation writing the "
            "sub-manager role marker -- this would make its own publish "
            "call refuse itself"
        )


def test_releaser_md_points_at_commands_release_md_as_the_single_source():
    """#673's own lesson, cited by #696 as a cost to weigh: two documents
    describing one procedure drift into agreement on a wrong answer with
    nothing to catch it. The releaser must not restate the six gates --
    it must follow commands/release.md, the same relationship
    agents/sub-manager.md holds to commands/tick.md's tick steps.
    """
    text = _releaser_md_text()
    assert "commands/release.md" in text
    # Not a second copy: the gate count in commands/release.md is not
    # reproduced as a numbered list inside the releaser's own file.
    assert not re.search(r"(?m)^\d\.\s+\*\*The default branch is green", text)


def test_commands_release_md_names_the_releaser_as_a_caller():
    """The other half of the wiring: commands/release.md should say a
    dedicated agent follows it, not only a maintainer session running
    `/oss:release` directly -- so a reader of that file knows both callers
    exist and neither is a fork of the procedure.
    """
    assert "releaser" in _release_md_text()


def test_releaser_authority_is_gated_on_release_authority_key():
    text = _releaser_md_text()
    assert "release.authority" in text


def test_sub_manager_still_never_tags_or_publishes():
    """Control: this wiring must not quietly widen the sub-manager's own
    authority while adding the releaser's.
    """
    text = _sub_manager_md_text()
    assert "never tags, never publishes" in text or (
        "never tags" in text and "never publishes" in text
    )


def _spawn_block(text):
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
    """Hold the model axis still, the same constraint #767 pinned for the
    sub-manager spawn -- a model override riding this diff would confound
    any later cost comparison with a different-model effect.
    """
    block = _spawn_block(_tick_md_text())
    assert block is not None
    assert "model" not in block, (
        "the oss:releaser spawn call's fenced block in commands/tick.md "
        "mentions `model` -- this overrides agents/releaser.md's own model "
        "pin: {!r}".format(block)
    )


def test_the_spawn_block_checker_catches_a_multi_line_override():
    fixture = (
        "```\n"
        'Agent(subagent_type: "oss:releaser",\n'
        '      model: "opus",\n'
        "      run_in_background: false)\n"
        "```\n"
    )
    block = _spawn_block(fixture)
    assert block is not None
    assert "model" in block
