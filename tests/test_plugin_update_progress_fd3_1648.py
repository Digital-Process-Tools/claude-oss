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
    assert writer.lines == [
        "    checking marketplace...\n",
        "    marketplace: ok\n",
    ]
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
