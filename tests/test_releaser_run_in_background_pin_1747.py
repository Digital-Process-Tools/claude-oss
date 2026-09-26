"""#1747: commands/run.md's own oss:releaser spawn carried no run_in_background
pin, the same gap #1586/#1649 already fixed for oss:recon and oss:doctor.

Observed: the scheduler spawned oss:releaser via this exact bare call
(`Agent(subagent_type: "oss:releaser")`), then resumed the paused releaser twice
with SendMessage; both resumes' task notifications reported delivery while
nothing arrived in the scheduler's context. `commands/tick.md`'s own release
spawn already pins `run_in_background: false` (tests/test_release_handback_1041.py,
tests/test_releaser_spawn_wiring_696.py) -- this file's own separate release
entry point (`/oss:run release`) did not.

Mirrors tests/test_doctor_run_in_background_pin_1649.py's own regex +
positive/negative-control shape.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_MD = REPO_ROOT / "commands" / "run.md"

RELEASER_CALL_RE = re.compile(
    r'Agent\(subagent_type:\s*"oss:releaser"[^\n]*?run_in_background:\s*false'
)


def _releaser_calls(text):
    return RELEASER_CALL_RE.findall(text)


def test_run_md_pins_the_releaser_spawn_to_run_in_background_false():
    text = RUN_MD.read_text(encoding="utf-8")
    calls = _releaser_calls(text)
    assert calls, (
        'commands/run.md\'s ## release section Agent(subagent_type: "oss:releaser") '
        "call carries no run_in_background: false pin -- the same gap #1586/#1649 "
        "fixed for oss:recon and oss:doctor (#1747)"
    )


def test_a_backgrounded_releaser_call_would_not_satisfy_the_check():
    bad = 'Agent(subagent_type: "oss:releaser", run_in_background: true)'
    assert not _releaser_calls(bad), (
        "fixture construction failed: a backgrounded call satisfies the "
        "call-shape check, so the check cannot tell blocking from backgrounded"
    )


def test_a_releaser_call_missing_run_in_background_would_not_satisfy_the_check():
    bad = 'Agent(subagent_type: "oss:releaser")'
    assert not _releaser_calls(bad), (
        "fixture construction failed: a call with no run_in_background at all "
        "satisfies the check, so it would pass the exact bare shape #1747 reports"
    )
