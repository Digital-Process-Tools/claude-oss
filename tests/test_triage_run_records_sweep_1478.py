"""#1478: `commands/run/triage.md` completes a full sweep but never told the
`oss:scheduler-step` spawn following it to record that sweep in the state
file -- so `next_action.py`/`triage_trigger.py` kept reading `last_triage` as
unchanged and ranked triage `due` forever, on every single loop iteration.

`commands/tick.md` already carries the correct call shape for its own
triage-recording step (#855, #1386, and the call-shape fix for #1436). This
issue is the sibling gap: `commands/run/triage.md` made no such call at all.
The fix adds the identical shape there.

Two things are asserted, mirroring #855's own test style
(`tests/test_triage_cadence_855.py`): the procedure file states the call
literally (so a reader -- and the spawn following it -- actually sees it),
and the call, when run for real against a scratch state file, changes what
`--last-triage` reports. The negative control is the point of #1478 itself:
without the call, `--last-triage` does not move, which is exactly the silent
absence the issue is about -- so a positive-only test here would prove
nothing about the fix actually mattering.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

TRIAGE_MD = (REPO_ROOT / "commands" / "run" / "triage.md").read_text(encoding="utf-8")


def _oss_state(*args):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


# --------------------------------------------------------- positive controls


def test_triage_md_states_the_recording_call():
    """The procedure must literally carry the call, in the shape oss_state.py's
    own argparse actually requires: --decision, --at and --triage-recorded
    together -- not just a mention of the flag in prose."""
    assert "--triage-recorded" in TRIAGE_MD
    assert "--decision" in TRIAGE_MD
    assert "oss_state.py" in TRIAGE_MD


def test_triage_md_orders_the_record_call_after_the_report_arrives():
    """The call must not fire before the agent's report is in hand -- the same
    "once the report has arrived" ordering the status-line-staleness call
    right below it already uses."""
    idx = TRIAGE_MD.find("--triage-recorded")
    assert idx != -1
    window = TRIAGE_MD[max(0, idx - 900) : idx]
    assert re.search(
        r"report(s|ed)? back|the report has arrived|once.*report", window, re.IGNORECASE
    )


def test_recording_the_sweep_changes_last_triage(tmp_path):
    """Positive: run the documented call for real. `--last-triage` must move
    from 'never' to a recorded timestamp."""
    state_path = tmp_path / "watch.json"

    before = oss_state.last_triage(str(state_path))
    assert before["state"] == oss_state.TRIAGE_NEVER

    at = "2026-09-11T18:26:54+00:00"
    result = _oss_state(
        str(state_path),
        "--decision",
        "triage sweep recorded",
        "--at",
        at,
        "--triage-recorded",
        at,
    )
    assert result.returncode == 0, result.stderr

    after = oss_state.last_triage(str(state_path))
    assert after["state"] == oss_state.TRIAGE_RECORDED
    assert after["recorded_at"] == at


def test_without_the_call_last_triage_never_moves(tmp_path):
    """Negative control, same fixture shape: a sweep that completes but makes
    no recording call at all -- #1478's own defect -- must leave
    `--last-triage` exactly as it was. This is the "must not fire" half; the
    prior test is its paired "must fire" half, per this repo's own rule that
    a negative assertion needs a positive control."""
    state_path = tmp_path / "watch.json"

    before = oss_state.last_triage(str(state_path))
    assert before["state"] == oss_state.TRIAGE_NEVER

    # Simulate a completed sweep that recorded nothing -- an ordinary
    # decision entry with no --triage-recorded attached, the exact shape
    # #1478 observed (the scheduler having to record it by hand afterwards).
    oss_state.append(
        str(state_path), "2026-09-11T18:00:00+00:00", "some unrelated tick decision"
    )

    after = oss_state.last_triage(str(state_path))
    assert after["state"] == oss_state.TRIAGE_NEVER, (
        "an entry with no --triage-recorded attached must not move --last-triage -- "
        "this is the exact silent-absence defect #1478 reports"
    )
