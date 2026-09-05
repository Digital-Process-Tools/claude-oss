"""#149: a state file the writer cannot read must not read as one with no entries.

The failing shape is a **dict keyed `tick_<ISO timestamp>`**, each value an object of
short named facts -- what a pre-plugin maintainer skill wrote before `oss_state.py`
existed. The fixtures here are **reconstructed from the shape described in #149**, not
copied from the repository that reported it: that file is another repo's history and is
not readable from this suite.

Every "must not fire" case below sits in the same function as a "must fire" case, so a
harness that produced nothing at all fails instead of passing.
"""

import errno
import json
import platform
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


def test_the_backup_is_the_original_bytes_not_a_re_encoding_of_them(tmp_path):
    """ "Kept whole" has to mean the bytes.

    `read_text` translates newlines, so a state file written on Windows round-trips
    through the backup with its CRLFs replaced -- a copy that is not what it is a copy
    of, held out as the thing to fall back to.
    """
    path = tmp_path / "crlf.json"
    original = json.dumps(PRE_PLUGIN, indent=2).replace("\n", "\r\n").encode("utf-8")
    path.write_bytes(original)

    result = oss_state.migrate(path)
    assert result["state"] == oss_state.MIGRATED
    assert Path(result["backup"]).read_bytes() == original


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


def test_a_json_document_that_is_neither_shape_is_named_rather_than_lumped_in(tmp_path):
    """A number or a string at the top level is not the pre-plugin shape either.

    It gets its own sentence rather than the migration hint, which would send a
    maintainer to run a conversion that cannot apply.
    """
    path = tmp_path / "odd.json"
    path.write_text("4", encoding="utf-8")

    found = oss_state.describe(path)
    assert found["state"] == oss_state.STATE_UNREADABLE
    assert "int" in found["reason"]
    assert "--migrate" not in found["reason"]

    result = oss_state.migrate(path)
    assert result["state"] == oss_state.CANNOT_MIGRATE
    assert "int" in result["reason"]

    # Must-fire control: the hint IS given for the shape it applies to, same fixture.
    assert "--migrate" in oss_state.describe(_pre_plugin(tmp_path))["reason"]


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


# --- migrate: the failure receipt has to be true of the file, not just readable ----
#
# #174. The receipt on a failed write says "the original is unchanged". Asserting that
# the sentence is present passes whether or not the file survived, so every case below
# injects the failure and reads the original back.


# The injection seam, and why it is this one.
#
# `io.open` was the first choice and it is version-dependent, which CI settled: the
# three cases below failed on ubuntu, macos AND windows at Python 3.10, and only 3.10.
# CPython 3.10 alone routes `Path.open` through `self._accessor.open`, and
# `_NormalAccessor.open = io.open` captures the function object when `pathlib` is
# imported -- so rebinding the module attribute afterwards is invisible to it. 3.9
# calls `io.open(...)` by name and 3.11 deleted the accessor, which is why the legs
# either side were green.
#
# A patched module attribute is a claim about a lookup somebody else's code performs.
# A method on the class the code under test calls by name -- `Path.write_text`,
# `Path.read_bytes` -- is looked up at call time on every version, and it is the call
# `migrate` itself makes rather than a layer underneath it.
#
# The measurement below is the second half, because "stable across the versions I
# reasoned about" is still a claim. Each case attempts the exact operation it is about
# to rely on, against a scratch file of the same shape, and skips with the interpreter
# and the sentence naming what went untested when the injection did not take. Nothing
# here asserts on a condition it did not establish.


def _is_sibling_of(path, target):
    """Is ``path`` the state file, or a temp file written beside it?

    The backup is excluded on purpose: it is written with the builtin `open`, and it
    has to succeed for the case under test to be "the converted history could not be
    written".
    """
    name = Path(path).name
    if name.endswith(oss_state.BACKUP_SUFFIX):
        return False
    return name == target.name or name.startswith(target.name + ".")


def _explode_writes_near(monkeypatch, target, limit=5):
    """Make the write of the converted history fail part-way, wherever it goes.

    Truncate-then-raise, because the whole of #174 is that the failure lands after the
    file is already destroyed -- an injection that raised before writing would leave
    the original intact on the old code too, and prove nothing.
    """
    real_write_text = Path.write_text
    target = Path(target)

    def write_text(self, data, *args, **kwargs):
        if not _is_sibling_of(self, target):
            return real_write_text(self, data, *args, **kwargs)
        with open(str(self), "w", encoding="utf-8") as handle:
            handle.write(data[:limit])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "write_text", write_text)


def _untested_if_writes_survive(tmp_path, target):
    """None if the write injection took, else the sentence to skip with.

    A probe rather than a version check: which interpreters route `Path.write_text`
    somewhere else is exactly what this cannot know in advance, and a table of versions
    cannot report one it does not contain.
    """
    probe = Path(tmp_path) / (Path(target).name + ".injection-probe")
    try:
        probe.write_text("probe", encoding="utf-8")
    except OSError:
        return None
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return (
        "Path.write_text is patched and a write to {} still succeeded on Python {}, so "
        "this harness cannot make a write fail here. UNTESTED on this interpreter: "
        "that a failed write of the converted history leaves the original "
        "intact.".format(probe.name, platform.python_version())
    )


def _untested_if_reads_survive(tmp_path):
    """None if the read-back injection took, else the sentence to skip with."""
    probe = Path(tmp_path) / ("probe.json" + oss_state.BACKUP_SUFFIX)
    probe.write_bytes(b"probe")
    try:
        probe.read_bytes()
    except OSError:
        return None
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return (
        "Path.read_bytes is patched and a read of {} still succeeded on Python {}, so "
        "this harness cannot make the read-back fail. UNTESTED on this interpreter: "
        "that a backup which cannot be read back stops the conversion.".format(
            probe.name, platform.python_version()
        )
    )


def test_a_failed_write_leaves_the_original_the_receipt_calls_unchanged(
    tmp_path, monkeypatch
):
    """The whole of #174: force the write to fail part-way, then read the file back.

    Two halves, and they answer different questions. The probe establishes that this
    harness can make a write fail at all; without it a `migrated` result reads as a
    product defect when it may be an injection that never fired -- an environment limit
    rendered as a product verdict, which is what CI caught here on 3.10. Past the probe
    the must-fire assertion is a real verdict: the failure was forced, so a conversion
    that reports success has genuinely written over the original.
    """
    path = _pre_plugin(tmp_path, name="state.json")
    original = path.read_bytes()

    _explode_writes_near(monkeypatch, path)
    untested = _untested_if_writes_survive(tmp_path, path)
    if untested:
        pytest.skip(untested)

    result = oss_state.migrate(path)

    assert result["state"] == oss_state.CANNOT_MIGRATE, (
        "the injected failure never fired"
    )
    assert "No space left on device" in result["reason"]
    # The sentence the receipt makes, checked against the file rather than the string.
    assert path.read_bytes() == original
    assert "unchanged" in result["reason"]
    # ... and the copy it points at is real, and is the history.
    assert json.loads(Path(result["backup"]).read_text(encoding="utf-8")) == PRE_PLUGIN


def test_a_failed_write_leaves_no_half_written_file_beside_the_original(
    tmp_path, monkeypatch
):
    """A temp file is the cost of the atomic write, so it is the thing to account for.

    Must-fire control in the same fixture: a migration that is allowed to finish also
    leaves nothing behind, so this cannot pass by nothing ever being created.
    """
    path = _pre_plugin(tmp_path, name="state.json")

    with monkeypatch.context() as patched:
        _explode_writes_near(patched, path)
        untested = _untested_if_writes_survive(tmp_path, path)
        if untested:
            pytest.skip(untested)
        assert oss_state.migrate(path)["state"] == oss_state.CANNOT_MIGRATE

    after_failure = sorted(p.name for p in tmp_path.iterdir())
    assert after_failure == ["state.json", "state.json" + oss_state.BACKUP_SUFFIX]

    Path(str(path) + oss_state.BACKUP_SUFFIX).unlink()
    assert oss_state.migrate(path)["state"] == oss_state.MIGRATED
    assert sorted(p.name for p in tmp_path.iterdir()) == after_failure


def test_the_backup_is_read_back_before_the_original_is_touched(tmp_path, monkeypatch):
    """A receipt pointing at a copy nobody read back is the same defect one layer out.

    The injection makes the backup write drop most of the bytes and report success --
    a short write, which is what a full or flaky filesystem does. Nothing may then be
    written to the original.
    """
    path = _pre_plugin(tmp_path, name="state.json")
    original = path.read_bytes()
    real_open = getattr(oss_state, "open", open)

    class _ShortWriter:
        def __init__(self, handle):
            self._handle = handle

        def write(self, payload):
            return self._handle.write(payload[:4])

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()
            return False

    def opener(file, *args, **kwargs):
        return _ShortWriter(real_open(file, *args, **kwargs))

    with monkeypatch.context() as patched:
        patched.setattr(oss_state, "open", opener, raising=False)
        # Same measurement as the two cases above, for a seam that needs it less:
        # `oss_state.open` is the module's own global lookup and does not vary by
        # version. Cheap enough that "less likely to break" is not a reason to assert
        # on a condition nobody established.
        probe = tmp_path / "probe.bin"
        with oss_state.open(str(probe), "xb") as handle:
            handle.write(b"12345678")
        short = probe.stat().st_size == 4
        probe.unlink()
        if not short:
            pytest.skip(
                "oss_state.open is patched and a backup write still stored every byte "
                "on Python {}, so this harness cannot fake a short write. UNTESTED on "
                "this interpreter: that a backup which does not match the original "
                "stops the conversion.".format(platform.python_version())
            )
        result = oss_state.migrate(path)

    assert result["state"] == oss_state.CANNOT_MIGRATE, "the short write never fired"
    assert "backup" in result["reason"]
    assert path.read_bytes() == original

    # Must-fire control, same fixture: with the write intact the backup verifies and
    # the conversion goes through, so the guard above is not simply always refusing.
    Path(str(path) + oss_state.BACKUP_SUFFIX).unlink()
    assert oss_state.migrate(path)["state"] == oss_state.MIGRATED


def test_a_backup_that_cannot_be_read_back_is_its_own_answer(tmp_path, monkeypatch):
    """Unverifiable is not the same state as verified-and-wrong, and neither is fine.

    Both stop before the original is touched, and neither hands back the copy as
    something to restore from -- `backup` stays None and the reason names the path as
    a thing to move aside.
    """
    path = _pre_plugin(tmp_path, name="state.json")
    original = path.read_bytes()
    real_read_bytes = Path.read_bytes

    def read_bytes(self):
        if Path(self).name.endswith(oss_state.BACKUP_SUFFIX):
            raise OSError(errno.EIO, "Input/output error")
        return real_read_bytes(self)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "read_bytes", read_bytes)
        untested = _untested_if_reads_survive(tmp_path)
        if untested:
            pytest.skip(untested)
        result = oss_state.migrate(path)

    assert result["state"] == oss_state.CANNOT_MIGRATE, "the read-back never failed"
    assert "Input/output error" in result["reason"]
    assert str(path) + oss_state.BACKUP_SUFFIX in result["reason"]
    assert result["backup"] is None
    assert path.read_bytes() == original

    # Must-fire control, same fixture: a backup that reads back is accepted, and the
    # copy is named as one -- so the guard is not refusing everything.
    Path(str(path) + oss_state.BACKUP_SUFFIX).unlink()
    done = oss_state.migrate(path)
    assert done["state"] == oss_state.MIGRATED
    assert done["backup"] == str(path) + oss_state.BACKUP_SUFFIX


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
