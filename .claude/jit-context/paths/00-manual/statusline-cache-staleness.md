---
title: "Editing statusline.py: keeping a cached reading's age alive to the render"
description: "The trap itself is in vocabulary/01-oss/plugin-currency.md. These are the implementation mechanics that were got wrong once each."
match: (^|/)scripts/statusline\.py$
---

`vocabulary/01-oss/plugin-currency.md` states the trap — a reading fresh by its own rule can still be
wrong — and the marker table. **These are the mechanics underneath it**, each of which failed once.

- **`gather()` discarding `latest_fetched_at` is how the guard died.** `refresh()` stores the stamp
  and its own docstring warns that stamping a carried value `now` would make an hour-old reading
  indistinguishable from one just taken. `gather()` then dropped it one function later, making them
  indistinguishable anyway. A guard can survive all the way into the cache and die at the one
  function that renders it.
- **`plugin_facts` / `version_status` take a `stale` flag**, so a comparison older than its own
  refresh interval folds into the existing `?` bucket rather than inventing vocabulary or printing a
  false `behind`/`ahead`.
- **`invalidate_latest_cache()` is called by the actor that falsifies the reading**, not on a timer:
  `/oss:release` calls it the moment `execute()` reports a Release `created`.
- **Test the stale case and the fresh-but-wrong case in the same fixture.** They are different
  defects and neither mechanism catches the other's. A fixture with one of them proves nothing about
  the incident that produced both.
- **Age is a trigger to refresh, never a reason to distrust what is already known (#1635, #1636).**
  A due reading already provoked its own refresh in this same pass; folding on age alone shows
  `unknown`/`cannot_determine` for a reading that is still correct while that refresh is in flight.
  The one thing that DOES fold a reading is a refresh actually attempted and recorded as having
  failed (`latest_refresh_failed_at`, `board_refresh_failed_at`, `doctor_refresh_failed_at`,
  `channel_refresh_failed_at`) -- or a reading never taken at all. This governs all FOUR cached
  fields on the line (`latest`, the default-branch marker, `/oss:doctor`, the watch channel), not
  only the one #1464 first fixed it for -- #1636 is #1635's own recon item left open: the channel
  field's `channel_status()` folded on `now - fetched_at >= interval` unconditionally, the identical
  shape, and its own docstring had argued the opposite conclusion ("no falsifying event to invalidate
  the cache against") that #1636's body rejects for the same reasoning applied to `doctor_state`.
