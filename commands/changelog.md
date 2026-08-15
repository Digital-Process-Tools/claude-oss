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

**Always pass `--dir` and `--changelog` — on every mode, including the fold below.** With
neither, the script derives its root by walking up from its own location for a `.git`. It
lives in the plugin, so that walk lands in **the plugin's own repository**, not the one you
are standing in — and it answers confidently rather than refusing, because it did find a
repo. That is harmless for `--check`, which only reads the wrong tree. It is not harmless
for the fold, which writes to it.

The fold no longer accepts that guess (#67): with either flag missing it exits `2` and
prints the invocation to run instead. `--check`, `--check-links` and `--count` keep the
derived default, because a scaffolded repo's CI calls the vendored `.oss/` copy bare and
that copy's derivation is correct — so passing the flags there is discipline, not a
requirement, and a wrong tree costs a read rather than a write.

Fragment names must parse, the section must be a real Keep a Changelog heading, and the body must be
a single top-level list with no headings, no raw HTML and no unclosed fences.

## Link refs, and the versions that were never tagged

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --check-links --untagged "$(python3 -c 'import json;print(",".join(json.load(open(".oss.json")).get("changelog_untagged") or []))')" --dir "$(python3 -c 'import json;print(json.load(open(".oss.json"))["changelog_dir"])')" --changelog CHANGELOG.md
```

`--check-links` refuses when a `## [x.y.z]` section has no link reference definition. If
that version was never tagged, the missing link is the **correct** state — there is no
release page to point at, and a `releases/tag/vX.Y.Z` URL written for one is a 404 that
renders as a working link.

`--untagged` is how that is declared, and the declaration lives in `.oss.json` under
`changelog_untagged`, not on this command line. Which sections were never tagged is a
fact about **one** repository, and the same answer has to reach three places — this
command, the rule under `.claude/jit-context/paths/01-oss/`, and the `oss-changelog.yml`
leg that gates every pull request. Read it from the config in all three and they cannot
drift; write it in each and they will. Read `changelog_untagged` from `.oss.json` and
pass it, as above.

**Its three states are three, not two.** Absent or `null` means nobody declared anything,
so every release section is expected to carry a link ref — that is the default reading,
not a statement. `[]` means the repository has declared that every section was tagged;
same audit, and a decision on record. A list names the exempt versions. The receipt says
which of the three it was given, on `ok` and on a refusal alike, because a finding about
a missing link ref means something different depending on whether anyone had answered the
question.

A declared version with no matching `## [x.y.z]` section is itself a finding. An
exemption for a section that is not there costs nothing and reports nothing, which is how
a stale declaration outlives the history it described.

`--untagged` is read by `--check-links` and by nothing else: passed to the fold, to
`--check` or to `--count`, it is **refused** rather than ignored, because a declaration
that was never consulted is indistinguishable from one that was honoured.

## Fold (release only)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --version X.Y.Z --dir "$(python3 -c 'import json;print(json.load(open(".oss.json"))["changelog_dir"])')" --changelog CHANGELOG.md
```

Both flags are **required** here — the fold refuses rather than derive a target, in this copy
and in the vendored one alike, because nothing on disk distinguishes "the repo this file is
stored in" from "the repo being released".

This rewrites `CHANGELOG.md` and **deletes the fragments**. Do not run it outside a release you have
already gated: default branch green at leg level for the exact commit, nothing mid-review, security
audit passed.

## After

The fold is not the release, and the tag is not the delivery. Bump every site in `version_sites` and
sweep **unfiltered** — a README is not a `.json`, and an allowlist by extension cannot see it. A
sweep keyed on the outgoing version finds only half-bumped sites, never one frozen at some third
value, which is the one most likely to be wrong.
