---
description: Add the missing repo furniture — CLAUDE.md, security policy, issue and PR templates.
allowed-tools: Bash
---

A maintained repo needs more than a loop pointed at it: a CLAUDE.md so the next agent starts
oriented, a security policy so a reporter knows where to go, issue and PR templates so a report
arrives with what it needs. These drift between sibling repos exactly the way the loop itself did —
one repo ends up with none of it, another with a differently-worded copy.

This is **not** part of `/oss:setup`. Setup writes one untracked local file and changes nothing
tracked, so it is safe to run anywhere. Scaffolding writes files *into* the repo, which is a real
change that wants a branch, a diff and a review.

## Show first

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" --root . --config .oss.json
```

Prints one line per file: `create` or `present`. **Nothing is written.**

The plan runs the same four checks the apply does, and one of them — `label` — reads the
repo's label list from the forge. So the preview is read-only but no longer strictly
offline: it can make one `gh` call, capped at 20 seconds, and it says so in the line when
it could not. That is the price of the preview reporting the same thing the apply will.

That names the plan but not the content, and the content is what actually needs a look. Get it with
`--show`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" --root . --config .oss.json --show
```

Prints the full body of every file `apply` would actually write — nothing written here, same as the
plan alone. That covers both halves of `apply`: files it would **create** (a template absent today)
and files it would **replace** (everything in OWNED — `.oss/README.md`, `.oss/assemble_changelog.py`,
`.github/workflows/oss-changelog.yml` — rewritten on every single run, whether or not a template is
missing). Each line says which: a repo that already has every default still gets three `replace`
lines out of a bare `--show`, because that is the destructive half of `apply` and the one a preview
is for. Name one file (`--show CLAUDE.md`) to see just that one, including a file already `present`,
when the question is what the default itself contains rather than whether it would be written.
`--show` and `--apply` refuse to run together — show, read it, then apply as a separate step. Relay
the plan and what each generated file would contain before going further — a default that nobody read
is not a default, it is a surprise.

## Then write

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" --root . --config .oss.json --apply
```

Only missing files are created. **An existing file is never overwritten** — the repo's own
SECURITY.md is a decision somebody made, and this ships a default. A default must not win against a
decision.

The full list, so a plan line is never the first time you hear of a file:

| File | What it is |
| --- | --- |
| `CLAUDE.md` | orientation for the next agent; carries the default branch and test command |
| `SECURITY.md` | where a reporter goes |
| `CODE_OF_CONDUCT.md` | the usual one |
| `.github/ISSUE_TEMPLATE/bug_report.md` | so a report arrives with what it needs |
| `.github/ISSUE_TEMPLATE/feature_request.md` | likewise |
| `.github/ISSUE_TEMPLATE/config.yml` | keeps blank issues enabled |
| `.github/PULL_REQUEST_TEMPLATE.md` | what a PR has to say |
| `.github/dependabot.yml` | weekly action bumps |
| `.gitignore` | the usual noise |
| `.supertool.json` | **changes your own tooling mid-session — see below** |
| `.oss/README.md` | the ownership table, stated inside the repo — **replaced every run** |
| `.oss/assemble_changelog.py` | the assembler CI calls — **replaced every run** |
| `.github/workflows/oss-changelog.yml` | the workflow that calls it — **replaced every run** |

The first nine are created once when absent and are yours afterwards. The last three are ours and
are rewritten on every `--apply`, which is why `--show` prints them as `replace` even in a repo that
already has everything.

## `.supertool.json` moves the ground you are standing on

`--apply` writes `.supertool.json` with `"presets": ["git", "github"]`, and roughly thirty `git-*`
and `gh-*` ops come into existence the moment it lands. **The op listing you are working from was
captured at session start, before that file existed, and is never refreshed.** The session that
installs the config is the one that cannot see what it installed.

What that feels like is a run of raw commands rejected one at a time — `gh label list`,
`gh issue create`, `git commit`, `git push` each bounced by the guard with the op named. The
messages are good and the guard is right; the cost is one round trip per discovery, and `ops` is
~30KB so the blind route is not cheap either.

Re-read the inventory once, immediately after `--apply`:

```bash
supertool 'ops-compact'
```

~2KB, and it is the only way the rest of this session knows what it can call.

One trap in the new inventory, because two adjacent ops take their target two different ways:
`gh-issue-create` reads the repo from its **payload** (`repo = "OWNER/NAME"`), not from a leading
`repo:` op, and defaults to whatever repo `.supertool.json` resolved from. Filing an issue about
this plugin from inside a scaffolded repo lands it in the wrong tracker unless the payload says
otherwise. supertool refuses the `repo:` op here rather than silently guessing — trust that refusal
and set it in the payload.

## Three contracts, and the repo can see which is which

| Kind | Where | On update |
| --- | --- | --- |
| **Yours** | everywhere else | never read, never written |
| **Defaults** | `SECURITY.md`, `CLAUDE.md`, `.github/ISSUE_TEMPLATE/`, `changelog.d/README.md`, … | created once when absent, then yours forever |
| **Ours** | `.oss/`, plus `.github/workflows/oss-changelog.yml` | replaced every run, so fixes reach the repo |

`.oss/README.md` states that table inside the repo, which is where somebody about to
edit a generated file is actually looking. Every owned file repeats it in its own header
and names the way out: copy it somewhere outside `.oss/` and point at your copy.

The workflow is the one owned file that cannot live in `.oss/` — a forge reads workflows
only from `.github/workflows/` itself, subdirectories are unsupported and a symlink there
fails outright. Hence the `oss-` prefix, so it is still obvious in a directory listing.

`.oss/assemble_changelog.py` ships into the repo rather than being called from the
plugin because CI checks out the repo and nothing else: a workflow calling a plugin path
is a red build on day one.

The generated workflow installs that script's parser before running it. Without the
install step the checker reports `skipped` and exits non-zero — which is the checker
being right and the job being red anyway. It is a gap a scaffolded repo cannot see in
itself: with zero fragments the checker reaches a verdict without needing a parser, so
the job goes green on the scaffold pull request and only fails on the first real change
after it. `.oss/README.md` names the same package for running the check on your own
machine, which CI does not cover.

The fragment directory the workflow polices is created alongside it, holding a
`changelog.d/README.md` that explains the naming. An absent directory is a *failure* to
the checker, not an empty one, so a workflow installed without it is red on the pull
request that installed it. The directory is `changelog_dir` from `.oss.json`, falling back
to `changelog.d/` when that is null — which is also the directory the generated workflow
names in that case, so the two cannot drift apart.

That README is a default like any other: created once when absent, never overwritten, and
previewable before it is written with
`--show changelog.d/README.md` (or your own fragment directory in place of `changelog.d`).

## What the run reports and will not do for you

Four checks run after the file list — `radar`, `label`, `ci`, `tests` — each naming
something measured and left alone, and each printing a line only when it has something to
say. They are printed before writing as well as after, so nothing in them is a surprise. A
line that is absent means that check came back clean — never that it did not run, which is
why every check here says so when it could not look.

`radar` — `.supertool.json` defines no radar tiers, so a session can receive channel
events and nothing publishes any. The line carries the block to add.

`label` — the generated workflow names `no-changelog` as the escape hatch for a change
users cannot see, and the run **checks whether the label exists**. Three answers, and the
third is the point of the check:

- **absent** — the line says so outright: the gate is installed and cannot be waived, on
  this pull request or any other, until the label exists.
- **present** — nothing is printed. There is no reminder to skim past.
- **not looked** — the line names *what stopped it*: `gh` is not on PATH, `.oss.json` has
  no `repo`, the checkout's `origin` is not that repo, or `gh` exited unauthenticated. An
  unchecked label is not an absent one, and neither is a pass.

The read is read-only, and it is gated on local facts before any network call: `gh` on
PATH, and `git remote get-url origin` naming the repo `.oss.json` does. `--root` can be
any directory, and a file-writing tool should not fire a request about whatever slug a
config happens to carry.

The label is still **not created**. The trade is not "intrusive versus restrained" — a
gate installed without its hatch is an incomplete install, and that objection is correct.
It is that every other thing this command produces is a file in a checkout: previewable
with `--show` before it exists, visible in a diff, revertible with git. A label has none
of the three, and `--apply` has no undo for it. Making `--apply` write to the forge would
also make it fail where scaffolding is most useful — an unauthenticated machine, a fork
you cannot administer — turning a working file write into a half-finished run.

So the affordance gap the check closes is the one that actually bit: nobody learned the
label was missing until the first pull request that needed it. Now the scaffold run says
it, at scaffold time, next to the command:

```bash
gh label create no-changelog --description "Change is invisible to users"
```

One command, once, and the `label` line goes quiet.

`ci` — `.oss.json` now describes a repo with no CI, because `ci.required_checks` was
derived before this run installed a workflow. **The value is not rewritten.** Counting
workflow jobs cannot see a check configured outside the repo — an organisation-level
required workflow, a branch protection rule, an app posting a status — so re-deriving it
would swap one unmeasured number for another, and a wrong count on disk is
indistinguishable from a measured one. Measure it from checks that actually ran:

```bash
gh api repos/OWNER/NAME/commits/<sha>/check-runs
```

then set it by hand. A value already set is left alone: that is a decision.

`tests` — if `.oss.json` carries a `test_command`, and no workflow runs it, the run says
so. A pull request in that repo goes green with its changelog fragment checked and its
tests not run at all, and `/oss:manager` merges on green — so green there is an absence
rather than a result. **No test workflow is generated.** The runner, the matrix, the
language version and whether a failure blocks a merge are all decisions nothing here has
measured, and a `ubuntu-latest` single-version guess shipped into a repo about
cross-platform behaviour would be actively misleading. The input to the *report* is
measured — `test_command` was executed and observed to pass — which is why it is stated
insistently and still not acted on.

`/oss:doctor` repeats the last two on every run.

## The rule layer is the exception, and deliberately so

The same run also installs `.claude/jit-context/<dimension>/01-oss/` — rules about this plugin's own
artifacts, so the fragment convention arrives when someone opens `changelog.d/` rather than sitting
in a command doc read at a moment when it does not apply.

**That layer is replaced wholesale every time.** Layers are the ownership boundary: `00-manual/`
belongs to whoever maintains the repo and is never read or written here, and `01-oss/` belongs to
this plugin. Owning it outright is what makes updates safe — a rule we stop shipping disappears
instead of surviving with nobody maintaining it, and nothing a human wrote is ever at risk, because
nothing a human wrote lives there.

Write your own rules in `00-manual/`. If you want to change one of ours, copy it there and edit the
copy; the next install will not fight you for it.

A symlink into the plugin checkout would have been simpler and is refused by the rules engine on
purpose — git carries symlinks, so a clone would need only one committed link to point rules at
anything on the machine.

Do this on a branch, and open a PR. Do not commit generated furniture straight to the default branch:
these are files everyone reads, and the review is the point.

## Description and topics

Files are only half the furniture. A repo also has a one-line description and a topic list, and both
are empty by default — an absence nobody notices, because it looks like every other new repo. They
are also the only thing a person sees before deciding whether to click.

```bash
gh repo view --json description,repositoryTopics
```

Feed the whole JSON object straight to `scaffold.check_metadata` and relay what it reports. It
reads topics from `repositoryTopics` — the shape `gh` actually returns — and says what is
**missing**; it never proposes a description or a topic. A finding can also come back `unknown`
rather than `missing`, when the probe did not carry a shape the function could check at all — that is
not the same as the repo having no topics, and it is relayed as "could not be determined," never
folded into a confident "missing." A generated description is written in the voice of a tool that has
not read the code, and a guessed topic list is how a repo ends up tagged for something it does not
do. Write them yourself:

```bash
gh repo edit --description '...'
gh repo edit --add-topic a,b,c
```

## What is deliberately not scaffolded

`.claude/settings.json`. That file registers hooks — writing it means arranging for code to run on
the machine of everyone who clones the repo. Scaffolding a policy document is a suggestion;
scaffolding a hook is not. If a repo wants hooks, that is a decision made in the open, in its own PR.

## After

The generated CLAUDE.md carries the repo's default branch and test command from `.oss.json`. If the
test command was not detected, it says so in the file rather than guessing — replace that paragraph
by hand. A guess in a CLAUDE.md becomes an instruction to every agent that reads it.

## Then name the next step

Once the furniture is in place, **`/oss:tick`** is the command it was put there for: one pass of the
maintainer loop — read the board, decide, delegate, review, merge on green. The templates, the policy
and the changelog gate are all things the loop assumes and none of them run anything by themselves.

Name it whatever the scaffold run reported, including a run where every file was already `present`.
`/oss:setup` closes by naming `/oss:scaffold` for the same reason: each command in this chain is
correct about itself and says nothing about what follows it, so a maintainer who stops here sees no
failure at all — a furnished repo, a clean run, and a loop nobody started.
