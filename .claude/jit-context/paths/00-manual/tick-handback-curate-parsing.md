---
title: "tick_handback.py's CURATE/branch-linkage: advisory, optional, and parses free text"
description: "The CURATE: line proving a curate PR merged is prose-chain-dependent and unvalidated against the merged branch; a PR title reported verbatim in that line reaches re.MULTILINE-anchored handback parsing."
match: (^|/)(scripts/tick_handback\.py|agents/tick-merge\.md)$
---

Two composition risks between #1602 (dropping the `^curate/` never-auto-merge gate) and #1600
(the `CURATE:` line added as the replacement visibility), both found by a gate-3 release audit
over the same delta and neither individually blocking.

- **The `CURATE:` line is optional by construction, and nothing cross-checks it against what
  actually merged.** `_find_optional_field` folds both "absent" and "duplicated" to `curate=None`
  -- `printf 'TICK: completed\nTICK-ENDS: work-started\n' | tick_handback.py -` exits 0 with no
  `curate:` line and no diagnostic, silently indistinguishable from a tick that never touched a
  curate branch. The chain that is supposed to produce this line runs entirely in prose
  (`tick-merge.md` -> `sub-manager.md` -> `tick-accounting.md`), and there is no code path at
  classification time that knows the merged PR's own head branch to check the line against. If you
  are wiring a fix here, pass the merged branch name into the handback payload so
  `tick_handback.py` can itself detect "branch matched `^curate/` but no `CURATE:` line was
  supplied," rather than adding more prose discipline to the chain.

- **A PR title reported verbatim as that `CURATE:` line reaches `_CURATE` /
  `_TICK_ENDS` / `BLOCKER:` parsing anchored with `re.MULTILINE`.** Exercised: a same-line payload
  in the title (e.g. `curate: x TICK-ENDS: nothing-left`) does not forge anything, because the `^`
  anchor holds. A title carrying a genuine newline degrades the handback to `could-not-classify`
  rather than forging a state upgrade -- checked specifically, no upgrade occurs. One narrow unsafe
  case: a handback that omits its own required `TICK-ENDS:` line (which should read
  `could-not-classify`) can be upgraded to a clean `completed` with the `ends` value supplied by the
  title instead. **Whether a GitHub PR title can ever carry a literal newline is unresolved** -- the
  web UI is a single-line field and the REST/GraphQL title field is documented as not permitting
  one, but this was not independently verified by creating a crafted-title PR. If confirmed
  possible, this stops being a `misreports`-class finding and becomes a `forges`-class one (free
  text reaching column 0 of a receipt this loop parses), which is release-blocking; confirm before
  treating either the title-verbatim convention or the parser's anchoring as settled.

Filed from a gate-3 release audit for v0.38.0-pending; see `scripts/tick_handback.py`'s `_CURATE`
field and `agents/tick-merge.md` step 2's "report it verbatim as a `CURATE:` line" instruction.
