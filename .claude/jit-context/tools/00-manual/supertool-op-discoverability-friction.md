---
title: "A bare pipe after any supertool call still trips the raw-command guard, and git-diff wants the branch: form"
description: "Piping a supertool call's own output through head/tail -- even to view a few lines of a help: body -- is refused the same as a raw shell read; and git-diff:main...HEAD / git-diff:BRANCH fail with 'not found', the working form is git-diff:branch:BASE[:full]."
tool: Bash
match: ~git-diff|supertool[^|;&]*\|[[:space:]]*(head|tail)
mode: once
---

Two related discoverability papercuts, both cheap to avoid once known, both costing several
round-trips when found by refusal instead (#1629):

- **`supertool 'help:X'` (or any op) piped through `| head`/`| tail` is refused, even when the pipe
  target is a harmless truncation of supertool's own already-fetched output** -- e.g. quoting only
  a `help:` body's first few lines. The raw-command guard matches at command position regardless
  of what produced the output ahead of the pipe; narrow the **op**, never the output (`help:X`
  already prints only what it has to -- read the whole thing, or use the op's own narrower form
  if one exists, rather than trimming with a shell pipe).
- **`git-diff:main...HEAD` and `git-diff:BRANCH` (a bare ref, or the `A...B` shape) fail with
  "not found under REPO".** The working form is `git-diff:branch:BASE[:full]` -- e.g.
  `git-diff:branch:main:full` for "this branch against main" -- discoverable only by reading
  `help:git-diff`, with no hint toward it in the bare-ref refusal itself.
