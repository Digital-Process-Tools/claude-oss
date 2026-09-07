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
- `root_scratch_guard`, the whole-suite generalisation of #1214's own
  root-level scratch-artifact detector -- #1228. See that module's
  docstring for the two design decisions (read-only, controller-only) and
  why it is scoped narrower than the issue's own harder "any shared path"
  ask.

`collect_ignore_glob` excludes the throwaway scratch directories
`tests/test_durations_recorded_881.py` and `tests/test_duration_report_
plugin_910.py` create under `tests/` to drive a real nested pytest
subprocess (#1214). Both remove their own scratch directory in a
`finally:` block, but that only runs on a normal Python-level unwind -- an
abnormal kill (CI job cancellation, OOM) can leave one behind, and a
leftover `test_stub.py` under `tests/` would otherwise be picked up as a
real test by the very next full-suite collection, `testpaths = ["tests"]`
placing no floor under how deep a match can sit.
"""

pytest_plugins = [
    "pytester",
    "must_assert_plugin",
    "duration_report_plugin",
    "root_scratch_guard",
]
collect_ignore_glob = ["_durprobe_*"]
