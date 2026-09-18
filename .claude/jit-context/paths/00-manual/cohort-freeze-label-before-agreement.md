---
title: "cohort_freeze_record.py writes the label before checking route agreement -- a partial run still mutates"
description: "A partial freeze (cutoff_scan vs label_filter disagree) still writes the label to whatever is currently open before the disagreement is discovered. Repeated partial attempts re-stamp the label onto successive snapshots of the open board rather than leaving it untouched."
match: (^|/)scripts/cohort_freeze_record\.py$
---

Recurred five times on the same cohort across five successive tags (v0.37.0, v0.37.1, v0.38.0,
v0.39.0, v0.40.0), each `--execute` run reporting `partial`: `cutoff_scan` (what is open right now)
disagrees with `label_filter` (what the label actually marks, read back from the forge), and the gap
worsens rather than converges on a re-run within the same attempt -- not the shape a stale
search-index disagreement usually takes, which converges toward agreement.

**The mechanism does the write first and discovers the disagreement after**: `cohort_freeze_record.py`
applies the label to whatever `cutoff_scan` currently sees as open, then reads back `label_filter`
and compares. A `partial` result has already mutated the label set by the time it reports partial.
Three-or-more separate partial attempts across different tags each apply the label to whatever was
open *at that attempt's own moment*, so the cohort's member count answers "the union of several
different snapshots taken weeks apart", not "what was open when this cohort was decided" -- the
invariant the freeze exists to establish. Not data loss (the label is over-applied, never dropped),
but the count is unusable as a decision-time snapshot once this has happened even once.

**A cohort in this state should not be re-attempted expecting it to converge.** It has not converged
in five tries; retrying again writes another partial snapshot on top of the last one. Cite the
last cohort that *did* fully agree instead (`cohort_citation_order.py` enforces this already) and
treat a repeatedly-partial cohort number as contaminated until one of two design fixes lands, neither
chosen yet: retire it and freeze a fresh cohort cleanly at the next release, or make the label write
conditional on the two routes already agreeing (no mutation at all on a `partial` result).

Routed via /oss:curate from
`trap.d/1666.cohort-35-label-accumulated-across-repeated-partial-freeze-attempts.md` and
`trap.d/1666.cohort-35-partial-freeze-again-at-v0.40.0.md`.
