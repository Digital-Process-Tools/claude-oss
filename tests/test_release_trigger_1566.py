"""#1566: `merged_prs_condition` measured its range from local `HEAD` in a
clone nobody pulls after a tick's own merges land on the forge.

A tick merges pull requests remotely (squash, via the GitHub API) and
nothing in the tick pulls the scheduler's own long-lived clone afterwards.
Local `HEAD` there sits at whatever commit it was last checked out to while
the branch it tracks keeps moving, and `release_delta.compute` measured a
range from that local `HEAD` alone -- a real, computable count (`0` where
the true count was `8`) that renders identically to a range that is
genuinely short. This pins the fix: `merged_prs_condition` now fetches the
tracked remote first and reports `could-not-evaluate` when `HEAD` is still
behind afterwards, rather than silently trusting a stale checkout.

Every case that shows the fix does not block also measures normally in the
same fixture, one `git fetch` + `git merge --ff-only` away -- the same
"must-not-fire needs a must-fire" shape every fixture in this repository is
held to.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_trigger  # noqa: E402

GIT = "git"

pytestmark = pytest.mark.skipif(
    subprocess.run(
        (GIT, "--version"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode
    != 0,
    reason="git is not on PATH, so a stale clone cannot be built or observed here",
)


def _git(repo, *args, check=True):
    proc = subprocess.run(
        (GIT, "-C", str(repo)) + args,
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


def _init(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "T")
    return repo


def _commit(repo, subject, path="file.txt"):
    target = Path(repo, path)
    target.write_text(subject, encoding="utf-8")
    _git(repo, "add", str(path))
    _git(repo, "commit", "-qm", subject)


@pytest.fixture
def stale_clone(tmp_path):
    """A bare remote, a clone that tracks it, tagged, then a squash merge
    lands on the remote after the clone was made and the clone never fetches
    again -- the scheduler's own steady state (#1566)."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        (GIT, "init", "-q", "--bare", "-b", "main", str(remote)),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    origin = _init(tmp_path / "origin")
    _commit(origin, "initial")
    _git(origin, "remote", "add", "origin", remote.as_uri())
    _git(origin, "push", "-q", "origin", "main")
    _git(origin, "tag", "v0.1.0")
    _git(origin, "push", "-q", "origin", "v0.1.0")

    clone = tmp_path / "clone"
    subprocess.run(
        (GIT, "clone", "-q", remote.as_uri(), str(clone)),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _git(clone, "config", "user.email", "t@example.invalid")
    _git(clone, "config", "user.name", "T")

    # The merge that lands after the clone was made and is never fetched --
    # exactly the shape #1566 reports.
    _commit(origin, "fix(x): squashed (#42)")
    _git(origin, "push", "-q", "origin", "main")
    return clone


def test_a_stale_local_clone_is_could_not_evaluate_not_a_false_short_count(
    stale_clone,
):
    """This is the bug: without the fix, the call below silently reports a
    real, computable NOT_MET count of 0 while the tracked branch already
    carries a squash merge the clone has not fetched."""
    row = release_trigger.merged_prs_condition(stale_clone, 1)
    assert row["state"] == release_trigger.COULD_NOT_EVALUATE, row
    assert "behind" in row["detail"], row


def test_a_clone_that_is_actually_current_measures_normally(stale_clone):
    """Positive control in the same fixture: once the clone is brought
    current, the same call must not block -- proving the case above is about
    genuine staleness and not about anything else in the fixture (a missing
    remote, an unreadable tag, and so on)."""
    _git(stale_clone, "fetch", "-q", "origin")
    _git(stale_clone, "merge", "-q", "--ff-only", "origin/main")
    row = release_trigger.merged_prs_condition(stale_clone, 1)
    assert row["state"] == release_trigger.MET, row
    assert row["count"] == 1


def test_a_repo_with_no_upstream_is_unaffected_by_the_new_check(tmp_path):
    """No remote configured at all -- a detached checkout, a repository that
    never talks to a forge -- is not the case this check exists for, and must
    fall through to the pre-#1566 behaviour rather than block on a comparison
    it has nothing to make."""
    repo = _init(tmp_path / "solo")
    _commit(repo, "initial")
    _git(repo, "tag", "v0.1.0")
    _commit(repo, "fix: one (#1)")
    row = release_trigger.merged_prs_condition(repo, 1)
    assert row["state"] == release_trigger.MET, row
    assert row["count"] == 1


def test_a_failed_fetch_is_could_not_evaluate_not_a_silent_reuse_of_a_stale_ref(
    stale_clone, tmp_path
):
    """A fetch that cannot reach the remote at all must not fall through to
    comparing against whatever remote-tracking ref happens to already be on
    disk -- that ref can be exactly as stale as local HEAD, which would
    silently reproduce #1566 under the one condition (no network) this check
    exists to guard against. Point origin somewhere unreachable so the fetch
    itself fails, while the clone's own `origin/main` remote-tracking ref
    stays at the same stale commit as HEAD (unset by the fixture's own
    unfetched squash merge) -- the exact shape a discarded fetch result
    would silently trust."""
    _git(stale_clone, "remote", "set-url", "origin", str(tmp_path / "no-such-remote"))
    row = release_trigger.merged_prs_condition(stale_clone, 1)
    assert row["state"] == release_trigger.COULD_NOT_EVALUATE, row
    assert "could not fetch" in row["detail"], row


def test_a_multiline_fetch_failure_does_not_forge_an_extra_receipt_line(
    stale_clone, monkeypatch
):
    """git's own stderr for a failed fetch is text the remote end can shape --
    a `remote: <message>` line, potentially several of them. `receipt()`
    joins condition rows with a newline and prints `detail` as one of them,
    so an unflattened newline in this string would splice an extra line into
    the printed receipt, indistinguishable from a genuine additional
    condition (second-pass review finding on #1566). The real `git fetch`
    is not a reliable way to manufacture a specific multi-line stderr, so
    this drives `_stale_local_head` through a monkeypatched `_git` that
    returns one instead."""
    calls = []
    real_git = release_trigger._git
    hostile = "remote: line one" + chr(10) + "remote: line two" + chr(10)

    def fake_git(repo, *args):
        if args[:1] == ("fetch",):
            calls.append(args)
            return False, "", hostile
        return real_git(repo, *args)

    monkeypatch.setattr(release_trigger, "_git", fake_git)
    reason = release_trigger._stale_local_head(stale_clone)
    assert calls, "the fake fetch was never reached"
    assert reason is not None
    assert chr(10) not in reason, reason
