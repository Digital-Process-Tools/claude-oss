# Autonomy: what the loop reaches, and what it does not

This records the gap between what this plugin does today and what "autonomous in somebody else's
repository" would require. It is a record, not a design: it answers none of the open questions
below, because each of them is a decision about a repository this project does not own, and #237
was filed rather than built for exactly that reason.

## The goal, in two halves

1. This plugin maintains itself — triage, delegate, review, merge, release — with no human in the
   merge path.
2. Every repository that installs the plugin reaches the same state.

Half one is exercised on every tick. Half two has no runtime at all, and that is the finding.

## What is true today, derived rather than asserted

**Every workflow this repository runs, and every workflow it writes into a repository that installs
it, fires on `push` or `pull_request` — a human act. Nothing fires on a clock or on a dispatch from
outside. The one thing an install does start on a clock is a `.github/dependabot.yml` seeded once
when absent, and nothing in this plugin merges what that opens.**

Both halves are measured by `tests/test_unattended_triggers_237.py`. It reads the `on:` block of
this repository's own workflows and of every workflow in `scaffold.OWNED`, and fails three ways:
when an unattended trigger appears, when a workflow declares no human trigger either, and when a
workflow's trigger block cannot be read at all. The third is the one that matters — a sweep that
could not look must not render as a sweep that found nothing. The dependabot exception is checked
separately, and is checked at all because it is the counter-example: the first version of the
sentence above did not have it, and was wrong. A sweep whose scope quietly excludes the one case
that would contradict it reports the answer it was scoped to give.

The consequence follows from the ownership contract rather than from anything about scheduling.
The executable artifacts an install puts in a managed repository are the changelog gate — a
`pull_request`-triggered workflow and the assembler it calls — and that dependabot config.
Everything else the loop does is a slash command someone types into a session: `/oss:tick`,
`/oss:scaffold`, `/oss:doctor`, `/oss:release`.

The dependabot config is worth more than a footnote, because it is the shape of the whole problem
in miniature. It is a **default**: written once when absent, theirs forever after, deletable and
never handed back. It starts a weekly clock the repository's owner consented to by keeping the
file. And what that clock produces is pull requests that this plugin will never look at, because
nothing on the far side of the install reviews or merges anything. An unattended loop is not the
clock. The clock is the easy part, and one is already installed. What is missing is everything
that would have to be true for something to act on what the clock produced.

The measured reach of the install itself — how many repositories carry a config, how many carry the
furniture, and whether a drifted owned file has ever been repaired — is in `CLAUDE.md`'s
`## What is not proven yet`, re-derived at each release. It is deliberately not restated here. A
second copy is the one that drifts, and the numbers are the part most worth not having two of.

## The three things that would have to exist

Named as requirements, not as a proposal.

**A runtime.** Something on the far side of the install that executes without a human. Every
candidate is a commitment somebody else pays for: a workflow in their repository burns their CI
minutes and holds their token; a scheduled job on a maintainer's machine only reaches repositories
that machine knows about, which is not the same set as the repositories that installed the plugin.

**A grant.** Merging on green is granted in this repository. Tagging and publishing are granted in
this repository. Neither is granted anywhere else, and installing a plugin is not consent to have it
merge. Whatever an unattended loop is allowed to do has to be a thing the repository's own
maintainer said yes to, in a place this plugin can read, with a default of nothing.

**A liveness signal.** A loop that died and a loop that had nothing to do render identically from
outside — this repository's own defect class, pointed at its reach. Whatever runs unattended has to
report that it ran, distinguishably from having found nothing to do, or the whole thing is
unfalsifiable.

## The open questions, and what would settle each

None of these is answered here.

- **What is the unit of autonomy?** A scheduled session in the managed repository, a workflow this
  plugin owns and installs, or something a maintainer's machine runs across every repository it
  knows about. Settled by deciding whose compute and whose credentials pay, which is a decision
  about somebody else's repository.
- **What may an unattended loop do?** Settled by a consent mechanism with a default of nothing, not
  by a better brief.
- **How does a managed repository report its loop is alive?** Settled by a signal with three states,
  where "no signal" is loud rather than absent.
- **What is the smallest thing that would move reach?** Genuinely open. The candidate this
  repository can already see is repair rather than reach: nothing has been observed clearing a
  drifted owned file anywhere, so the ownership contract's promise that fixes reach everyone is
  half-proven, and a repaired copy would be the first evidence for the half that is not.

## Deliberately out of scope

- **Any answer to the four questions above.** Each is somebody else's repository.
- **Building a runtime, a consent mechanism or a liveness signal.** Those are separate issues with
  separate reviews; a document is not the place to smuggle in a design.
- **Anything about the quality of the loop's decisions.** Whether the triager labels well or the
  reviewer catches bugs is a different subject; this is only about whether anything runs.
- **A number for reach.** `CLAUDE.md` holds it, and holding it twice is how it goes stale.
- **Scheduling on the maintainer's own machine.** Out of scope for this document because it is not a
  property of the plugin: two maintainers running the same install would have different answers, and
  a fact about one machine does not live in shared code.

## When to re-derive this

When `tests/test_unattended_triggers_237.py` fails, and only then, for the derived half. That is the
point of it being derived: the first workflow that fires on a clock reddens the suite with a message
naming this file, so the document cannot go quietly stale the way an unguarded claim does. Everything
above the derived sentence is argument, and argument is re-opened by disagreeing with it rather than
by a test.
