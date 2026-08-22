"""Root conftest for `tests/` -- see #430.

Registers two pytest plugins for the whole suite:

- `pytester`, pytest's own built-in fixture for driving a real, isolated
  pytest subprocess. It ships with pytest but is not enabled by default
  (it is not free), so it has to be turned on here, at the top-level
  conftest, once. `tests/test_must_assert_on_430.py` is the only user.
- `must_assert_plugin`, the `must_assert_on` marker and the session-level
  check that holds it to account -- see that module's docstring for what it
  does and why it lives on the test rather than in the CI workflow.
"""

pytest_plugins = ["pytester", "must_assert_plugin"]
