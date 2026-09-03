---
title: "The rules engine refuses symlinked layers"
description: "Git carries symlinks, so a clone could aim rules anywhere. Copies into an owned layer are the supported shape."
match: (^|/)scripts/oss_rules\.py$
---

- **A symlinked rule layer is refused, by design.** Git carries symlinks, so a clone could aim a
  rules layer at any path on the machine that checked it out. **Copies into an owned layer are the
  supported shape** — the `01-oss/` directories are replaced wholesale on every run, which is what
  makes a fix reach everyone.
- **Editing a shipped `01-oss/` rule means editing this file**, not the `.md` on disk: that layer is
  regenerated from here and a hand edit is overwritten on the next scaffold run without a word.
