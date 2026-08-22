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
- **Three separate notes about version candidates**, and they are three different
  facts (#396). None is the same as a candidate read and found to hold no version,
  which is dropped silently and correctly.
  - **`in the index and not on disk`** — `git ls-files` reports the index and the
    probe reads the working tree, so this is what an uncommitted delete looks like.
    Nothing was wrong with the read; there was nothing to read. Until #396 this
    printed *could not read* about a file that was simply not there.
  - **`are on disk and could not read`** — the file is there and its bytes did not
    come back. The tool failed to answer: a mode bit, an encoding, a filesystem.
  - **`read completely and their contents are not the shape the file type promises`**
    — every byte arrived and the structure is wrong, a `.json` that is not JSON or
    that is not an object. A fact about the file, not about the read.
- **`worktree_root: ...` / `state_file: ...` — a guess from a naming convention, not
  something measured on disk** — neither has a filesystem signal to measure on a repo
  being set up for the first time. If the repo has been onboarded before under a
  different layout, the emitted path is very likely wrong; check what is actually
  there before trusting it (#85).

**If a file already stands where `state_file` points, read it before the first tick.** A repo
that ran a maintainer loop before this plugin existed has a history in whatever shape that loop
wrote — the one seen in the wild is an object keyed `tick_<ISO>`, and `/oss:tick` needs a list of
entries. Setup is not the place to convert it: setup is a one-shot step, it does not see the file
on a repo it has already onboarded, and the conversion is somebody's history rather than a
default. Ask instead, and if the answer is yes, run the conversion where its receipt is visible:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py" <state_file> --migrate
```

It keeps the original at `<state_file>.pre-migration`, reads that copy back and compares it before
it writes anything, refuses rather than overwriting an earlier one, and refuses any shape it would
have to guess at. The converted file is written beside the original and renamed over it, so a
failure leaves the original as it was rather than truncated (#174). `/oss:doctor` reports the same
thing at any later point, and so does step 1 of a tick (#149).

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

## Show, then write — two files, not one

Print the derived config and what each value was derived *from*, then ask before writing. A config
the user has not seen is a set of assumptions nobody reviewed.

Write the derived config to `.oss.json` in the repo root, then split it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_config.py" --split .oss.json
```

That leaves two files, and which key goes where is the plugin's decision rather than each
maintainer's:

| File | Scope | Keys | Git |
| --- | --- | --- | --- |
| `.oss.json` | the project | `repo`, `default_branch`, `branch_pattern`, `test_command`, `version_sites`, `changelog_dir`, `docs_targets`, `labels`, `ci`, `milestones`, `release` | **tracked** — `git add` it and commit it in review |
| `.oss.local.json` | this machine | `clone`, `worktree_root`, `state_file` | git-excluded, never shared |

The reason the release block cannot stay local: `/oss:release` reads `tag_pattern`, `merge_method`,
`commit_subject`, `version_sites`, `changelog_dir` and `triggers`, and every one of them is a fact
about the repo. Held in one untracked file, the second maintainer to cut a release has none of them,
is asked for `tag_pattern` by the command's own stop-and-ask, and can answer differently. A repo
tagged `v1.2.3` then acquires `1.2.4` — the second tag namespace this plugin warns about, opened by
the plugin. `.git/info/exclude` is also not copied by `git clone`, so a fresh clone inherits neither
the file nor the exclusion.

`--split` repoints `.git/info/exclude` for you: `.oss.local.json` in, `.oss.json` out. It never runs
`git add` — the project half is meant to be reviewed, so committing it stays a human act. It is
idempotent, so it is also the migration for a repo that already has a combined `.oss.json`: run it
once and commit the result.

**A second maintainer on a repo that already has a committed `.oss.json`** runs this same command
unchanged. `--split` writes their `.oss.local.json` and rewrites the project half in place; review
that diff before committing, because a project half that changed is a finding about the repo rather
than about their laptop.

Confirm afterwards that `git status` shows `.oss.json` and nothing else — no `.oss.local.json`, no
stray file.

## The dependencies install themselves; they do not configure themselves

`supertool`, `remember` and `claude-jit-context` are declared dependencies, so they arrive with the
plugin. Arriving is not the same as working, and the gap is invisible:

- **Memory with no identity** still runs and still saves. What it cannot do is record
  **who the agent is** in this repo — its name, voice, values, and what it has learned here.
  That is the subject of the file: not the human maintainer, not their name or org or role. A file
  describing the human is a well-formed answer to the wrong question: it is written, `git status`
  stays clean, and every check in the loop reports the identity gap as closed. The memory plugin
  ships an `identity.example.md` — seed from that and edit it, rather than reconstructing the format
  from a second description here.

  The file goes at `<repo>/.remember/identity.md`, and the reason it is safe there is
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

## Settle the merge permission now, not at the merge

`gh-pr-merge` is the only op the loop uses that writes, and the harness's permission layer decides
whether it may run. If nobody has told the harness about it, the first time anyone finds out is at
the merge step — gates all satisfied, review already spent, nothing to do but stop. **Ask the
maintainer to add the rule; do not write it for them.** A permission grant arranged without asking
is the tool deciding on an irreversible action, which is not this command's job.

The rule goes in `.claude/settings.local.json`, not `.claude/settings.json`, for the same reason
`.oss.json` and `.oss.local.json` split: it carries an absolute path off one person's disk. That
file is machine scope and untracked; committing it publishes one laptop's layout to everyone who
clones, and it would be wrong for all of them.

Matching is on the **literal command string**, so a rule has to cover how the call is actually
spelled — and the loop spells it two ways:

| Where the call runs | How the binary is spelled |
| --- | --- |
| the clone | `./supertool` |
| a worktree | an absolute path to that same binary — `./supertool` does not resolve there |

A rule written for one spelling does not cover the other, and the loop uses both within a single
tick. The rule itself is a `Bash(...)` allow entry naming the binary and the op; the quickest way to
get it exactly right is to let the harness's own permission prompt or `/permissions` write it, then
confirm it landed in `.claude/settings.local.json` rather than the tracked file.

Two more literal-string traps, each worth a round trip to rediscover:

- `gh-pr-merge:N:squash` and `gh-pr-merge:N:squash|force` are **different strings**. Approving the
  first does not carry to the second, and the second is the one that merges — without `|force` the
  op previews and writes nothing.
- A rule is one input to the decision, not the decision. An entry that matches does not guarantee
  the call is permitted, and no entry does not guarantee it is refused.

**The harness permission is a separate, fourth gate**, sitting in front of supertool's own three
opt-outs (`|force` per call, `SUPERTOOL_NO_PUBLISH_CONFIRM=1` per environment, `no_publish_confirm`
per project). Say this out loud at setup, because the obvious move when a merge comes back denied is
to widen a supertool setting — and that setting was never the thing refusing. `/oss:doctor` reports
which state this is in, and there are four rather than the obvious two: a rule naming the op is
present, a rule naming it is a **deny** rule, none names it at all, or the settings files could not
be read. The last one is not the third one — "I could not look" sends you somewhere different from
"there is nothing there" — and doctor reports the rule either way, never the decision.

## Then

Run `/oss:doctor` and relay the verdict. Setup that has not been verified is a claim.

## Then measure the furniture rather than recommending it

Setup writes nothing tracked, which is exactly what makes it safe to run anywhere and also why it
leaves the repo half-furnished: config on disk, and no CLAUDE.md, no security policy, no issue
templates, no changelog gate. Naming the next command does not close that — a setup that stopped
here and a setup that completed render identically: clean run, clean `git status`, half-furnished
repo, no warning anywhere. So end by **running** the read-only plan:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" --root . --config .oss.json
```

**Run it unconditionally**, and relay what it printed. Not "only when something looks missing" —
whether something is missing is the thing this run is measuring, so gating on it means deciding the
answer before asking. A `PLAN: 0 to create` line does carry information: it separates *furnished*
from *nobody looked*, which are the two states this repo is named after confusing.

**Never `--apply`, and never from here.** This command writes one untracked local file; the flag
that writes tracked files belongs to `/oss:scaffold`, on a branch, with a diff and a review. That
boundary is the working part of the split and running the plan is what keeps it — the maintainer
gets the measured gap without anything being written for them.

### The three outcomes, and the third is the point

| What the run printed | What it means | What to say |
| --- | --- | --- |
| `PLAN: N to create …`, N ≥ 1 | measured gap | relay the `create` lines verbatim, then name `/oss:scaffold` |
| `PLAN: 0 to create …` | furnished, and checked | say so, and still name `/oss:scaffold` — the owned files are replaced on every run, so a repo scaffolded before they existed is furnished and stale at once |
| a `FAIL` line, a non-zero exit, or no output at all | **could not plan** | say the furniture gap is *unmeasured*, and why |

The third row is not the second one. *Nothing to do* and *I could not look* are opposite facts, and
collapsing them here is the same defect this plan was added to close, one layer up.

**A plan that could not run is not a failed setup.** By this point `.oss.json` is on disk and
correct; the config write and the furniture measurement are two things, and only the second one
failed. Report it that way — "config written, furniture gap unmeasured because X" — because a run
reported as failed sends the maintainer to re-run the half that already worked.

### Which lines are offline and which one is not

The per-file lines — `create`, `present`, `replace`, `decline`, `remove` — and the `layer` lines
beside them are **read from the filesystem**, so they answer on a machine with no network at all.
(`remove` and `layer` arrived with #182, which taught the plan to preview the `01-oss` rule layer;
they are local reads like the rest.) The findings printed underneath are not uniformly
local: the `label` finding is the **only line that asks the forge**, one `gh` call capped at 20
seconds, and it degrades to its own stated `unknown` with a reason rather than to silence or to a
guess. The `radar` and `tests` findings beside it are local reads like the plan itself.

So an unreachable forge does not make the furniture gap unmeasurable — it makes one finding
unmeasured. Relay them as the two different things they are. A `label` line that could not answer
must never be relayed as a furniture verdict, and a furniture verdict must never be withheld because
that line could not answer.

### Then name the next step

Name **`/oss:scaffold`** whatever the plan and the doctor verdict said. Scaffold is a separate
command because it writes tracked files, and tracked files want a branch, a diff and a review rather
than a command that has already run. The plan above is what makes naming it a measurement with a
recommendation attached, rather than a recommendation on its own.
