"""`tests/root_scratch_guard.py` extended to site 3 -- #1250.

#1228's own generalisation (`tests/test_root_scratch_guard_1228.py`) watches
only the repository root's direct children, and its own module docstring
names the reason: the harder case, "any path inside the checkout that is
shared between concurrent workers and written, created or removed during a
run", was declined under time pressure and filed as this issue's own
follow-up. The one concrete instance of that harder case named there is
site 3 -- `skills/manager/phases/`, a shared TRACKED SOURCE directory, not a
scratch/root path -- and it is not hypothetical: `tests/test_skill_phase_
split.py`'s own `test_unreferenced_is_reported_rather_than_assumed` and
`test_a_phase_file_on_disk_that_nobody_budgeted_is_reported` each plant and
remove a transient control file directly inside that real, live directory
(`unreferenced-control.md`, `undeclared-control.md`), which is exactly what
`scripts/manager_docs.py`'s `documents()`/`text()` glob over concurrently
from every other worker. `trap.d/1228.site3-race-recurred-on-release-
commit-dd2353e.md` records this actually reddening a release commit's own
CI run with the FileNotFoundError signature #1228's thread predicted.

This module extends the same read-only, controller-only watcher mechanism
to that one concrete tracked path, with its own small allowlist for the two
known self-test control filenames above -- mirroring the root watcher's own
`_watcher_selftest_*`/`pytest-cache-files-*` allowlist precedent exactly.
It does not attempt the general "any shared path" invariant (still out of
scope, per the issue's own text), and it does not change `manager_docs.py`
itself: this is the detector `root_scratch_guard.py`'s own docstring
promised as the follow-up, not a fix to the underlying race.

Same harness shape as `test_root_scratch_guard_1228.py`: `pytester` drives a
real, separate pytest subprocess over a throwaway tree containing the real,
unmodified `root_scratch_guard.py` plugin, with `skills/manager/phases/`
recreated under the throwaway root so `_TRACKED_PHASES_REL` resolves inside
it exactly the way it resolves under the real repository.
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
    """Same layout as #1228's own harness, plus a real `skills/manager/
    phases/` directory under the throwaway root -- one already-budgeted
    stand-in file inside it, so the watcher's baseline is non-empty exactly
    like the real repository's own is."""
    tests_dir = pytester.path / "tests"
    tests_dir.mkdir()
    (tests_dir / "root_scratch_guard.py").write_text(
        _root_scratch_guard_source(), encoding="utf-8"
    )
    (tests_dir / "conftest.py").write_text(
        "pytest_plugins = ['root_scratch_guard']\n", encoding="utf-8"
    )
    (tests_dir / "test_probe.py").write_text(probe_body, encoding="utf-8")
    phases_dir = pytester.path / "skills" / "manager" / "phases"
    phases_dir.mkdir(parents=True)
    (phases_dir / "existing.md").write_text("already here\n", encoding="utf-8")
    return tests_dir


def test_an_unaccounted_write_under_the_tracked_phases_dir_fails_the_session(pytester):
    """Must-fire case: a test writes an unrecognised file directly into
    `skills/manager/phases/` and never removes it. This is site 3's own
    "litter left behind" shape -- the session must come back red, naming
    the file, exactly as the root watcher already does for site 1."""
    tests_dir = _make_guarded_tree(
        pytester,
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    (root / 'skills' / 'manager' / 'phases' / '_leaked_1250.md')"
        ".write_text('x')\n"
        "    time.sleep(0.1)\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret != 0, "\n".join(result.outlines + result.errlines)
    result.stdout.fnmatch_lines(["*root_scratch_guard*_leaked_1250.md*"])


def test_a_transient_unaccounted_write_under_phases_still_fails_the_session(pytester):
    """Must-fire, the harder half: created AND removed within the run --
    the same transient shape site 3's own real race takes (a control file
    that appears and disappears while another worker reads the directory).
    The watcher polls continuously, so a before/after snapshot missing this
    would silently defeat the whole point of extending it here."""
    tests_dir = _make_guarded_tree(
        pytester,
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    p = root / 'skills' / 'manager' / 'phases' / '_transient_1250.md'\n"
        "    p.write_text('x')\n"
        "    time.sleep(0.1)\n"
        "    p.unlink()\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret != 0, "\n".join(result.outlines + result.errlines)
    result.stdout.fnmatch_lines(["*root_scratch_guard*_transient_1250.md*"])


def test_an_ordinary_run_touching_nothing_under_phases_does_not_fail(pytester):
    """Must-not-fire control: an ordinary test that never touches
    `skills/manager/phases/` at all must leave the session exactly as
    green as with no guard registered."""
    tests_dir = _make_guarded_tree(pytester, "def test_it():\n    assert 1 + 1 == 2\n")
    result = _run(pytester, str(tests_dir))
    assert result.ret == 0, "\n".join(result.outlines + result.errlines)
    assert "root_scratch_guard" not in "\n".join(result.outlines)


def test_the_two_known_self_test_control_files_do_not_fail_the_session(pytester):
    """Must-not-fire control, paired with the two must-fire cases above:
    `test_skill_phase_split.py`'s own two legitimate, self-cleaning control
    files (`unreferenced-control.md`, `undeclared-control.md`) must never
    be reported as an unexpected site-3 entry -- the guard's whole point is
    catching something ELSE happening in that directory, not this
    repository's own already-understood self-test fixtures. Without this
    allowlist entry, every ordinary run of the real suite would flag its
    own ordinary test twice, deterministically -- the exact false-positive
    shape #1228's own `_watcher_selftest_*` allowlist entry was written to
    avoid at site 1."""
    tests_dir = _make_guarded_tree(
        pytester,
        "import time\n"
        "from pathlib import Path\n"
        "def test_it():\n"
        "    root = Path(__file__).resolve().parent.parent\n"
        "    phases = root / 'skills' / 'manager' / 'phases'\n"
        "    for name in ('unreferenced-control.md', 'undeclared-control.md'):\n"
        "        p = phases / name\n"
        "        p.write_text('x')\n"
        "        time.sleep(0.05)\n"
        "        p.unlink()\n"
        "    assert True\n",
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret == 0, "\n".join(result.outlines + result.errlines)
    assert "root_scratch_guard" not in "\n".join(result.outlines)


def test_a_tree_with_no_phases_directory_at_all_does_not_fail(pytester):
    """Must-not-fire control for the design decision `pytest_sessionstart`
    states: a rootdir that simply has no `skills/manager/phases/` at all
    -- every #1228-era harness that never recreates it, and any repository
    that has not adopted this convention -- must never be reported as
    `could_not_watch()` (which would read this session as red for a
    directory that was never supposed to be watched)."""
    tests_dir = pytester.path / "tests"
    tests_dir.mkdir()
    (tests_dir / "root_scratch_guard.py").write_text(
        _root_scratch_guard_source(), encoding="utf-8"
    )
    (tests_dir / "conftest.py").write_text(
        "pytest_plugins = ['root_scratch_guard']\n", encoding="utf-8"
    )
    (tests_dir / "test_probe.py").write_text(
        "def test_it():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    result = _run(pytester, str(tests_dir))
    assert result.ret == 0, "\n".join(result.outlines + result.errlines)
    assert "root_scratch_guard" not in "\n".join(result.outlines)


def test_is_allowed_phase_control_accepts_only_the_two_known_names():
    """Fast, deterministic unit check for the allowlist rule itself -- no
    subprocess, no timing dependency."""
    assert root_scratch_guard._is_allowed_phase_control("unreferenced-control.md")
    assert root_scratch_guard._is_allowed_phase_control("undeclared-control.md")
    assert not root_scratch_guard._is_allowed_phase_control("dispatch.md")
    assert not root_scratch_guard._is_allowed_phase_control("_leaked_1250.md")


def test_tracked_path_watcher_could_not_watch_when_every_read_fails():
    """Same absence-vs-absence control #1228 already pins for the root
    watcher (`test_could_not_watch_is_true_when_every_read_of_the_root_
    fails`), re-proven for the new tracked-path watcher rather than
    assumed to hold just because it shares the base class."""

    class _AlwaysBroken:
        def iterdir(self):
            raise OSError("pretend the tracked path is unreadable")

    watcher = root_scratch_guard._TrackedPathWatcher(_AlwaysBroken())
    watcher._poll_once_for_test()
    assert watcher.could_not_watch() is True


def test_tracked_path_watcher_could_not_watch_is_false_once_any_read_succeeds(
    tmp_path,
):
    """Must-not-fire control paired with the check above."""
    watcher = root_scratch_guard._TrackedPathWatcher(tmp_path)
    assert watcher.could_not_watch() is False
