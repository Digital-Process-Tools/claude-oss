"""#149: a state file the writer cannot read must not read as one with no entries.

The failing shape is a **dict keyed `tick_<ISO timestamp>`**, each value an object of
short named facts -- what a pre-plugin maintainer skill wrote before `oss_state.py`
existed. The fixtures here are **reconstructed from the shape described in #149**, not
copied from the repository that reported it: that file is another repo's history and is
not readable from this suite.

Every "must not fire" case below sits in the same function as a "must fire" case, so a
harness that produced nothing at all fails instead of passing.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

STAMP = "2026-08-12T17:00:00Z"

# The pre-plugin shape, reconstructed from #149's description. Deliberately out of
# chronological order in the literal: a dict carries no order, so the conversion has to
# impose one rather than take the file's.
PRE_PLUGIN = {
    "tick_2026-08-01T09:00:00Z": {"decision": "merged #4", "prs": 1},
    "tick_2026-08-03T09:00:00Z": {"note": "triaged the board", "issues": 3},
    "tick_2026-08-02T09:00:00Z": {"decision": "cut 0.2.0", "release": "0.2.0"},
}


def _pre_plugin(tmp_path, name="oss-watch.json"):
    path = tmp_path / name
    path.write_text(json.dumps(PRE_PLUGIN, indent=2), encoding="utf-8")
    return path


def _list_shaped(tmp_path, name="list.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps([{"at": STAMP, "decision": "merged #4"}], indent=2), encoding="utf-8"
    )
    return path


# --- describe: the three states, each one asserted against the other two ------------


def test_describe_keeps_absent_ok_and_unreadable_apart(tmp_path):
    """The whole issue in one function: three files, three different answers.

    An assertion that the dict shape is not `ok` also passes when nothing at all is
    `ok`, so the readable file is checked in the same fixture.
    """
    absent = oss_state.describe(tmp_path / "never-written.json")
    assert absent["state"] == oss_state.STATE_ABSENT
    assert absent["entries"] is None

    readable = oss_state.describe(_list_shaped(tmp_path))
    assert readable["state"] == oss_state.STATE_OK
    assert len(readable["entries"]) == 1

    pre_plugin = oss_state.describe(_pre_plugin(tmp_path))
    assert pre_plugin["state"] == oss_state.STATE_UNREADABLE
    assert pre_plugin["entries"] is None
    # Actionable, not merely correct: it has to name the way out.
    assert "--migrate" in pre_plugin["reason"]


def test_describe_reports_an_unreadable_path_without_calling_it_absent(tmp_path):
    """`FileNotFoundError` is absence; every other `OSError` is not.

    A directory standing where the state file should be is the portable way to make the
    read fail without a permission fixture: POSIX raises `IsADirectoryError`, Windows
    raises `PermissionError`, both are `OSError`, and neither is `FileNotFoundError`.
    No errno is written down here -- only the class boundary the code branches on.
    """
    blocked = tmp_path / "a-directory.json"
    blocked.mkdir()
    found = oss_state.describe(blocked)
    assert found["state"] == oss_state.STATE_UNREADABLE
    assert found["reason"]

    # The must-fire half: absence still reports as absence from the same fixture.
    assert oss_state.describe(tmp_path / "gone.json")["state"] == oss_state.STATE_ABSENT


def test_describe_survives_a_file_that_is_not_utf_8(tmp_path):
    """`UnicodeDecodeError` is a `ValueError`, not an `OSError`.

    So an `except OSError` around the read cannot catch it, and one stray byte in the
    state file would reach `/oss:doctor` as a traceback -- through a contract that is
    exit 0 always, one VERDICT line. Latin-1 bytes are the realistic way this happens:
    a pre-plugin loop writing with the console's codepage rather than UTF-8.
    """
    path = tmp_path / "state.json"
    path.write_bytes(b'[{"at": "2026-08-01", "decision": "merg\xe9"}]')
    found = oss_state.describe(path)
    assert found["state"] == oss_state.STATE_UNREADABLE
    assert found["reason"]

    # Must-fire control: a UTF-8 file of the same shape still reads.
    assert oss_state.describe(_list_shaped(tmp_path))["state"] == oss_state.STATE_OK


def test_describe_calls_a_corrupt_file_unreadable_rather_than_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")
    found = oss_state.describe(path)
    assert found["state"] == oss_state.STATE_UNREADABLE
    assert "parse" in found["reason"]


# --- read(): still refuses, and now says what to do about it -----------------------


def test_read_refuses_the_pre_plugin_shape_and_names_the_way_out(tmp_path):
    path = _pre_plugin(tmp_path)
    with pytest.raises(oss_state.StateError) as caught:
        oss_state.read(path)
    assert "--migrate" in str(caught.value)
    # And the readable shape still reads, in the same fixture.
    assert len(oss_state.read(_list_shaped(tmp_path))) == 1


# --- migrate: explicit, lossless, and refusing what it cannot convert --------------


def test_migrate_converts_the_pre_plugin_shape_losslessly(tmp_path):
    path = _pre_plugin(tmp_path)
    result = oss_state.migrate(path)
    assert result["state"] == oss_state.MIGRATED
    assert result["entries"] == 3

    entries = oss_state.read(path)
    # A dict carries no order, so the conversion imposes one: sorted by key.
    assert [entry["at"] for entry in entries] == [
        "2026-08-01T09:00:00Z",
        "2026-08-02T09:00:00Z",
        "2026-08-03T09:00:00Z",
    ]
    # Nothing invented and nothing dropped: the original object is kept whole.
    assert entries[0]["detail"] == PRE_PLUGIN["tick_2026-08-01T09:00:00Z"]
    assert entries[2]["detail"] == PRE_PLUGIN["tick_2026-08-03T09:00:00Z"]
    # A decision the old shape carried is carried over ...
    assert entries[0]["decision"] == "merged #4"
    # ... and one it never carried is said to be missing rather than guessed at.
    assert "no decision" in entries[2]["decision"]

    # The point of the whole exercise: the next tick can now write.
    oss_state.append(path, STAMP, "merged #149")
    assert len(oss_state.read(path)) == 4


def test_migrate_keeps_the_original_beside_the_converted_file(tmp_path):
    path = _pre_plugin(tmp_path)
    result = oss_state.migrate(path)
    backup = Path(result["backup"])
    assert json.loads(backup.read_text(encoding="utf-8")) == PRE_PLUGIN


def test_migrate_refuses_rather_than_overwriting_an_earlier_backup(tmp_path):
    path = _pre_plugin(tmp_path)
    backup = Path(str(path) + oss_state.BACKUP_SUFFIX)
    backup.write_text("the history from an earlier attempt", encoding="utf-8")

    result = oss_state.migrate(path)
    assert result["state"] == oss_state.CANNOT_MIGRATE
    assert backup.read_text(encoding="utf-8") == "the history from an earlier attempt"
    assert json.loads(path.read_text(encoding="utf-8")) == PRE_PLUGIN


def test_migrate_is_a_no_op_on_a_file_that_is_already_a_list(tmp_path):
    path = _list_shaped(tmp_path)
    before = path.read_text(encoding="utf-8")
    result = oss_state.migrate(path)
    assert result["state"] == oss_state.ALREADY_A_LIST
    assert path.read_text(encoding="utf-8") == before
    assert not Path(str(path) + oss_state.BACKUP_SUFFIX).exists()


def test_migrate_refuses_a_shape_it_would_have_to_guess_at(tmp_path):
    """A value that is not an object of facts is not a tick entry, and inventing an
    entry for it would put a fabricated record in a file that exists to be evidence.
    """
    path = tmp_path / "odd.json"
    path.write_text(
        json.dumps({"tick_2026-08-01T09:00:00Z": "merged #4"}), encoding="utf-8"
    )
    result = oss_state.migrate(path)
    assert result["state"] == oss_state.CANNOT_MIGRATE
    assert result["reason"]
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "tick_2026-08-01T09:00:00Z": "merged #4"
    }

    # Must-fire control: the shape it CAN convert still converts, same fixture.
    assert oss_state.migrate(_pre_plugin(tmp_path))["state"] == oss_state.MIGRATED


def test_migrate_refuses_a_corrupt_file_without_touching_it(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")
    assert oss_state.migrate(path)["state"] == oss_state.CANNOT_MIGRATE
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_migrate_refuses_a_file_that_is_not_there(tmp_path):
    """Absence is not something to convert, and it is not a conversion that worked."""
    result = oss_state.migrate(tmp_path / "gone.json")
    assert result["state"] == oss_state.CANNOT_MIGRATE
    assert "not there" in result["reason"]


# --- the CLI /oss:tick invokes -----------------------------------------------------


def test_cli_migrate_converts_and_reports_the_count(tmp_path, capsys):
    path = _pre_plugin(tmp_path)
    assert oss_state._main([str(path), "--migrate"]) == 0
    assert "3" in capsys.readouterr().out
    assert len(oss_state.read(path)) == 3


def test_cli_migrate_exits_nonzero_on_a_shape_it_will_not_convert(tmp_path, capsys):
    path = tmp_path / "odd.json"
    path.write_text(json.dumps({"tick_x": 4}), encoding="utf-8")
    assert oss_state._main([str(path), "--migrate"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_last_on_the_pre_plugin_shape_fails_rather_than_saying_no_entries(
    tmp_path, capsys
):
    """The read at the top of a tick is where this has to surface.

    `no entries yet` over a file holding 159 of them is this repo's own defect class,
    and it is the sentence a maintainer would act on by starting fresh.
    """
    path = _pre_plugin(tmp_path)
    assert oss_state._main([str(path), "--last"]) == 1
    out = capsys.readouterr().out
    assert "no entries yet" not in out
    assert "--migrate" in out

    # Must-fire control: an empty history still reports as one.
    assert oss_state._main([str(tmp_path / "gone.json"), "--last"]) == 0
    assert "no entries yet" in capsys.readouterr().out
