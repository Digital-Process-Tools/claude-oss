"""#1585: `tick_handback.py --clear-marker-root` clears a sub-manager's own
role marker as a side effect of the same call `agents/sub-manager.md` already
runs, mandatorily, to validate its own draft handback (#1048) -- rather than
leaving the clear a second, separate step nothing forces an agent to run.
`agent_role.clear_role_marker()` was found to have zero programmatic
callers; this tests the wiring that closes that gap, not the function
itself (`tests/test_agent_role_marker_staleness_695.py` already covers the
function).

Asserted through the same handback path that reports `completed`, per the
issue's own instruction -- never by calling `clear_role_marker()` directly,
which would test the function rather than the missing wiring.
"""

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agent_role  # noqa: E402
import tick_handback  # noqa: E402


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_a_completed_tick_clears_the_marker_through_the_handback_path(tmp_path):
    root = _repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(root), written_at=time.time())
    assert agent_role.current_role(root=str(root)) == "sub-manager"

    msg = tmp_path / "handback.txt"
    msg.write_text(
        "TICK: completed\nTICK-ENDS: nothing-left\nAll clean.\n", encoding="utf-8"
    )
    rc = tick_handback.main([str(msg), "--clear-marker-root", str(root)])
    assert rc == 0
    assert agent_role.current_role(root=str(root)) is None


def test_a_blocked_tick_does_not_clear_the_marker(tmp_path):
    """Positive control: the tick is not actually over, so the marker must
    survive -- proves this does not just clear on every call regardless of
    the verdict."""
    root = _repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(root), written_at=time.time())

    msg = tmp_path / "handback.txt"
    msg.write_text("TICK: blocked\nBLOCKER: waiting on CI\n", encoding="utf-8")
    rc = tick_handback.main([str(msg), "--clear-marker-root", str(root)])
    assert rc == 3
    assert agent_role.current_role(root=str(root)) == "sub-manager"


def test_without_the_flag_a_completed_tick_leaves_the_marker_alone(tmp_path):
    root = _repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(root), written_at=time.time())

    msg = tmp_path / "handback.txt"
    msg.write_text(
        "TICK: completed\nTICK-ENDS: nothing-left\nAll clean.\n", encoding="utf-8"
    )
    rc = tick_handback.main([str(msg)])
    assert rc == 0
    assert agent_role.current_role(root=str(root)) == "sub-manager"


def test_clearing_when_nothing_was_ever_written_reports_nothing_to_clear(
    tmp_path, capsys
):
    root = _repo(tmp_path)
    msg = tmp_path / "handback.txt"
    msg.write_text(
        "TICK: completed\nTICK-ENDS: nothing-left\nAll clean.\n", encoding="utf-8"
    )
    rc = tick_handback.main([str(msg), "--clear-marker-root", str(root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "marker: nothing to clear" in out
