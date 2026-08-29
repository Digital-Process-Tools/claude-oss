"""The role marker survives across separate processes -- an environment
variable does not (#695, auditor finding).

`OSS_AGENT_ROLE=... export`, set in one `Bash` tool call, does not reach a
later `Bash` tool call in this harness -- measured directly: `export
OSS_AGENT_ROLE=sub-manager` in one call, then a bare `echo "[$OSS_AGENT_ROLE]"`
in the next, printed `[]`. An agent's first "declare your role" call and its
later call into `release_publish.py` are two different `Bash` invocations,
so a mechanism that only reads the environment provides no defense at all
by the time it matters -- silently, which is this repository's own defect
class landing inside the one gate #695 was filed to make code-level.

So the role is also written to a marker file under the repository's own git
directory (`git rev-parse --git-dir`, which resolves correctly inside a
worktree, where `.git` is a file rather than a directory) -- a location
that is local to the repository rather than to one shell process, and is
therefore readable from a wholly separate `python3` invocation, which is
what this test actually exercises: writing happens in one `subprocess.run`,
reading in a second, completely independent one.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "agent_role.py"

sys.path.insert(0, str(REPO / "scripts"))

import agent_role  # noqa: E402


def _init_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"],
        check=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True, timeout=30
    )
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, timeout=30)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True, timeout=30
    )


def test_marker_survives_across_two_wholly_separate_processes(tmp_path):
    _init_repo(tmp_path)

    write = subprocess.run(
        [sys.executable, str(SCRIPT), "--write", "sub-manager", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert write.returncode == 0, write.stdout + write.stderr

    # A second, independent process -- no environment carried over, no
    # in-memory state shared. This is what a later Bash tool call actually
    # looks like from the target script's point of view.
    read_back = subprocess.run(
        [sys.executable, "-c", (
            "import sys; sys.path.insert(0, {0!r}); import agent_role; "
            "print(agent_role.current_role(root={1!r}))"
        ).format(str(REPO / "scripts"), str(tmp_path))],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert read_back.stdout.strip() == "sub-manager", read_back.stdout + read_back.stderr


def test_marker_works_inside_a_worktree_where_git_is_a_file(tmp_path):
    """`.git` is a file, not a directory, inside a worktree -- `git rev-parse
    --git-dir` resolves it correctly either way, which is why the marker
    goes through that rather than assuming `<root>/.git` is a directory."""
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", "-b", "wt-branch", str(wt)],
        check=True,
        timeout=30,
    )
    assert (wt / ".git").is_file(), "fixture assumption: .git is a file in a worktree"

    write = subprocess.run(
        [sys.executable, str(SCRIPT), "--write", "sub-manager", "--root", str(wt)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert write.returncode == 0, write.stdout + write.stderr

    read_back = subprocess.run(
        [sys.executable, "-c", (
            "import sys; sys.path.insert(0, {0!r}); import agent_role; "
            "print(agent_role.current_role(root={1!r}))"
        ).format(str(REPO / "scripts"), str(wt))],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert read_back.stdout.strip() == "sub-manager", read_back.stdout + read_back.stderr


def test_no_marker_and_no_env_is_none(tmp_path):
    _init_repo(tmp_path)
    assert agent_role.current_role(root=str(tmp_path)) is None


def test_environment_still_wins_when_both_are_present(monkeypatch, tmp_path):
    """The environment variable is kept as a fast path for a caller that
    genuinely can set it right before the call it guards (an inline prefix
    on the same command line) -- it must not be removed outright, only
    stopped being the *only* mechanism."""
    _init_repo(tmp_path)
    agent_role.write_role_marker("maintainer", root=str(tmp_path))
    monkeypatch.setenv(agent_role.ROLE_ENV, "sub-manager")
    assert agent_role.current_role(root=str(tmp_path)) == "sub-manager"


def test_role_forbids_release_reads_the_marker_when_no_env_is_set(monkeypatch, tmp_path):
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    assert agent_role.role_forbids_release(root=str(tmp_path)) is True
