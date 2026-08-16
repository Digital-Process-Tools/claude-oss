"""The oss_state CLI that /oss:tick invokes."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

STAMP = "2026-08-12T17:00:00Z"


def test_read_on_an_empty_history_prints_an_empty_list(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--read"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_last_on_an_empty_history_says_so_rather_than_printing_null(tmp_path, capsys):
    """`null` on stdout reads like a value. It is the absence of one."""
    assert oss_state._main([str(tmp_path / "state.json"), "--last"]) == 0
    assert "no entries yet" in capsys.readouterr().out


def test_appending_requires_a_timestamp(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--decision", "merged #4"]) == 1
    assert "not read from a clock" in capsys.readouterr().out
    assert not path.exists()


def test_append_writes_and_prints_the_entry(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--decision", "merged #4", "--at", STAMP]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["decision"] == "merged #4"
    assert oss_state.read(path) == [entry]


def test_append_carries_a_json_detail(tmp_path, capsys):
    path = tmp_path / "state.json"
    oss_state._main(
        [str(path), "--decision", "triaged", "--at", STAMP, "--detail", '{"issues": [1, 2]}']
    )
    assert json.loads(capsys.readouterr().out)["detail"] == {"issues": [1, 2]}


def test_a_malformed_detail_is_refused_and_writes_nothing(tmp_path, capsys):
    path = tmp_path / "state.json"
    assert oss_state._main([str(path), "--decision", "x", "--at", STAMP, "--detail", "{oops"]) == 1
    assert "not valid JSON" in capsys.readouterr().out
    assert not path.exists()


def test_an_over_long_decision_is_refused_with_the_reason(tmp_path, capsys):
    path = tmp_path / "state.json"
    long_decision = "x" * (oss_state.MAX_DECISION + 1)
    assert oss_state._main([str(path), "--decision", long_decision, "--at", STAMP]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "belongs in the pull request" in out


# ------------------------------------------------- the intake line is a receipt (#222)
#
# Every assertion below is paired. A "must not print" on its own passes against a run
# that printed nothing at all -- a crash before the first line, an argv the parser
# rejected -- so each silence is asserted in the same fixture as the run where the line
# must appear.

INTAKE_ARGV = [
    "--at",
    STAMP,
    "--filings",
    "3",
    "--merged-prs",
    "0",
    "--window",
    "since the 07:05Z tick",
]


def _lines_starting(text, prefix):
    return [line for line in text.splitlines() if line.startswith(prefix)]


def _first(lines, prefix):
    """Index of the first line with this prefix, or None. None is the third state: a
    boolean here would render "not present" and "present at index 0" alike."""
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


def _permitted_writes(directory, path):
    """Which of the two writes this platform still allows, by attempting each one.

    Named rather than counted: the skip message has to say what went untested, and
    "the platform ignored a mode bit" is not that.
    """
    permitted = []
    try:
        handle, probe = tempfile.mkstemp(dir=str(directory), prefix="probe")
    except OSError:
        pass
    else:
        os.close(handle)
        os.unlink(probe)
        permitted.append("creating a file in a 0o500 directory")
    try:
        with open(str(path), "a", encoding="utf-8"):
            pass
    except OSError:
        pass
    else:
        permitted.append("opening a 0o444 file for writing")
    return permitted


def test_the_intake_receipt_prints_only_when_the_entry_landed(tmp_path, capsys):
    """It reads as a receipt, so it must not exist before the write it receipts.

    The refused run used to print the intake sentence first and the FAIL under it, so a
    caller filtering for the metric saw a success-shaped line for a write that never
    happened.
    """
    path = tmp_path / "state.json"

    # must fire
    assert oss_state._main([str(path), "--decision", "merged #4"] + INTAKE_ARGV) == 0
    landed = capsys.readouterr()
    assert _lines_starting(landed.err, "RECORDED intake since the 07:05Z tick")
    assert oss_state.read(path)[0]["detail"]["intake"]["filings"] == 3

    # must not fire
    over_cap = "x" * (oss_state.MAX_DECISION + 1)
    assert oss_state._main([str(path), "--decision", over_cap] + INTAKE_ARGV) == 1
    refused = capsys.readouterr()
    assert _lines_starting(refused.err, "RECORDED intake") == []
    assert len(oss_state.read(path)) == 1


def _piped(argv):
    """Run the CLI as a real process with the two streams merged into one pipe.

    `capsys` keeps stdout and stderr apart, so it cannot see the ordering this asserts:
    stdout is block-buffered the moment it is a pipe, and a FAIL printed first still
    surfaces second unless something flushes. A transcript is read as one merged stream,
    so that is what the fixture has to be.
    """
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def test_a_refused_entry_says_the_intake_pair_was_not_recorded_after_the_fail(tmp_path):
    """A count somebody took and the tool dropped needs a line saying so -- and it is a
    different string from the receipt, so a filter that catches one cannot catch the
    other. The verdict comes first in the merged stream, which is the whole issue."""
    path = tmp_path / "state.json"
    over_cap = "x" * (oss_state.MAX_DECISION + 1)

    # must fire: a run that lands, so the "no FAIL" half below cannot pass against a
    # process that died before it printed anything.
    landed = _piped([str(path), "--decision", "merged #4"] + INTAKE_ARGV)
    assert landed.returncode == 0, landed.stdout
    lines = landed.stdout.splitlines()
    # Not an index: nothing here engineers the receipt's position relative to the JSON
    # payload, and pinning it would assert a buffering accident.
    assert _first(lines, "RECORDED intake") is not None, lines
    assert _first(lines, "FAIL") is None, lines
    assert _first(lines, "NOT RECORDED") is None, lines

    # must not fire, and the verdict must be above what survives of the run
    refused = _piped([str(path), "--decision", over_cap] + INTAKE_ARGV)
    assert refused.returncode == 1, refused.stdout
    lines = refused.stdout.splitlines()
    assert _first(lines, "FAIL") == 0, lines
    assert _first(lines, "NOT RECORDED") == 1, lines
    assert "3 filings" in lines[1]
    assert not [line for line in lines if line.startswith("RECORDED")]
    assert len(oss_state.read(path)) == 1


def test_a_malformed_detail_still_says_the_intake_pair_was_dropped(tmp_path):
    """The refusal that fires before the record is attached still drops a measured pair.

    `--detail` is parsed in the same run that carries the counts, so a refusal there was
    a pair going nowhere with nothing said about it -- this issue's own defect one branch
    over, and it was live until the record was built ahead of the parse.
    """
    path = tmp_path / "state.json"
    argv = [str(path), "--decision", "merged #4"] + INTAKE_ARGV

    # must fire: the same argv with a well-formed detail lands and receipts, so the
    # assertion below cannot pass against a run that printed nothing.
    landed = _piped(argv + ["--detail", '{"pr": 222}'])
    assert landed.returncode == 0, landed.stdout
    assert _first(landed.stdout.splitlines(), "RECORDED intake") is not None

    refused = _piped(argv + ["--detail", "{oops"])
    assert refused.returncode == 1, refused.stdout
    lines = refused.stdout.splitlines()
    assert _first(lines, "FAIL") == 0, lines
    assert _first(lines, "NOT RECORDED") == 1, lines
    assert "3 filings" in lines[1]
    assert len(oss_state.read(path)) == 1


def test_the_trend_line_is_labelled_as_a_computation_not_a_receipt(tmp_path):
    """`--trend` renders the same sentence and stores nothing, so it carries its own
    label. Paired with a run that does write, because "no RECORDED here" is worth
    nothing unless RECORDED appears somewhere."""
    path = tmp_path / "state.json"

    # must fire
    landed = _piped([str(path), "--decision", "merged #4"] + INTAKE_ARGV)
    assert landed.returncode == 0, landed.stdout
    landed_lines = landed.stdout.splitlines()
    assert _first(landed_lines, "RECORDED intake") is not None, landed_lines
    assert _first(landed_lines, "TREND") is None, landed_lines

    # must not fire: a read-only mode receipts nothing
    before = path.read_text(encoding="utf-8")
    trend = _piped([str(path), "--trend"])
    assert trend.returncode == 0, trend.stdout
    lines = trend.stdout.splitlines()
    assert _first(lines, "TREND intake") is not None, lines
    assert [line for line in lines if line.startswith("RECORDED")] == []
    assert _first(lines, "NOT RECORDED") is None, lines
    assert path.read_text(encoding="utf-8") == before


def test_a_write_that_cannot_land_is_a_fail_line_and_leaves_the_history_intact(
    tmp_path, capsys
):
    """The third case: validation passes, and the write itself fails.

    It used to reach the caller as the receipt followed by a traceback -- no FAIL line
    at all, so a caller watching for one saw only the success-shaped sentence.
    """
    directory = tmp_path / "ro"
    directory.mkdir()
    path = directory / "state.json"
    oss_state.append(path, STAMP, "the tick before")
    before = path.read_text(encoding="utf-8")

    # Both bits, because the write has had two shapes and the fixture has to deny the
    # one actually attempted: a temp file created beside the state file and renamed over
    # it needs the directory, and an in-place rewrite needs the file.
    os.chmod(str(path), 0o444)
    os.chmod(str(directory), 0o500)
    try:
        # A permission fixture is a measurement, not a given: root ignores the mode bit,
        # some filesystems ignore it, and Windows' os.chmod toggles a read-only
        # attribute that stops neither. So attempt both exact operations and skip with
        # what went untested if either one is permitted.
        permitted = _permitted_writes(directory, path)
        if permitted:
            pytest.skip(
                "this platform permitted {}, so the failed-write arm of append() went "
                "untested here".format(" and ".join(permitted))
            )

        assert oss_state._main([str(path), "--decision", "merged #4"] + INTAKE_ARGV) == 1
        captured = capsys.readouterr()
        assert _lines_starting(captured.out, "FAIL"), captured.out
        assert "unchanged" in captured.out
        assert _lines_starting(captured.err, "RECORDED intake") == []
        assert _lines_starting(captured.err, "NOT RECORDED"), captured.err
    finally:
        os.chmod(str(directory), 0o700)
        os.chmod(str(path), 0o644)

    assert path.read_text(encoding="utf-8") == before


def test_a_corrupt_state_file_fails_loudly_and_is_not_reset(tmp_path, capsys):
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")
    assert oss_state._main([str(path), "--read"]) == 1
    assert "could not parse" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == "{ not json"
