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


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd)] + list(args), check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    (repo / ".oss.json").write_text(json.dumps({
        "repo": "owner/name",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "changelog_dir": "changelog.d",
        "docs_targets": [],
        "version_sites": [],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }))
    (repo / "README.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def test_claim_from_the_clone_records(clone):
    """Positive control: run from the clone -- a real working tree, not a
    linked one -- and the claim must actually record."""
    result = _run(["999", "--claim", "--lane", "README.md"], cwd=clone)
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
