---
title: "Validating an .oss.json value that reaches a generated file"
description: "Anchor \\A...\\Z in the pattern, never ^...$ and never fullmatch at the call site. Enumerate substitution sites, not compiled patterns -- a value with no pattern cannot appear in a sweep of patterns."
match: (^|/)scripts/(oss_config|scaffold)\.py$
---

`.oss.json` is tracked, so every value arrives by ordinary contribution from a stranger.

- **`$` matches before a trailing newline, so `^…$` is not a whole-string anchor.** `"changelog.d\n"`
  and `"0.1.0\n"` validated. The harm was not shell escape — a newline cannot leave a single-quoted
  string — it ended the `run:` block scalar, so the workflow this plugin writes into somebody else's
  repository stopped parsing and its changelog gate stopped running, with no failed check on the pull
  request.
- **Anchor `\A…\Z` in the pattern itself**, not `fullmatch` at the call site, so a later caller
  reaching for `.match` or `.search` cannot lose it.
- **Assert the rendered file still parses**, not that the regex returned False. The regex is the
  cause; the parse is the harm.
- **Enumerate substitution sites, never compiled patterns.** A sweep of all 28 patterns in `scripts/`
  closed a newline hole in `repo` and left `test_command` and `default_branch` — substituted into the
  same file by the same function — behind a bare `str` type check, guard and bypass three lines
  apart. Neither had a pattern, so neither could appear in a sweep of patterns.
- **Report the sites found clean as loudly as the ones fixed.** A sweep that reports only hits cannot
  be told from one that stopped early.
- **Choose the refusal from the harm, not from a shape this repo invented.** A shell command admits
  nearly everything, so its refusal is a character class; a branch name already has an authority, so
  its refusal is a transcription of `git check-ref-format` — **measured against that authority in a
  test**, since a borrowed control set that carves out tab was already false for a git ref name.
- **Deliberate over-refusals live in a named exception list with a reason each**, and a test fails
  when an entry stops being an exception. An exception list that has drifted is a licence.
