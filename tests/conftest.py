"""Root conftest for `tests/` -- see #430.

Registers pytest plugins for the whole suite:

- `pytester`, pytest's own built-in fixture for driving a real, isolated
  pytest subprocess. It ships with pytest but is not enabled by default
  (it is not free), so it has to be turned on here, at the top-level
  conftest, once. `tests/test_must_assert_on_430.py` is the only user.
- `must_assert_plugin`, the `must_assert_on` marker and the session-level
  check that holds it to account -- see that module's docstring for what it
  does and why it lives on the test rather than in the CI workflow.
- `duration_report_plugin`, the `--durations` reader -- #910. See that
  module's docstring for the three states it reports (measured /
  no-baseline / could-not-measure) and why it reads
  `terminalreporter.stats` rather than reparsing pytest's own printed text.
"""

pytest_plugins = ["pytester", "must_assert_plugin", "duration_report_plugin"]
