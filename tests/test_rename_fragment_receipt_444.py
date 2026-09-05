"""#444: two findings from the release-auditor at gate 3 of v0.10.0, round 2, both
in `scripts/rename_changelog_fragment.py`, both carried past the cap.

Finding 1: the `git add` result at :183-185 is discarded and the receipt is
byte-identical whether it succeeds or fails. The comment three lines above it says
this `git add` is what stops `git commit --amend` from committing the pre-rewrite
body under the new filename -- "the exact defect this tool exists to close, one
layer later." A failed add therefore reproduces #426's own defect while the tool
reports OK. Judgment call the issue frames rather than decides: staging IS this
tool's job (the comment at :180-182 says so), so the fix is to give the failure a
state rather than to remove the `git add`.

Same class, second site, found by sweeping rather than by reading the reported
line: `new_path.write_text(...)` at :177 runs after `git mv` and was unguarded,
with no handler in `main()` -- an `OSError` there left the fragment
renamed-but-not-rewritten, a traceback and no receipt, against the module
docstring's claim that "the receipt says which of the above fired."

Finding 2: `_destination_occupied` claimed the same shape as
`lane_setup.worktree_occupancy` without matching it -- the docstring says "the same
shape ... already use", but `worktree_occupancy` confirms absence positively via
`_absence_confirmed` (#380) and this function returned `False` on the exception
type alone. CLAUDE.md records that Windows folds an over-`MAX_PATH` destination
onto `FileNotFoundError, errno 2, winerror None`, indistinguishable from a genuine
absence -- so on that platform the overwrite guard answered "free" for a
destination nothing had actually looked at. Fixed by calling `_absence_confirmed`,
making the docstring's claim true rather than restating that it differs.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rename_changelog_fragment as rcf  # noqa: E402
from rename_changelog_fragment import OK, REFUSED, rename  # noqa: E402


def _git_repo(tmp_path, name, body):
    root = tmp_path / "repo"
    (root / "changelog.d").mkdir(parents=True)
    frag = root / "changelog.d" / name
    frag.write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add fragment"], cwd=str(root), check=True
    )
    return root, frag


def _run_with_faked_add(monkeypatch, returncode):
    """Real `git mv` runs; `git add` is intercepted and made to answer `returncode`
    instead of whatever the real one would say, so the two calls in the fixture
    below differ in exactly one respect."""
    real_run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if len(argv) >= 2 and argv[1] == "add":
            result = real_run(argv, *args, **kwargs)
            result.returncode = returncode
            return result
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(rcf.subprocess, "run", fake_run)


def _rename_in(root, frag, new_issue):
    """`rename()` shells out to `git mv`/`git add` with no `cwd=`, so it must be
    called from inside the repo, not the pytest process's own cwd."""
    cwd = os.getcwd()
    os.chdir(str(root))
    try:
        return rename(str(frag.relative_to(root)), new_issue, use_git=True)
    finally:
        os.chdir(cwd)


def test_a_failed_git_add_does_not_render_as_the_success_receipt(tmp_path, monkeypatch):
    """The reported case: `git mv` returns 0, `git add` returns 128 -- must not be
    reported as OK with the same receipt a successful add would produce."""
    root, frag = _git_repo(tmp_path, "111.fixed.md", "- Fixed the thing (#111).\n")
    _run_with_faked_add(monkeypatch, 128)

    state, message, new_path = _rename_in(root, frag, 222)

    assert state == REFUSED, (
        "a failed `git add` must not be reported the same as a successful one -- "
        "an amend without an explicit `git add` would then commit the pre-rewrite "
        "body under the new filename, reproducing #426's own defect",
        state,
        message,
    )
    assert new_path is not None, (
        "the rename and rewrite did happen; only staging failed"
    )
    new = root / "changelog.d" / "222.fixed.md"
    assert new.exists() and "#222" in new.read_text(encoding="utf-8")


def test_a_successful_git_add_still_reports_ok(tmp_path, monkeypatch):
    """Control paired with the failure case above: an ordinary successful `git add`
    must still report OK, or the fix above would be the opposite bug."""
    root, frag = _git_repo(tmp_path, "111.fixed.md", "- Fixed the thing (#111).\n")
    _run_with_faked_add(monkeypatch, 0)

    state, message, new_path = _rename_in(root, frag, 222)

    assert state == OK, (state, message)
    new = root / "changelog.d" / "222.fixed.md"
    assert new.exists() and "#222" in new.read_text(encoding="utf-8")


def test_an_unwritable_rewrite_leaves_a_receipt_not_a_traceback(tmp_path, monkeypatch):
    """`new_path.write_text` raising after a successful `git mv` must produce a
    REFUSED receipt naming what happened, not an uncaught exception -- the module
    docstring claims "the receipt says which of the above fired," which was false
    for this site."""
    root, frag = _git_repo(tmp_path, "111.fixed.md", "- Fixed the thing (#111).\n")

    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if self.name == "222.fixed.md":
            raise OSError("disk full (injected)")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    state, message, new_path = _rename_in(root, frag, 222)

    assert state == REFUSED, (
        "an OSError from the rewrite must be reported, not raised past main()",
        state,
        message,
    )
    assert "222" in message and ("OSError" in message or "disk full" in message)


def test_git_mv_and_write_still_succeed_with_no_injection(tmp_path):
    """Control paired with the injection above: with nothing faked, the ordinary
    rename-and-rewrite path must still work end to end."""
    root, frag = _git_repo(tmp_path, "111.fixed.md", "- Fixed the thing (#111).\n")

    state, message, new_path = _rename_in(root, frag, 222)

    assert state == OK, (state, message)
    new = root / "changelog.d" / "222.fixed.md"
    assert new.exists() and "#222" in new.read_text(encoding="utf-8")


def _fold_stat(monkeypatch, target):
    """Emulate the Windows fold on `target` only: `os.stat` answers ordinary
    absence for a name that is really there. `_destination_occupied` calls
    `os.stat` directly (no `Path.stat` route), so this one seam is sufficient --
    unlike test_unlookable_absence_380.py's two-seam patch for a function that is
    reached both ways."""
    import errno

    wanted = os.path.normcase(os.path.abspath(str(target)))
    real_stat = os.stat

    def fake_stat(value, *fargs, **fkwargs):
        try:
            key = os.path.normcase(os.path.abspath(os.fspath(value)))
        except (TypeError, OSError, ValueError):
            key = None
        if key == wanted:
            raise FileNotFoundError(
                errno.ENOENT, "No such file or directory", str(value)
            )
        return real_stat(value, *fargs, **fkwargs)

    monkeypatch.setattr(os, "stat", fake_stat)


def test_destination_occupied_confirms_absence_rather_than_trusting_the_exception(
    tmp_path, monkeypatch
):
    """The reported gap: a folded `FileNotFoundError` on a destination that really
    exists must not render as `False` (free) -- it must go through
    `_absence_confirmed` and come back `None` ("could not look"), the same as
    `lane_setup.worktree_occupancy` would answer for the identical fold."""
    real = tmp_path / "222.fixed.md"
    real.write_text("- someone else's work (#222)\n", encoding="utf-8")

    try:
        os.stat(str(real))
    except OSError:
        pytest.skip("could not establish the destination as present before folding it")

    _fold_stat(monkeypatch, real)

    result = rcf._destination_occupied(real)

    assert result is None, (
        "a destination stat cannot reach while its parent lists it must render as "
        "'could not look' (None), never as free (False) -- CLAUDE.md's Windows "
        "measurement is exactly this fold",
        result,
    )


def test_destination_occupied_still_answers_absent_for_a_genuine_miss(tmp_path):
    """Positive control paired with the fold above: a destination that really is
    absent, with no injection at all, must still answer False -- or the fix would
    be the opposite bug, folding every genuine absence into 'could not look'."""
    missing = tmp_path / "222.fixed.md"
    assert rcf._destination_occupied(missing) is False


def test_destination_occupied_still_answers_present_for_a_genuine_hit(tmp_path):
    """Second control: an ordinary occupied destination, no injection, must still
    answer True."""
    present = tmp_path / "222.fixed.md"
    present.write_text("- occupied\n", encoding="utf-8")
    assert rcf._destination_occupied(present) is True


def test_destination_occupied_still_answers_could_not_look_for_a_non_directory_component(
    tmp_path,
):
    """Third table row from the issue: a path component that is a file rather than
    a directory. `NotADirectoryError` is on the same absence arm as
    `FileNotFoundError` in this function, and a component being a file rather than
    a directory means nothing can genuinely be under it -- so this is expected to
    answer False (confirmed absent), matching `lane_setup.worktree_occupancy`'s
    documented behaviour for the same case, not the unlookable arm."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    under = blocker / "222.fixed.md"

    try:
        os.stat(str(under))
    except NotADirectoryError:
        pass
    except OSError as exc:
        pytest.skip(
            "this platform did not raise NotADirectoryError for a component that "
            "is a file: {}: {}. UNTESTED here.".format(type(exc).__name__, exc)
        )

    assert rcf._destination_occupied(under) is False


def test_destination_occupied_answers_could_not_look_for_an_embedded_null(tmp_path):
    """Reviewer finding on this same fix: `os.stat` raises `ValueError`, not
    `OSError`, for a path carrying an embedded null byte, so neither `except` arm
    in `_destination_occupied` caught it and it escaped as a raw traceback --
    exactly the class this issue's own fix closes elsewhere in this function.
    `lane_setup.worktree_occupancy` (this function's stated model) already has a
    `except ValueError` arm for this (see `tests/test_unlookable_absence_380.py`);
    this pins the sibling."""
    bad = str(tmp_path / "222.fixed.md") + chr(0) + "extra"
    assert rcf._destination_occupied(bad) is None


def test_source_present_confirms_absence_rather_than_trusting_the_exception(
    tmp_path, monkeypatch
):
    """#468: `_source_present`'s absence arm used to return `False` on the
    exception type alone, unlike `_destination_occupied` which #444 already
    fixed to consult `_absence_confirmed` first. A folded `FileNotFoundError`
    on a source that really exists must not render as `False` ("no such
    file") -- it must come back `None` ("could not tell"), the same fold as
    the destination-side test above, on the source helper this time."""
    real = tmp_path / "111.fixed.md"
    real.write_text("- someone else's work (#111)\n", encoding="utf-8")

    try:
        os.stat(str(real))
    except OSError:
        pytest.skip("could not establish the source as present before folding it")

    _fold_stat(monkeypatch, real)

    result = rcf._source_present(real)

    assert result is None, (
        "a source stat cannot reach while its parent lists it must render as "
        "'could not tell' (None), never as absent (False) -- the same fold "
        "CLAUDE.md records for the destination side",
        result,
    )


def test_source_present_still_answers_absent_for_a_genuine_miss(tmp_path):
    """Positive control paired with the fold above: a source that really is
    absent, with no injection at all, must still answer False -- or the fix
    would be the opposite bug, folding every genuine absence into 'could not
    tell'."""
    missing = tmp_path / "111.fixed.md"
    assert rcf._source_present(missing) is False


def test_source_present_still_answers_present_for_a_genuine_hit(tmp_path):
    """Second control: an ordinary present source, no injection, must still
    answer True."""
    present = tmp_path / "111.fixed.md"
    present.write_text("- present\n", encoding="utf-8")
    assert rcf._source_present(present) is True


def test_source_present_answers_could_not_look_for_an_embedded_null(tmp_path):
    """The second instance from #468: `os.stat` raises `ValueError`, not
    `OSError`, for a path carrying an embedded null byte. Before this fix
    that escaped `_source_present` as a raw traceback -- neither `except`
    arm caught it -- unlike `_destination_occupied`, which already has this
    arm (see the embedded-null test above). Not reachable through this
    script's own CLI (POSIX argv cannot carry a NUL); this pins the
    importing-caller hazard directly."""
    bad = str(tmp_path / "111.fixed.md") + chr(0) + "extra"
    assert rcf._source_present(bad) is None


def test_a_git_add_that_cannot_even_run_returns_refused_not_a_traceback(
    tmp_path, monkeypatch
):
    """Reviewer finding on this same fix: `git mv` is wrapped in
    `except (OSError, ValueError)` to survive git becoming unspawnable mid-run,
    but the new `git add` call was not -- so an unspawnable `git` between the two
    calls (deleted, locked by AV, fork/exec exhaustion) raised straight past
    `rename()` instead of returning the REFUSED receipt this same commit's
    subject line promises for a failed `git add`."""
    root, frag = _git_repo(tmp_path, "111.fixed.md", "- Fixed the thing (#111).\n")
    real_run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if len(argv) >= 2 and argv[1] == "add":
            raise OSError("git vanished mid-run (injected)")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(rcf.subprocess, "run", fake_run)

    state, message, new_path = _rename_in(root, frag, 222)

    assert state == REFUSED, (
        "an unspawnable `git add` must return REFUSED, not raise past rename()",
        state,
        message,
    )
    assert "add" in message.lower()


def test_an_unwritable_rewrite_does_not_overclaim_the_on_disk_state(
    tmp_path, monkeypatch
):
    """Reviewer finding on this same fix: `Path.write_text` truncates on open
    before writing, so an `OSError` raised *during* the write (disk full mid-
    flush) can leave the file empty or partially written, not holding the OLD
    body as the original message unconditionally asserted. The receipt must not
    name a specific on-disk state it cannot verify."""
    root, frag = _git_repo(tmp_path, "111.fixed.md", "- Fixed the thing (#111).\n")

    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if self.name == "222.fixed.md":
            raise OSError("disk full mid-write (injected)")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    state, message, new_path = _rename_in(root, frag, 222)

    assert state == REFUSED
    assert "OLD body" not in message, (
        "the message must not assert a specific on-disk state write_text's "
        "failure mode cannot guarantee",
        message,
    )
