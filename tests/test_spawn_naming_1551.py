"""#1551 Part A: `commands/run/triage.md` named its spawn by a friendly short name,
`the triager agent`, rather than the registered type string `oss:triager` -- what
supplied the real name was `agents/scheduler-step.md`, which names `oss:triager`
only as a parenthetical EXAMPLE. Compare `skills/manager/phases/dispatch.md`, which
spells the equivalent spawn out as a literal `Agent(subagent_type: "oss:triager",
...)` line: prose naming an agent by a friendly short name is the form that drifts,
per the #1414 precedent this issue's own body cites.

This is the regression: `triage.md` must carry the literal `subagent_type:
"oss:triager"` form, not merely the bare word "triager" in prose -- a check for the
bare word alone would already have passed the pre-fix text and caught nothing.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAGE_MD = REPO_ROOT / "commands" / "run" / "triage.md"

#: The literal spawn form, the same shape `skills/manager/phases/dispatch.md` uses
#: for the identical spawn.
LITERAL_SPAWN = re.compile(r'Agent\(subagent_type:\s*"oss:triager"')


def test_triage_md_spawns_triager_by_the_literal_registered_type():
    text = TRIAGE_MD.read_text(encoding="utf-8")
    assert LITERAL_SPAWN.search(text), (
        "commands/run/triage.md does not spawn oss:triager by its literal "
        "subagent_type string -- a friendly-name spawn rests on "
        "agents/scheduler-step.md's own example happening to name the right "
        "thing (#1551)"
    )


def test_the_literal_spawn_check_fires_on_the_pre_fix_prose_name():
    """Must-fire control: the pre-#1551 wording named the agent only by its
    friendly short name, never the literal `subagent_type` string -- so the
    check above must not have passed against it by accident.
    """
    before = "Delegate one sweep to the `triager` agent.\n"
    assert not LITERAL_SPAWN.search(before), (
        "the control fixture already contains a literal subagent_type spawn -- "
        "it no longer reproduces the pre-fix state this test is pinned against"
    )


def test_the_literal_spawn_check_does_not_fire_on_an_unrelated_document():
    """Must-not-fire control, paired with the one above: a document with no
    triager spawn at all reports nothing, rather than matching on the bare
    word "triager" appearing anywhere.
    """
    unrelated = "The triager keeps the tracker honest. It never touches code."
    assert not LITERAL_SPAWN.search(unrelated)
