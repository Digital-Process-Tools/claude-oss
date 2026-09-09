---
title: "Probing the filesystem in scripts/: never let a library decide the classification"
description: "Path.exists swallows errnos and varies by version; rglob swallows PermissionError while walking and yields nothing; is_dir returns True for a directory that cannot be entered. Each destroys the answer a guard beside it was written to read."
match: (^|/)scripts/[^/]+\.py$
---

**This fires on every `scripts/*.py`, deliberately.** Narrowing it to the four modules where these were found would stay silent for the fifth, and every one of these was found in a module nobody expected it in.

Every checker here has three states — `ok`, a finding, and `skipped`/`unknown`. **A check that never
ran and a check that found nothing must not render identically.**

- **Do not ask the filesystem a second question to explain why the first one failed.** The exception
  in hand answers which arm runs: `FileNotFoundError` is the absence arm, anything else is
  unreadable. `Path.exists()` swallows a short list of errnos, re-raises the rest, and the list
  varies by version — `release_delta._read_config` called it from inside its own `except` and killed
  the release gate with a traceback.
- **Splitting the exception is not the whole fix if only one arm has a sentence.**
  `oss_state.check_plugin_root` had the right arms and one `why` string written for the absence case,
  telling a maintainer whose snapshot exists and cannot be read (`chmod 0`, `PermissionError`,
  errno 13) to run `--record-plugin-root`, which cannot help them. Each arm names its own remedy.
- **An absence arm must ask whether the absence is real.** Windows folds an over-`MAX_PATH` name onto
  `FileNotFoundError`, errno 2, `winerror` None — indistinguishable from a genuine miss, which is how
  `lane_setup.worktree_occupancy` and `doctor._dir_state` printed a confident absence for a path
  nothing had looked at. Ask a different question the version cannot swallow: `os.stat` the subject's
  own deepest lookable ancestor, then `os.listdir` it — enumeration answers regardless of path length.
- **`Path.is_dir()` returns True for a directory that exists and cannot be entered**, so
  `if not d.is_dir(): return []` passes and the `iterdir()` under it raises `PermissionError`.
- **`Path.rglob` swallows `PermissionError` while walking** and yields nothing for that subtree, so an
  `except OSError` around it can never fire for the case it was written for. A walk that must report
  has to be `os.walk(onerror=...)`; no argument to `rglob` makes it speak.
- **Do not catch the raise into `[]`** when `[]` already means something. `scaffold._workflow_scan`
  returns `(files, unreadable)` because "no workflows here" and "could not read the tree" are two
  states, and collapsing them wrote the owned trio into a repo nobody had looked at.

- **List-then-read is a TOCTOU, and it is the shape most of these functions have.**
  `skill_phases._undeclared_rows()` listed a directory (`manager_docs.documents(root)`) and then
  read each listed path in a separate call. Anything deleting a file in that window -- here a
  sibling xdist worker's own legitimate cleanup in the same shared, tracked directory -- makes the
  second call raise uncaught. Confirmed against the real function with a monkeypatch that deletes
  between the list and the read; no timing or threading needed, it is a plain two-step race (#1293).
  The brief's own hypothesis (xdist collection timing) was plausible and wrong, and ruling it out
  explicitly was worth the time.
- **`except FileNotFoundError` alone does not close that race on Windows**, where a delete racing an
  open more commonly surfaces as `PermissionError` (WinError 5/32, delete-pending or a sharing
  violation). Catch both, or use an `OSError` arm that reports rather than silently continuing.
- **Grep for the second copy once the first is confirmed.** That same `_undeclared_rows` body is
  copy-pasted verbatim into `developer_phases.py`, scanning a different directory. Same bug, fixed
  in the same commit even though nothing writes concurrently there today.
