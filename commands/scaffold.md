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

Three lines after the file list, each naming something measured and left alone. They are
printed before writing as well as after, so nothing in them is a surprise.

`label` — the generated workflow names `no-changelog` as the escape hatch for a change
users cannot see. That label is **not created**. Writing a file into a checkout is a
change somebody reads in a diff and reverts; creating a label changes their repository on
the forge, from a command they ran to write files. Create it once, yourself:

```bash
gh label list | grep no-changelog
gh label create no-changelog --description "Change is invisible to users"
```

Feed a real label list to `scaffold.check_changelog_label` if you want the state rather
than the reminder — it answers `missing`, or nothing, or `unknown` when the list could
not be read. An unchecked label is not an absent one.

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
