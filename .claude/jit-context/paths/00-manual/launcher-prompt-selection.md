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

**Three of the four env relays are gone entirely, not merely dead plumbing pending a decision.**
Issue #1474 removed `OSS_WORKSPACE_MCP_CHECKED` (#629), `OSS_WORKSPACE_CENSUS_CHECKED` (#810) and
`OSS_WORKSPACE_CHANNEL_ARM_TARGET` (#1307) from this file outright, closing #1432's
open question by deletion rather than by threading them into `/oss:run`'s own
`doctor.sh` call. **Do not go looking for them** -- a session
touching this file will not find them, and that is correct.
`OSS_WORKSPACE_MCP_LIST_OUTPUT` is the one survivor, because it still has a real, same-process
consumer (the #1361 census heredoc), and it is still unset before `exec` for the ordinary staleness
reason. Its own sentinel, `OSS_WORKSPACE_MCP_LIST_CHECKED`, was dropped along with the other three
-- nothing has read it since #1392. A rule that quotes a removed name is worse than silent: it sends
a reader hunting for plumbing that was deliberately deleted (#1474).

Routed via /oss:curate from `trap.d/1392.env-relays-now-consumerless.md`; the sibling docs
staleness (`docs/open-the-workspace.md`, `docs/install.md`) this same launcher change left behind
is tracked separately (#1439), not in this file.
