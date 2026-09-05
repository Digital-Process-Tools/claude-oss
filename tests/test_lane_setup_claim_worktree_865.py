"""#865: `lane_setup.py --claim` silently cannot record a claim when a
developer lane runs it as its own first call from inside its own worktree.
`.oss.local.json` is git-excluded, so it is absent from every worktree this
loop cuts, by construction -- and `worktree_root` (#608) is then *derived*
from THIS worktree's own path rather than the clone's, which points the
lane registry `--claim` writes into at a sibling of that one worktree,
invisible to every other lane. Reproduced directly (not inferred from the
docstring): a `--claim` call standing in a real linked worktree writes into
`<worktree>-wt/.oss-lanes`, never the shared registry any other lane reads.

This drives `--claim` from a real second worktree, the way the issue itself
asks for ("A test driving --claim from a real second worktree ... would
confirm which of the two is chosen"), and pairs it with the ordinary
successful case in the same fixture -- a fix that fails every claim would
also "solve" this.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"


def _fake_gh_bin(tmp_path):
    """#1069: `--claim` now also writes the GitHub assignee
    (`lane_setup_claim.claim_and_register`), so a subprocess test of the
    worktree-safety refusal alone must not depend on a real, authenticated
    `gh` -- a fake `gh` on PATH, answering only the two calls
    `select_issues_claim_read.py` makes, keeps the assignee half a fixed
    `claimed` so the worktree check is the only thing varying under test.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    gh_path = bin_dir / "gh"
    gh_path.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"api\" ]; then echo tester; exit 0; fi\n"
        "if [ \"$1\" = \"issue\" ] && [ \"$2\" = \"view\" ]; then "
        "echo '{\"assignees\": []}'; exit 0; fi\n"
        "if [ \"$1\" = \"issue\" ] && [ \"$2\" = \"edit\" ]; then exit 0; fi\n"
        "exit 1\n"
    )
    gh_path.chmod(0o755)
    return bin_dir


def _run(args, cwd, extra_path=None):
    env = dict(os.environ)
    if extra_path is not None:
        env["PATH"] = str(extra_path) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        env=env,
    )


def _git(cwd, *args):
    subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def clone(tmp_path):
    """A minimal git repo with an `.oss.json` and a real `origin` remote,
    standing in for the maintainer's own clone -- not a worktree this loop
    cut."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))

    repo = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "owner/name",
                "default_branch": "main",
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "changelog_dir": "changelog.d",
                "docs_targets": [],
                "version_sites": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": ".max/oss-watch.json",
            }
        )
    )
    (repo / "README.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def test_claim_from_the_clone_records(clone, tmp_path):
    """Positive control: run from the clone -- a real working tree, not a
    linked one -- and the claim must actually record."""
    fake_bin = _fake_gh_bin(tmp_path)
    result = _run(["999", "--claim", "--lane", "README.md"], cwd=clone, extra_path=fake_bin)
    assert result.returncode == 0, result.stdout
    assert "not recorded" not in result.stdout, result.stdout


def test_claim_from_inside_a_real_worktree_fails_loudly(clone, tmp_path):
    """The bug: `--claim` run as the dispatched lane's own first call, from
    inside the worktree it was just cut into. That must now exit non-zero
    rather than rendering identically to a successful claim -- and must not
    silently write into the wrong, sibling-of-the-worktree registry either."""
    worktree = tmp_path / "wt-865"
    _git(clone, "worktree", "add", "-q", "-b", "fix/865", str(worktree), "main")
    result = _run(["865", "--claim", "--lane", "README.md"], cwd=worktree)
    assert result.returncode != 0, result.stdout
    # The phantom registry this bug used to write into, sibling of the
    # worktree itself -- must not exist after the refusal.
    phantom = Path(str(worktree) + "-wt") / ".oss-lanes"
    assert not phantom.exists(), "wrote into the phantom registry {}".format(phantom)


import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(REPO_ROOT / "scripts"))
import lane_setup  # noqa: E402


def test_could_not_tell_refuses_the_claim_too(clone, monkeypatch):
    """#865 review round: `linked_worktree_state`'s own docstring says its
    `could-not-tell` state must never render as `main` -- but the call site
    only ever compared against `WORKTREE_LINKED`, so a `could-not-tell`
    reading (git itself failed to answer one of the two rev-parse calls)
    silently fell through to `effective_claim = True`, indistinguishable
    from a claim genuinely verified safe. Refusing on `LINKED` alone is not
    enough; `could-not-tell` must refuse too, for the identical reason this
    repository states everywhere else: an absence produced by the tool must
    never read as an absence in the world."""
    monkeypatch.setattr(
        lane_setup.lane_setup_worktree,
        "linked_worktree_state",
        lambda repo: (lane_setup.WORKTREE_COULD_NOT_TELL, "git would not answer"),
    )
    payload = lane_setup.compute(
        str(clone), 999, claim=True, lane_patterns=["README.md"]
    )
    assert lane_setup.blocked(payload), payload
    assert payload["lanes"]["record"]["state"] != "recorded", payload


def test_the_claim_refusal_receipt_does_not_blame_705(clone, tmp_path):
    """Review round: the generic 'not-claimed' line -- built for a call that
    genuinely never passed --claim (#705's own probing convention) -- was
    printed unedited beside the #865 refusal, telling the reader the call
    'did not pass --claim' when it plainly did. The receipt must not carry
    that contradiction."""
    worktree = tmp_path / "wt-865b"
    _git(clone, "worktree", "add", "-q", "-b", "fix/865b", str(worktree), "main")
    result = _run(["865", "--claim", "--lane", "README.md"], cwd=worktree)
    assert "did not pass --claim" not in result.stdout, result.stdout
    assert "CLAIM REFUSED" in result.stdout, result.stdout
