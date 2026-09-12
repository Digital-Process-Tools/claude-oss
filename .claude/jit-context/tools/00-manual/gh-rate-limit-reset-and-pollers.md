---
title: "gh rate limit: read against the reset clock, and count pollers before blaming credentials"
description: "A full core bucket right after reset says nothing about the hour before it. A 403 'rate limit exceeded for user ID' next to a full core bucket is the secondary limit, which rate_limit does not track and names no clearing time."
tool: Bash
match: ~gh api rate_limit|rate limit exceeded
mode: remind
---

**A full `core` bucket right after an hourly reset is expected, not evidence the poller is
unauthenticated.** Read `rate_limit`'s `reset` timestamp before drawing any conclusion from its
count -- a read taken minutes after `reset` says nothing about consumption in the hour before it
(#1421).

- **Count pollers per channel before blaming credentials.** `ps -eo etime,command | grep
  dispatcher.py` -- a stale channel left polling after its own session ended drains the same
  shared per-user token as the live one. Eleven `presets/watch/dispatcher.py poll` processes
  across four channel ids, three of them days-old orphans, produced two confident wrong
  diagnoses in twenty minutes.
- **A 403 `rate limit exceeded for user ID ...` beside a full `core: 5000/5000` is the
  *secondary* rate limit** (points per minute / concurrent requests), which the `rate_limit`
  endpoint does not count and whose `reset` field -- if `rate_limit` even reports one relevant to
  it -- keeps sliding forward with each read rather than naming when it clears. It clears in
  minutes on its own; there is nothing to fix and nothing to wait on a timestamp for.
- **A burst of doctor/CI reads on top of a fleet of pollers is enough to trip it.** Ten
  `doctor.sh` checks fell to `could not tell` at once from `doctor.sh` run three times in eight
  minutes stacked on a tick's own lanes plus eighteen pollers -- each doctor run alone is ~20
  `gh api` reads.

Read `gh api rate_limit` through `supertool`, not raw `gh`, for the reason
`tools/00-manual/a-watcher-is-a-checker.md` gives for every other unguarded `gh` call.
