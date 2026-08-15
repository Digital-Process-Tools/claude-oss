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

Read `changelog_untagged` from `.oss.json` first, and build the invocation from **which of
its three states** you found. Do not collapse them with `or []` or any other falsy test:
`null` and `[]` are both falsy and mean different things, and a one-liner that maps the
first onto the second reports "declared empty" for a repository that declared nothing —
the defect this key exists to remove, reintroduced at the surface that documents it.

```bash
# absent or null -- nobody declared anything. Pass no --untagged at all.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --check-links --dir 'changelog.d' --changelog CHANGELOG.md

# [] -- declared that every release section was tagged.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --check-links --untagged '' --dir 'changelog.d' --changelog CHANGELOG.md

# a list -- comma-separated, in the order you found them.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --check-links --untagged '0.1.0' --dir 'changelog.d' --changelog CHANGELOG.md
```

Three commands rather than one clever line, because the clever line is where the bug goes.
Substitute `changelog_dir` for `changelog.d` as the check above does; the versions are
validated as `x.y.z` before they are ever written into a workflow, so they carry nothing a
shell reads as an instruction.

`--check-links` refuses when a `## [x.y.z]` section has no link reference definition. If
that version was never tagged, the missing link is the **correct** state — there is no
release page to point at, and a `releases/tag/vX.Y.Z` URL written for one is a 404 that
renders as a working link.

`--untagged` is how that is declared, and the declaration lives in `.oss.json` under
`changelog_untagged`, not on this command line. Which sections were never tagged is a
fact about **one** repository, and the same answer has to reach three places — this
command, the rule under `.claude/jit-context/paths/01-oss/`, and the `oss-changelog.yml`
leg that gates every pull request. Read it from the config in all three and they cannot
drift; write it in each and they will.

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

### The heading, and `--title`

The default heading is `## [x.y.z] - YYYY-MM-DD`, which is Keep a Changelog's own shape and stays
the default. Some repositories put a sentence in the heading instead — what the release is about,
or why the previous design was wrong — and until `--title` existed the only way to keep that while
using this script was to fork it, which is an owned file that `/oss:scaffold --apply` replaces
wholesale.

```bash
# a title: written after the date, `## [X.Y.Z] - YYYY-MM-DD — <title>`
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --version X.Y.Z --title 'What this release is about' --dir 'changelog.d' --changelog CHANGELOG.md

# no title, deliberately: the plain heading, and the receipt records that somebody chose it
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --version X.Y.Z --title '' --dir 'changelog.d' --changelog CHANGELOG.md
```

**Its three states are three, not two, and the flag is not in `.oss.json` on purpose.** A title is
a per-release editorial choice, so unlike `changelog_untagged` — one fixed fact about a
repository's history — it has no single value a config file written once could hold. Where the
*convention* lives is the changelog itself, which already states it: the fold reads the newest
`## [x.y.z]` heading in the file it was handed and asks whether that one carries a title.

- **Omitted**, against a file whose newest release heading carries a title: **refused**, nothing
  written, nothing consumed. This is the quiet direction — writing the plain heading would succeed
  and look right, and the break is visible only to somebody reading the new heading against the
  ones above it.
- **Omitted**, against a plain, bare, or absent history: the default heading, and the receipt says
  which of those three it read. "No release heading to read a convention from" is not the same
  answer as "read one and it was plain".
- **`--title ''`**: the plain heading, recorded as a decision. This is the way to cut one plain
  release in a repository that titles the rest.

`--title` is read by the fold and by nothing else: passed to `--check`, `--check-links` or
`--count` it is **refused** rather than ignored, for the same reason `--untagged` is.

## After

The fold is not the release, and the tag is not the delivery. Bump every site in `version_sites` and
sweep **unfiltered** — a README is not a `.json`, and an allowlist by extension cannot see it. A
sweep keyed on the outgoing version finds only half-bumped sites, never one frozen at some third
value, which is the one most likely to be wrong.
