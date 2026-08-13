---
description: Check changelog fragments, or fold them into CHANGELOG.md for a release.
allowed-tools: Bash
---

Fragments are the policy: one file per PR at `<changelog_dir>/<issue>.<section>.md`, so two open PRs
share no file and stop conflicting on every merge.

Read `changelog_dir` from `.oss.json`. If it is `null`, this repo hand-edits `CHANGELOG.md` and has
not adopted fragments — say so and stop. Rolling fragments out to a repo is a change to that repo,
which is a separate decision, not something this command does on the way past.

## Check (default)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --check --dir "$(python3 -c 'import json;print(json.load(open(".oss.json"))["changelog_dir"])')" --changelog CHANGELOG.md
```

**Always pass `--dir` and `--changelog`.** The script derives its default root from
its own location, which assumes it lives in the target repo's `.github/scripts/`. It
lives in the plugin instead, so the default resolves somewhere above whatever repo
you are in — and it answers confidently rather than refusing.

Fragment names must parse, the section must be a real Keep a Changelog heading, and the body must be
a single top-level list with no headings, no raw HTML and no unclosed fences.

## Fold (release only)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --version X.Y.Z
```

This rewrites `CHANGELOG.md` and **deletes the fragments**. Do not run it outside a release you have
already gated: default branch green at leg level for the exact commit, nothing mid-review, security
audit passed.

## After

The fold is not the release, and the tag is not the delivery. Bump every site in `version_sites` and
sweep **unfiltered** — a README is not a `.json`, and an allowlist by extension cannot see it. A
sweep keyed on the outgoing version finds only half-bumped sites, never one frozen at some third
value, which is the one most likely to be wrong.
