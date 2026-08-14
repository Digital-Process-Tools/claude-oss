---
description: Probe this repo and write .oss.json — the per-repo config the maintainer loop reads.
allowed-tools: Bash
---

Write `.oss.json` for the repo in the current directory, by **measuring it**, not by asking.

## Probe

**Do not assemble the probe by hand.** `--probe` measures the repo and writes it, and
`--build` reads that and nothing else. One implementation of the schema is the point:
a hand-written probe listing `files` as top-level directory entries produced
`test_command: null` and a `version_sites` list with the wrong file in it, and nothing
at any layer reported a problem.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_config.py" --probe . | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_config.py" --build
```

`--probe` shells out to `git` and `gh` itself. If it cannot measure something it says
so and writes no probe at all — half a probe is the underspecified probe this replaced.
Relay the `FAIL` line rather than filling the gap in by hand.

Run the two separately when you want to look at the probe first; `--help` prints the
full schema, including what `files` and `version_evidence` mean:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_config.py" --help
```

`--build` prints `NOTE` lines on stderr. **Relay them.** They are the absences the
config cannot show:

- **`N of M labels matched no priority or lane pattern`** — with the names. An empty
  `priority` list is the honest answer on a repo with no priority labels *and* what a
  pattern miss produces; the note is the only thing that tells the two apart. If the
  repo has a priority vocabulary spelled some way the patterns miss, say so — that is
  a decision for the human, not something to paper over by writing the labels in
  yourself.
- **`could not read, so not claimed as version sites`** — a candidate file that could
  not be read. Not the same as one read and found to hold no version, which is dropped
  silently and correctly.

The rules that matter, all enforced by `scripts/oss_config.py`:

- **Label spellings come off the repo.** One repo spells it `priority-high`, a sibling spells it
  `priority:high`. Never write a label name you have not seen in the probe's `labels`, which holds
  them as the repo spells them. Not `gh-labels`: that op is provided by a preset, presets load from
  `.supertool.json`, and the repo being onboarded does not have one — not having it is what makes it
  a repo to onboard. `--probe` calls `gh` directly for this reason.
- **A repo with no labels gets empty lists.** Not a plausible default set. An invented value is
  indistinguishable from a measured one once it is on disk, and it will reach a brief with the same
  authority.
- **A repo with no milestones does not get milestones.** Say the list is empty.
- **An undetectable test command stays `null`.** `null` is an honest "I could not tell"; a guess is
  a wrong instruction with an agent attached.
- **A version site is a file that was read and found to carry a version.** Existence is not
  evidence. Every repo has a `README.md`, and most of them carry no version anywhere — listing it
  tells `/oss:release` to bump a file with nothing to bump. `--probe` reads each candidate; you do
  not need to check them yourself.

## Verify the test command before writing it

Detection reads a marker file and infers. **Run it.** A detected command that does not
work is a confident wrong config, and the next thing to find out is an agent that was
told to use it.

```bash
python3 -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts'); import oss_config, json; print(json.dumps(oss_config.verify_test_command('<detected>', '.')))"
```

Four states, each with a different remedy — relay which one:

| State | Means |
| --- | --- |
| `ok` | ran and passed; write it |
| `failed` | the suite ran and did not pass. The command is probably right and the repo is red; say both |
| `not-found` | the runner is not installed here. Nothing to conclude about the suite |
| `timeout` | **unverified**, not broken. Saying broken sends somebody to debug a suite that is merely slow |

Write the command on `ok`. On anything else, say what happened and let the human
decide — a `null` they chose beats a value they did not.

## Show, then write

Print the derived config and what each value was derived *from*, then ask before writing. A config
the user has not seen is a set of assumptions nobody reviewed.

Write it to `.oss.json` in the repo root, and add it to `.git/info/exclude` rather than `.gitignore`
— the target repo's tracked files must not change. Confirm afterwards that `git status` is still
clean.

## The dependencies install themselves; they do not configure themselves

`supertool`, `remember` and `claude-jit-context` are declared dependencies, so they arrive with the
plugin. Arriving is not the same as working, and the gap is invisible:

- **Memory with no identity** still runs and still saves. What it cannot do is record whose sessions
  these are. The file goes at `<repo>/.remember/identity.md`, and the reason it is safe there is
  measured rather than assumed: the memory plugin writes a `.gitignore` containing `*` into that
  directory when it creates it, so the store is untracked by construction and seeding identity
  publishes nothing.

  **Confirm that before writing, and do not write it anywhere else.** The hazard is real — identity
  is per-user, and committing it publishes one developer's setup to everyone who clones — but the
  hazard lives in *tracked* locations. `.claude/` is partly tracked in a scaffolded repo, so an
  identity file landing there is one `git add .` from being published, and it would not be read
  anyway: the session-start hook looks in the store, then at the store's parent, then at the
  plugin's own directory. In a normal install none of those is `<repo>/.claude/remember/`. Check
  `git status` after writing; the file must not appear.
- **Rules with no built index** never fire, because the matcher reads the index rather than the
  markdown — and a rule that never fires is indistinguishable from one that fired and had nothing to
  say. Rules live per dimension and per layer, and **each layer carries its own index**; rebuild it in
  the same change that adds a rule, then confirm the row is there.

  The rules plugin ships an example per dimension and documents the frontmatter each one takes. Point
  people at those rather than at a copy — a second explanation of someone else's format is a second
  thing to keep in step, and it goes stale without anything failing.

`/oss:doctor` reports both, with `WARN` for the memory gaps and `FAIL` for a missing or empty index,
naming the layer.

## Then

Run `/oss:doctor` and relay the verdict. Setup that has not been verified is a claim.
