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
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import plugin_update  # noqa: E402
import spawn_guard  # noqa: E402


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
    assert plugin_update.main(["--root", ".", "--progress-fd", "3"]) == 0
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
    assert plugin_update.main(["--root", ".", "--progress-fd", "3"]) == 0
    assert capture["kwargs"]["progress"] is not None
    assert writer.lines == []
    assert writer.closed


def test_a_progress_fd_that_will_not_open_passes_no_progress(monkeypatch):
    """`--progress-fd 3` named, but `os.fdopen(3, ...)` answers with the real
    `OSError` (`errno.EBADF`) a closed slot produces -- the launcher asked for
    a channel it did not actually open. `update()` must then be called with
    `progress=None`, exactly as it always was, never a callback nobody can use."""

    def _raise(fd, mode, closefd=True):
        raise OSError(9, "Bad file descriptor")

    monkeypatch.setattr(plugin_update.os, "fdopen", _raise)
    capture = {}
    _stub_update(monkeypatch, capture)
    assert plugin_update.main(["--root", ".", "--progress-fd", "3"]) == 0
    assert capture["kwargs"]["progress"] is None


def test_without_progress_fd_the_descriptor_is_never_touched_1673(monkeypatch):
    """#1673, the actual cause: `main()` used to PROBE fd 3 blindly, on every
    caller, and let `OSError` mean "nobody opened one". Under a pytest-xdist
    worker on `windows-latest` slot 3 is not closed -- it is one of execnet's
    own live descriptors -- and `os.fdopen(3, "w")` on it BLOCKED forever:
    two workers sat inside `<frozen os>:1066 fdopen` from
    `test_plugin_update_debounce_753.py:240` and
    `test_doctor_launcher_caller_1154.py:139` (both call `main()` in-process
    with no fd-3 stub) until the job's own 30-minute cap cancelled the leg,
    named by `-o faulthandler_timeout=180` on run 35363849336, job
    105661393528, after four issues (#1658, #1660, #1671, #1673) had read
    the same cancellation as a post-session hang.

    An inherited descriptor cannot be detected -- a slot that happens to be
    open is indistinguishable from one the caller opened on purpose -- so the
    channel is opt-in: without `--progress-fd`, `os.fdopen` is never called at
    all, whatever is or is not in slot 3. Must-fire control: the same stub
    records the call when the flag IS passed."""
    calls = []

    def _record(fd, mode, closefd=True):
        calls.append(fd)
        return _FakeWriter()

    monkeypatch.setattr(plugin_update.os, "fdopen", _record)
    capture = {}
    _stub_update(monkeypatch, capture)
    assert plugin_update.main(["--root", "."]) == 0
    assert calls == []
    assert capture["kwargs"]["progress"] is None

    assert plugin_update.main(["--root", ".", "--progress-fd", "3"]) == 0
    assert calls == [3]
    assert capture["kwargs"]["progress"] is not None


def test_a_non_integer_progress_fd_is_refused_1673(monkeypatch, capsys):
    """`--progress-fd` names a descriptor number and nothing else: a value
    `int()` refuses is reported, not silently read as "no channel" -- an
    absence the caller asked for and one produced by a typo must not render
    the same. Must-fire control: `3` on the same path is accepted."""
    monkeypatch.setattr(
        plugin_update.os, "fdopen", lambda fd, mode, closefd=True: _FakeWriter()
    )
    capture = {}
    _stub_update(monkeypatch, capture)
    assert plugin_update.main(["--root", ".", "--progress-fd", "three"]) == 2
    assert "--progress-fd" in capsys.readouterr().err
    assert "kwargs" not in capture
    assert plugin_update.main(["--root", ".", "--progress-fd", "3"]) == 0
    assert capture["kwargs"]["progress"] is not None


# #1673 self-review (a spawned reviewer, not this lane's own first pass): the
# first draft of this test did the pipe/dup2-onto-slot-3 dance directly inside
# the pytest WORKER's own process, restored in a `finally`. Under
# pytest-xdist on macOS that crashed a worker outright
# (`INTERNALERROR`/`AssertionError` on `<WorkerController gw0>`) -- xdist
# holds its own worker-communication file descriptors somewhere near the low
# end of the table too, and clobbering slot 3 process-wide, even briefly and
# even restored afterwards, collided with whatever xdist itself had there.
# `bin/oss-workspace`'s own contract is literal fd 3 (`exec 3>&1` then
# `--progress-fd 3`), so the number itself cannot move to a safer slot
# without changing what is under test. What CAN move is which process's fd table pays
# for the exercise: a real child process, spawned fresh for exactly this, has
# its own fd table from the OS's own fork/exec -- nothing it does to its own
# slot 3 can reach back into the pytest worker that spawned it, crash or no
# crash. `spawn_guard.run` (this repo's own `subprocess.run` wrapper -- see
# `tests/spawn_guard.py`) is used rather than a bare `subprocess.run`, per the
# guard `tests/test_spawn_guard_716.py` enforces over every spawn under
# `tests/` that carries a `timeout=`.
_FD3_CHILD_SCRIPT = textwrap.dedent(
    """
    import os
    import sys

    sys.path.insert(0, sys.argv[1])
    import plugin_update

    def _fake_update(**kwargs):
        progress = kwargs.get("progress")
        if progress is not None:
            progress("marketplace")
            progress("marketplace", "ok")
        return {"state": "current", "plugin": "oss"}

    plugin_update.update = _fake_update
    plugin_update.write_receipt = lambda document: None
    plugin_update.read_receipt = lambda: None

    read_fd, write_fd = os.pipe()

    # A freshly spawned python -c child starts with only 0/1/2 open, so
    # os.pipe() readily hands back (3, 4) as its own two ends -- and this
    # script is about to force fd 3 to become a dup of write_fd. Left
    # unguarded, that dup2 would destroy read_fd out from under itself
    # whenever os.pipe() happened to pick 3 for it (found running this
    # standalone: "OSError: Bad file descriptor" closing read_fd afterwards,
    # because fd 3 -- read_fd's own number -- had already been overwritten
    # and then closed once by the time read_fd's own close ran). Move
    # either end off slot 3 first if os.pipe() landed there.
    def _off_fd3(fd):
        if fd != 3:
            return fd
        moved = os.dup(fd)
        os.close(fd)
        return moved

    read_fd = _off_fd3(read_fd)
    write_fd = _off_fd3(write_fd)

    os.set_inheritable(write_fd, True)
    os.dup2(write_fd, 3, inheritable=True)
    os.close(write_fd)

    before = os.get_inheritable(3)
    rc = plugin_update.main(["--root", ".", "--progress-fd", "3"])
    after = os.get_inheritable(3)

    os.close(3)
    os.close(read_fd)

    print("RESULT before={} after={} rc={}".format(before, after, rc))
    sys.exit(0 if (before is True and after is False and rc == 0) else 1)
    """
)


def test_fd_3_is_marked_non_inheritable_after_a_real_open_1673():
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
    `timeout-minutes` cap.

    A CI run of this exact fix (PR #1654, commit 547b4b86) showed the
    `windows-latest`/3.12 leg STILL cancelling at the same ~30min mark with
    this fix in place -- so the fd-inheritance theory as the CAUSE of #1673 is
    refuted, not confirmed, and this test (and the production change it pins)
    makes no claim about resolving #1673. `os.set_inheritable(3, False)` is
    still a correct, narrowly-scoped improvement on its own terms regardless:
    a descriptor this process did not open and does not need its own children
    to inherit should not be handed to them, independent of whether it turns
    out to explain the CI hang.

    This spawns a REAL child process (see `_FD3_CHILD_SCRIPT` above) that
    opens a real pipe, `dup2`'s it onto its OWN fd slot 3 with
    `inheritable=True` -- mirroring exactly what a shell's `exec 3>&1` hands a
    child -- and reports what `os.get_inheritable(3)` read before and after
    `plugin_update.main()` ran. `os.set_inheritable`/`os.get_inheritable` are
    POSIX *and* Windows primitives (PEP 446), so the property under test is
    portable even though this file only runs the check on whatever platform
    collects it. What stays Windows-only and unverified by this test is the
    actual failure mode #1673 was opened to explain (a runner step outliving
    the process) -- see the CI result quoted above: that is a CI-only
    observation nobody has reproduced, on any platform, by any local run."""
    scripts_dir = str(REPO_ROOT / "scripts")
    result = spawn_guard.run(
        [sys.executable, "-c", _FD3_CHILD_SCRIPT, scripts_dir],
        subject="plugin_update.py's real fd-3 non-inheritance (#1673)",
        timeout=30,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "before=True after=False rc=0" in result.stdout, (
        result.stdout,
        result.stderr,
    )
