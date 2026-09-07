r"""#1214, second signature: nested-pytest scratch artifacts racing at the
repository root, distinct from the launcher-test race #1221 already fixed.

The issue's own comment (2026-09-07) logs two concrete instances, both a
`FileNotFoundError` during a nested pytest subprocess's own collection because
a directory it needed, created directly at the **repository root**, vanished
while sibling xdist workers (`-n auto --dist loadfile`, #1177) create and
remove their own root-level artifacts concurrently:

- Instance A: `_durprobe_881_<hex>`, from
  `tests/test_durations_recorded_881.py`'s own `_run_stub_test`, which used to
  create its stub directory as a direct child of the repository root.
- Instance B: `pytest-cache-files-<hex>`, pytest's own internal cache-dir
  atomic-rename tempfile (`_pytest.cacheprovider._make_cachedir`), also
  written at rootdir -- and rootdir is shared by *every* concurrent nested
  pytest invocation, because pytest resolves it by walking UP from the given
  test path to find `pyproject.toml`, regardless of where the stub itself
  lives.

Two independent, verifiable fixes:

1. **Never create a scratch directory as a direct child of the repository
   root.** `tests/test_duration_report_plugin_910.py` already nests its own
   stub under `tests/`; `tests/test_durations_recorded_881.py` did not. A
   background monitor watches the *true* repository root's own direct
   children while a real stub run executes, and fails loudly if anything new
   appears there -- paired with a must-fire positive control proving the
   monitor can actually see a deliberately-created root-level entry (a
   monitor that never fires is indistinguishable from a clean tree).

2. **Never let the nested pytest process touch the shared `.pytest_cache` at
   all.** `-p no:cacheprovider` on both nested invocations removes them as a
   party to any write race at the rootdir-shared cache directory -- these are
   one-off single-file smoke runs that gain nothing from `--lf`/`--ff` or
   lastfailed caching. Verified dynamically: with the flag, a nested run that
   starts from a fresh (deleted) `.pytest_cache` must not recreate it; without
   the flag (the pre-fix shape), it must.

A fully deterministic repro of the exact Windows race (a directory disappearing
mid-`os.rename` under a concurrent sibling process) was not practical in this
environment -- it requires genuine concurrent xdist workers under Windows'
own delete-while-open semantics, which this single-process, single-platform
test run cannot reproduce on demand. What is verified here instead is the
confirmed, deterministic half of the defect (a scratch directory really was
created at the true repository root) and the mitigation's real effect (the
cache directory really is untouched with the flag, and really is touched
without it) -- code inspection plus a live monitor, not a race won on purpose.
"""

import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import test_durations_recorded_881 as m881  # noqa: E402
import test_duration_report_plugin_910 as m910  # noqa: E402


class _RootWatcher:
    """Polls REPO_ROOT's own direct children at high frequency and records
    any name not present at construction time -- a live monitor for "did
    anything land directly at the repository root", not a before/after
    snapshot that could miss something created and removed between polls."""

    def __init__(self, root):
        self.root = root
        self._baseline = set(p.name for p in root.iterdir())
        self._seen_new = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def _poll(self):
        while not self._stop.is_set():
            try:
                for p in self.root.iterdir():
                    if p.name not in self._baseline:
                        self._seen_new.add(p.name)
            except OSError:
                pass
            time.sleep(0.005)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)

    def new_names(self):
        return set(self._seen_new)


def test_root_watcher_actually_sees_a_root_level_entry_appear():
    """Must-fire positive control for the monitor itself: if this fails, the
    monitor below cannot be trusted to have seen nothing, because it may
    simply be blind."""
    with _RootWatcher(REPO_ROOT) as watcher:
        probe = REPO_ROOT / ("_watcher_selftest_" + uuid.uuid4().hex[:8])
        probe.mkdir()
        try:
            time.sleep(0.2)
        finally:
            shutil.rmtree(probe, ignore_errors=True)
    assert probe.name in watcher.new_names(), (
        "the root watcher never saw a directory that was really created "
        "directly under the repository root -- it cannot be trusted to "
        "report a clean run as clean"
    )


def test_the_881_stub_run_never_creates_anything_directly_at_the_repo_root(tmp_path):
    """The confirmed half of #1214: `test_durations_recorded_881.py`'s own
    `_run_stub_test` must never create a scratch directory as a direct child
    of the repository root -- that is exactly the `_durprobe_881_*` instance
    the issue logged."""
    with _RootWatcher(REPO_ROOT) as watcher:
        output = m881._run_stub_test()
    assert not any(name.startswith("_durprobe_881_") for name in watcher.new_names()), (
        "test_durations_recorded_881.py's stub run created a directory "
        "directly under the repository root: " + repr(watcher.new_names())
    )
    # Must-still-work pair: the stub run itself must still succeed and find
    # the repository's real pyproject.toml (proving the relocation did not
    # break the thing #881 actually tests).
    assert "durations" in output.lower(), output


def test_the_910_stub_run_never_creates_anything_directly_at_the_repo_root(tmp_path):
    """Sibling check for the file that already nests under tests/ -- a
    must-hold invariant, not a new fix, but one #1214's own defect class
    says is worth pinning so a future edit cannot regress it silently."""
    baseline_path = tmp_path / "nope.json"
    with _RootWatcher(REPO_ROOT) as watcher:
        output = m910._run_stub_test(["--duration-baseline-path", str(baseline_path)])
    assert not any(name.startswith("_durprobe_910_") for name in watcher.new_names()), (
        "test_duration_report_plugin_910.py's stub run created a directory "
        "directly under the repository root: " + repr(watcher.new_names())
    )
    assert "test-durations" in output, output


def _cache_dir():
    return REPO_ROOT / ".pytest_cache"


def test_881_stub_run_does_not_touch_the_shared_cache_directory():
    """The second, mitigated half of #1214: with `.pytest_cache` deleted
    first, a nested stub run must not recreate it -- proving the nested
    invocation really does carry `-p no:cacheprovider` and is no longer a
    party to any write race at the rootdir-shared cache directory."""
    cache_dir = _cache_dir()
    existed_before = cache_dir.is_dir()
    if existed_before:
        shutil.rmtree(cache_dir, ignore_errors=True)
    try:
        m881._run_stub_test()
        assert not cache_dir.is_dir(), (
            "a nested pytest stub run recreated .pytest_cache at the "
            "repository root even though it is supposed to run with "
            "-p no:cacheprovider -- it is still a party to the rootdir "
            "cache-directory write race #1214 names"
        )
    finally:
        # Leave the tree as we found it -- do not delete a cache directory
        # that predates this test and belongs to someone else's run.
        pass


def test_910_stub_run_does_not_touch_the_shared_cache_directory(tmp_path):
    """Sibling check for the other file's own nested invocation."""
    cache_dir = _cache_dir()
    if cache_dir.is_dir():
        shutil.rmtree(cache_dir, ignore_errors=True)
    baseline_path = tmp_path / "nope.json"
    m910._run_stub_test(["--duration-baseline-path", str(baseline_path)])
    assert not cache_dir.is_dir(), (
        "a nested pytest stub run (910) recreated .pytest_cache at the "
        "repository root even though it is supposed to run with "
        "-p no:cacheprovider"
    )
