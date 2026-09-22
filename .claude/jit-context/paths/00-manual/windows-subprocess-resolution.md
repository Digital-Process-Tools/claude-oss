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
- **Never probe a low-numbered fd to learn whether a caller set something up; have the caller say
  so.** `main()` used to open `os.fdopen(3, "w")` unconditionally on every call to detect a
  launcher-supplied progress channel, letting `OSError` mean "no caller opened one". Under an
  execnet worker on Windows CI, fd 3 is one of execnet's own live descriptors, and `fdopen` on it
  blocks forever rather than raising -- a hang, not a clean no-op (#1673). Fixed by making the
  channel explicit: the caller passes `--progress-fd 3`, and `main()` touches no descriptor at all
  when the flag is absent.
- **A fix that closes the hang does not by itself confirm the feature streams (#1648).** The
  opt-in flag above stops `main()` from blocking, but whether a subprocess launched from
  `bin/oss-workspace`'s `exec 3>&1` actually reaches the real terminal through the MSYS/`python.exe`
  boundary on Windows was never directly observed -- Win32 `CreateProcess` only propagates fds 0-2
  by default, and whether MSYS's own fd-passing convention reaches a plain hosted `python.exe` is
  reasoned, not measured, same as this file's own standing instruction. Settle it with a real
  Windows CI run of the `plugin` branch checking whether streamed lines land in the log, not by
  reading the source and predicting.
- **A failed fd-3 open and a debounced-nothing run render identically (#1654).** `plugin_update.py`
  (`update()`'s caller) does `os.fdopen(progress_fd, "w", closefd=False)` inside a `try`/`except`
  that sets `progress_writer = None` on any failure and proceeds with `progress=None` -- the same
  state a healthy run reaches when there is simply nothing to report yet. "The descriptor could not
  be opened" and "the run streamed nothing because there was nothing to stream" are two different
  facts sharing one code path. No CI leg exercises this arm (only the `shell` job touches
  `bin/oss-workspace`, and it only shellchecks). Not fixed by writing this rule -- the third state a
  caller would need (`could-not-open-progress-fd` distinct from `nothing-to-report`) does not exist
  yet; this is a known, unclosed gap, not settled knowledge.
