"""#642: `check_statusline` read only `.claude/settings.json`, so a repo that wired
the status line in `.claude/settings.local.json` -- the untracked, per-machine file, and
the ONLY correct place for it in a repo like `claude-supertool` that forbids the key in
the tracked file -- was reported as never having opted in at all.

Four states, and the fixture below exercises each one directly rather than only the
must-fire half:

* tracked-and-wired -- OK, unchanged from before this fix.
* wired in `settings.local.json` only -- OK, and the message must say which file, because
  a reader needs to know contributors do not get this.
* wired in neither -- the original WARN, unchanged.
* either file present and unreadable/unparseable -- WARN, but the message must say
  "unknown" rather than "sets no statusLine", because that sentence sends a reader to add
  a key that may already be there.

Every "must not fire" pairs with a "must fire" in this same fixture, per this repo's own
CLAUDE.md rule.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import scaffold  # noqa: E402


def _reset():
    doctor.FINDINGS.clear()


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _ours_block():
    return scaffold.STATUSLINE_COMMAND


# --------------------------------------------------------------- tracked-and-wired


def test_tracked_wired_reports_ok(tmp_path):
    _write(tmp_path / ".claude" / "settings.json", {"statusLine": {"command": _ours_block()}})
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "statusline.py" in message


# --------------------------------------------------------------- local-only


def test_local_only_wired_is_ok_and_names_the_file(tmp_path):
    """The state #642 is about: wired in settings.local.json alone must not WARN, and
    the message must say which file answered, because it means contributors who clone
    this repo will not get it."""
    _write(tmp_path / ".claude" / "settings.local.json", {"statusLine": {"command": _ours_block()}})
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "settings.local.json" in message
    assert "statusline.py" in message


def test_local_only_not_ours_is_ok_and_names_the_file(tmp_path):
    _write(tmp_path / ".claude" / "settings.local.json", {"statusLine": {"command": "mine.sh"}})
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "settings.local.json" in message
    assert "not ours" in message


def test_local_overrides_tracked_when_both_carry_the_key(tmp_path):
    """The harness runs the local key when both files carry one; the message names the
    disagreement rather than silently reporting the tracked file's command."""
    _write(tmp_path / ".claude" / "settings.json", {"statusLine": {"command": "old.sh"}})
    _write(tmp_path / ".claude" / "settings.local.json", {"statusLine": {"command": _ours_block()}})
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "settings.local.json" in message
    assert "old.sh" in message, "the disagreement must be named, not silently dropped"


def test_tracked_wins_when_local_carries_no_key(tmp_path):
    """Must-not-fire control for the merge above: a settings.local.json that exists but
    sets no statusLine must not shadow a tracked one -- this must NOT read as local-only,
    so there is no "settings.local.json" naming in the message."""
    _write(tmp_path / ".claude" / "settings.json", {"statusLine": {"command": _ours_block()}})
    _write(tmp_path / ".claude" / "settings.local.json", {"otherKey": True})
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "OK", doctor.FINDINGS
    assert "statusline.py" in message
    assert "settings.local.json" not in message


# --------------------------------------------------------------- neither (must-fire, unchanged)


def test_neither_file_wired_still_warns(tmp_path):
    (tmp_path / ".claude").mkdir(parents=True)
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "sets a statusLine" in message and "neither" in message


# --------------------------------------------------------------- unreadable / unparseable


def test_unreadable_local_file_is_unknown_not_absent(tmp_path):
    """The third state #642 asks for: an unparseable settings.local.json must not render
    as "sets no statusLine", which would send a reader to add a key that may already be
    there."""
    path = tmp_path / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "sets no statusLine" not in message
    assert "unknown" in message
    assert "settings.local.json" in message


def test_unreadable_tracked_file_is_unknown_not_absent(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "unknown" in message
    assert "settings.json" in message


def test_readable_local_next_to_unreadable_tracked_is_still_unknown(tmp_path):
    """Must-fire control for the composed case: an unreadable file elsewhere in the pair
    must not be silently dropped just because the other file parsed fine."""
    _write(tmp_path / ".claude" / "settings.local.json", {"statusLine": {"command": _ours_block()}})
    tracked = tmp_path / ".claude" / "settings.json"
    tracked.write_text("{not json", encoding="utf-8")
    _reset()
    doctor.check_statusline(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", doctor.FINDINGS
    assert "unknown" in message


def test_unsearchable_directory_is_unknown_not_absent(tmp_path):
    """A settings.json that genuinely exists, behind a .claude/ directory this process
    cannot traverse, must not collapse into "sets no statusLine" -- the same defect this
    module's own docstring already warns against for a parse failure, one call earlier.
    An earlier version of this fix used doctor._safe_is_file() to test existence, which
    swallows OSError (including "directory not searchable") into False, misreporting this
    exact case as "neither file sets a statusLine".

    A permission fixture is a measurement, not a given (CLAUDE.md): root ignores the mode
    bit and some filesystems ignore it too, so the deny is confirmed by attempting the
    exact read the code under test performs, and this skips (carrying what went untested)
    rather than asserting on a permission nothing here established.
    """
    claude_dir = tmp_path / ".claude"
    _write(claude_dir / "settings.json", {"statusLine": {"command": _ours_block()}})
    import os

    os.chmod(claude_dir, 0o000)
    try:
        # Establish the condition for real: can THIS process still read the file?
        try:
            (claude_dir / "settings.json").read_text(encoding="utf-8")
            took = False
        except PermissionError:
            took = True
        except OSError:
            took = True
        if not took:
            pytest.skip(
                "chmod 0o000 on .claude/ did not block this process's own read "
                "(root, or a filesystem that ignores the mode bit) -- untested here"
            )
        _reset()
        doctor.check_statusline(str(tmp_path))
        assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
        state, message = doctor.FINDINGS[0]
        assert state == "WARN", doctor.FINDINGS
        assert "unknown" in message
        assert "sets no statusLine" not in message
        assert "neither" not in message, (
            "a real, unreadable file must not render identically to both files being "
            "genuinely absent: " + message
        )
    finally:
        os.chmod(claude_dir, 0o755)
