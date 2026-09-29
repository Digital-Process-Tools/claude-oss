---
title: "A launcher test that builds its own env still reads the real plugin registry"
description: "Since #1768, bin/oss-workspace refuses to open a session when installed_plugins.json has no oss record for the repo, and an absent registry counts as not-installed. A test env with only PATH pinned trips the same refusal for the wrong reason."
match: (^|/)(tests/test_workspace_launcher.*\.py|bin/oss-workspace)$
---

Any test that runs `bin/oss-workspace` end to end without pinning `HOME` reads the runner's real
`~/.claude/plugins/installed_plugins.json`. Since #1768 the launcher refuses to open a session
when that registry has no `oss` record applying to the repo, and an absent registry file counts
as not-installed -- which is the normal state of a CI runner, and also the state of a maintainer's
own machine for every repo except the ones actually enabled there.

**Observed:** `tests/test_workspace_launcher.py::test_it_survives_being_run_through_a_symlink`
built its own env with only `PATH` pinned. Locally it failed with the new "not installed" refusal
(the real registry has `oss` only for other projects); on CI it would have failed the same way for
the opposite reason (no registry at all). 72 other tests in the launcher suites failed at first
too, because the shared `run()` fixture pinned `HOME` to a temp dir but wrote a registry (or none)
without an `oss` record.

**Fix that landed:** `_with_oss_enabled(home)` in `tests/test_workspace_launcher.py` merges a
user-scope `oss@dpt-plugins` record into the fixture registry; the shared `run()` fixture calls it
for every test, and the symlink test now pins `HOME` and calls it too. **A new launcher test that
builds its own env has to do the same, or it is testing the enablement refusal by accident** rather
than whatever the test's own subject is.

Routed via /oss:curate from `trap.d/1768.launcher-tests-read-the-real-plugin-registry.md`.
