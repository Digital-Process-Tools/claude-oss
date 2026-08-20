---
description: Check changelog fragments, or fold them into CHANGELOG.md for a release.
allowed-tools: Bash
---

Fragments are the policy: one file per PR at `<changelog_dir>/<issue>.<section>[.<slug>].md`, so
two open PRs share no file and stop conflicting on every merge. `<slug>` is optional and lets one
issue file two entries in the same section without the two pull requests colliding on a path.

Read `changelog_dir` from `.oss.json`. If it names a string, that is the directory. If it is
`null` or absent, do not conclude "not adopted" yet (#299) — `/oss:scaffold --apply` creates the
fragment directory and its own gating workflow **without** writing `changelog_dir`, on purpose
(`commands/scaffold.md`), because `.oss.json` is a tracked file somebody owns and a default must
never win against a decision a person made. So `null` alone is ambiguous between "this repo
hand-edits `CHANGELOG.md` and never adopted fragments" and "scaffold adopted them and nobody has
recorded which directory it picked". Tell the two apart with the same signal `release_version.py`
uses — whether THIS repo's own `.github/workflows/oss-changelog.yml` exists, the one path a forge
will read a workflow from:

```bash
FRAGMENTS_DIR="$(python3 -c "import sys, json; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
import oss_config
config = json.load(open('.oss.json'))
named = config.get('changelog_dir')
if isinstance(named, str) and named.strip():
    problem = oss_config.changelog_dir_problem(named)
    if problem:
        print('REFUSED: ' + problem, file=sys.stderr); sys.exit(1)
    print(named)
else:
    state, detail = oss_config.scaffolded_changelog_gate('.')
    if state == 'present':
        print(oss_config.DEFAULT_FRAGMENTS_DIR)
    elif state == 'present-other-dir':
        print(detail)
    elif state == 'present-refused-dir':
        print('REFUSED: ' + detail, file=sys.stderr); sys.exit(1)
    elif state == 'absent':
        print('NOT-ADOPTED', file=sys.stderr); sys.exit(1)
    elif state == 'unknown':
        print('UNKNOWN: ' + detail, file=sys.stderr); sys.exit(1)
    else:
        print('UNKNOWN: unrecognised gate state ' + repr(state), file=sys.stderr); sys.exit(1)
")"
```

**Five states, one arm each, and a sixth arm for a state this resolver has never heard of (#328).**
The gate grew `present-other-dir` in #325 and this resolver did not, so it fell through to
`NOT-ADOPTED` and refused a repository whose fragments the gate had just located — a loud wrong
answer, which is the only reason it ranks below the silent one it descends from. The trailing `else`
exists so the next state added to `scaffolded_changelog_gate` produces a refusal that *names what it
did not understand* rather than inheriting whichever arm happened to be last;
`tests/test_gate_state_consumers_328.py` is what makes it a refusal somebody has to come and fix.

- `present` — our gate is on disk and polices the default, so use `changelog.d/`.
- `present-other-dir` — our gate is on disk and its own `--dir` names some other directory, because
  that is what `changelog_dir` held when `/oss:scaffold --apply` ran and the key was nulled
  afterwards. `detail` **is** that directory, read back out of the workflow. Use it: the point of
  reading it back is to stop guessing, not to guess correctly by coincidence.
- `present-refused-dir` — our gate is on disk, it was read without trouble, and its `--dir` names a
  directory that cannot be used: absolute, a `..` chain, or something a shell would read as an
  instruction. `detail` is the refusal, **not** a directory — printing it as one is the whole defect
  (#343). The same value refused at the `.oss.json` entrance since #173 arrived unchecked through
  this one, and the directory printed here is the one the fold below deletes every fragment in. Say
  what was refused and stop. Do not repair the value: what its author meant is not on disk, and a
  repaired directory is a directory nobody named.
- `absent` — `NOT-ADOPTED` on stderr; say so and stop, exactly as before #299. Rolling fragments out
  to a repo is a change to that repo, a separate decision, not something this command does on the
  way past.
- `unknown` — this repo's tree could not be fully read, or the workflow's own `--dir` lines disagree
  with each other. Say what stopped the read and stop, the same as a genuine "not adopted" would,
  rather than guess a directory nobody confirmed.

**`changelog_dir` out of `.oss.json` is validated here too, and that is not belt and
braces (#343).** `changelog_dir_problem` is reached from `oss_config.validate()`, which
nothing on this path calls — so the value that reads as the *guarded* entrance arrived
here unchecked, exactly like the one read back out of the workflow. Both were measured
returning `/etc` with no complaint. Whichever route the directory came by, it is the one
`--dir` argument every command below is given, and the fold at the end of them unlinks
every fragment it consumes.

Anything printed on stdout is the directory to use for every command below.

## Check (default)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --check --dir "$FRAGMENTS_DIR" --changelog CHANGELOG.md
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

**An empty `$FRAGMENTS_DIR` is refused the same way a missing one is (#349).** The resolver
above captures its own refusal into the variable with no exit-status check, so a reader who
continues past a `REFUSED:` on stderr carries an empty string into the commands below as
`--dir ''`. `assemble_changelog.py` treats an empty `--dir` or `--changelog` as absent rather
than as `.` — the fold refuses loudly instead of silently scanning and consuming whatever cwd
happens to hold. Fixed at the callee rather than by adding `set -e` here, because the same
gap exists for any future caller of either copy of the script, in this repo or a scaffolded
one, not only for this command's own resolver.

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
Substitute `$FRAGMENTS_DIR` (from the derivation above, #299) for `changelog.d`; the versions
are validated as `x.y.z` before they are ever written into a workflow, so they carry nothing a
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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --version X.Y.Z --dir "$FRAGMENTS_DIR" --changelog CHANGELOG.md
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
