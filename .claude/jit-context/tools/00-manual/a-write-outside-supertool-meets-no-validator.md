---
title: "A validator protects a route, not a file"
description: "jsonlint, ruff, gitleaks and rollback_on_fail are hooked to supertool write ops. A python heredoc that opens a path and writes it matches no op, so it passes unmapped, unvalidated and unrollbackable -- and the raw-command guard never sees it."
tool: Bash
match: ~open.*['\"][wa]['\"]|[.]write[(]|[.]write_text[(]
mode: remind
---

**`.supertool.json` configures validators over write *ops*, not over
paths.** `jsonlint` on `*.json`, `gitleaks` on `*`, both with
`rollback_on_fail: true` -- all hooked into `edit`, `replace`,
`replace_lines`, `paste`, `append` and `vim`. A write that reaches the
file any other way gets none of them, and no error either.

    python3 - <<'PY'
    open('.oss.json','w').write(...)
    PY

Measured twice in one week:

- **#1075**: two such writes to `.oss.json`. The first round-tripped the
  file through `json.dumps(indent=2)` and reformatted three unrelated
  inline arrays -- 15 insertions for a 5-item edit. `jsonlint` would not
  have caught that either; the reformatted file is valid JSON. It was
  caught by reading `git diff` afterwards.
- **#1055**: a heredoc appending several test functions rather than
  `edit:@-`. Caught only by a habitual `git diff --stat`.

**The raw-command guard is not the backstop.** It hooks Bash and maps
*known invocations*; a heredoc that opens a path matches no op, so it
passes unmapped and unmentioned. Its own refusal text says as much --
and reaches nobody who never triggers a refusal.

**The pull is strongest when appending several similar chunks**, because
that shape feels like generating a file rather than editing one. It is
still an `edit`: anchor `old` on the last existing block and carry it
into `new` along with everything appended.

A background watcher escapes the guard the same way, for a different
reason: `tools/00-manual/a-watcher-is-a-checker.md`.
