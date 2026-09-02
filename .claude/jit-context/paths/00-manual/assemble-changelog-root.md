---
title: "assemble_changelog.py derives its root from the caller's cwd, not from where it lives"
description: "Since #590 the walk for a .git starts at the caller's cwd, not __file__. Pass both --dir and --changelog on every mode, or an older copy can silently fold the wrong repository's fragments."
match: (^|/)(\.oss/assemble_changelog\.py|scripts/assemble_changelog\.py)$
---

- **`assemble_changelog.py` derives its root by walking up for a `.git`** — since #590, from the
  **caller's current working directory**, not from the script's own install location. It used to
  walk from `__file__`: under a plugin that walk finds **the plugin's own repository** regardless of
  where the caller stands, so a fold given neither `--dir` nor `--changelog` rewrote this repo's
  `CHANGELOG.md` and deleted this repo's fragments, and said it worked — it did find a repo, just
  never the caller's. **Since #67 the fold refuses instead**, exits `2` and prints the invocation to
  run — that refusal is unconditional across both copies on purpose: which repository the caller
  *meant* is not on disk, so a detector would be guessing, and a wrong guess writes to a repository
  nobody named. Still pass both, on every mode. The read-only modes (`--check`, `--count`,
  `--check-links`) used to keep the `__file__`-derived default unconditionally, on the reasoning
  that they only read — which held for the vendored `.oss/` copy (stored inside the repo it serves,
  so the two roots always agreed) and did not hold for the plugin's own copy, which reported a clean
  `ok` about its own fragments no matter which repo, or non-repo, the caller ran it from (#590). Now
  they derive from the caller's cwd and refuse the same way the fold does when no `.git` is found
  above it, and the `ok`/`skipped` receipts name the resolved directory so the answer's subject is
  never implicit. This trap said `.github/scripts/` and a fixed parent count until #65; the
  derivation changed and the warning beside it did not, so `commands/changelog.md` carried the fix
  for one shape of the bug and the description of another — the reason this bullet gets rewritten
  rather than appended to every time the derivation moves again.
