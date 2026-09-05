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

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "agent_role.py"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import agent_role  # noqa: E402
import spawn_guard  # noqa: E402


def _init_repo(tmp_path):
    """Routed through `spawn_guard.run` rather than bare `subprocess.run` so that a
    runner too slow to answer skips this test carrying what went unmeasured, rather
    than erroring on a setup step (#716). Setup is deliberately not exempt: a `git
    commit` that never returned leaves this file's subject exactly as unmeasured as
    one that returned the wrong thing.
    """
    subject = (
        "the role marker, in a git repository this fixture never finished creating"
    )
    spawn_guard.run(
        ["git", "init", "-q", str(tmp_path)], subject=subject, check=True, timeout=30
    )
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"],
        subject=subject,
        check=True,
        timeout=30,
    )
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "t"],
        subject=subject,
        check=True,
        timeout=30,
    )
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "add", "-A"],
        subject=subject,
        check=True,
        timeout=30,
    )
    spawn_guard.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
        subject=subject,
        check=True,
        timeout=30,
    )


def test_marker_survives_across_two_wholly_separate_processes(tmp_path):
    _init_repo(tmp_path)

    write = spawn_guard.run(
        [
            sys.executable,
            str(SCRIPT),
            "--write",
            "sub-manager",
            "--root",
            str(tmp_path),
        ],
        subject="whether --write records a role a second process can read back",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert write.returncode == 0, write.stdout + write.stderr

    # A second, independent process -- no environment carried over, no
    # in-memory state shared. This is what a later Bash tool call actually
    # looks like from the target script's point of view.
    read_back = spawn_guard.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, {0!r}); import agent_role; "
                "print(agent_role.current_role(root={1!r}))"
            ).format(str(REPO / "scripts"), str(tmp_path)),
        ],
        subject="what a wholly separate process reads back as the current role",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert read_back.stdout.strip() == "sub-manager", (
        read_back.stdout + read_back.stderr
    )


def test_marker_works_inside_a_worktree_where_git_is_a_file(tmp_path):
    """`.git` is a file, not a directory, inside a worktree -- `git rev-parse
    --git-dir` resolves it correctly either way, which is why the marker
    goes through that rather than assuming `<root>/.git` is a directory."""
    main = tmp_path / "main"
    _init_repo(main)
    wt = tmp_path / "wt"
    spawn_guard.run(
        ["git", "-C", str(main), "worktree", "add", "-q", "-b", "wt-branch", str(wt)],
        subject="the role marker inside a worktree this fixture never finished creating",
        check=True,
        timeout=30,
    )
    assert (wt / ".git").is_file(), "fixture assumption: .git is a file in a worktree"

    write = spawn_guard.run(
        [sys.executable, str(SCRIPT), "--write", "sub-manager", "--root", str(wt)],
        subject="whether --write records a role inside a worktree, where .git is a file",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert write.returncode == 0, write.stdout + write.stderr

    read_back = spawn_guard.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, {0!r}); import agent_role; "
                "print(agent_role.current_role(root={1!r}))"
            ).format(str(REPO / "scripts"), str(wt)),
        ],
        subject="what a separate process reads back as the role inside a worktree",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert read_back.stdout.strip() == "sub-manager", (
        read_back.stdout + read_back.stderr
    )


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


def test_role_forbids_release_reads_the_marker_when_no_env_is_set(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    _init_repo(tmp_path)
    agent_role.write_role_marker("sub-manager", root=str(tmp_path))
    assert agent_role.role_forbids_release(root=str(tmp_path)) is True
