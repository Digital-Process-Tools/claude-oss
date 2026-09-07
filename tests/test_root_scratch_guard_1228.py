"""`tests/root_scratch_guard.py` end to end -- #1228.

Same harness shape as `tests/test_must_assert_on_430.py`: the subject is
SESSION-level exit-code behaviour (did the whole pytest run come back red
because of an unexpected root-level entry), which no in-process assertion
inside a test that same run is executing can observe -- `pytester` drives a
real, separate pytest subprocess and hands back its exit code and output.

Every case builds a small throwaway repository shape under `pytester.path`:
a `tests/` subdirectory holding `root_scratch_guard.py` (the real module
under test, loaded verbatim -- not a rewritten copy, so a bug in the module
is exactly as visible here as it would be to the real suite) plus a
`conftest.py` that registers it as a plugin, mirroring this real
repository's own `tests/conftest.py`. `root_scratch_guard.REPO_ROOT` is
computed from `Path(__file__).resolve().parent.parent`, so placing the
module two directories under `pytester.path` makes `pytester.path` itself
the "repository root" the guard watches -- the same relationship the real
module has to the real repository.

`_run()` below is a small, deliberately local re-implementation of the
#719 harness-failure skip `tests/test_must_assert_on_430.py` already has
for the identical `pytester` subprocess-import hazard (a `pytester` child's
relocated `HOME` can leave it unable to import pytest, at which point every
assertion here would be measuring nothing but reads as six false failures
about `root_scratch_guard`, not about #719). Not shared with that file's
own copy in this change; see this issue's own report for the follow-up.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import root_scratch_guard  # noqa: E402

pytest_plugins = ["pytester"]

_CHILD_COULD_NOT_IMPORT_PYTEST = re.compile(r"No module named ['\"]?pytest['\"]?\s*$")


def _child_could_not_run(result):
    if result.outlines:
        return None
    for line in result.errlines:
        if _CHILD_COULD_NOT_IMPORT_PYTEST.search(line):
            return line
    return None


def _run(pytester, *args):
    result = pytester.runpytest_subprocess(*args)
    reason = _child_could_not_run(result)
    if reason is not None:
        pytest.skip(
            "the pytester child could not import pytest ({!r}) -- this "
            "measures nothing about root_scratch_guard, not a defect in it "
            "(#719)".format(reason)
        )
    return result


def _root_scratch_guard_source():
    return Path(root_scratch_guard.__file__).read_text(encoding="utf-8")


def _make_guarded_tree(pytester, probe_body):
    """Lay out `pytester.path/tests/{root_scratch_guard.py,conftest.py,
    test_probe.py}` -- the real plugin, registered exactly the way the real
    repository registers it, watching `pytester.path` as its own
    "repository root"."""
    tests_dir = pytester.path / "tests"
    tests_dir.mkdir()
    (tests_dir / "root_scratch_guard.py").write_text(
        _root_scratch_guard_source(), encoding="utf-8"
    )
    (tests_dir / "conftest.py").write_text(
        "pytest_plugins = ['root_scratch_guard']\n", encoding="utf-8"
    )
    (tests_dir / "test_probe.py").write_text(probe_body, encoding="utf-8")
    return tests_dir


def test_a_leaked_root_level_entry_fails_the_whole_session(pytester):
    """Must-fire case: a test creates a directory directly under the
    watched root and never removes it -- exactly the shape of #1214's own
    two original sites before their fixes, and of any future third site
    this guard exists to catch. The session must come back red, naming the
    entry, not green."""
    tests_dir = _make_guarded_tree(
        pytester,
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    (root / '_leaked_root_entry_1228').mkdir()\n"
        # A trivial `assert True` test runs in well under a millisecond --
        # faster than the guard's own 5ms poll interval can reliably win a
        # race against, in this artificial harness alone (a real suite runs
        # for tens of seconds). The sleep gives the background watcher
        # thread at least one scheduling slice to see the entry before the
        # session ends; it is a harness timing fix, not a change to what
        # the guard itself watches for.
        "    time.sleep(0.1)\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret != 0, "\n".join(result.outlines + result.errlines)
    result.stdout.fnmatch_lines(["*root_scratch_guard*_leaked_root_entry_1228*"])


def test_a_transient_root_level_entry_still_fails_the_session(pytester):
    """Must-fire case, the harder half: the entry is created AND removed
    within the run, the same way #1214's own two original instances were
    transient (a directory that vanished mid-collection, not litter left at
    the end). The guard polls continuously in the background (like
    `_RootWatcher`'s own mechanism), not a before/after snapshot, so this
    must be caught too -- a snapshot-only check would silently miss exactly
    the failure mode #1214 was filed for."""
    tests_dir = _make_guarded_tree(
        pytester,
        "import shutil\n"
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    scratch = root / '_transient_root_entry_1228'\n"
        "    scratch.mkdir()\n"
        "    time.sleep(0.1)\n"
        "    shutil.rmtree(scratch)\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret != 0, "\n".join(result.outlines + result.errlines)
    result.stdout.fnmatch_lines(["*root_scratch_guard*_transient_root_entry_1228*"])


def test_an_ordinary_run_with_nothing_at_the_root_does_not_fail_the_session(pytester):
    """Must-not-fire control: a completely ordinary test, touching nothing
    at the root, must leave the session exactly as green as it would be
    with no guard registered at all."""
    tests_dir = _make_guarded_tree(pytester, "def test_it():\n    assert 1 + 1 == 2\n")
    result = _run(pytester, str(tests_dir))
    assert result.ret == 0, "\n".join(result.outlines + result.errlines)
    assert "root_scratch_guard" not in "\n".join(result.outlines)


def test_an_allowlisted_watcher_selftest_artifact_does_not_fail_the_session(pytester):
    """Regression for a reviewer finding on this same round: `tests/test_
    root_scratch_isolation_1214.py`'s own must-fire positive control
    (`test_root_watcher_actually_sees_a_root_level_entry_appear`)
    deliberately creates and removes a `_watcher_selftest_<hex>` directory
    directly at the real repository root, on purpose, to prove ITS OWN
    local watcher can see one. Without an allowlist entry for that exact
    shape, this whole-suite guard flagged that pre-existing, entirely
    legitimate self-test as a false "unexpected" leak on essentially every
    ordinary run of the real suite -- confirmed by running that real test
    against the real repository with this plugin active before this
    allowlist entry existed (`EXIT: 1` on a run every individual test in
    reported `passed`). Reproduced here in the harness's own isolated tree
    instead, so it stays a fast, deterministic regression rather than a
    dependency on the real suite's own layout."""
    tests_dir = _make_guarded_tree(
        pytester,
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    probe = root / '_watcher_selftest_deadbeef'\n"
        "    probe.mkdir()\n"
        "    time.sleep(0.1)\n"
        "    probe.rmdir()\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret == 0, "\n".join(result.outlines + result.errlines)
    assert "root_scratch_guard" not in "\n".join(result.outlines)


def test_pytest_cache_files_tempname_is_allowed_by_the_pure_check():
    """Fast, deterministic unit check for the allowlist rule itself,
    against the exact prefix `_pytest.cacheprovider._make_cachedir`
    creates (`tempfile.mkdtemp(prefix="pytest-cache-files-", ...)`,
    verified against installed pytest's own source) -- no subprocess, no
    timing dependency on winning the real atomic-rename race."""
    assert root_scratch_guard._is_allowed("pytest-cache-files-q0w20222")
    assert root_scratch_guard._is_allowed("pytest-cache-files-abcdefgh")


def test_an_allowlisted_pytest_cache_bootstrap_does_not_fail_the_session(pytester):
    """Regression for PR #1249's own CI failure (job 101700147592, ubuntu
    3.9): `_pytest.cacheprovider._make_cachedir` creates its own atomic-
    rename tempfile -- `tempfile.mkdtemp(prefix="pytest-cache-files-",
    dir=target.parent)`, where `target.parent` is the repository root
    itself -- then renames it to `.pytest_cache`. #1214's own fix disabled
    `-p no:cacheprovider` on the two known NESTED stub invocations, but the
    real, OUTER top-level suite invocation still runs cacheprovider
    normally and creates `.pytest_cache` fresh on any checkout that does
    not already have one -- exactly a fresh CI checkout, every time.
    Reproduced here by driving a real nested pytest run against a fresh
    throwaway tree with no pre-existing `.pytest_cache` and cacheprovider
    left ENABLED (the default `_run()` call already leaves it on -- no
    `-p no:cacheprovider` is passed anywhere in this harness), which is
    the exact condition that exercises the real mechanism end to end
    rather than only a synthetic literal."""
    tests_dir = _make_guarded_tree(pytester, "def test_it():\n    assert True\n")
    result = _run(pytester, str(tests_dir))
    assert result.ret == 0, "\n".join(result.outlines + result.errlines)
    assert "root_scratch_guard" not in "\n".join(result.outlines)


def test_a_real_non_tool_owned_leak_still_fails_after_the_pytest_cache_allowlisting(
    pytester,
):
    """Must-fire control, paired with the two must-not-fire cases above:
    adding `pytest-cache-files-*` to the allowlist must not widen it far
    enough to swallow a genuine leak. A name that shares no prefix with
    any allowlisted pattern must still fail the session, exactly as
    `test_a_leaked_root_level_entry_fails_the_whole_session` already
    proves for the pre-existing allowlist -- re-verified here, in the same
    round the allowlist grew, so the guard is confirmed to still have
    teeth rather than merely assumed to."""
    tests_dir = _make_guarded_tree(
        pytester,
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    (root / '_genuinely_unaccounted_for_1228').mkdir()\n"
        "    time.sleep(0.1)\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret != 0, "\n".join(result.outlines + result.errlines)
    result.stdout.fnmatch_lines(
        ["*root_scratch_guard*_genuinely_unaccounted_for_1228*"]
    )


def test_an_allowlisted_coverage_artifact_does_not_fail_the_session(pytester):
    """Must-not-fire control for the allowlist: a per-worker coverage.py
    data file (`.coverage.<host>.<pid>.<rand>`, the real shape pytest-cov /
    coverage.py produce under xdist, and legitimately still present at
    session end if the combine step has not run yet) must never be reported
    as an unexpected entry -- the guard's whole point is a THIRD scratch
    site, not this repository's own already-understood coverage machinery.
    """
    tests_dir = _make_guarded_tree(
        pytester,
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    (root / '.coverage.somehost.12345.abcdef').write_text('x')\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret == 0, "\n".join(result.outlines + result.errlines)
    assert "root_scratch_guard" not in "\n".join(result.outlines)


def test_the_guard_still_catches_a_leak_under_real_xdist_worker_execution(pytester):
    """Design decision #2 (controller-only), proven rather than only
    documented: under a real `-n 1 --dist loadfile` xdist run, the offending
    test executes inside a WORKER process, never the controller. This must
    still fail the session -- the controller's own watcher observes the
    same shared filesystem every worker writes to, so it does not need to
    run inside the worker at all to see what the worker leaves behind.

    Skips (naming why) rather than failing outright if `pytest-xdist` is not
    importable in the pytester child's own environment -- a genuine
    could-not-check, not a false pass or a defect in the guard.
    """
    tests_dir = _make_guarded_tree(
        pytester,
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    (root / '_leaked_under_xdist_1228').mkdir()\n"
        "    time.sleep(0.1)\n"
        "    assert True\n",
    )
    result = _run(pytester, "-n", "1", "--dist", "loadfile", str(tests_dir))
    combined = "\n".join(result.outlines + result.errlines)
    if "unrecognized arguments" in combined or "no such option" in combined.lower():
        pytest.skip(
            "pytest-xdist is not available to this pytester child -- this "
            "measures nothing about the controller-only design decision, "
            "not a defect in it: " + combined
        )
    assert result.ret != 0, combined
    result.stdout.fnmatch_lines(["*root_scratch_guard*_leaked_under_xdist_1228*"])


# ------------------------------------------------------- an auditor finding on this round


def test_could_not_watch_is_true_when_every_read_of_the_root_fails(monkeypatch):
    """A root that raises OSError on construction AND on every poll -- the
    watcher NEVER once managed to read it -- must report `could_not_watch()`
    True. Without this, `offenders()` renders identically empty whether the
    run was genuinely clean or the watcher was blind the whole time, which
    is the exact absence-vs-absence defect CLAUDE.md names, one level down
    inside the module meant to catch it (an auditor finding on this round).
    """

    class _AlwaysBroken:
        def iterdir(self):
            raise OSError("pretend the root is unreadable")

    watcher = root_scratch_guard._SessionRootWatcher(_AlwaysBroken())
    # One manual poll iteration, standing in for what the background
    # thread would do -- exercised directly rather than raced against a
    # real thread, for a deterministic unit test.
    watcher._poll_once_for_test()
    assert watcher.could_not_watch() is True


def test_could_not_watch_is_false_once_any_read_succeeds(tmp_path):
    """Must-not-fire control: a root that answers at least once -- even if
    every check afterward is on a genuinely empty, unchanged directory --
    must never report `could_not_watch()`. This is the ordinary, everyday
    case the check above must not accidentally start flagging."""
    watcher = root_scratch_guard._SessionRootWatcher(tmp_path)
    assert watcher.could_not_watch() is False
