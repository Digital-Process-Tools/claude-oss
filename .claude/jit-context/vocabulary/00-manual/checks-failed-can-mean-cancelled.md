---
title: "checks_failed can fire on a cancelled leg, not a failing one"
description: "The github-pr watcher's checks_failed event fired four times on a PR whose checks had zero failing legs -- one leg was cancelled, which the watcher's event vocabulary folds into the same key as a real failure."
keywords: checks_failed, checks failed event, cancelled leg, not all green
---

A `checks_failed` channel event means **not green**, not **found a defect**. Before treating it as
a CI failure, read `gh-pr:N:status` directly: a `cancelled` leg (superseded run, infra stop) is a
third state distinct from a leg that ran and failed, and the two need different diagnoses.

Observed on PR #1654: four `checks_failed` events in an hour, each time `gh-pr:1654:status` showed
`9 passed, 0 failed, 0 pending, 1 cancelled`. The event will keep firing (~every 20 minutes) for as
long as the PR sits in that state -- re-reading status each time is cheap, but do not act on the
event name alone.
