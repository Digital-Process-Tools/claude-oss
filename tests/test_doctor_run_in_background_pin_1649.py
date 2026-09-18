"""#1649: /oss:run step 1's doctor spawn carries no run_in_background pin.

Every other Agent(...) spawn call in this codebase pins run_in_background explicitly
(#1586 fixed the one prior exception, agents/developer.md's own oss:recon call).
commands/run.md's step 1 spawn (`Agent(subagent_type: "oss:doctor")`) was the
remaining bare call -- recon located it while investigating #1649's own point 3,
which reports oss:doctor running concurrently with oss:sub-manager against the same
clone. A missing pin does not by itself prove the runtime backgrounds the call, but
it is the same "no call shape to copy" gap #1586 named and fixed elsewhere, and
leaving it unpinned means a future edit could silently make it a background spawn
with nothing here to say otherwise.

This test pins the literal call in commands/run.md, mirroring
tests/test_recon_call_shape_1586.py's own regex + positive/negative-control shape.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_MD = REPO_ROOT / "commands" / "run.md"

DOCTOR_CALL_RE = re.compile(
    r'Agent\(subagent_type:\s*"oss:doctor"[^\n]*?run_in_background:\s*false'
)


def _doctor_calls(text):
    return DOCTOR_CALL_RE.findall(text)


def test_run_md_pins_the_doctor_spawn_to_run_in_background_false():
    text = RUN_MD.read_text(encoding="utf-8")
    calls = _doctor_calls(text)
    assert calls, (
        'commands/run.md\'s step 1 Agent(subagent_type: "oss:doctor") call carries '
        "no run_in_background: false pin -- the one bare Agent(...) call #1586's own "
        "fix elsewhere did not reach (#1649)"
    )


def test_a_backgrounded_doctor_call_would_not_satisfy_the_check():
    bad = 'Agent(subagent_type: "oss:doctor", run_in_background: true)'
    assert not _doctor_calls(bad), (
        "fixture construction failed: a backgrounded call satisfies the call-shape "
        "check, so the check cannot tell blocking from backgrounded"
    )


def test_a_doctor_call_missing_run_in_background_would_not_satisfy_the_check():
    bad = 'Agent(subagent_type: "oss:doctor")'
    assert not _doctor_calls(bad), (
        "fixture construction failed: a call with no run_in_background at all "
        "satisfies the check, so it would pass the exact bare shape #1649 reports"
    )
