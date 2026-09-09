"""#1386: is a post-release triage sweep due?

`scripts/oss_state.py` (#855) already writes and reads the triage record in
three states; nothing consumed it. `triage_trigger.compute` is that consumer,
mirroring `release_trigger.py` (#966): a real git repository, a real tag, and
a real state file, never a mock of any of those -- the claim under test is
what git and the state file actually say, not what a fake is told to say.

Every "must fire" case is paired with a "must not fire" case in the same
fixture family, per this repository's own rule that a negative assertion
needs a positive control: a trigger that never fires would pass every
not-due assertion below for the wrong reason.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402
import triage_trigger  # noqa: E402


def _git(repo, *args, check=True):
    proc = subprocess.run(
        ("git", "-C", str(repo)) + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            "git {0} failed: {1}".format(
                " ".join(args), proc.stdout.decode("utf-8", "replace")
            )
        )
    return proc.stdout.decode("utf-8", "replace")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("start\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "initial")
    _git(root, "tag", "v1.0.0")
    return root


def _config(enabled=True):
    return {"release": {"triggers": {"triage_after_release": enabled}}}


def _state_path(tmp_path):
    return tmp_path / "state" / "watch.json"


def test_never_recorded_is_due(repo, tmp_path):
    """Positive control: a tag exists and no triage sweep was ever recorded."""
    state_path = _state_path(tmp_path)
    payload = triage_trigger.compute(repo, config=_config(), state_path=str(state_path))
    assert payload["state"] == triage_trigger.STATE_DUE


def test_recorded_after_the_tag_is_not_due(repo, tmp_path):
    """Negative control, same fixture: record a sweep after the tag lands."""
    state_path = _state_path(tmp_path)
    oss_state.append(
        str(state_path),
        "2030-01-01T00:00:00+00:00",
        "test: triage sweep",
        detail={"triage": oss_state.triage_recorded("2030-01-01T00:00:00+00:00")},
    )
    payload = triage_trigger.compute(repo, config=_config(), state_path=str(state_path))
    assert payload["state"] == triage_trigger.STATE_NOT_DUE


def test_recorded_before_the_tag_is_due(repo, tmp_path):
    """A release landed after the last recorded sweep -- due again."""
    state_path = _state_path(tmp_path)
    oss_state.append(
        str(state_path),
        "2000-01-01T00:00:00+00:00",
        "test: triage sweep",
        detail={"triage": oss_state.triage_recorded("2000-01-01T00:00:00+00:00")},
    )
    payload = triage_trigger.compute(repo, config=_config(), state_path=str(state_path))
    assert payload["state"] == triage_trigger.STATE_DUE


def test_not_enabled_is_not_due(repo, tmp_path):
    """Absent/false config declares the repository does not want this route."""
    state_path = _state_path(tmp_path)
    payload = triage_trigger.compute(
        repo, config=_config(enabled=False), state_path=str(state_path)
    )
    assert payload["state"] == triage_trigger.STATE_NOT_DUE

    payload_absent = triage_trigger.compute(repo, config={}, state_path=str(state_path))
    assert payload_absent["state"] == triage_trigger.STATE_NOT_DUE


def test_first_release_is_not_due(tmp_path):
    """No tag at all -- nothing has been released for a sweep to follow."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("start\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "initial")
    state_path = _state_path(tmp_path)
    payload = triage_trigger.compute(root, config=_config(), state_path=str(state_path))
    assert payload["state"] == triage_trigger.STATE_NOT_DUE


def test_unreadable_state_file_is_could_not_tell(repo, tmp_path):
    """A state file that cannot be read is not evidence the board was swept."""
    state_path = tmp_path / "state" / "watch.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("not json", encoding="utf-8")
    payload = triage_trigger.compute(repo, config=_config(), state_path=str(state_path))
    assert payload["state"] == triage_trigger.STATE_COULD_NOT_TELL


def test_no_previous_tag_no_history_is_could_not_run(tmp_path):
    """A path that is not a git repository at all -- release_delta itself blocks."""
    root = tmp_path / "not-a-repo"
    root.mkdir()
    state_path = _state_path(tmp_path)
    payload = triage_trigger.compute(root, config=_config(), state_path=str(state_path))
    assert payload["state"] == triage_trigger.STATE_COULD_NOT_TELL


def test_receipt_prints_the_verdict(repo, tmp_path):
    state_path = _state_path(tmp_path)
    payload = triage_trigger.compute(repo, config=_config(), state_path=str(state_path))
    text = triage_trigger.receipt(payload)
    assert "triage-trigger: due" in text
    assert "DUE" in text
