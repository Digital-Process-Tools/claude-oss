"""`tests/duration_report_plugin.py` end to end -- #910.

Drives a real, separate `pytest` subprocess over a trivial stub test placed
INSIDE `tests/` (not at the repository root, unlike `tests/test_durations_
recorded_881.py`'s own stub) so pytest's normal conftest discovery picks up
`tests/conftest.py` on the way down and registers `duration_report_plugin`
for that subprocess exactly the way it is registered for the real suite --
proving the wiring, not just the pure functions `tests/test_test_durations_
910.py` already covers directly.

Every case passes `--duration-baseline-path` pointing at a throwaway
`tmp_path`, never at the real `tests/duration-baseline.json` -- this file
must never read or write the repository's own recorded baseline as a side
effect of running the suite.
"""

import shutil
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))
import spawn_guard  # noqa: E402

_STUB_TEST_BODY = "def test_stub_trivial():\n    assert True\n"

# Minimal addopts: no coverage flags (irrelevant to a one-file stub run and
# slower to compute), no --durations (the plugin reads terminalreporter.stats
# directly and does not need pytest's own printed summary at all -- proving
# that decoupling is part of what this file is for).
_STUB_ADDOPTS = "-rs"


def _run_stub_test(extra_args, keep=None):
    """Run one trivial, always-passing test, placed inside `tests/` so
    `tests/conftest.py` -- and with it `duration_report_plugin` -- is on the
    real collection path, in a fresh subprocess, and return everything it
    printed.

    `keep`, if given, is a callable invoked with the stub directory before it
    is removed, so a case can inspect files the plugin wrote (a recorded
    baseline) before cleanup.
    """
    stub_dir = REPO_ROOT / "tests" / ("_durprobe_910_" + uuid.uuid4().hex[:8])
    stub_dir.mkdir()
    stub_path = stub_dir / "test_stub.py"
    try:
        stub_path.write_text(_STUB_TEST_BODY, encoding="utf-8")
        args = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=" + _STUB_ADDOPTS,
        ] + extra_args + [str(stub_path)]
        result = spawn_guard.run(
            args,
            subject="whether duration_report_plugin's terminal summary appears for this stub run",
            timeout=60,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        if keep is not None:
            keep(stub_dir)
        return output
    finally:
        shutil.rmtree(stub_dir, ignore_errors=True)


def test_a_normal_run_with_no_baseline_reports_no_baseline_and_the_real_numbers(tmp_path):
    baseline_path = tmp_path / "nope.json"
    output = _run_stub_test(["--duration-baseline-path", str(baseline_path)])
    assert "test-durations: no-baseline" in output, output
    assert "test_stub_trivial" in output, output


def test_a_collect_only_run_reports_could_not_measure(tmp_path):
    """Must-fire pair to the case above: nothing executed, so nothing was
    measured -- the third state, not a silent absence rendering like a clean
    suite. This is the issue's own acceptance criterion, driven end to end
    rather than only asserted on the pure function."""
    baseline_path = tmp_path / "nope.json"
    output = _run_stub_test(["--collect-only", "--duration-baseline-path", str(baseline_path)])
    assert "test-durations: could-not-measure" in output, output


def test_a_run_with_an_existing_baseline_reports_measured_and_compares_against_it(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        '{"slowest_share": 0.5, "slowest_nodeid": "tests/x.py::y", "total_seconds": 2.0}',
        encoding="utf-8",
    )
    output = _run_stub_test(["--duration-baseline-path", str(baseline_path)])
    assert "test-durations: measured" in output, output
    assert "tests/x.py::y" in output, output


def test_record_duration_baseline_writes_a_new_baseline_file(tmp_path):
    """Must-fire pair proving `--record-duration-baseline` actually writes,
    rather than merely accepting the flag and doing nothing -- the silent-
    absence shape this whole issue is about, one flag over."""
    baseline_path = tmp_path / "baseline.json"
    assert not baseline_path.exists()
    output = _run_stub_test(
        ["--duration-baseline-path", str(baseline_path), "--record-duration-baseline"]
    )
    assert "recorded new baseline" in output, output
    assert baseline_path.exists(), output
    payload = baseline_path.read_text(encoding="utf-8")
    assert "test_stub_trivial" in payload or "test_stub.py" in payload, payload


def test_a_run_with_no_record_flag_never_writes_the_baseline(tmp_path):
    """Must-not-fire pair to the case above: recording is opt-in per the
    issue's own "measure, report, and stop" framing -- an ordinary run must
    never write the file merely because it computed a shape."""
    baseline_path = tmp_path / "baseline.json"
    _run_stub_test(["--duration-baseline-path", str(baseline_path)])
    assert not baseline_path.exists()
