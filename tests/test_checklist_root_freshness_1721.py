"""`compare_root_freshness` -- whether the root gate 3 resolved and measured
is the newest copy of the plugin cached on this machine, or a stale one
behind it (#1721).

Gate 3's `checklist_skew.py --plugin-root` already names WHICH checklist
version ran. It has never named whether that version was current: a
`resolved-install` root is built from the version recorded for THIS
project, which is not necessarily the newest copy an update elsewhere (or a
cache nobody pruned) has already superseded. #1328's `compare_effect` catches
the spawn resolving a DIFFERENT root than the gate measured; it says nothing
about whether the gate's own root was current to begin with. This closes
that second, separate gap the same way: three states, never a silent match.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import checklist_skew  # noqa: E402


def test_equal_versions_is_root_current():
    payload = checklist_skew.compare_root_freshness("0.41.1", "0.41.1")
    assert payload["state"] == checklist_skew.ROOT_CURRENT
    assert payload["resolved_version"] == "0.41.1"
    assert payload["newest_cached_version"] == "0.41.1"


def test_a_behind_version_is_root_stale():
    payload = checklist_skew.compare_root_freshness("0.34.0", "0.41.1")
    assert payload["state"] == checklist_skew.ROOT_STALE
    assert "0.34.0" in payload["reason"]
    assert "0.41.1" in payload["reason"]


def test_missing_resolved_version_is_could_not_tell():
    payload = checklist_skew.compare_root_freshness(None, "0.41.1")
    assert payload["state"] == checklist_skew.ROOT_COULD_NOT_TELL
    assert payload["resolved_version"] is None


def test_missing_newest_cached_version_is_could_not_tell():
    payload = checklist_skew.compare_root_freshness("0.34.0", None)
    assert payload["state"] == checklist_skew.ROOT_COULD_NOT_TELL
    assert payload["newest_cached_version"] is None


def test_both_missing_is_could_not_tell_and_names_both():
    payload = checklist_skew.compare_root_freshness(None, None)
    assert payload["state"] == checklist_skew.ROOT_COULD_NOT_TELL
    assert "resolved" in payload["reason"]
    assert "newest cached" in payload["reason"]


def test_root_freshness_receipt_never_renders_could_not_tell_as_current():
    payload = checklist_skew.compare_root_freshness(None, "0.41.1")
    text = checklist_skew.root_freshness_receipt(payload)
    assert "root-current" not in text
    assert "could not tell" in text


def test_cli_compare_root_freshness_reports_stale(capsys):
    rc = checklist_skew.main(
        [
            "--compare-root-freshness",
            "--resolved-version",
            "0.34.0",
            "--newest-cached-version",
            "0.41.1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "checklist-root-freshness: stale" in out
    assert "0.34.0" in out
    assert "0.41.1" in out
