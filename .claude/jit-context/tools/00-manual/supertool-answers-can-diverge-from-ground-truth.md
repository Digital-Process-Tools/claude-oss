---
title: "A supertool read/grep/validate answer can diverge from the file it names -- cross-check when the result surprises you"
description: "read and grep both returned a file's pristine pre-edit content several edit:@- calls after those edits had already applied and the file's real byte count had changed; validate: reported markdownlint findings at the pre-.markdownlint.json line length after the config raised it. Neither failure was signalled -- the op returned a normal-looking, wrong answer."
tool: Bash
match: ~supertool
mode: once
---

Two separate divergences between a supertool op's answer and the file's real, on-disk state,
neither one signalled as an error:

- **`read:` and `grep:` served stale, pre-edit content several `edit:@-` calls later**, on the same
  file, twice in one session -- each `edit:@-` call itself returned a diff showing the new content
  landing correctly, immediately before the next `read`/`grep` returned the old one. `wc -l`, a raw
  `python3 -c "print(open(...).read())"`, and `git status --short` all agreed the edits were really
  on disk; only `read`/`grep` disagreed. Not isolated to a path-keyed cache, a line-count-keyed
  index, or something else -- the workaround (fall back to a raw read to confirm ground truth) was
  cheap enough that root cause was never pinned down.
- **`validate:` answered from a default rather than the project's own `.markdownlint.json`.** After
  that config raised MD013's line-length limit and excluded code blocks/tables, the real
  `markdownlint` CLI (run both with and without an explicit `--config`) reported zero findings over
  a set of files; `validate:` on the same tree still reported MD013 findings at the old 80-column
  default. The dangerous direction is a rule the config *enables* that the default does not --
  it would render as clean and was not tested here.

**When a supertool op's answer looks stale, wrong, or surprisingly clean, cross-check it against a
second, independent read of the same ground truth** -- a raw read, the real CLI the op wraps, or a
byte/line count -- before trusting either the op's "nothing changed" or its "no findings." A single
call to one of these ops, on its own, renders identically whether or not it actually looked at
current, complete content.

Routed via /oss:curate from `trap.d/1566.supertool-read-grep-served-stale-cached-content.md` and
`trap.d/1576.supertool-validate-op-ignores-markdownlint-config.md`.
