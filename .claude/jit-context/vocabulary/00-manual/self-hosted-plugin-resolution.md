---
title: "This repo IS the plugin, so the checkout is the authority -- not ${CLAUDE_PLUGIN_ROOT}"
description: "A session's pinned plugin root can be several releases behind the checkout it is managing. Scripts run from it silently regress to old behaviour, and validators run from it return UNVALIDATABLE against perfectly valid newer payloads."
keywords: CLAUDE_PLUGIN_ROOT, plugin root, pinned root, resolved install, report schema, schema version, checklist skew
---

**Three copies, and the pinned one is the least current.** A session is injected with
`${CLAUDE_PLUGIN_ROOT}`; `plugin_update.py --print-resolved-root` names a second, usually newer
copy; and this checkout is a third, ahead of both, because claude-oss *is* the `oss` plugin's own
source. `vocabulary/01-oss/plugin-currency.md` owns the version-reading question and is not
restated here. This rule is only about **which copy to execute**.

**Run the checkout's own script, not the pinned root's, whenever the managed repo is this plugin --
for a write as much as a read.** Measured, all on 2026-09-09, all from the same tick:

- `${CLAUDE_PLUGIN_ROOT}` resolved to a **0.26.0** cache directory while the resolved install was
  **0.29.1** and the checkout was 13 commits past that. `select_issues.py --board` from the pinned
  root still carried the pre-#1200 stdin bug and died with `stdin: not valid JSON`. The checkout's
  own `./scripts/select_issues.py` worked (#1127).
- `report_schema.py` from the pinned root implements an older contract, so a lane's report written
  to the current one comes back `UNVALIDATABLE` with `unknown key '<newer field>'` -- a false
  negative about a valid report. Two lanes hit it independently in one tick (#1324).
- The release gate's own checklist ran against installed prose older than the tree it was gating:
  `agents/auditor.md` and `skills/manager/phases/findings.md` both predated sections already on
  `main`, and `checklist_skew.py` still read `matches` while one file differed (#1334).
- **`scaffold.py --apply` run from the pinned root silently regressed two tracked jit-context
  files.** Run against this repo from `${CLAUDE_PLUGIN_ROOT}` (0.32.0) while the checkout was
  0.33.0, it regenerated `.claude/jit-context/tools/01-oss/00-README.md` and `merge-gate.md` from
  an older generator, reverting real prose trims already on `main`. The write receipt read WROTE/
  replaced identically either way; only `git status` on tracked files caught it. Re-running the
  identical `--apply` from the checkout's own `scripts/scaffold.py` produced a byte-identical,
  correct result (#1417).
- **`cohort_citation_order.py` without `--claude-md` reads `${CLAUDE_PLUGIN_ROOT}/CLAUDE.md`, not
  the checkout's.** The flag defaults to a path resolved relative to the script's own location, so
  it printed `ok` about the previous release's already-frozen cohort while the checkout's own
  marker had already moved on to the next one -- caught only because the printed cohort number did
  not match the paragraph just written. `--claude-md ./CLAUDE.md` reads the right file (#1459).

**`UNVALIDATABLE` and `matches`-with-a-differing-row are the tells.** Neither says "you asked an old
copy"; both render as a statement about the payload. Before believing either, compare the version
the tool came from against the tree it was asked about.

`skills/manager/phases/tick-order.md` already draws this distinction for `doctor.py`. It is the same
distinction, and it applies to every script the loop runs against itself.
