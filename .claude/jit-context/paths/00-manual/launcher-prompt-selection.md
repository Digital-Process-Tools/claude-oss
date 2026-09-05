---
title: "bin/oss-workspace: it chooses the session's first command, and that choice needs a memory"
description: "The launcher's whole output is one prompt. A route that fires on a condition the maintainer cannot clear pins every future launch to it. No /reload-plugins is needed after a pre-exec update."
match: (^|/)bin/oss-workspace$
---

**What this file is for.** Open a maintainer session over the repository the caller is standing in,
and decide the one command that session starts on. Everything else here -- the currency check, the
symlink repoint, the census, the identity check, the diagnostic -- exists to make that one choice
correctly and to report what it could not establish. The working directory is the selection; it
opens THEIR repo, never this plugin's checkout.

**The intended order of the prompt decision**, and each departure from it is a bug:

1. no `.oss.json` -> `/oss:setup`. A tick on guessed values merges into a guessed default branch.
2. the plugin was just updated -> `/oss:doctor`, to diagnose the tree it moved to.
3. otherwise, and once doctor has already run here against this state -> `/oss:tick`.

**`/reload-plugins` is not part of step 2 and adding it is wrong.** The update runs *before*
`exec claude`, so the session that starts has never held the old registry. `/reload-plugins` moves
the registry and does not move text already injected -- in a session zero turns old there is nothing
stale to move. The file's own comment says so: *no stale-copy window to reload or restart out of*.
A fresh session that still resolved the old copy would be a harness bug worth filing, not a launcher
fix.

**A route that fires on a standing condition must carry a receipt (#1064).** There are two routes
into `/oss:doctor` and only the first is bounded: the update route fires once per update, and the
diagnostic route (`VERDICT: usable with gaps` / `not usable`) is stateless and re-fires on every
launch for as long as any actionable WARN survives. One WARN the maintainer cannot clear -- #1062 is
the live instance -- therefore pins every session to the diagnostic and the loop never ticks. The
route can no longer tell *something changed* from *the same thing as last time*, which is this
repository's own defect class pointed at the router.

So: record the verdict word and the plugin version the route fired against, arm it only when one of
those has moved, and never write a receipt from the `could not run` or unrecognised-verdict arms --
a diagnostic that did not answer must not clear a route on no evidence.

**Handing a computed reading forward beats spending a turn on it.** What the route wanted is for the
acting agent to start with what the diagnostic found. The launcher already holds the whole report and
already knows the shape: `OSS_WORKSPACE_MCP_CHECKED` (#629) and `OSS_WORKSPACE_CENSUS_CHECKED` (#810)
relay an answer into a subprocess instead of recomputing it. Relaying the verdict is cheaper than
replacing the prompt, and both env relays are unset before `exec` for the reason named there.
