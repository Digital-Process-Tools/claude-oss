"""#1774: `/oss:doctor` reports whether `labels.priority` is declared and
non-empty, and what an empty list costs -- `select_issues_rank.rank` (#798)
treats `labels.priority == []` exactly the same as the key being entirely
absent, so a repo `/oss:setup` scaffolded with no `priority-*` labels on the
forge gets a declared, empty list written to `.oss.json`, and dispatch has no
bands to rank within for any issue, forever, with nothing anywhere naming why.

Mirrors `tests/test_doctor_filed_by_loop_990.py`'s own shape one key over,
adjusted for the list-typed value: `declared` (a non-empty list of usable
label names), `declared-empty` (present but empty, or the key missing/null --
folded into the same WARN text, see `check_priority_labels`'s own docstring
for why), and `could-not-tell` (present but not a usable list). A positive
control (`declared`) proves the same fixture does NOT trip the empty-list
consequence line when the labels are actually set.
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


def test_declared_reports_ok_and_names_the_labels():
    doctor.FINDINGS.clear()
    doctor.check_priority_labels(
        "/tmp", _config({"priority": ["priority-high", "priority-low"]})
    )
    state, message = doctor.FINDINGS[-1]
    assert state == "OK"
    assert "priority-high" in message
    assert "select_issues_rank" not in message
    doctor.FINDINGS.clear()


def test_empty_list_reports_warn_and_names_the_select_issues_rank_consequence():
    """The must-fire half: the scaffold-produced case #1774 reports."""
    doctor.FINDINGS.clear()
    doctor.check_priority_labels("/tmp", _config({"priority": [], "lanes": []}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "labels.priority is empty" in message
    assert "select_issues_rank" in message
    assert "could-not-rank" in message
    doctor.FINDINGS.clear()


def test_missing_key_reports_warn_same_as_empty():
    doctor.FINDINGS.clear()
    doctor.check_priority_labels("/tmp", _config({"filed_by_loop": "x"}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "labels.priority is empty" in message
    doctor.FINDINGS.clear()


def test_null_value_reports_warn_same_as_missing():
    doctor.FINDINGS.clear()
    doctor.check_priority_labels("/tmp", _config({"priority": None}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "labels.priority is empty" in message
    doctor.FINDINGS.clear()


def test_malformed_value_reports_could_not_tell_not_empty():
    doctor.FINDINGS.clear()
    doctor.check_priority_labels("/tmp", _config({"priority": "priority-high"}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "could-not-tell" in message
    doctor.FINDINGS.clear()


def test_list_with_a_non_string_entry_reports_could_not_tell():
    doctor.FINDINGS.clear()
    doctor.check_priority_labels("/tmp", _config({"priority": ["priority-high", 3]}))
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "could-not-tell" in message
    doctor.FINDINGS.clear()


def test_missing_config_is_reported_not_silently_skipped():
    doctor.FINDINGS.clear()
    doctor.check_priority_labels("/tmp", None)
    state, message = doctor.FINDINGS[-1]
    assert state == "WARN"
    assert "labels.priority" in message
    doctor.FINDINGS.clear()
