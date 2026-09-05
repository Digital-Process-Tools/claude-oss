"""#686 -- `check_plugin_root`'s could-not-read `why` collapses two different
facts into one sentence.

The auditor for the 0.16.0 release gate recorded a snapshot, ran `chmod 0` on
it, confirmed the deny actually took (`PermissionError`, errno 13), and found
that a genuine absence (no snapshot recorded yet, or one already consumed)
and an unreadable snapshot (present, but the read itself failed) both return
the byte-identical `why`:

    no snapshot was recorded earlier in this tick (or an earlier check
    already consumed it) -- record one at the start of the tick with
    --record-plugin-root before checking

`state` is correctly `PLUGIN_ROOT_COULD_NOT_READ` in both cases and does not
collapse into `PLUGIN_ROOT_UNCHANGED` -- so this is the mild form of the
defect class this repo is named after. What is wrong is the sentence: it
asserts an absence nothing established, and it names a remedy
(`--record-plugin-root`) that cannot help a caller whose snapshot exists and
cannot be read.

Both arms are covered in this one fixture, on purpose: a fix that reports
every could-not-read as "unreadable" would pass a test that only checked the
unreadable arm, and that is exactly the failure mode CLAUDE.md's own rule
about positive controls exists to catch.

The permission fixture is a measurement, not a given (root ignores the mode
bit; some filesystems ignore it too) -- if `chmod 0` does not actually
produce a PermissionError on this machine, the unreadable-arm assertion is
skipped rather than faked, carrying what went untested.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

ROOT_A = "/home/x/.claude/plugins/cache/dpt-plugins/oss/0.14.0"


def test_absent_snapshot_says_absent_not_unreadable(tmp_path):
    """MUST FIRE (positive control): no snapshot was ever recorded -- the `why`
    must still name the absence/remedy sentence, not the unreadable one."""
    path = tmp_path / "state.json"
    record = oss_state.check_plugin_root(str(path), ROOT_A)
    assert record["state"] == oss_state.PLUGIN_ROOT_COULD_NOT_READ
    assert "no snapshot was recorded" in record["why"]
    assert "--record-plugin-root" in record["why"]


def test_undecodable_snapshot_says_unreadable_not_absent(tmp_path):
    """Self-review finding: `UnicodeDecodeError` is a `ValueError`, not an
    `OSError`, so it slips past an `except OSError` the same way #76 already
    demonstrated for `describe()`'s identical read. MUST FIRE: a snapshot
    holding one stray non-UTF-8 byte must come back as a clean
    PLUGIN_ROOT_COULD_NOT_READ record naming the decode failure, never as an
    uncaught traceback and never as the absence sentence."""
    path = tmp_path / "state.json"
    oss_state.record_plugin_root(str(path), ROOT_A)
    snapshot = Path(str(path) + ".plugin-root-snapshot.json")
    snapshot.write_bytes(b"\xff\xfe\x00\x01invalid utf8 bytes \x80\x81")

    record = oss_state.check_plugin_root(str(path), ROOT_A)
    assert record["state"] == oss_state.PLUGIN_ROOT_COULD_NOT_READ
    assert "no snapshot was recorded" not in record["why"]
    assert "--record-plugin-root" not in record["why"]
    assert "decode" in record["why"].lower()


def test_unreadable_snapshot_says_unreadable_not_absent(tmp_path):
    """MUST FIRE: a snapshot that exists but cannot be read (permission denied)
    must not be told to run --record-plugin-root -- there is already a
    snapshot; the read itself failed. If chmod 0 does not actually deny the
    read on this machine (root, or a filesystem that ignores the mode bit),
    skip rather than assert on an unestablished condition."""
    path = tmp_path / "state.json"
    oss_state.record_plugin_root(str(path), ROOT_A)
    snapshot = Path(str(path) + ".plugin-root-snapshot.json")
    assert snapshot.exists()

    original_mode = snapshot.stat().st_mode
    os.chmod(str(snapshot), 0)
    try:
        try:
            snapshot.read_text(encoding="utf-8")
        except OSError as exc:
            assert isinstance(exc, PermissionError), (
                "fixture measurement: chmod 0 did not deny the read as "
                "expected ({!r}) -- the deny did not take on this "
                "platform/filesystem".format(exc)
            )
        else:
            import pytest

            pytest.skip(
                "chmod 0 did not deny the read on this platform/filesystem "
                "(root, or a filesystem that ignores the mode bit) -- the "
                "unreadable arm was not exercised"
            )

        record = oss_state.check_plugin_root(str(path), ROOT_A)
        assert record["state"] == oss_state.PLUGIN_ROOT_COULD_NOT_READ
        assert "no snapshot was recorded" not in record["why"]
        assert "--record-plugin-root" not in record["why"]
        assert "13" in record["why"] or "Permission" in record["why"]
    finally:
        os.chmod(str(snapshot), original_mode)
