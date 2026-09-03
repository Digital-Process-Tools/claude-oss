---
title: "A running session's PATH is not the PATH a maintainer's own shell has"
description: "Measured on macOS: a clean login shell has no dpt-plugins entry at all, so the symlink instruction is not a stopgap waiting to be dropped."
keywords: oss-workspace launcher, launcher symlink, login shell path, dpt-plugins path
---

**#526 asked whether the marketplace cache directory is reliably on a maintainer's own `PATH`**, which would make the `ln -sf` step in `docs/install.md` redundant. It is not, and this is the measured answer.

**A hit inside the plugin's own `bin/` proves nothing** (#617) about whether a command a maintainer is told
to run resolves outside a session — which is why `oss_workspace_launcher_state` does not search there.

**Measured directly rather than assumed:**

```bash
env -i HOME="$HOME" TERM=xterm /bin/zsh -i -l -c 'echo $PATH' | tr : '\n' | grep -c dpt-plugins
```

returns `0` on a clean macOS login shell — no `dpt-plugins` entry at all, plugin cache or otherwise.
So the `ln -sf` step in the README is **not** a stopgap waiting to be dropped: there is nothing on a
plain shell's `PATH` to shadow it.

- **Scope:** macOS, marketplace install. **Not observed:** Linux, Windows, or a project- or
  local-scope install. Do not restate this as a universal claim.
- **A launcher symlink is pinned to whatever version was current when it was made**, so
  `PINNED ELSEWHERE` is the expected reading after any release, not a fault.
