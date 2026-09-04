"""#990: `/oss:doctor` reports whether `labels.filed_by_loop` is declared, and what it
costs when it is not -- `dispatch_rank.rank` (#798) refuses to rank ANY issue on a
board where this key is undeclared, and that refusal is permanent and indistinguishable
from a board with nothing rankable on it today unless something says so out loud.

Three states: `declared` (a non-empty string), `not-declared` (absent, null, or the key
missing from `labels` entirely), `could-not-tell` (present but not a usable label name --
a bool, an empty string, a number). `not-declared` must name the `dispatch_rank`
consequence; a positive control (`declared`) proves the same fixture does NOT trip that
consequence line when the label is actually set.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _config(labels):
    config = {"repo": "o/r"}
    if labels is not None:
        config["labels"] = labels
    return config


def test_declared_reports_ok_and_names_the_label():
    doctor.FINDINGS.clear()
    doctor.check_filed_by_loop("/tmp", _config({"filed_by_loop": "filed-by-loop"}))
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "filed-by-loop" in message
    assert "dispatch_rank" not in message
    doctor.FINDINGS.clear()


def test_missing_key_reports_warn_and_names_the_dispatch_rank_consequence():
    doctor.FINDINGS.clear()
    doctor.check_filed_by_loop("/tmp", _config({"priority": ["priority-high"]}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not-declared" in message
    assert "dispatch_rank" in message
    assert "could-not-rank" in message
    doctor.FINDINGS.clear()


def test_null_value_reports_warn_same_as_missing():
    doctor.FINDINGS.clear()
    doctor.check_filed_by_loop("/tmp", _config({"filed_by_loop": None}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "not-declared" in message
    assert "dispatch_rank" in message
    doctor.FINDINGS.clear()


def test_malformed_value_reports_could_not_tell_not_not_declared():
    doctor.FINDINGS.clear()
    doctor.check_filed_by_loop("/tmp", _config({"filed_by_loop": True}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "could-not-tell" in message
    doctor.FINDINGS.clear()


def test_empty_string_value_reports_could_not_tell():
    doctor.FINDINGS.clear()
    doctor.check_filed_by_loop("/tmp", _config({"filed_by_loop": "   "}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "could-not-tell" in message
    doctor.FINDINGS.clear()


def test_missing_config_is_reported_not_silently_skipped():
    doctor.FINDINGS.clear()
    doctor.check_filed_by_loop("/tmp", None)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "filed_by_loop" in message
    doctor.FINDINGS.clear()
