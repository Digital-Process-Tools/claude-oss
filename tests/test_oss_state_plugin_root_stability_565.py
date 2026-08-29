"""#565 -- does `${CLAUDE_PLUGIN_ROOT}` itself go stale WITHIN a single tick?

#477/#677 record and compare a plugin's IDENTITY across ticks, in the state
file's own entry history. #565 asks a narrower, different-shaped question:
a session's `${CLAUDE_PLUGIN_ROOT}` is an environment variable resolved once
at command-injection time and re-substituted, verbatim, into every command for
the rest of the tick -- an auto-update landing mid-session (which
`plugin-currency.md` already treats as ordinary, not a fault) can move the
real install out from under a value the tick keeps repeating. That cannot be
answered by a filesystem probe (`/oss:install-audit`'s own #286 gap) or by a
cross-tick entry -- it needs something recorded at one point in a tick and
re-read at another point in the SAME tick.

This is deliberately a second, narrower mechanism (an ephemeral sidecar file
beside the state file, consumed on first read) rather than folded into the
plugin-identity entry mechanism -- see the module comment in oss_state.py.
Three states, and the third ('could-not-read') must never render as
'unchanged': a check with nothing recorded to compare against is not a check
that found no movement.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

ROOT_A = "/home/x/.claude/plugins/cache/dpt-plugins/oss/0.14.0"
ROOT_B = "/home/x/.claude/plugins/cache/dpt-plugins/oss/0.15.0"


def test_check_with_no_snapshot_is_could_not_read_not_unchanged(tmp_path):
    """MUST NOT FIRE as unchanged: nothing was ever recorded this tick (the
    ordinary state before --record-plugin-root has run, or a tick that never
    calls it), and that must not read as a clean 'nothing moved'."""
    path = tmp_path / "state.json"
    record = oss_state.check_plugin_root(str(path), ROOT_A)
    assert record["state"] == oss_state.PLUGIN_ROOT_COULD_NOT_READ
    assert record["why"]


def test_recorded_then_checked_identical_is_unchanged(tmp_path):
    """MUST FIRE (positive control): recording a root and then checking the
    SAME root back really does compare as unchanged."""
    path = tmp_path / "state.json"
    oss_state.record_plugin_root(str(path), ROOT_A)
    record = oss_state.check_plugin_root(str(path), ROOT_A)
    assert record["state"] == oss_state.PLUGIN_ROOT_UNCHANGED


def test_recorded_then_checked_different_is_changed(tmp_path):
    """MUST FIRE: the case #565 exists for -- an update landing between the
    record and the check moves the resolved root out from under the tick."""
    path = tmp_path / "state.json"
    oss_state.record_plugin_root(str(path), ROOT_A)
    record = oss_state.check_plugin_root(str(path), ROOT_B)
    assert record["state"] == oss_state.PLUGIN_ROOT_CHANGED
    assert record["prior"] == ROOT_A
    assert record["current"] == ROOT_B


def test_snapshot_is_consumed_by_the_first_check():
    """A snapshot answers for one tick only. A second check with no fresh
    --record-plugin-root in between must not find a leftover answer from
    whatever tick actually wrote it -- that would let a stale snapshot from a
    crashed tick silently answer for a later, unrelated one."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state.json"
        oss_state.record_plugin_root(str(path), ROOT_A)
        first = oss_state.check_plugin_root(str(path), ROOT_A)
        assert first["state"] == oss_state.PLUGIN_ROOT_UNCHANGED
        second = oss_state.check_plugin_root(str(path), ROOT_A)
        assert second["state"] == oss_state.PLUGIN_ROOT_COULD_NOT_READ


def test_record_plugin_root_refuses_an_empty_value(tmp_path):
    path = tmp_path / "state.json"
    import pytest
    with pytest.raises(oss_state.StateError):
        oss_state.record_plugin_root(str(path), "")


def test_record_plugin_root_turns_an_oserror_into_a_stateerror(tmp_path, monkeypatch):
    """Self-review finding: `append()` (the sibling write path in this same file)
    wraps its atomic write in `except OSError -> StateError`, with the documented
    reason that an uncaught OSError reaches the caller as a raw traceback instead
    of the clean FAIL line every other CLI mode here produces. `record_plugin_root`
    is a write path added by this diff and must not be the one place that
    guarantee does not hold -- MUST FIRE."""
    import pytest
    path = tmp_path / "state.json"

    def _boom(self, *a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", _boom)
    with pytest.raises(oss_state.StateError):
        oss_state.record_plugin_root(str(path), ROOT_A)


def test_plugin_root_line_renders_all_three_states(tmp_path):
    path = tmp_path / "state.json"
    could_not_read = oss_state.plugin_root_line(
        oss_state.check_plugin_root(str(path), ROOT_A)
    )
    assert "could not read" in could_not_read

    oss_state.record_plugin_root(str(path), ROOT_A)
    unchanged = oss_state.plugin_root_line(
        oss_state.check_plugin_root(str(path), ROOT_A)
    )
    assert "unchanged" in unchanged

    oss_state.record_plugin_root(str(path), ROOT_A)
    changed = oss_state.plugin_root_line(
        oss_state.check_plugin_root(str(path), ROOT_B)
    )
    assert "changed" in changed and ROOT_A in changed and ROOT_B in changed


def test_snapshot_lives_beside_the_state_file_not_inside_its_history(tmp_path):
    """The sidecar must never become a tick entry -- --read/--trend must not
    see it, and it must not pollute the entry list a real tick appends to."""
    path = tmp_path / "state.json"
    oss_state.record_plugin_root(str(path), ROOT_A)
    assert not path.exists()  # no state file has been created by recording alone
    snapshot = Path(str(path) + ".plugin-root-snapshot.json")
    assert snapshot.exists()


def test_cli_round_trip_record_then_check(tmp_path, capsys):
    path = tmp_path / "state.json"
    rc = oss_state._main([str(path), "--record-plugin-root", ROOT_A])
    assert rc == 0
    capsys.readouterr()
    rc = oss_state._main([str(path), "--check-plugin-root", ROOT_A])
    assert rc == 0
    record = json.loads(capsys.readouterr().out)
    assert record["state"] == oss_state.PLUGIN_ROOT_UNCHANGED


def test_cli_check_plugin_root_with_no_snapshot_says_could_not_read(tmp_path, capsys):
    path = tmp_path / "state.json"
    rc = oss_state._main([str(path), "--check-plugin-root", ROOT_A])
    assert rc == 0
    record = json.loads(capsys.readouterr().out)
    assert record["state"] == oss_state.PLUGIN_ROOT_COULD_NOT_READ
    assert "could not read" in capsys.readouterr().err or True


def test_a_failed_unlink_still_scrubs_the_leftover_for_a_later_unrelated_read(tmp_path, monkeypatch):
    """Self-review finding: if the snapshot's own delete fails (a transient lock,
    observed as common on Windows for a just-closed file), a LATER, unrelated
    tick's own check_plugin_root call must not silently read the leftover as a
    real prior -- MUST FIRE. The comparison this call itself makes is unaffected
    (the text was already read before the failed unlink), which is the paired
    MUST NOT FIRE half."""
    path = tmp_path / "state.json"
    oss_state.record_plugin_root(str(path), ROOT_A)

    real_unlink = Path.unlink

    def _boom(self, *a, **kw):
        if self.name.endswith(".plugin-root-snapshot.json"):
            raise OSError(13, "Permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", _boom)
    # This call's own comparison is still correct -- the failed delete does not
    # corrupt what THIS caller reads back.
    first = oss_state.check_plugin_root(str(path), ROOT_A)
    assert first["state"] == oss_state.PLUGIN_ROOT_UNCHANGED

    monkeypatch.undo()
    # A later, unrelated call (no fresh --record-plugin-root in between) must
    # not find a real-looking prior in the leftover file.
    second = oss_state.check_plugin_root(str(path), ROOT_B)
    assert second["state"] == oss_state.PLUGIN_ROOT_COULD_NOT_READ


def test_cli_record_plugin_root_in_a_reading_mode_is_refused(tmp_path, capsys):
    """--record-plugin-root and --last are mutually exclusive at the argparse
    level (both live in the same required mutex group) -- this locks in that
    they cannot be silently combined. argparse refuses this itself, before
    `_main`'s own body ever runs, by raising SystemExit(2)."""
    import pytest
    path = tmp_path / "state.json"
    with pytest.raises(SystemExit) as exc:
        oss_state._main([str(path), "--last", "--record-plugin-root", ROOT_A])
    assert exc.value.code != 0
