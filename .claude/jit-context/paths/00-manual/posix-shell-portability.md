---
title: "Any shell script here: two portability traps that already cost a round each"
description: "${0%/*} strips nothing under Git Bash. || true on a heredoc opener under set -eu can swallow errexit as well as the exit status -- attach the status capture to the command itself."
match: (^|/)(bin/[^/]+|scripts/[^/]+\.sh)$
---

**Scoped to every file under `bin/` and every `.sh` under `scripts/`, not just the two files where
these were first found** -- both traps are general POSIX-shell-writing mistakes, and a rule keyed
only on `scripts/doctor.sh` and `bin/oss-workspace` would stay silent for a third shell script that
repeats either one.

- **`${0%/*}` strips nothing under Git Bash**, where `$0` is `D:\a\repo\scripts\doctor.sh`. Both
  `scripts/doctor.sh` and `bin/oss-workspace` strip either separator. This failed all four Windows
  legs while every POSIX leg was green.
- **A glyph a shell script prints can be unencodable on the console it reaches, even when the
  bytes going out are correct UTF-8.** `bin/oss-workspace`'s `oss_step()` prints `▸` (U+25B8) and
  `✓` (U+2713); both raise `UnicodeEncodeError` under `.encode('cp1252')`, the default Windows
  console codepage. Neither is new -- both predate the diff that found them (#1511) -- and CI's
  `shell` job only runs `shellcheck`/`bash -n` on `ubuntu-latest`, so nothing in the matrix would
  ever exercise a real Windows console's TTY-gated printf here at all: whether this has actually
  crashed a real session (git-bash/mintty and Windows Terminal are both UTF-8-capable) versus being
  a live-but-never-triggered exposure was not established. Check a new glyph against cp1252 before
  adding it to this launcher's output, mirroring the `ascii()`-by-construction convention its own
  watch-name-derivation code already uses for Python-emitted text.
- **A trailing `|| true` on a shell command can be doing two jobs, and replacing it with a captured
  status only removes one.** Under `set -eu`, `|| true` on a bare simple command inside an `if` body
  both swallows the exit status AND suppresses errexit for that command. #573 replaced
  `bin/oss-workspace`'s `ASK_CONSUMER` heredoc opener's `|| true` with `ask_consumer_status=$?`
  captured on the line after the heredoc closed — which restored the first job and left the second
  undone, since a crashed probe now killed the whole script via errexit before that capture line, or
  the 34-line reporting arm past it, ever ran (#588). The fix is to attach the status capture to the
  command itself — `<<'HEREDOC' && status=0 || status=$?` on the opener line, the idiom
  `bin/oss-workspace`'s doctor-diagnostic call already used before this fix — not to a line after
  it, which errexit never lets execution reach. The harness that shipped alongside #573's fix could not see this: it ran the extracted block
  under a bare `sh`, never turning `set -eu` on, so a script that dies from errexit and a script that
  runs to completion look identical to it.
