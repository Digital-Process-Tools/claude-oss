---
title: "bin/oss-workspace: it always opens on /oss:run now, and its job is priming what /oss:run reads"
description: "The launcher no longer picks the opening command (#1392) -- prompt is a fixed /oss:run. Its remaining job is the currency check, symlink repoint, census, identity check, and handing each reading forward via env relays that currently die at exec, unconsumed."
match: (^|/)bin/oss-workspace$
---

**What this file is for.** Open a maintainer session over the repository the caller is standing in.
Before #1392 it also chose which command that session opened on (`/oss:setup` / `/oss:doctor` /
`/oss:tick`); it no longer does -- `prompt="/oss:run"` is fixed, and `/oss:run` itself now makes
that decision from inside the session (`commands/run.md`, `scripts/next_action.py`, which produces
a ranked candidate list rather than a single verdict). **Do not add a route back into this file for
"if X, open on Y instead"** -- that logic now lives one layer in, where `next_action.rank()` can see
the whole ranked candidate list rather than one launcher-time reading.

**What still runs here, and why:** the plugin-currency check and its own repoint of
`~/.local/bin/oss-workspace` if stale, the MCP census, the identity/registration check for
`oss-channel`, and the channel-arm decision (#1307 -- whether an installed plugin already provides
an in-scope consumer). Each is still computed synchronously before `exec claude`, for the same
reason it always was: a maintainer session should not spend its first turn re-deriving something
the launcher already measured.

**`/reload-plugins` is still not needed after a pre-exec update.** The update runs before `exec
claude`, so the session that starts has never held the old registry -- there is no stale copy to
reload out of.

**Four env relays hand each computed reading forward, and are unset again right before `exec`:**
`OSS_WORKSPACE_MCP_CHECKED` (#629), `OSS_WORKSPACE_CENSUS_CHECKED` (#810),
`OSS_WORKSPACE_MCP_LIST_CHECKED` (#1372), `OSS_WORKSPACE_CHANNEL_ARM_TARGET` (#1307). **Since #1392
removed this file's own synchronous `doctor.sh` call, none of the four currently has a live
consumer** -- the one thing that read them was the launcher's own diagnostic, which now runs from
inside the session instead (`/oss:run` step 1). They are still computed and still unset, unchanged,
pending a decision on whether to thread them into `/oss:run`'s own first `doctor.sh` call or retire
them (#1432): treat a relay here as dead plumbing until that lands, not as something a session
downstream can rely on.

Routed via /oss:curate from `trap.d/1392.env-relays-now-consumerless.md`; the sibling docs
staleness (`docs/open-the-workspace.md`, `docs/install.md`) this same launcher change left behind
is tracked separately (#1439), not in this file.
