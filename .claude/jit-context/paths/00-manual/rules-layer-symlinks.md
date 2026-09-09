---
title: "The rules engine refuses symlinked layers"
description: "Git carries symlinks, so a clone could aim rules anywhere. Copies into an owned layer are the supported shape, and a dependency's own index rebuilder must not be pointed at one."
match: (^|/)scripts/oss_rules\.py$|(^|/)\.claude/jit-context/.*/00-index\.tsv$
---

- **A symlinked rule layer is refused, by design.** Git carries symlinks, so a clone could aim a
  rules layer at any path on the machine that checked it out. **Copies into an owned layer are the
  supported shape** — the `01-oss/` directories are replaced wholesale on every run, which is what
  makes a fix reach everyone.
- **Editing a shipped `01-oss/` rule means editing this file**, not the `.md` on disk: that layer is
  regenerated from here and a hand edit is overwritten on the next scaffold run without a word.
- **Do not run the dependency's index rebuilder over a layer this repo generates.**
  `claude-jit-context`'s `scripts/rebuild-tsv.sh` is the right tool for the three `00-manual`
  layers, which have no generator on this side — and it also rewrites `01-oss/00-index.tsv`, which
  `oss_rules.install()` owns. The two disagree by one byte per row: the rebuilder emits a trailing
  tab (an empty third column), `install()` emits two columns and no trailing tab. Every row reads as
  drift to `tests/test_rule_layer_sync_1063.py`, and the cost is a red CI leg on four platforms for
  a whitespace difference on a prose pull request (#1331). Rebuild the manual layers only, or
  restore the owned index afterwards with `git checkout main -- <that file>` — **not**
  `git checkout -- <file>`, which restores the already-committed drifted copy and looks like it did
  nothing.
