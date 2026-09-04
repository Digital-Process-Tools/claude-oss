"""#971 -- `root: "."` at snapshot and compare time is resolved against
whatever the caller's live cwd happens to be at each call, and the Bash tool
that drives `agents/developer/review.md`'s snapshot/compare pair resets its
cwd between tool calls. A `snapshot` taken inside the branch worktree,
followed by a `compare` whose cwd has since reset to the main clone -- a
second, unrelated but perfectly valid git repository -- silently compares
the wrong tree: its HEAD differs from the worktree's own HEAD, so `compare`
reports `mutated` about a worktree that was never touched.

Found by a developer lane doing self-review on a different issue
(claude-supertool #2227): re-running the identical `compare` from inside the
correct worktree, against the same before-snapshot JSON, returned `clean`.

The fix: `snapshot()` records the *absolute, resolved* root it actually
looked at, and `compare`'s CLI defaults to re-snapshotting *that* recorded
root -- not the live cwd -- whenever the caller does not pass an explicit
`--root`. Passing `--root` explicitly still overrides it, unchanged from
before this fix; the class this closes is specifically the *silent* default
to a cwd that has moved.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tree_snapshot.py"

sys.path.insert(0, str(REPO / "scripts"))

import tree_snapshot  # noqa: E402


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _real_git_repo(tmp_path, name="repo"):
    """A real, committed git repo, distinct from any sibling created by the
    same test.

    The commit's *content* -- not just its path -- embeds `name`, so two
    calls in the same test produce commits with genuinely different trees
    and therefore different HEAD hashes. Content-addressed commit hashes
    are not otherwise guaranteed to differ: git includes the author/
    committer timestamp at one-second granularity, so two repos created
    with identical tree content, identical identity and an identical
    commit message within the same wall-clock second hash to the *same*
    SHA -- confirmed while writing this fixture, and it is exactly the
    condition under which `test_compare_after_a_cwd_reset_does_not_
    falsely_report_mutated` would pass by accident: HEAD unchanged and an
    empty status diff both trivially true regardless of which of the two
    repos `compare` actually looked at. Embedding `name` removes the
    collision rather than merely making it unlikely."""
    repo = tmp_path / name
    repo.mkdir()
    env = _git_env()
    done = subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        env=env,
    )
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip() or done.returncode))
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], env=env, check=True)
    (repo / "tracked.txt").write_text("original content in {0}\n".format(name))
    subprocess.run(["git", "-C", str(repo), "add", "."], env=env, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "initial commit for {0}".format(name)],
        env=env, check=True,
    )
    return repo


def _run_cli(args, cwd=None, stdin=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        cwd=cwd, input=stdin,
    )


# --- the exact false-mutated scenario ---------------------------------------


def test_compare_after_a_cwd_reset_does_not_falsely_report_mutated(tmp_path):
    """Negative assertion: nothing changed in the worktree the snapshot was
    taken in -- only the calling process's cwd moved to a second, unrelated
    git repository before `compare` ran, exactly as the Bash tool's cwd
    resets between calls. `compare` must still report `clean`."""
    worktree = _real_git_repo(tmp_path, "worktree")
    other_clone = _real_git_repo(tmp_path, "other_clone")

    before = _run_cli(["snapshot"], cwd=str(worktree)).stdout

    # Nothing touches `worktree` at all. Only the cwd for the `compare` call
    # differs -- the reset the Bash tool performs between calls.
    done = _run_cli(["compare", "--before", "-"], cwd=str(other_clone), stdin=before)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "VERDICT: clean" in done.stdout, done.stdout + done.stderr


def test_compare_after_a_cwd_reset_still_reports_a_real_mutation(tmp_path):
    """Positive control for the assertion above: something *did* change in
    the snapshotted worktree before `compare` ran. A cwd reset to a second
    repo must not swallow a genuine mutation either."""
    worktree = _real_git_repo(tmp_path, "worktree")
    other_clone = _real_git_repo(tmp_path, "other_clone")

    before = _run_cli(["snapshot"], cwd=str(worktree)).stdout

    (worktree / "tracked.txt").write_text("reverted\n")

    done = _run_cli(["compare", "--before", "-"], cwd=str(other_clone), stdin=before)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "VERDICT: mutated" in done.stdout, done.stdout + done.stderr


def test_snapshot_records_an_absolute_root_not_the_literal_dot(tmp_path):
    """`snapshot()`'s own `root` field must be independently resolvable --
    not the literal `"."` it was called with -- or nothing downstream can
    reuse it once the cwd that made `.` meaningful is gone. Exercised
    through the CLI's own default (`--root` omitted, so argparse hands
    `snapshot()` the literal `"."`), which is the shape every real caller
    uses."""
    repo = _real_git_repo(tmp_path)
    done = _run_cli(["snapshot"], cwd=str(repo))
    payload = json.loads(done.stdout)
    assert payload["root"] == str(repo.resolve()), payload


def test_explicit_root_at_compare_time_still_overrides_the_recorded_one(tmp_path):
    """An explicit `--root` is not silently discarded in favour of the
    recorded root -- it is the caller overriding on purpose, unchanged from
    before this fix."""
    worktree = _real_git_repo(tmp_path, "worktree")
    elsewhere = _real_git_repo(tmp_path, "elsewhere")

    before = _run_cli(["snapshot"], cwd=str(worktree)).stdout

    # Mutate `elsewhere`, not `worktree`. An explicit --root pointing at
    # `elsewhere` should compare against `elsewhere`, not the recorded root.
    (elsewhere / "tracked.txt").write_text("reverted\n")

    done = _run_cli(
        ["compare", "--before", "-", "--root", str(elsewhere)],
        cwd=str(worktree), stdin=before,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert "VERDICT: mutated" in done.stdout


# --- a resolution failure must not be trusted as though it succeeded -------
# (self-review findings, both against `_resolved_root` and its consumer in
# `main()`)


def test_resolved_root_reports_failure_rather_than_a_trusted_fallback():
    """An embedded NUL byte is legal inside a JSON string, so it is a real
    input `_resolved_root` can be handed -- `compare --before -` reads
    arbitrary JSON off stdin. `Path.resolve()` raises `ValueError` on a NUL
    byte (confirmed directly: it is not an `OSError`), so the exception
    tuple this module already caught before this test was written did not
    cover it -- an uncaught `ValueError` would crash the CLI with Python's
    default handler, exiting 1, the same integer as `EXIT_CODES["mutated"]`.
    `_resolved_root` must catch it and say `resolved=False`, never raise."""
    root_string, resolved = tree_snapshot._resolved_root("bad\x00path")
    assert resolved is False
    assert root_string == "bad\x00path"


def test_compare_does_not_trust_an_unresolved_recorded_root(tmp_path):
    """A before-snapshot whose `root` failed to resolve (`root_resolved:
    False`) must not be reused as `compare`'s default root -- that is
    exactly the pre-#971 failure one level removed: an unresolved,
    cwd-dependent string treated as though it were the cwd-independent path
    the whole point of recording `root` was to provide. `compare` must fall
    back to its own live cwd instead, the same fallback a before-snapshot
    with no `root` at all already gets."""
    repo = _real_git_repo(tmp_path)
    before = json.dumps(
        {
            "root": "/this/path/does/not/exist/and/must/not/be/trusted",
            "root_resolved": False,
            "head": tree_snapshot.snapshot(str(repo))["head"],
            "status": "",
            "error": None,
        }
    )
    done = _run_cli(["compare", "--before", "-"], cwd=str(repo), stdin=before)
    # Falls back to the live cwd (`repo`, which is clean and matches the
    # recorded HEAD) rather than trying -- and failing -- to snapshot the
    # untrusted path.
    assert done.returncode == 0, done.stdout + done.stderr
    assert "VERDICT: clean" in done.stdout, done.stdout + done.stderr
