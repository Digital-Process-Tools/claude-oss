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

`lane_coupling_real_repo_report` (#1318): a session-scoped memoizing
fixture over `scripts/lane_coupling.py`'s own `lane_coupling_report`,
which walks this repository's real `tests/` tree. Two real-repo checks --
`tests/test_doctor_check_lane_coupling_1244.py`'s doctor-wrapper test and
`tests/test_lane_coupling_allowlist_1244.py`'s direct-module test -- call
it with the IDENTICAL arguments (this repo's own root, its real
`labels.lane_patterns`, its real `labels.lane_coupling_allowlist`), so the
second caller reuses the first caller's already-computed answer instead of
re-walking the same tree. Keyed on every argument that changes the answer,
so a caller whose arguments genuinely differ still gets its own fresh,
independent walk -- this can never paper over two callers disagreeing
about their own inputs, only avoid paying twice for the identical one.
`tests/test_lane_coupling_1234.py`'s own real-repo test passes no
allowlist at all (a deliberately different query, proving a different
thing) and is not routed through this cache for that reason.
"""

pytest_plugins = [
    "pytester",
    "must_assert_plugin",
    "duration_report_plugin",
    "root_scratch_guard",
]

collect_ignore_glob = ["_durprobe_*"]

import json as _json  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def lane_coupling_real_repo_report():
    # Imported, and the real function captured, once at fixture setup --
    # lazily rather than at collection time, so a test file that never
    # requests this fixture never pays for the import. Captured as a
    # closure variable rather than looked up fresh on every call:
    # `test_doctor_check_lane_coupling_1244.py`'s own caller monkeypatches
    # `dclc.lane_coupling.lane_coupling_report` -- the SAME module object
    # this import resolves to, since Python caches modules by name -- and
    # pytest resolves this fixture (a test's declared dependency) before
    # that test's own body runs, so `real_report` below is bound before any
    # test has a chance to monkeypatch anything. A fresh attribute lookup
    # on every call would instead recurse into that monkeypatch on a cache
    # miss; capturing it once here means every cache miss still calls the
    # real, un-stubbed function regardless of what a later test patches.
    import lane_coupling

    real_report = lane_coupling.lane_coupling_report
    cache = {}

    def _get(repo_root, lane_patterns, allowlist=None, test_dir="tests"):
        key = (
            str(repo_root),
            _json.dumps(lane_patterns, sort_keys=True)
            if lane_patterns is not None
            else None,
            tuple(sorted(allowlist)) if allowlist else (),
            test_dir,
        )
        if key not in cache:
            cache[key] = real_report(
                repo_root, lane_patterns, test_dir=test_dir, allowlist=allowlist
            )
        return cache[key]

    return _get
