"""`main()`'s fd-3 progress channel (#1648).

`bin/oss-workspace`'s pre-`exec claude` call is otherwise silent for the whole
~46s a real update can take. The fix (per the issue's own sketch) is: `update()`
takes an optional `progress` callback (tested directly against `update()` in
`tests/test_plugin_update_dependencies_605.py`), and `main()` wires that
callback to a writer on file descriptor 3 -- IF the caller opened one -- and to
nothing when it did not.

This file tests `main()`'s OWN half of that wiring: does it attempt fd 3, does
it hand `update()` a real callback only when that attempt succeeds, and does a
failure to open fd 3 (the ordinary case -- every caller except the launcher,
including every other test in this suite) leave `update()` called exactly as
it always was. `os.fdopen` is monkeypatched rather than a real fd 3 opened via
a pipe + `preexec_fn`, which is POSIX-only and would make this file
Windows-only-skip for no reason: what is under test is `main()`'s own control
flow around whatever `os.fdopen(3, ...)` answers, not the OS-level fd
mechanics themselves.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


class _FakeWriter:
    def __init__(self):
        self.lines = []
        self.closed = False
        self.flushed = 0

    def write(self, text):
        self.lines.append(text)

    def flush(self):
        self.flushed += 1

    def close(self):
        self.closed = True


def _stub_update(monkeypatch, capture):
    """Replace `update()` with a stub that records whether it was called with a
    real `progress` callable, and if so, calls it with two known steps --
    exactly what a real run does for the marketplace, the loop plugin and each
    dependency."""

    def _fake_update(**kwargs):
        capture["kwargs"] = kwargs
        progress = kwargs.get("progress")
        if progress is not None:
            progress("marketplace")
            progress("marketplace", "ok")
        return {"state": "current", "plugin": "oss"}

    monkeypatch.setattr(plugin_update, "update", _fake_update)
    monkeypatch.setattr(plugin_update, "write_receipt", lambda document: None)
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)


def test_a_writable_fd_3_becomes_a_real_progress_callback(monkeypatch):
    """#1648: when fd 3 opens successfully (the launcher's own case -- it ran
    `exec 3>&1` before this), `main()` must hand `update()` a callable that
    actually writes what `progress()` is called with."""
    writer = _FakeWriter()
    monkeypatch.setattr(
        plugin_update.os, "fdopen", lambda fd, mode, closefd=True: writer
    )
    capture = {}
    _stub_update(monkeypatch, capture)
    assert plugin_update.main(["--root", "."]) == 0
    assert capture["kwargs"]["progress"] is not None
    # #1648 self-review: the terminating newline for the shell's own dangling
    # in-flight "checking..." mark is written lazily, once, before the FIRST
    # real progress line -- never unconditionally -- so a run that streams at
    # least one line still starts with exactly one newline.
    assert writer.lines == [
        "\n",
        "    checking marketplace...\n",
        "    marketplace: ok\n",
    ]
    assert writer.closed


def test_no_bytes_are_written_when_update_never_calls_progress_1648(monkeypatch):
    """#1648 self-review: `update()` returns with ZERO calls to `progress` on
    its debounce/opt-out/unreadable-manifest paths -- the common case for a
    session opened shortly after another one. On those runs, even with fd 3
    open and writable, NOTHING may be written to it -- not even the
    terminating newline -- or the shell's own dangling "checking..." mark
    would be frozen, permanently un-overwritten, on every ordinary launch."""
    writer = _FakeWriter()
    monkeypatch.setattr(
        plugin_update.os, "fdopen", lambda fd, mode, closefd=True: writer
    )
    capture = {}

    def _fake_update(**kwargs):
        # Simulates a debounced/opted-out/unreadable-manifest run: `update()`
        # returns immediately WITHOUT ever calling the `progress` callback it
        # was handed.
        capture["kwargs"] = kwargs
        return {"state": "off", "detail": "switched off by OSS_NO_AUTO_UPDATE"}

    monkeypatch.setattr(plugin_update, "update", _fake_update)
    monkeypatch.setattr(plugin_update, "write_receipt", lambda document: None)
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    assert plugin_update.main(["--root", "."]) == 0
    assert capture["kwargs"]["progress"] is not None
    assert writer.lines == []
    assert writer.closed


def test_fd_3_not_open_is_the_ordinary_case_and_passes_no_progress(monkeypatch):
    """Must-fire control for the case above: every caller except the launcher --
    the async SessionStart hook, a bare CLI invocation, every OTHER test in this
    suite -- never opened fd 3, and `os.fdopen(3, ...)` answers with the real
    `OSError` (`errno.EBADF`) that produces. `update()` must then be called with
    `progress=None`, exactly as it always was, never a callback nobody can use."""

    def _raise(fd, mode, closefd=True):
        raise OSError(9, "Bad file descriptor")

    monkeypatch.setattr(plugin_update.os, "fdopen", _raise)
    capture = {}
    _stub_update(monkeypatch, capture)
    assert plugin_update.main(["--root", "."]) == 0
    assert capture["kwargs"]["progress"] is None


def test_fd_3_is_marked_non_inheritable_after_a_real_open_1673(monkeypatch):
    """#1673: `update()` below fd 3's own successful open spawns real
    `subprocess.run()` calls of its own (`_run()`, once for the marketplace
    refresh, once per plugin/dependency). fd 3 was never opened by THIS
    process -- it arrives already-open, inherited straight across
    `bin/oss-workspace`'s own `exec 3>&1` -- so PEP 446's
    non-inheritable-by-default (which covers only descriptors Python itself
    creates) does not apply to it, and left alone every one of those child
    `subprocess.run()` calls would hand its own grandchild a live copy of the
    same handle. On Windows this is the documented cause of a runner step
    that outlives the whole test process, cancelled only by the job's own
    `timeout-minutes` cap -- exactly what PR #1654's `windows-latest`/3.12 leg
    was observed doing on every run.

    This uses a REAL file descriptor at slot 3 -- a pipe, `dup2`'d on with
    `inheritable=True` to mirror exactly what a shell's `exec 3>&1` hands a
    child -- rather than the `os.fdopen` monkeypatch the sibling tests in this
    file use, because inheritability is precisely the OS-level property a
    mock cannot exercise. `os.set_inheritable`/`os.get_inheritable` are POSIX
    *and* Windows primitives (PEP 446), so this is a real, portable assertion
    about the fix -- not a Windows-only claim. What stays Windows-only and
    unverified by this test is the actual failure mode itself (a runner step
    outliving the process): that is a CI-only observation, not something a
    local run on any one platform can reproduce or disprove; this test only
    pins that the code takes the narrowing step it is supposed to."""
    # pytest's own fd-level capture manager may already hold something at slot
    # 3 (it saves the real stdout/stderr fds at whatever slot `os.dup()`
    # happens to hand back, and that is frequently the next free low number).
    # A blind `dup2(..., 3)` with no save/restore was tried first and left
    # pytest's own teardown crashing with "Bad file descriptor" -- found
    # running this test standalone, not from reading the pytest source. So
    # whatever is at 3 before this test touches it is preserved and put back
    # afterwards, exactly like any other fd this test does not own.
    try:
        saved_fd = os.dup(3)
    except OSError:
        saved_fd = None
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    os.dup2(write_fd, 3, inheritable=True)
    os.close(write_fd)
    try:
        # Positive control: the fd genuinely starts inheritable, exactly as a
        # shell-handed one would -- so a test that always saw False could not
        # tell "the fix ran" from "this platform starts fds non-inheritable
        # anyway".
        assert os.get_inheritable(3) is True
        capture = {}
        _stub_update(monkeypatch, capture)
        assert plugin_update.main(["--root", "."]) == 0
        assert os.get_inheritable(3) is False
    finally:
        os.close(read_fd)
        if saved_fd is not None:
            os.dup2(saved_fd, 3)
            os.close(saved_fd)
        else:
            try:
                os.close(3)
            except OSError:
                pass
