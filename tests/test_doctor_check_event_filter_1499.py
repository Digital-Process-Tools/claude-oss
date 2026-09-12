"""#1499: `doctor.py` reports whether this repo's `gh-prs` radar tier filters the
per-PR channel events that would otherwise land in the scheduler session as a
turn each -- `ops.radar.radar_tiers["gh-prs"].pr_exclude_events` in
`.supertool.json`.

An unfiltered scheduler renders identically to a filtered one until the quota is
gone, which is the defect class this plugin is named after, so the check has four
outcomes and every one is exercised here:

* `OK` -- the list is present and non-empty; the message names the events.
* `WARN unfiltered` -- the tier is registered and the key is absent or empty; the
  message says every per-PR event lands in the scheduler as a turn and names the
  key with its initial value.
* `NOTICE not-configured` -- the file registers no `gh-prs` tier: no per-PR
  pollers, nothing to filter, structurally unable to answer.
* `WARN could-not-read` -- the file is missing or is not valid JSON.

Every "must not fire" case has a "must fire" case beside it.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_event_filter as dcef  # noqa: E402

INITIAL = ["checks_pending", "checks_succeeded", "pr_opened", "conflicts_appeared"]


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _write(tmp_path, doc):
    text = doc if isinstance(doc, str) else json.dumps(doc)
    (tmp_path / ".supertool.json").write_text(text, encoding="utf-8")


def _only():
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    return doctor.FINDINGS[0]


def test_ok_names_the_excluded_events(tmp_path):
    _write(
        tmp_path,
        {"ops": {"radar": {"radar_tiers": {"gh-prs": {"pr_exclude_events": INITIAL}}}}},
    )
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "OK"
    assert "event filter" in message
    for event in INITIAL:
        assert event in message


def test_unfiltered_when_the_key_is_absent(tmp_path):
    _write(tmp_path, {"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}})
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "WARN"
    assert "unfiltered" in message
    assert "scheduler session" in message and "turn" in message
    assert "pr_exclude_events" in message
    assert json.dumps(INITIAL) in message


def test_unfiltered_when_the_key_is_empty(tmp_path):
    _write(
        tmp_path,
        {"ops": {"radar": {"radar_tiers": {"gh-prs": {"pr_exclude_events": []}}}}},
    )
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "WARN"
    assert "unfiltered" in message


def test_unfiltered_when_the_key_is_not_a_list(tmp_path):
    _write(
        tmp_path,
        {"ops": {"radar": {"radar_tiers": {"gh-prs": {"pr_exclude_events": "x"}}}}},
    )
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "WARN"
    assert "unfiltered" in message
    assert "not a list" in message


def test_not_configured_when_no_gh_prs_tier_is_registered(tmp_path):
    _write(tmp_path, {"ops": {"radar": {"radar_tiers": {"gh-issues": {}}}}})
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "NOTICE"
    assert "not-configured" in message
    assert "gh-prs" in message


def test_not_configured_when_there_are_no_tiers_at_all(tmp_path):
    _write(tmp_path, {"presets": ["git"]})
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "NOTICE"
    assert "not-configured" in message


def test_could_not_read_when_the_file_is_missing(tmp_path):
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "WARN"
    assert "could-not-read" in message
    assert ".supertool.json" in message


def test_could_not_read_when_the_file_is_not_json(tmp_path):
    _write(tmp_path, "{not json")
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "WARN"
    assert "could-not-read" in message


def test_could_not_read_when_the_document_is_not_an_object(tmp_path):
    _write(tmp_path, "[]")
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "WARN"
    assert "could-not-read" in message


def test_a_fresh_scaffold_is_filtered_by_default(tmp_path):
    """#1499 decision D6: the blacklist ships as a scaffolded default. A repo
    `scaffold.apply` just wrote must come back `OK` from this check, or every
    fresh install starts life with a WARN nothing but a hand edit clears -- the
    positive control for the hand-written `{}` registration above, which stays
    `unfiltered` because it is the pre-#1499 shape a repo may still carry.
    """
    import scaffold

    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": str(tmp_path),
        "worktree_root": str(tmp_path / "wt"),
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": None,
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    scaffold.apply(tmp_path, config, plugin_root=REPO_ROOT)
    written = json.loads((tmp_path / ".supertool.json").read_text(encoding="utf-8"))
    assert (
        written["ops"]["radar"]["radar_tiers"]["gh-prs"]["pr_exclude_events"] == INITIAL
    )
    dcef.check_event_filter(tmp_path)
    state, message = _only()
    assert state == "OK", message
    # And the remedy `check_radar_publish` prints for a repo with no tier at all
    # carries the same default, so pasting it does not land straight in WARN.
    remedy = doctor.RADAR_REMEDY_CONFIG["ops"]["radar"]["radar_tiers"]["gh-prs"]
    assert remedy["pr_exclude_events"] == INITIAL
    assert (
        scaffold.RADAR_REMEDY_CONFIG["ops"]["radar"]["radar_tiers"]["gh-prs"] == remedy
    )


def test_this_repo_is_filtered():
    """Dogfood: the repo carrying this check sets the key with the initial value."""
    dcef.check_event_filter(REPO_ROOT)
    state, message = _only()
    assert state == "OK", message
    for event in INITIAL:
        assert event in message


def test_doctor_main_runs_the_check(tmp_path, monkeypatch, capsys):
    """The check is registered: doctor's own run prints its line."""
    _write(tmp_path, {"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}})
    monkeypatch.setattr(doctor, "PLUGIN_ROOT", REPO_ROOT)
    doctor.main(["--root", str(tmp_path), "--plugin-root", str(REPO_ROOT)])
    out = capsys.readouterr().out
    assert "event filter" in out
    assert "unfiltered" in out
