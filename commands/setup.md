---
description: Probe this repo and write .oss.json — the per-repo config the maintainer loop reads.
allowed-tools: Bash
---

Write `.oss.json` for the repo in the current directory, by **measuring it**, not by asking.

## Probe

Batch these. Every value below is observed; nothing is assumed.

```bash
supertool 'gh-labels' 'ls:.' 'ls:.github/workflows' 'ls:tests'
gh repo view --json nameWithOwner,defaultBranchRef
gh api repos/OWNER/REPO/milestones -q '.[].title'
```

Then derive the config:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_config.py" --help
```

The rules that matter, all enforced by `scripts/oss_config.py`:

- **Label spellings come off the repo.** One repo spells it `priority-high`, a sibling spells it
  `priority:high`. Never write a label name you have not seen in `gh-labels` output.
- **A repo with no labels gets empty lists.** Not a plausible default set. An invented value is
  indistinguishable from a measured one once it is on disk, and it will reach a brief with the same
  authority.
- **A repo with no milestones does not get milestones.** Say the list is empty.
- **An undetectable test command stays `null`.** `null` is an honest "I could not tell"; a guess is
  a wrong instruction with an agent attached.

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
  these are. Fix it where the memory store lives — **never in the target repo**: identity is
  per-user, and committing it publishes one developer's setup to everyone who clones.
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
