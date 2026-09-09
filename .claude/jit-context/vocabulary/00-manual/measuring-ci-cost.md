---
title: "Measuring CI cost: job start offsets, not job durations, and never one leg"
description: "Wall clock on a push is governed by the slowest single leg and by runner concurrency, not by the suite. One leg's --durations block is a profile of that leg, and the shape of a test file predicts neither its cost nor its platform variance."
keywords: CI slow, slowest test, durations, test suite performance, matrix reduction, wall clock, runner concurrency, queue time, flaky rerun
---

**"CI is slow" on this repository was, on measurement, almost never the
test suite.**

**Read start offsets, not durations.** Durations say which leg is
slowest; offsets say whether the legs ran at the same time, and that is
what decides whether removing one buys anything.

    gh api "repos/OWNER/REPO/actions/runs/<id>/jobs?per_page=50"

Diff each `started_at` against the earliest. A run's `created_at` versus
its first job's `started_at` is the queue, and it is invisible in every
per-job duration table.

Measured (#1246, run 34099357435, 14 jobs): thirteen of fourteen started
within 7 seconds of each other. Wall clock is the slowest single leg
(311s), not the 35.9 leg-minutes the run consumes. Two things dominate
instead, and neither is the suite: **runner concurrency during a merge
train** (one run created at 08:12:25Z did not start a job until
08:16:53Z -- 4.5 minutes of pure queue) and **reruns caused by a flaky
leg** (6.3 of an 11.5-minute span).

**One leg is not a profile (#1176/#1177).** Same run, same test:

| leg | measured test time | slowest test | share |
| --- | --- | --- | --- |
| ubuntu 3.12 | 234.23s | 12.73s | 5.4% |
| windows 3.9 | 603.24s | 11.68s | 1.9% |

The first reads as "a few hot tests worth fixing"; the second as "the
cost is flat and no individual test is worth touching". Only the second
is true, and only the second is where half the matrix's wall clock is.

**And the shape of a test file predicts nothing.** A `grep -L` for
`tmp_path`, `subprocess` or `monkeypatch` over `tests/` selects 19% of
the suite and **none of the 25 slowest tests on either leg**: it selects
the cheap tests by construction, because a test that spawns nothing
costs nothing to run again. A proxy for "is this expensive" and a proxy
for "does this vary by platform" are both answerable from the real
durations output, and neither is answerable from the source.
