"""#887: the reserved count in dispatch_rank's CLI receipt renders two states
identically -- "nobody declared a spelling" and "measured, and none matched"
both print as "0 reserved".

`reserved()` (`scripts/dispatch_rank.py:267`) is fine as a predicate: for the
question "is this issue reserved", answering False when nothing is declared
is defensible, and its own docstring argues so. The defect is one layer out,
in the rendered receipt at `main()`'s closing `print` (lines 472-473), which
is a different claim to a different reader -- a maintainer reads "0 reserved"
as a measurement, not as "the mechanism never ran".

The line directly above it in the same print already has the third state:
`labels.filed_by_loop is not declared, so who filed an issue cannot be read
off the board`. This receipt should read like its neighbour.

Positive control: a board with `labels.reserved` declared and genuinely zero
matches must still render as a measurement (e.g. "0 reserved"), distinct from
the undeclared case -- a test asserting only the undeclared arm would also
pass if the count were deleted outright.

Python 3.9 compatible.
"""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import dispatch_rank  # noqa: E402


def _run_main(issues, capsys, monkeypatch, declared):
    payload = {"declared": declared, "issues": issues}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = dispatch_rank.main([])
    return code, capsys.readouterr().out


def test_undeclared_reserved_spelling_is_not_rendered_as_zero(capsys, monkeypatch):
    """No `labels.reserved` key at all: the receipt must not print a bare
    count, because a bare "0 reserved" is indistinguishable from a board that
    was actually measured and found clean."""
    declared = {"priority": [], "filed_by_loop": "loop-filed"}
    code, out = _run_main(
        [{"number": 1, "labels": ["reserved"]}], capsys, monkeypatch, declared)
    assert code == 0, out
    last_line = out.strip().splitlines()[-1]
    assert "0 reserved" not in last_line, last_line
    assert "not declared" in last_line, last_line


def test_declared_reserved_spelling_with_zero_matches_still_renders_a_count(
    capsys, monkeypatch
):
    """Positive control: a genuinely measured board with zero reservations
    must still print a count distinguishable from the undeclared case -- a
    test that only covers the undeclared arm also passes if the count is
    removed entirely."""
    declared = {
        "priority": [], "filed_by_loop": "loop-filed", "reserved": "reserved",
    }
    code, out = _run_main(
        [{"number": 1, "labels": []}], capsys, monkeypatch, declared)
    assert code == 0, out
    last_line = out.strip().splitlines()[-1]
    assert "0 reserved" in last_line, last_line
    assert "not declared" not in last_line, last_line


def test_declared_reserved_spelling_with_a_match_still_counts_correctly(
    capsys, monkeypatch
):
    declared = {
        "priority": [], "filed_by_loop": "loop-filed", "reserved": "reserved",
    }
    code, out = _run_main(
        [{"number": 1, "labels": ["reserved"]}], capsys, monkeypatch, declared)
    assert code == 0, out
    last_line = out.strip().splitlines()[-1]
    assert "1 reserved" in last_line, last_line
