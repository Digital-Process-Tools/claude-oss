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

Setup does end by running the **plan** below — the read-only invocation, never `--apply` — so the
furniture gap reaches the maintainer measured rather than recommended (#136). The plan writes
nothing, so that costs the boundary nothing. Every write lives here.

## Show first

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" --root . --config .oss.json
```

Prints one line per file — `create` or `present` for a template, and `replace` or `decline` for each
of the three OWNED files, which this bare invocation reports on every run and not only under
`--apply`. **Nothing is written.** A repo that already has every default still gets three `replace`
lines here; that is the destructive half of the apply, previewed.

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

The owned changelog trio follows the same rule from a different direction: before writing it, the
run looks for a changelog gate this repo already runs under a different name — another workflow
mentioning `assemble_changelog`, naming the fragment directory, or referencing the `no-changelog`
label; or an `assemble_changelog*` file anywhere in the tree. A hit **declines** the trio instead of
writing it, and prints why, next to a `changelog` finding that names what it found. Two gates
checking the same thing on every pull request — two jobs both named `fragment`, two assemblers, a
check count that moves by one with nothing pointing at it — is not a corrected default, it is the
defect #86 and #105 both filed. `--force-owned` writes the trio anyway, for a maintainer who checked
the match by hand and decided it is not a real conflict; nothing here creates that decision for you.
A workflow that could not be read counts the same as one that matched — the direction that matters is
never writing a second gate on top of a working one, so an unreadable file is treated as a possible
collision rather than a clean repo.

Same for a **directory** the walk could not enter (#124). That used to be unreportable rather than
untreated: `Path.rglob` swallows a permission error mid-walk and simply yields nothing for the
subtree, so "read the whole tree, no gate here" and "could not finish reading the tree" arrived as
the identical answer and the trio was written on the strength of it. The walk now names what it
could not enter, and the plan `decline`s with that as the reason.

The same walk stopped counting things that are not gates. Derived and vendored trees are not
evidence that anything runs — the skip list already said so for `dist`, `build`, `node_modules` and
a virtualenv, and `__pycache__` was the Python one it was missing, so a gitignored
`assemble_changelog.*.pyc` used to decline the trio on its own once the source beside it was
deleted. Skips now match at every depth rather than on the first path component. A dangling symlink
is not a gate either; a name that cannot be stat'd at all is reported as unreadable rather than as
one.

`--force-owned` overrides that too — an unreadable subtree is a fact about the process's privileges,
not about the repository, and the maintainer holding the credentials it lacks is exactly who can
settle it. But the two overrides are **not** the same decision and the receipt says which one you
made: forcing past a gate that was seen reads *overrides the changelog gate detected under a
different name*, and forcing past a tree that was not fully read reads *overrides an incomplete read
of this repository … the collision check could not run — it was overridden, not answered.*

All three paths honour the flag (#125). It reached `--apply` alone until then, so the dry run printed
three `decline` lines each advising the flag that had just been passed, and `--show` previewed
nothing for the three files the next command was about to overwrite — which is precisely the preview
a maintainer runs *because* they are about to force past a collision.

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

`--apply` writes `.supertool.json` with `"presets": ["git", "github", "watch"]`, and roughly thirty
`git-*` and `gh-*` ops come into existence the moment it lands. `watch` is in that list because it
is what provides `radar`: the template registers a radar tier, and until #191 it registered one with
no route to the op that reads it, so every scaffolded repo got a board that could never publish and
looked exactly like one that did. Loading the preset spawns nothing — the ops become available and a
poller starts only when something asks for one. **The op listing you are working from was
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

"Replaced every run" is the whole delivery mechanism for a fix to one of these files, and
nothing schedules the run. `/oss:doctor` is what closes that gap: its `owned files` lines
say whether re-running here would change **what a file does** — naming the regions, such as
`on.pull_request.types` — or only its comments and prose, so the maintainer can tell a
broken changelog gate from a reworded paragraph before deciding. It does not claim to know
whether a difference means their copy is old or means somebody edited it; nothing in a
managed repo records which plugin version wrote the file. Re-running discards a deliberate
edit either way, which is what the ownership table above already says and what the doctor
line repeats at the moment it matters.

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

Four checks run after the file list — `radar`, `label`, `tests`, `changelog` — each naming
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

When the origin names some other repo, the reason line quotes it with any userinfo and
any query string redacted — a remote can carry a token in either, and this line is the one
most likely to be pasted somewhere. A spelling whose credentials could not be recognised
is reported as not shown rather than quoted. The neighbouring arm, where git could not
read the origin at all, redacts the same shapes out of git's own error text, but it prints
that text rather than withholding it: suppressing the line would cost the reader the error
itself.

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

`tests` — if `.oss.json` carries a `test_command`, and no workflow runs it, the run says
so. A pull request in that repo goes green with its changelog fragment checked and its
tests not run at all, and `/oss:manager` merges on green — so green there is an absence
rather than a result. **No test workflow is generated.** The runner, the matrix, the
language version and whether a failure blocks a merge are all decisions nothing here has
measured, and a `ubuntu-latest` single-version guess shipped into a repo about
cross-platform behaviour would be actively misleading. The input to the *report* is
measured — `test_command` was executed and observed to pass — which is why it is stated
insistently and still not acted on.

`changelog` — this repo already runs a changelog gate under a different name, so the owned trio
was **declined**: not written, and named as such in the plan (`decline` rather than `replace`) as
well as here. Detected the same way as everywhere else in this file — measured, three states, never
a guessed absence — from another workflow mentioning `assemble_changelog`, the fragment directory, or
the `no-changelog` label, or an `assemble_changelog*` file anywhere in the tree. The third state is
reachable: a directory the walk could not enter reports as *could not determine*, which is not the
same as a repo with no gate. `--force-owned` overrides both, and the finding then says the trio was
written anyway rather than continuing to claim it was not. See "Only missing files are created"
above for the full contract.

`tests` reports a third state from the same walk: `.github/workflows/` that cannot be listed no
longer reads as a repo with no CI, and `test_command … and nothing in .github/workflows/ runs it` is
no longer printed about workflows nothing read.

That third state is one name over three situations — the directory would not open, a name in it
would not stat, or a file would not read — so each path it names now carries which one it was:
`.github/workflows/ci.yml (file-unreadable)`. Two of the three name the *same* path, and printing
the path alone made them the same sentence, which is a different thing to go and check in each case.
The state stays one because the remedy is one; the cause travels beside it, and on the finding as a
machine-readable `causes` list (#134).

There is no longer a `ci` finding about a leg count. It reported `ci.required_checks` as stale, and
#113 deleted that key rather than guarding it — the only quantity derivable offline is the workflow
*job declaration* count, which a build matrix, a reusable workflow or an organisation/app-level check
multiplies or adds to invisibly. This repo's own config was the proof: three declarations against
fourteen check runs. Count the legs on the pull request, with `gh pr checks`.

`/oss:doctor` repeats the `tests` finding on every run, and adds one of its own when `.oss.json`
still carries the deleted `ci` block.

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

**The layer ships whole, and the changelog rule is told why the checker is not there.** Since #117 the
run hands `oss_rules.install()` the same gate detection the trio's decision came from, and the rule's
could-not-locate branch renders one of four sentences rather than one:

| What the run established | What the rule says |
| --- | --- |
| no gate under another name | `/oss:scaffold` vendors the checker; run it and this rule is rewritten |
| a gate under another name | `/oss:scaffold` **will not put one here** — it declined, it declines again, and this rule does not know that gate's command. Read what it names — one file or several, and possibly a note about part of the tree that could not be read; `--force-owned` installs ours alongside |
| the tree could not be fully read | why it is missing is **unknown**, which is not the same as this repo having no gate. It declines again until the read succeeds |
| nothing checked | why it is missing **was not established** — running the scaffold may or may not rewrite this rule |

The rule is not omitted in the declined case, which was the other candidate shape: an omitted rule
leaves the reader with no statement at all, where the defect was a statement about a *different*
repository. The layer's own ownership contract is unchanged — it is still replaced wholesale.

What this composition produced before #117 is worth keeping in view, because neither half contained
it. `/oss:scaffold` declined the trio (#116/#126), and the rule told every reader that
`/oss:scaffold` vendors the checker and would rewrite the rule — naming the command that had just
declined and would decline again. The sentence was false in exactly the repo the decline creates, and
rendered identically to the same sentence in a repo where it is true.

`--force-owned` is the one case where the gate state is deliberately not passed through: the trio was
*written*, so a `found` reaching the rule would report a decline that did not happen.

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
Each command in this chain is correct about itself and says nothing about what follows it, so a
maintainer who stops here sees no failure at all — a furnished repo, a clean run, and a loop nobody
started.

**This seam is still carried by prose, and that is a weaker guarantee than the one upstream of it.**
`/oss:setup` no longer merely names this command: since #136 it ends by running this command's own
read-only plan, so the furniture gap arrives there as a measured list. The same treatment does not
transfer here, because a tick is not read-only — it comments, labels, delegates and merges — and so
it **cannot be previewed**. There is no dry run to print, which means nothing here can measure
whether the loop was ever started. A repo that stops at this line looks exactly like one that ran a
tick and found nothing to do, and no check in this repository can currently tell those apart. Said
out loud so the closed seam upstream is not read as both seams closed.
