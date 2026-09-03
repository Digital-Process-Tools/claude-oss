---
title: "plugin_update.py on Windows: PATHEXT resolution and per-test receipt isolation"
description: "shutil.which() resolves claude to claude.cmd via PATHEXT; subprocess.run(shell=False) does not. receipt_dir() checks LOCALAPPDATA before HOME, so HOME isolation is a silent no-op on Windows."
match: (^|/)scripts/plugin_update\.py$
---

Windows CI is the only thing that exercises this and it cannot be reproduced on macOS or Linux.
**Measure the mechanism; do not reason from the source and push.**

- **`shutil.which()` performs the `PATHEXT` search and `subprocess.run(..., shell=False)` does not.**
  Three call sites asked `which()` for the answer and then handed `run()` the bare, unresolved name
  anyway. Pass the resolved path.
- **`receipt_dir()` checks `LOCALAPPDATA` before `HOME` on Windows**, so a test isolating `HOME` /
  `USERPROFILE` is a silent no-op there and every subprocess shares one real, machine-scoped receipt
  file across tests within the same CI job. Pin `LOCALAPPDATA` and `XDG_CACHE_HOME` per test.
- **A fix for one Windows-only mechanism can break a second, unrelated Windows-only mechanism.** The
  reasoned round over-fired — `argv` always resolving to `/oss:doctor` instead of the expected prompt
  — and passed two spawned agents' review before CI showed otherwise. The round that measured the
  mechanism shipped clean on the first try.
- **The must-not-fire controls in `tests/test_workspace_auto_update_753.py` are what made the
  over-fire visible.** Three of the six failures were those controls. Keep them.
