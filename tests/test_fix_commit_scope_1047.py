"""#1047: does the fix for an audit finding cross a threshold worth a second
review pass, or is this a check that never runs and renders identically to
one that ran and found the fix small?

Every "must not fire" case here is paired with a "must fire" case in the
same fixture, per this repo's own convention -- a fixture that never
produces `needs-second-pass` at all would satisfy "small fixes are not
flagged" without ever exercising the flag itself.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import fix_commit_scope  # noqa: E402


# --- check() -----------------------------------------------------------------


def test_one_file_untouched_budget_is_within_scope():
    result = fix_commit_scope.check(["scripts/oss_config.py"])
    assert result["state"] == "within-scope"
    assert result["budgeted_files_touched"] == []


def test_three_files_crosses_the_count_threshold():
    result = fix_commit_scope.check(["a.py", "b.py", "c.py"])
    assert result["state"] == "needs-second-pass"
    assert "3" in result["reason"]


def test_two_files_stays_within_scope_when_neither_is_budgeted():
    result = fix_commit_scope.check(["a.py", "b.py"])
    assert result["state"] == "within-scope"


def test_a_single_budgeted_file_crosses_regardless_of_count():
    result = fix_commit_scope.check(["agents/sub-manager.md"])
    assert result["state"] == "needs-second-pass"
    assert "agents/sub-manager.md" in result["budgeted_files_touched"]


def test_budgeted_paths_is_a_real_union_not_an_empty_set():
    paths = fix_commit_scope.budgeted_paths()
    assert "agents/sub-manager.md" in paths
    assert "commands/tick.md" in paths
    assert "skills/manager/phases/tick-order.md" in paths
    assert "agents/developer/review.md" in paths


# --- files_from_git ------------------------------------------------------------


def _git(repo, *args):
    subprocess.run(["git"] + list(args), cwd=str(repo), check=True, capture_output=True)


def test_files_from_git_reads_a_real_diff(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "one.txt").write_text("a\n")
    _git(repo, "add", "one.txt")
    _git(repo, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()
    (repo / "one.txt").write_text("b\n")
    (repo / "two.txt").write_text("c\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()

    files, error = fix_commit_scope.files_from_git(repo, base, head)
    assert error is None
    assert sorted(files) == ["one.txt", "two.txt"]


def test_files_from_git_reports_could_not_determine_never_an_empty_list(tmp_path):
    """The negative control for the positive case above: a repo that cannot
    answer must say so, not render as a clean, empty diff."""
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    files, error = fix_commit_scope.files_from_git(repo, "bogus-base", "bogus-head")
    assert files is None
    assert error


# --- CLI -----------------------------------------------------------------------


def test_main_prints_needs_second_pass_for_three_files(capsys):
    rc = fix_commit_scope.main(["--file", "a.py", "--file", "b.py", "--file", "c.py"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "VERDICT: needs-second-pass" in out


def test_main_could_not_determine_when_neither_input_given(capsys):
    rc = fix_commit_scope.main([])
    out = capsys.readouterr().out
    assert rc != 0
    assert "VERDICT: could-not-determine" in out


# --- #1251: a locale codec that cannot decode git's output must not raise ----


def test_files_from_git_survives_a_locale_that_cannot_decode_the_output(
    tmp_path, monkeypatch
):
    """Under the old bare `text=True` (no explicit `encoding=`/`errors=`),
    stdout is decoded with `locale.getpreferredencoding(False)` under
    `errors="strict"`. A path git prints that codec cannot represent raises
    `UnicodeDecodeError` -- a `ValueError`, uncaught by this function's own
    `except (OSError, subprocess.TimeoutExpired)` clause -- escaping this
    module's documented `(files, error)` contract entirely.

    This is the positive control: force the ambient locale codec down to
    plain ASCII (never touching `subprocess.run`'s own explicit
    `encoding=`/`errors=` kwargs) and prove a non-ASCII filename still comes
    back as a reported result rather than a raised exception.

    `locale.getencoding` (PEP 597) does not exist before Python 3.11 -- this
    repo's declared floor is 3.9 (CLAUDE.md) and CI runs the matrix down to
    it, so `raising=False` is required here or `monkeypatch.setattr` raises
    its own `AttributeError` on 3.9/3.10 before the test body even runs
    (observed on CI, `pytest (ubuntu-latest, 3.9)`). On those interpreters
    `subprocess`'s own text-mode default-encoding resolution never calls
    `locale.getencoding` either -- it only exists there via `raising=False`
    for symmetry with 3.11+, and the `locale.getpreferredencoding` patch
    below is what actually forces the ASCII codec pre-3.11.
    """
    monkeypatch.setattr("locale.getencoding", lambda: "ascii", raising=False)
    monkeypatch.setattr(
        "locale.getpreferredencoding", lambda do_setlocale=True: "ascii"
    )

    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    # Without this, git quotes any non-ASCII byte in a pathname as a
    # backslash-octal escape (`"caf\\303\\251.txt"`), which is pure ASCII on
    # the wire and never exercises the decode this test targets.
    _git(repo, "config", "core.quotepath", "false")
    (repo / "one.txt").write_text("a\n")
    _git(repo, "add", "one.txt")
    _git(repo, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()
    (repo / "café.txt").write_text("b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()

    files, error = fix_commit_scope.files_from_git(repo, base, head)
    assert error is None
    assert any("caf" in f for f in files)


# --- #1254: an unbounded revision argument needs a `--` separator -----------


def test_files_from_git_does_not_let_a_leading_dash_base_be_read_as_an_option(
    tmp_path,
):
    """The negative control for the positive git-diff read above: a
    `base`/`head` beginning with `-` must be rejected by git as a bad
    revision (via `--end-of-options`), never accepted and reinterpreted as
    an option such as `--output=<path>`.

    Self-review finding (both spawned reviewers independently caught this):
    the naive assertion here would be `assert not (tmp_path /
    "pwned.txt").exists()`, but that is not a discriminating check -- the
    vulnerable code joins `base` and `head` into one `"{base}..{head}"`
    argv token, so an unguarded `--output=<target>` actually receives
    `<target>..HEAD` as its value and writes to a file named
    `pwned.txt..HEAD`, never to bare `pwned.txt`. That file's absence is
    `True` under both the vulnerable and the fixed code, so asserting it
    alone would pass either way. Assert against the actual filename the
    injection produces instead, so this control can fail on the code this
    diff replaces and pass on the code it introduces."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "one.txt").write_text("a\n")
    _git(repo, "add", "one.txt")
    _git(repo, "commit", "-q", "-m", "base")

    target = tmp_path / "pwned.txt"
    injected_write_target = Path(str(target) + "..HEAD")
    files, error = fix_commit_scope.files_from_git(
        repo, "--output={0}".format(target), "HEAD"
    )
    assert not injected_write_target.exists()
    assert not target.exists()
    assert files is None
    assert error
