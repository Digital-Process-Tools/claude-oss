---
title: "sub_manager_spawn_guard.py: two known gaps in its own fail-open promise"
description: "The module docstring promises every error resolves to allow, but the import that would need to fail sits outside the try, and the role check reads a repo-global marker rather than the caller's own identity."
match: (^|/)scripts/sub_manager_spawn_guard\.py$
---

The module's own docstring promises "a crash reading the role, an
unreadable payload, an unexpected shape, all resolve to allow." Two
gaps found in the same audit round, both non-blocking today because
nothing has hit either in practice yet:

- **`import agent_role` sits at module scope, outside `decide()`'s own
  try/except.** With `agent_role` missing, the process exits 1 with an
  empty stdout and a bare `ModuleNotFoundError` traceback on stderr --
  not the "allow, could-not-tell" note the docstring's contract
  implies. A fail-open guarantee has to guard its own imports, not
  just its body.
- **The role check reads `agent_role.current_role`, a repo-global
  marker file with a 4-hour TTL**, not the calling agent's own
  identity. It cannot distinguish "a sub-manager is asking" from "a
  sub-manager wrote a marker in this repo within the last four hours"
  -- and the marker clears only on the clean exit path, so a crash,
  kill or context death leaves it live. Exercised: with a stale live
  marker, a *scheduler* (not a sub-manager) spawning a nested
  `oss:sub-manager` was refused with a remedy ("spawn
  `oss:tick-dispatch` or a developer lane instead") that is wrong for
  a scheduler, which legitimately must spawn one.

Both are `misreports`/`misdirects`, not merge-blocking. Read the
current docstring's promise before changing either the import shape or
the role check here -- it is the contract this file is supposed to
keep and currently does not, in both these ways.
