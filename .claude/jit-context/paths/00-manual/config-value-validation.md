---
title: "Validating an .oss.json value that reaches a generated file"
description: "Anchor \\A...\\Z in the pattern, never ^...$ and never fullmatch at the call site. Enumerate substitution sites, not compiled patterns -- a value with no pattern cannot appear in a sweep of patterns."
match: (^|/)scripts/(oss_config|scaffold|fix_commit_scope)\.py$
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

- **A trailing `--` does not close an option-injection hole in a git revision argument**, and it is
  the natural first fix to reach for. `git diff --name-only "{base}..{head}" --` still lets a
  `base` starting with `-` be parsed as an option: `--` only separates a pathspec section from a
  revision section, and does nothing about an option-shaped token appearing before it. Verified:
  `git diff --name-only --output=X..HEAD --` still wrote a file. Putting `--` *before* the revision
  does block it and breaks the ordinary case -- git then reads the whole range as a pathspec and a
  real `<sha>..<sha>` silently returns an empty diff. **The fix is `--end-of-options` (git >= 2.24)
  placed before the revision argument**, which makes git itself refuse the option-shaped revision
  (`fatal: option '--output=...' must come before non-option arguments`, exit 128) (#1254).
- **Assert against the filename the vulnerable code actually creates.** With the argv built as one
  joined `"{base}..{head}"` string, an injected `--output=/tmp/pwned.txt` writes to
  `/tmp/pwned.txt..HEAD` -- the whole joined string becomes the option's value. A negative control
  asserting `not Path("/tmp/pwned.txt").exists()` is vacuous: that path is absent both before and
  after the fix, for two different wrong reasons. Two independent review spawns caught this in the
  same first-draft test.
