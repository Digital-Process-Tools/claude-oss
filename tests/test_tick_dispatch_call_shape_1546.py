"""#1546: the call shape agents/tick-dispatch.md documents must actually render.

#1544's new spawn exists to hand its caller a ready-to-paste ``Agent(...)`` call.
The shape written into its own file omitted ``--phrase`` and ``--subagent-type``,
and ``lane_setup.py`` renders the bare description in that case -- exit 0, no
error, no ``Agent(...)`` line. A spawn following its own documented call would
report ``DISPATCH: rendered`` with nothing pasteable in it, which is
indistinguishable from a lane that legitimately rendered nothing.

Found by the v0.35.0 gate 3 release audit, round 1, and confirmed by running the
documented line against a claimable issue before this file was written.

Both halves are here on purpose. The negative assertion (the documented line
names both flags) is paired with a positive control (``compose_claim_label``
really does withhold the ``Agent(...)`` render without ``subagent_type``), so
"the flags stopped mattering" can never render as "the documentation is fine".
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402

TICK_DISPATCH = REPO_ROOT / "agents" / "tick-dispatch.md"


def _documented_claim_lines():
    """Every INVOCATION of ``lane_setup.py --claim`` in the spawn's own file.

    Scoped to lines that actually start a command, not every line that mentions
    the script: the file's own report template quotes "the exact ``Agent(...)``
    call ``lane_setup.py --claim`` printed" as prose, and a matcher wide enough
    to catch that would demand flags on a sentence.
    """
    text = TICK_DISPATCH.read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if line.strip().startswith("python3 ")
        and "lane_setup.py" in line
        and "--claim" in line
    ]


def test_the_file_documents_a_claim_call_at_all():
    """Positive control: without this, every assertion below passes vacuously."""
    lines = _documented_claim_lines()
    assert lines, (
        "agents/tick-dispatch.md documents no lane_setup.py --claim call at all -- "
        "the checks below would pass over an empty list"
    )


def test_every_documented_claim_call_can_render_an_agent_call():
    for line in _documented_claim_lines():
        assert "--phrase" in line, (
            "a documented --claim call omits --phrase, so lane_setup.py renders "
            "nothing at all (main() gates the render on `args.phrase is not None`) "
            "-- exit 0, no error (#1546). Line: {0!r}".format(line)
        )
        assert "--subagent-type" in line, (
            "a documented --claim call omits --subagent-type, so compose_claim_label "
            "renders the bare description rather than the Agent(...) call the spawn "
            "is required to report verbatim (#1546). Line: {0!r}".format(line)
        )


def test_a_documented_subagent_type_is_one_lane_setup_accepts():
    """A flag naming an agent type lane_setup refuses renders nothing either."""
    for line in _documented_claim_lines():
        match = re.search(r"--subagent-type\s+(\S+)", line)
        assert match, "no --subagent-type value on: {0!r}".format(line)
        value = match.group(1)
        assert value in lane_setup.KNOWN_AGENT_TYPES, (
            "agents/tick-dispatch.md documents --subagent-type {0!r}, which is not "
            "in lane_setup.KNOWN_AGENT_TYPES {1!r} -- the call refuses rather than "
            "rendering (#1546)".format(value, lane_setup.KNOWN_AGENT_TYPES)
        )


def test_compose_claim_label_really_does_withhold_the_render_without_a_type():
    """The positive control for the two negative assertions above.

    If this ever stops holding, the documentation checks are guarding a
    mechanism that no longer exists and should be deleted rather than kept
    passing.
    """
    payload = {
        "issue": 1546,
        "claim_result": {"state": "claimed"},
        "branch": "fix/1546",
        "worktree": "/wt/1546",
    }
    without = lane_setup.compose_claim_label(payload, "a phrase")
    assert "Agent(" not in (without.get("text") or ""), (
        "compose_claim_label rendered an Agent(...) call with no subagent_type -- "
        "the flags this file checks for no longer decide anything"
    )
    assert without.get("brief") is None, (
        "brief must stay None when subagent_type was never given, so a caller "
        "never has to guess whether the prompt was skipped or genuinely clean"
    )
