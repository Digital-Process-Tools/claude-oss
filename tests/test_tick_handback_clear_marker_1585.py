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


def test_a_removal_failure_is_reported_distinctly_not_as_nothing_to_clear(
    tmp_path, monkeypatch, capsys
):
    """#1585 self-review (auditor finding): `clear_role_marker()` collapses
    "no marker was there" and "a marker was found and removal failed" onto
    the same `False` -- exactly the defect class `agent_role.py`'s own CLI
    already avoids by reading `_clear_role_marker_detail` instead. This
    proves the wiring in tick_handback.py does too, rather than reporting a
    marker that is still on disk as already gone."""
    root = _repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(root), written_at=time.time())

    def _boom(root, expect_role=None):
        return agent_role._MARKER_OS_ERROR, OSError("permission denied")

    monkeypatch.setattr(agent_role, "_clear_role_marker_detail", _boom)

    msg = tmp_path / "handback.txt"
    msg.write_text(
        "TICK: completed\nTICK-ENDS: nothing-left\nAll clean.\n", encoding="utf-8"
    )
    rc = tick_handback.main([str(msg), "--clear-marker-root", str(root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "marker: could not clear" in out
    assert "nothing to clear" not in out


# -- #1752 (Explore self-review finding): this clear must not drop a rival --


def test_a_completed_tick_does_not_drop_a_marker_that_now_names_a_different_role(
    tmp_path, capsys
):
    """The structural mirror of #1752's own doctor-side fix: this is the
    sub-manager's own end-of-tick unconditional clear, the same shape as the
    doctor's own end-of-run clear that #1752 protected with `expect_role`.
    Nothing forces an overwrite of a live `sub-manager` marker today (#1740's
    only forced-write path targets a live `doctor` marker), but the
    underlying primitive already supports this for free, and leaving this
    call site unguarded would silently reintroduce the exact #1752 defect
    class the day a symmetric forced-overwrite path is ever added here."""
    root = _repo(tmp_path)
    # Simulates the race: something else now holds the marker.
    agent_role.write_role_marker("doctor", root=str(root), written_at=time.time())

    msg = tmp_path / "handback.txt"
    msg.write_text(
        "TICK: completed\nTICK-ENDS: nothing-left\nAll clean.\n", encoding="utf-8"
    )
    rc = tick_handback.main([str(msg), "--clear-marker-root", str(root)])
    assert rc == 0
    assert agent_role.current_role(root=str(root)) == "doctor", (
        "a marker that no longer names sub-manager must be left alone -- "
        "clearing it would drop someone else's live declaration"
    )
    out = capsys.readouterr().out
    assert "marker: refused" in out or "owner mismatch" in out.lower()
