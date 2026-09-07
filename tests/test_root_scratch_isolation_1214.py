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
   lastfailed caching. Verified via `--trace-config`: pytest prints one
   `PLUGIN registered:` line per active plugin at startup, before any real
   collection happens, so the flag's effect is checked by grepping that
   startup trace for `cacheprovider` rather than by deleting and racing the
   real, shared `.pytest_cache` directory. An earlier version of this file
   verified the flag by deleting `.pytest_cache` outright and checking
   whether the stub run recreated it -- caught in this lane's own self-review
   as the same defect class #1214 is about: deleting a directory every
   concurrent xdist worker's own session start/finish also writes to is
   itself root-level interference, and the version that did this also never
   restored a pre-existing cache directory it had deleted, contradicting its
   own comment. `--trace-config` needs no such destructive probing.

A fully deterministic repro of the exact Windows race (a directory disappearing
mid-`os.rename` under a concurrent sibling process) was not practical in this
environment -- it requires genuine concurrent xdist workers under Windows'
own delete-while-open semantics, which this single-process, single-platform
test run cannot reproduce on demand. What is verified here instead is the
confirmed, deterministic half of the defect (a scratch directory really was
created at the true repository root) and the mitigation's real effect (the
cache plugin really is inactive with the flag, and really is active without
it) -- code inspection plus a live monitor, not a race won on purpose.
"""

import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import spawn_guard  # noqa: E402
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


def test_the_881_stub_run_never_creates_anything_directly_at_the_repo_root():
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


def test_881_stub_run_disables_the_cache_plugin():
    """The mitigated half of #1214: the 881 stub run's own real, shipped
    argument list must actually disable pytest's cache plugin. Checked via
    `--trace-config`'s startup plugin-registration trace, never by deleting
    the real, shared `.pytest_cache` -- see this module's own docstring for
    why the earlier, destructive version of this check was replaced."""
    output = m881._run_stub_test(extra_args=["--trace-config"])
    assert "cacheprovider" not in output, output


def test_881_stub_run_cacheprovider_check_is_not_vacuous(tmp_path):
    """Must-fire positive control for the check above: with the disabling
    flags left off entirely, the identical stub setup must show the
    cacheprovider plugin actually registering -- proving the assertion above
    would have caught a `-p no:cacheprovider` that silently stopped being
    passed.

    `COVERAGE_FILE` isolated to `tmp_path` (#1228, a full-suite `-n auto`
    run's own finding on this round): with no disabling flag at all, this
    nested run also inherits `pyproject.toml`'s real `--cov=scripts`, so
    without isolation it would start its own coverage.py session against
    the SAME shared repository `.coverage` file every other concurrent
    xdist worker uses -- the exact site 4 race this issue exists to remove,
    reintroduced by the one control in this file that deliberately runs
    with no disabling flags at all. Confirmed live: a real `-n auto --dist
    loadfile` run over the whole suite raced this control against `tests/
    test_durations_recorded_881.py::test_stub_run_never_touches_the_
    shared_coverage_file` in a different worker and failed it, before this
    isolation was added."""
    stub_dir = REPO_ROOT / "tests" / ("_durprobe_881_ctrl_" + uuid.uuid4().hex[:8])
    stub_dir.mkdir()
    isolated = tmp_path / "isolated.coverage"
    try:
        stub_path = stub_dir / "test_stub.py"
        stub_path.write_text(m881._STUB_TEST_BODY, encoding="utf-8")
        result = spawn_guard.run(
            [sys.executable, "-m", "pytest", "-q", "--trace-config", str(stub_path)],
            subject="whether pytest's cacheprovider plugin registers without any disabling flag",
            timeout=60,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=dict(os.environ, COVERAGE_FILE=str(isolated)),
        )
        output = result.stdout + result.stderr
    finally:
        shutil.rmtree(stub_dir, ignore_errors=True)
    assert "cacheprovider" in output, (
        "the --trace-config probe never showed cacheprovider registering even "
        "with no disabling flag passed -- the check above cannot actually "
        "detect the flag being dropped:\n" + output
    )


def test_910_stub_run_disables_the_cache_plugin(tmp_path):
    """Sibling check for the other file's own nested invocation."""
    baseline_path = tmp_path / "nope.json"
    output = m910._run_stub_test(
        ["--duration-baseline-path", str(baseline_path), "--trace-config"]
    )
    assert "cacheprovider" not in output, output


def test_881_stub_run_disables_the_root_scratch_guard(tmp_path):
    """#1228, a reviewer finding on that same round: `root_scratch_guard` was
    added to `tests/conftest.py`'s plugin list after this file's own
    disable lists already existed, and neither was updated to match --
    living under `tests/`, both nested stub runs inherit it, spinning up a
    second, redundant watcher thread inside an already-nested process for
    no reason. Checked the same way as the cacheprovider check above:
    `--trace-config`'s startup registration trace, never a live artifact."""
    output = m881._run_stub_test(extra_args=["--trace-config"])
    assert "root_scratch_guard" not in output, output


def test_881_stub_run_root_scratch_guard_check_is_not_vacuous(tmp_path):
    """Must-fire positive control, same shape as the cacheprovider one
    above: with the disabling flag left off, the identical stub setup must
    show `root_scratch_guard` actually registering.

    `COVERAGE_FILE` isolated to `tmp_path`, same reason as the sibling
    control above: with no disabling flag, this nested run also inherits
    real `--cov=scripts`, and this control specifically wants that -- it is
    proving `root_scratch_guard` registers under the exact conditions this
    issue's own fix removes it from, which is precisely the shared-`.
    coverage`-racing shape #1228 is about."""
    stub_dir = REPO_ROOT / "tests" / ("_durprobe_881_ctrl3_" + uuid.uuid4().hex[:8])
    stub_dir.mkdir()
    isolated = tmp_path / "isolated.coverage"
    try:
        stub_path = stub_dir / "test_stub.py"
        stub_path.write_text(m881._STUB_TEST_BODY, encoding="utf-8")
        result = spawn_guard.run(
            [sys.executable, "-m", "pytest", "-q", "--trace-config", str(stub_path)],
            subject="whether root_scratch_guard registers without any disabling flag",
            timeout=60,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=dict(os.environ, COVERAGE_FILE=str(isolated)),
        )
        output = result.stdout + result.stderr
    finally:
        shutil.rmtree(stub_dir, ignore_errors=True)
    assert "root_scratch_guard" in output, (
        "the --trace-config probe never showed root_scratch_guard "
        "registering even with no disabling flag passed -- the check above "
        "cannot actually detect the flag being dropped:\n" + output
    )


def test_910_stub_run_disables_the_root_scratch_guard(tmp_path):
    """Sibling check for the other file's own nested invocation (#1228)."""
    baseline_path = tmp_path / "nope.json"
    output = m910._run_stub_test(
        ["--duration-baseline-path", str(baseline_path), "--trace-config"]
    )
    assert "root_scratch_guard" not in output, output
