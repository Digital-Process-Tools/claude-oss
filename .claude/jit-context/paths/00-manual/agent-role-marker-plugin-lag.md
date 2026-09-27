---
title: "A live role-marker refusal can be a stale installed-package lag, not a rival"
description: "An installed plugin package can predate a role-marker behaviour fix, leaving its marker on disk for the full TTL regardless of source-repo fixes -- name-only checks cannot tell that from a genuine rival."
match: (^|/)(scripts/agent_role\.py|agents/doctor\.md|agents/sub-manager\.md)$
mode: remind
---

`agent_role.py --write` refusing with "a live marker already names role 'doctor'" does not by
itself mean a doctor is genuinely still running. `~/.claude/plugins/cache/dpt-plugins/oss/<ver>/`
can be an older release than this checkout's own `HEAD` -- an installed copy that predates a
role-marker behaviour fix (e.g. `doctor.md` gaining a `--clear` step) keeps leaving its marker on
disk for the full `MARKER_TTL_SECONDS` (4h) on every run, indistinguishable by name alone from a
genuine concurrent doctor.

Before forcing past the refusal, check:

- `grep -c -- --clear ~/.claude/plugins/cache/dpt-plugins/oss/<installed-version>/agents/doctor.md`
  -- zero hits means the installed package cannot self-clear, so a marker under its own TTL is the
  expected residue, not evidence of a live rival.
- The marker's own age against the TTL, and whether any other agent activity in this session
  plausibly explains a live doctor.

Confirmed live (#1733): a marker only ~4.5 minutes old, well inside the 4h TTL, blocked a tick's
own role write; the installed package's `agents/doctor.md` had no `--clear` step at all even though
this repo's own HEAD already carried the fix.
