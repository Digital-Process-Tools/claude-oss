"""`scripts/test_durations.py` -- #910: report a hot test's share of the suite,
before somebody notices it by hand.

`--durations=25` (#881) already prints the numbers; nothing reads them. This
module is the read: it turns pytest's own resolved per-test timings into a
share of the whole suite (a ratio, since an absolute second count says more
about the runner than about the test -- the issue's own reasoning), compares
that share against a recorded baseline, and reports one of three states --
`measured`, `no-baseline`, `could-not-measure` -- naming the third explicitly
rather than letting a step that could not parse anything render identically
to a suite with no hot test at all, which is the defect class this whole
project is named after, reappearing inside the detector meant to catch it.

These are unit tests over the pure functions in `scripts/test_durations.py`
-- no subprocess, no `pytester`. `tests/test_duration_report_plugin_910.py`
is the companion file driving the real pytest-plugin hook end to end, the
same split `tests/test_must_assert_on_430.py` (subprocess) and its plugin
under test already use.

Every "must not fire" case here (`could-not-measure` on nothing collected,
`no-baseline` on an absent file) is paired with a "must fire" case
(`measured` on real durations, a baseline actually loaded) per CLAUDE.md's
own rule -- an assertion that a state does NOT apply also passes if the
function is simply broken and never returns anything meaningful.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import test_durations  # noqa: E402


# --------------------------------------------------------------- collect_durations


class _FakeReport(object):
    def __init__(self, nodeid, when, duration):
        self.nodeid = nodeid
        self.when = when
        self.duration = duration


def _fake_terminalreporter(stats):
    class _Fake(object):
        pass

    tr = _Fake()
    tr.stats = stats
    return tr


def test_collect_durations_reads_only_call_phase_reports_sorted_longest_first():
    stats = {
        "passed": [
            _FakeReport("tests/test_a.py::test_1", "setup", 0.001),
            _FakeReport("tests/test_a.py::test_1", "call", 1.5),
            _FakeReport("tests/test_b.py::test_2", "call", 9.0),
        ],
        "failed": [
            _FakeReport("tests/test_c.py::test_3", "call", 4.0),
        ],
    }
    tr = _fake_terminalreporter(stats)
    result = test_durations.collect_durations(tr)
    assert result == [
        ("tests/test_b.py::test_2", 9.0),
        ("tests/test_c.py::test_3", 4.0),
        ("tests/test_a.py::test_1", 1.5),
    ]


def test_collect_durations_on_a_session_with_no_call_phase_reports_is_empty():
    """Must-fire pair to the case above: a collect-only session (or one where
    nothing ran) reports setup/teardown phases at most, never `call`, and this
    must come back empty rather than inventing a duration for a test that
    never executed."""
    stats = {
        "deselected": [
            _FakeReport("tests/test_a.py::test_1", "collect", 0.0),
        ],
    }
    tr = _fake_terminalreporter(stats)
    assert test_durations.collect_durations(tr) == []


# ------------------------------------------------------------------- compute_shape


def test_compute_shape_on_real_durations_reports_total_and_slowest_share():
    durations = [
        ("tests/test_b.py::test_2", 9.0),
        ("tests/test_c.py::test_3", 4.0),
        ("tests/test_a.py::test_1", 1.5),
    ]
    shape = test_durations.compute_shape(durations, top_n=2)
    assert shape is not None
    assert shape["count"] == 3
    assert shape["total_seconds"] == 14.5
    assert shape["slowest_nodeid"] == "tests/test_b.py::test_2"
    assert shape["slowest_seconds"] == 9.0
    assert shape["slowest_share"] == 9.0 / 14.5
    assert shape["top"] == durations[:2]


def test_compute_shape_on_no_durations_is_none_not_a_report_of_nothing_wrong():
    """Must-not-fire pair: an empty measurement produces no shape at all --
    the caller decides that means could-not-measure -- rather than a shape
    claiming a 0% share, which would print exactly like a healthy suite."""
    assert test_durations.compute_shape([]) is None


def test_compute_shape_on_all_zero_durations_is_also_none():
    """A total of zero seconds cannot support a share (division by zero), and
    it is itself evidence nothing real was measured -- not a healthy 0%."""
    assert test_durations.compute_shape([("tests/test_a.py::test_1", 0.0)]) is None


# -------------------------------------------------------------------- load_baseline


def test_load_baseline_absent_file_reports_absent_not_an_error(tmp_path):
    baseline, error = test_durations.load_baseline(tmp_path / "nope.json")
    assert baseline is None
    assert error == "absent"


def test_load_baseline_present_and_valid(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"slowest_share": 0.21, "slowest_nodeid": "tests/x.py::y", "total_seconds": 10.0}),
        encoding="utf-8",
    )
    baseline, error = test_durations.load_baseline(path)
    assert error is None
    assert baseline["slowest_share"] == 0.21
    assert baseline["slowest_nodeid"] == "tests/x.py::y"


def test_load_baseline_unparseable_json(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text("{not json", encoding="utf-8")
    baseline, error = test_durations.load_baseline(path)
    assert baseline is None
    assert error is not None
    assert error != "absent"


def test_load_baseline_missing_required_key_is_malformed_not_absent(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"total_seconds": 10.0}), encoding="utf-8")
    baseline, error = test_durations.load_baseline(path)
    assert baseline is None
    assert error is not None
    assert error != "absent"


class _RaisingExistsPath(object):
    """A stand-in for `pathlib.Path` whose `.exists()` raises `OSError` --
    reproducing the failure `Path.exists()` can genuinely surface (an
    over-long path component, a permission-denied ancestor directory) and
    which CPython's own `exists()` only swallows a version-dependent subset
    of. This repository has already paid for the unguarded form of this
    exact call twice: `scripts/release_delta.py` (killed the release gate
    with a traceback) and `scripts/doctor_check_worktree_reap_permission.py`
    (now wraps it in `try/except OSError`)."""

    def exists(self):
        raise OSError(13, "Permission denied")


def test_load_baseline_an_exists_check_that_raises_os_error_is_unreadable_not_a_crash():
    """Reviewer finding (#910): an unguarded `path.exists()` inside
    `load_baseline` would let a real `OSError` propagate out of this
    function and, from there, out of `pytest_terminal_summary` itself --
    aborting the hook with an unrelated internal-error traceback instead of
    landing in the one state (`could-not-measure`) this whole module exists
    to make explicit. Must land as a named, non-absent error instead."""
    baseline, error = test_durations.load_baseline(_RaisingExistsPath())
    assert baseline is None
    assert error is not None
    assert error != "absent"


# -------------------------------------------------------------------- write_baseline


def test_write_baseline_round_trips_through_load_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    shape = test_durations.compute_shape([("tests/x.py::y", 9.0), ("tests/z.py::w", 1.0)])
    test_durations.write_baseline(path, shape)
    baseline, error = test_durations.load_baseline(path)
    assert error is None
    assert baseline["slowest_nodeid"] == "tests/x.py::y"
    assert abs(baseline["slowest_share"] - 0.9) < 1e-9


# ------------------------------------------------------------------------ report_state


def test_report_state_is_measured_when_shape_and_baseline_both_exist():
    shape = test_durations.compute_shape([("a", 1.0)])
    baseline = {"slowest_share": 0.5, "slowest_nodeid": "a", "total_seconds": 2.0}
    assert test_durations.report_state(shape, baseline, None) == test_durations.MEASURED


def test_report_state_is_no_baseline_when_shape_exists_but_baseline_does_not():
    """Must-fire pair to the measured case: real numbers, nothing to compare
    against -- said out loud as its own state, never silently folded into
    'measured' or 'nothing changed'."""
    shape = test_durations.compute_shape([("a", 1.0)])
    assert test_durations.report_state(shape, None, "absent") == test_durations.NO_BASELINE


def test_report_state_is_could_not_measure_when_shape_is_none_even_with_a_baseline_present():
    """The third state outranks the other two: nothing was measured this run,
    so the fact a baseline file happens to exist does not make this 'measured'
    or 'no-baseline' -- both would print exactly like a healthy comparison
    when nothing was actually observed."""
    baseline = {"slowest_share": 0.5, "slowest_nodeid": "a", "total_seconds": 2.0}
    assert test_durations.report_state(None, baseline, None) == test_durations.COULD_NOT_MEASURE


# ------------------------------------------------------------------------ format_report


def test_format_report_names_the_state_could_not_measure_explicitly():
    lines = test_durations.format_report(None, None, "absent", test_durations.COULD_NOT_MEASURE)
    joined = "\n".join(lines)
    assert "could-not-measure" in joined.lower()


def test_format_report_names_the_state_no_baseline_explicitly():
    shape = test_durations.compute_shape([("tests/x.py::y", 9.0), ("tests/z.py::w", 1.0)])
    lines = test_durations.format_report(shape, None, "absent", test_durations.NO_BASELINE)
    joined = "\n".join(lines)
    assert "no-baseline" in joined.lower()
    assert "tests/x.py::y" in joined


def test_format_report_names_the_state_measured_explicitly():
    """Must-fire pair for the state-naming assertion above: the measured
    state prints its own name too, not just the other two."""
    shape = test_durations.compute_shape([("tests/x.py::y", 9.0), ("tests/z.py::w", 1.0)])
    baseline = {"slowest_share": 0.5, "slowest_nodeid": "tests/x.py::y", "total_seconds": 2.0}
    lines = test_durations.format_report(shape, baseline, None, test_durations.MEASURED)
    joined = "\n".join(lines)
    assert "measured" in joined.lower()
    assert "tests/x.py::y" in joined
