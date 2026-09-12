"""The default-branch poller's live `only=` filter, read from its own state file -- #1508.

`pr_exclude_events` (#1499) filters the per-PR pollers; the `gh-branch` poller
has no config knob at all. supertool's radar forks it subscribed to every key,
and a poller keeps the filter it was forked with, so the only route today is to
arm it by hand with `watch:gh-branch:<ref>:only=went_green,went_failed` before
radar's heal runs. This check reads what the poller actually recorded (`only`
in `supertool-watch-gh-branch__<ref>.state.json`), never the config, because
the config has nothing to say.

Five outcomes, one test each, must-fire beside must-not-fire.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_event_filter as dcef  # noqa: E402

NAME = "example-channel"


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A repo declaring one watch name, and a state base the check resolves the
    poller slot directory under, so nothing here touches the real /tmp."""
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"ops": {"radar": {"watch_name": NAME}}}), encoding="utf-8"
    )
    base = tmp_path / "slots"
    base.mkdir()
    monkeypatch.setenv(dcef.STATE_BASE_ENV, str(base))
    monkeypatch.delenv(dcef.STATE_DIR_ENV, raising=False)
    slots = base / "supertool-watch-{}".format(NAME)
    slots.mkdir()
    return tmp_path, slots


def _state(slots, ref, only):
    path = slots / "supertool-watch-gh-branch__{}.state.json".format(ref)
    path.write_text(json.dumps({"only": only, "last_emit": {}}), encoding="utf-8")


def _only():
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    return doctor.FINDINGS[0]


def test_ok_when_the_live_filter_is_exactly_the_two_kept_keys(rig):
    root, slots = rig
    _state(slots, "main", ["went_failed", "went_green"])
    dcef.check_branch_filter(root)
    state, message = _only()
    assert state == "OK"
    assert "branch filter" in message and "main" in message


def test_unfiltered_when_only_is_empty(rig):
    root, slots = rig
    _state(slots, "main", [])
    dcef.check_branch_filter(root)
    state, message = _only()
    assert state == "WARN"
    assert "unfiltered" in message
    assert "only=went_green,went_failed" in message


def test_unfiltered_when_a_noisy_key_is_subscribed(rig):
    root, slots = rig
    _state(slots, "main", ["went_green", "went_failed", "went_not_green"])
    dcef.check_branch_filter(root)
    state, message = _only()
    assert state == "WARN"
    assert "went_not_green" in message


def test_unfiltered_when_a_kept_key_is_missing(rig):
    """`only=went_green` alone makes a red default branch arrive as silence."""
    root, slots = rig
    _state(slots, "main", ["went_green"])
    dcef.check_branch_filter(root)
    state, message = _only()
    assert state == "WARN"
    assert "went_failed" in message


def test_not_armed_is_a_notice_not_a_warn(rig):
    root, _slots = rig
    dcef.check_branch_filter(root)
    state, message = _only()
    assert state == "NOTICE"
    assert "not-armed" in message


def test_could_not_read_on_a_broken_state_file(rig):
    root, slots = rig
    (slots / "supertool-watch-gh-branch__main.state.json").write_text(
        "{", encoding="utf-8"
    )
    dcef.check_branch_filter(root)
    state, message = _only()
    assert state == "WARN"
    assert "could-not-read" in message
    assert "unfiltered" not in message.split("--")[0]


def test_could_not_read_when_no_watch_name_resolves(tmp_path, monkeypatch):
    (tmp_path / ".supertool.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(dcef.STATE_BASE_ENV, str(tmp_path))
    monkeypatch.delenv(dcef.STATE_DIR_ENV, raising=False)
    monkeypatch.delenv(doctor.WATCH_NAME_ENV, raising=False)
    dcef.check_branch_filter(tmp_path)
    state, message = _only()
    assert state == "WARN"
    assert "could-not-read" in message


def test_state_dir_override_wins(tmp_path, monkeypatch):
    """`SUPERTOOL_WATCH_STATE_DIR` names the slot directory outright."""
    (tmp_path / ".supertool.json").write_text("{}", encoding="utf-8")
    slots = tmp_path / "anywhere"
    slots.mkdir()
    monkeypatch.setenv(dcef.STATE_DIR_ENV, str(slots))
    _state(slots, "trunk", ["went_green", "went_failed"])
    dcef.check_branch_filter(tmp_path)
    state, message = _only()
    assert state == "OK"
    assert "trunk" in message
