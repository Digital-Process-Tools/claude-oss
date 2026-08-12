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

## Show, then write

Print the derived config and what each value was derived *from*, then ask before writing. A config
the user has not seen is a set of assumptions nobody reviewed.

Write it to `.oss.json` in the repo root, and add it to `.git/info/exclude` rather than `.gitignore`
— the target repo's tracked files must not change. Confirm afterwards that `git status` is still
clean.

## Then

Run `/oss:doctor` and relay the verdict. Setup that has not been verified is a claim.
