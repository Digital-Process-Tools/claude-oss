"""`clone HEAD` is the one WARN in `/oss:doctor`'s report that names a problem
and no way out of it.

Both off-branch arms state a fact -- `on <branch> (not main), remote ref exists`
-- and stop. Every other WARN in the same run carries something the reading
agent can execute: an `ln -sf`, a `claude mcp remove`, a `--refresh` call, a
`/oss:scaffold`. This repository's own doctor rule says the remedy has to be
runnable, not only clickable, and a bare statement of the branch name is not
even clickable.

The two arms need different remedies and that is why they are separate arms:

* `remote == "gone"` -- the branch's pull request very likely merged, so
  returning is unambiguously right and the local branch is deletable too.
* otherwise -- the branch may still be carrying unmerged work, so the remedy
  says how to return WITHOUT implying the work should be abandoned. Doctor
  performs no writes and never decides this; it names the command.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_clone_head as clone_head  # noqa: E402

CONFIG = {"default_branch": "main"}


def setup_function(_):
    doctor.FINDINGS.clear()


def _report(state, detail, monkeypatch):
    monkeypatch.setattr(
        clone_head, "clone_head_state", lambda *_a, **_k: (state, detail)
    )
    clone_head.check_clone_head("/repo", CONFIG)
    return doctor.FINDINGS[-1]


def test_a_merged_branch_is_told_how_to_go_back(monkeypatch):
    level, message = _report(
        "on-other", {"branch": "fix/1234", "remote": "gone"}, monkeypatch
    )
    assert level == "WARN"
    assert "git checkout main" in message
    assert "git pull" in message


def test_a_branch_whose_remote_still_exists_is_told_too(monkeypatch):
    """The arm that was silent. `remote ref exists` was the whole message."""
    level, message = _report(
        "on-other", {"branch": "fix/1234", "remote": "exists"}, monkeypatch
    )
    assert level == "WARN"
    assert "git checkout main" in message


def test_the_still_open_arm_does_not_tell_anyone_to_discard_work(monkeypatch):
    """The reason the two arms stay separate. A branch whose remote ref is
    still there may carry unmerged work, and a remedy that reads as `abandon
    this` is worse than no remedy -- doctor performs no writes and this
    decision is not its to make."""
    _, message = _report(
        "on-other", {"branch": "fix/1234", "remote": "exists"}, monkeypatch
    )
    assert "-D" not in message
    assert "--force" not in message
    assert "reset" not in message
    # ... and it says why returning may not be what you want yet.
    assert "unmerged" in message or "still open" in message


def test_a_clone_already_on_the_default_branch_is_offered_nothing(monkeypatch):
    """Positive control. Without it, a check that appended the remedy to every
    line would satisfy all three assertions above."""
    level, message = _report(
        "on-default", {"ahead": 0, "behind": 0, "branch": "main"}, monkeypatch
    )
    assert level == "OK"
    assert "git checkout" not in message
