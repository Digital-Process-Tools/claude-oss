"""The `--durations` reader -- #910: report a hot test's share of the suite,
before somebody notices it by hand.

Registered as a pytest plugin via `pytest_plugins` in the top-level
`tests/conftest.py`, so `pytest_terminal_summary` below runs at the end of
every invocation of this suite -- CI's or a contributor's own local partial
run -- with zero extra CI wiring. This mirrors `tests/must_assert_plugin.py`'s
own registration for the same reason: the earliest possible signal is a local
run on a contributor's own machine, not only a named CI step somebody has to
remember to add.

The actual computation -- reading `terminalreporter.stats`, computing a
share, loading/writing a baseline, formatting the three states -- lives in
`scripts/test_durations.py`, imported here rather than reimplemented, so
there is exactly one place that logic can go wrong. This file is the pytest
wiring around it: `pytest_addoption` for the two flags, `pytest_terminal_
summary` for the hook pytest actually calls.

`tests/test_test_durations_910.py` drives `scripts/test_durations.py`'s pure
functions directly (no subprocess). `tests/test_duration_report_plugin_910.py`
drives this file end to end, in a real subprocess pytest invocation over a
stub test placed inside `tests/` so it inherits this repository's own
`tests/conftest.py` -- the same reasoning `tests/test_durations_recorded_881.
py`'s own subprocess probe already documents for why a real run is needed
rather than a string search over a file.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import test_durations  # noqa: E402


def pytest_addoption(parser):
    group = parser.getgroup("test-durations", "#910: report the suite's hot tests")
    group.addoption(
        "--record-duration-baseline",
        action="store_true",
        default=False,
        help="#910: after reporting, also record this session's numbers as "
        "the new baseline (tests/duration-baseline.json by default) -- a "
        "deliberate act, never done on an ordinary run.",
    )
    group.addoption(
        "--duration-baseline-path",
        action="store",
        default=None,
        help="#910: read/write the baseline at this path instead of "
        "tests/duration-baseline.json. Mainly for this plugin's own test "
        "suite, so it never touches the real repository baseline file.",
    )


def _baseline_path(config):
    override = config.getoption("--duration-baseline-path")
    return Path(override) if override else test_durations.DEFAULT_BASELINE_PATH


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    path = _baseline_path(config)
    durations = test_durations.collect_durations(terminalreporter)
    shape = test_durations.compute_shape(durations)
    baseline, baseline_error = test_durations.load_baseline(path)
    state = test_durations.report_state(shape, baseline, baseline_error)
    for line in test_durations.format_report(shape, baseline, baseline_error, state):
        terminalreporter.write_line(line)
    if config.getoption("--record-duration-baseline") and shape is not None:
        payload = test_durations.write_baseline(path, shape)
        terminalreporter.write_line(
            "test-durations: recorded new baseline at {} (slowest share {:.1%})".format(
                path, payload["slowest_share"]
            )
        )
