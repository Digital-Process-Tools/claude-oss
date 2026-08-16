---
description: Cut a release — gates first, then version sites, tag, and the surfaces it actually reached.
allowed-tools: Bash, Agent, Skill
---

Read `.oss.json`'s `release` block for what this repo does: `tag_pattern`, `commit_subject`,
`merge_method`, `triggers`. It is the tracked half of the config, so it is the same block for every
maintainer; the git-excluded `.oss.local.json` beside it holds only this machine's paths and nothing
release reads.

Two of those keys may be null, and they are handled differently on purpose:

- **`tag_pattern: null` — stop.** The probe could not tell how this repo tags, and inventing one
  opens a second tag namespace nobody notices until a release goes missing from it. Ask, then write
  it into the config. A wrong tag is permanent.
- **`commit_subject: null` — use `chore(release): {version}`.** That is the plugin's default, not a
  line for you to compose: a subject invented per release is an absence the tool produced, rendered
  as a value. Substitute the version being released. Nothing to ask about, because a wrong subject
  line is cosmetic and the next commit fixes it — which is exactly why this one gets a default and
  `tag_pattern` does not.

Load the loop for the judgment behind each gate:

```
Skill(manager)
```

## The gates are not configurable

Nothing in `.oss.json` can switch one off. Each is a call, not a feeling:

1. **The default branch is green at leg level for the exact commit being tagged.** `supertool
   'gh-branch'`, which is conjunctive over every workflow on the head SHA. Count the *workflows*,
   not the runs — and read the answer in **three** states, because that is how many the op gives
   you and how many the world has:

   - **covered and green** — the workflow ran on this commit and every leg passed.
   - **declared, and could not have run on this commit** — its triggers do not include the event
     that produced the commit. The op says so in as many words, under *Declared in
     .github/workflows at this commit with no run on it*. Not a pass and **not a blocker** — but it
     **contributes no coverage**, so a commit where every declared workflow lands here is
     **uncovered, not green**, and gate 1 is not satisfied by it.
   - **declared, should have run, and did not** — `UNKNOWN`, and it **blocks**. This is the state
     the two-state sentence this replaces was written for, and it is unchanged and just as strict.

   Two states over an op that answers in three collapses the middle onto an outside, and both
   collapses are wrong the same way. Read as `UNKNOWN` it blocks every release a repository with a
   `pull_request`-only workflow will ever cut — which is structural, not transient, so the block
   never clears. Waved through, it takes the third state with it, because at the point of decision
   a workflow that was silently skipped looks exactly like one that could not have run.

   **Name the middle state in the release report, and say where its coverage did come from.**
   *"Tagged with `<workflow>` not covered on this commit, covered on each pull request"* is a
   sentence a reader can check; silence about it is indistinguishable from not having looked, which
   is the whole of this plugin's defect class pointed at its own gate. The workflow name comes out
   of the op's own output at the moment you write the report — the placeholder above is a
   placeholder deliberately, because a name typed into this file is the remembered verdict below
   arriving one paragraph early.

   **Re-read it from the op on every release; never carry the verdict forward** and never write
   down which workflow it was. *No push trigger* is a measurement of an `on:` block somebody can
   change, and on the day it changes the workflow moves from the middle state to the blocking one
   with nothing announcing it — a remembered verdict then waves through the one case the gate
   exists for. Which workflow it is, is a per-repo fact and belongs in no document here.
2. **Nothing in flight is mid-review.**
3. **A security audit of the delta since the last tag passed.** Three outcomes: clean, findings, or
   **could not run**. An audit that did not execute must never render as an audit that found nothing.
   **Two rounds, hard cap** — a competent audit of any non-trivial delta always finds something, so
   an unbounded "findings, therefore stop" makes every release hostage to diminishing returns. After
   round two, file the rest against the next milestone and ship.

   **Except a finding in a row the ranking table marks blocking, which is not carry-forward
   material.** It stops the tag in either round. Each finding comes back carrying its row, so this is
   a read rather than a judgement — and without it the cap outranks the table by being later in the
   document, which makes the gate's worst outcome a filed issue.

   **A finding can also arrive with no row at all, and that is not the same as a row that does not
   block.** `${CLAUDE_PLUGIN_ROOT}/agents/auditor.md` defines the two rowless answers a finding can
   carry instead of a row, and they are deliberately different answers. Read as one, the cheaper of
   the two swallows the other and the gate re-creates a layer down the defect it exists to catch — so
   the arms are separate here, and each one is stated rather than left to the omission above:

   - **`unranked` — the agent classified it and no row fits.** Rank it **here**, before the cap is
     applied to it, and let the row decide from there: put it in a row, or earn it a new one in the
     table. **The cap does not reach a finding that has no row yet**, so nothing is ever carried
     forward unranked. The rows are a record of what has already gone wrong rather than a partition
     of what can, so a finding outside all of them has an *unknown* cost, and the escape hatch is
     deliberately the productive one: the table grows by exactly the rows that were missing.
   - **`could not rank` — the ranking table never reached the agent.** Nothing was ranked, so the
     audit did not complete: that is **`could not run`, and it stops the tag**, the same contract as
     a spawn that never started. Re-dispatch with the ranking table pasted into the payload verbatim
     and record that you did — that is how the answer gets computed, not an extra round. A rank
     nothing computed says nothing whatever about the finding, and must never be read as a row that
     happens not to block.

   The range is computed before anyone judges it, because "could not run" is a fact about the
   repository and not a reading:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_delta.py" --repo . --json
   ```

   It reads `release.tag_pattern` out of this repo's `.oss.json` itself and derives the tag glob
   from it — `v{version}` becomes `v*`. **Do not compute that glob and interpolate it into the
   command.** A value you are told to substitute is a value you can substitute wrongly, and a wrong
   glob answers confidently about the wrong range. `--match` exists to override the derivation and
   `--config` to point at another file; neither is part of the normal call.

   - **exit 3, `could-not-run`** — no commits, a shallow clone, or tags HEAD cannot reach. That
     **stops the release**. Report the reason it gave; do not spawn the audit over a range you
     picked instead, and do not read the gate as satisfied because nothing objected.
   - **`first-release`** — no tag exists, so this is a **first release** and the delta is the whole
     history reachable from HEAD. A named state, not an empty diff: it is audited like any other
     range and it permits the release once audited. Inventing a tag so a previous one exists is a
     history nobody made.
   - **`delta`** — audit `range`. `commits: 0` is an empty delta, which is computable and is not a
     finding.

   `scope` is a separate fact from the state, and it is not a fourth outcome. **`scope: null`, which
   the receipt prints as `UNSCOPED`, does not stop anything** — a repo that has not said how its tags
   are spelled is common, and blocking it trades a reporting gap for a release nobody can cut. It
   does have to be carried: pass `scope_reason` to the auditor with the payload and repeat it in the
   release report, because an unscoped range anchors on whatever tag is newest, which in a repo that
   also tags nightlies or candidates is a fraction of the real delta. When the reason is a null
   `tag_pattern`, that is the same finding as the stop-and-ask at the top of this file, reaching you
   from the other direction.

   The reverse is now true as well: `tag_pattern` decides the range, not just the tag you are about
   to write. A pattern that disagrees with how this repo actually tagged its last release anchors the
   audit somewhere else — or reports `first-release` in a repo with releases — so a `scope` that does
   not match the tag you expect is a config finding, not a delta.

   **Record the checklist in effect before you spawn.** The auditor is loaded from the installed
   plugin, and the installed plugin is updated *by* releases — so an improvement to the checklist
   cannot audit the release that ships it, and will not audit the next one either unless the install
   is refreshed. That is a read, and both numbers are cheap: the version in
   `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`, and this repository's own
   `.claude-plugin/plugin.json` when this repository is the one that ships the definitions. Pass the
   answer to the auditor with the payload and repeat it in the release report. Three states:

   - **it matches** — name the version, once.
   - **it differs** — name both. This **annotates, it does not stop the release.** For a repo that
     merely installed the plugin the installed version is legitimately whatever they installed, and
     blocking on a skew nobody chose trades a reporting gap for a release nobody can cut — the same
     trade `scope: null` above already refuses. For the repository that *ships* the definitions both
     numbers are on its own disk, and a gate older than the rules it is gating is a **config
     finding** in the release report.
   - **could not tell** — a manifest was absent or would not read, or `${CLAUDE_PLUGIN_ROOT}` is
     unset. Say it in those words: *I could not tell which checklist I am running.* It annotates
     rather than stopping, for the reason above, but **it never renders as a match** and a `clean`
     underneath it is a clean audit of unknown vintage, reported as one.

   This is where a `could not rank` usually comes from, and the two are still reported separately: a
   version skew is evidence about the cause, never a substitute for the agent's own answer.

   Then, and only for the two computable states of the range:

   ```
   Agent(subagent_type: "oss:release-auditor", run_in_background: false)
   ```

   Hand it the payload verbatim and the round number. It writes nothing and it does not tag. **A
   spawn that did not run is `could not run`**, never a clean audit — if the agent fails to start or
   comes back empty, that is the third outcome and the same stop applies.

   **A spawn that errors because the name does not resolve is that same `could not run`**, and it is
   not hypothetical: this gate dispatched to a name the harness never registered for two releases,
   so its third outcome was its permanent state and nothing reported it (#81). A release read as
   having passed its gates because the error scrolled past. So:

   - **Quote the spawn error verbatim in the release report.** It is the only thing that separates a
     wiring failure from a clean audit, and both otherwise render as silence.
   - **Re-dispatch to `general-purpose` with a pointer to `agents/release-auditor.md`**, handing it
     the same payload, the same round number and the same "writes nothing, does not tag". An audit
     performed by the fallback is an audit; record which agent ran.
   - **If the fallback does not run either, the gate is `could not run` and the release stops.** The
     contract above is unchanged by *why* nothing ran. Do not audit the delta yourself in its place
     — the gate asks for an independent read, and the releaser is not one.

4. **Every site in `version_sites` bumped**, swept **unfiltered**:

   ```bash
   git grep -n "<the new version>"
   ```

   A sweep keyed on the *outgoing* version only finds sites that are half-bumped. It cannot find one
   frozen at some third value, which is the one most likely to be wrong. A README is not a `.json`,
   so an allowlist by extension cannot see it.

   **The number swept for comes from the section below, not from an impression of the delta.**
   `version_sites` says where the number goes; nothing here used to say what it is.

## Which number the release gets

Every other input above is pinned. The version was not, so it came from whoever happened to be
cutting the release — and in #171 that produced a recommendation of a minor bump that never
mentioned the `removed` fragment sitting in the same directory. The number was right by luck.

The fragments already carry the evidence, so it is read rather than felt:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_version.py" --repo . --json
```

It reads `changelog_dir` and `release.tag_pattern` out of this repo's own `.oss.json`, counts the
fragment sections, and reads the current version out of the last matching tag. Pass `--current
X.Y.Z` when the baseline is not a tag. **It proposes; it never writes, bumps or tags.**

- **exit 0, `proposed`** — `version` is the number, with `change_class`, `line`, `bump` and the
  fragments behind them. **Quote the receipt, then accept it or override the proposal, and record
  which you did and why.** A release number is a promise to users, so the decision stays yours; what
  this removes is the *unsourced* guess, not the judgement.
- **exit 3, `could not decide`** — no fragments, a section outside the six, a compatibility line that
  will not read, or a `removed` fragment that declares nothing. **It names no number**, deliberately:
  a default patch bump over a breaking change is indistinguishable in the tag from a considered one.
  Fix what it names — usually one bullet in one fragment — and re-run. Do not pick a number instead.
- **exit 4, `no baseline`** — the change class is known and the version it applies to is not: no tag,
  a null `tag_pattern`, or a tag that does not spell a triple. A first release lands here, and the
  number is yours to choose. It names none either.

The rule, so that "it depends" stops producing this issue: **in a `0.x` line a breaking change is a
minor** — semver's own clause 4, where anything may change at any time — **and at `1.0.0` or later it
is a major.** In a `0.x` line that fold makes `breaking` and `feature` the same number, so the
receipt says the fold happened; a maintainer who wants `1.0.0` here has to override the proposal
rather than notice nothing.

And the section alone never decides it. A removal need not break anything — `113.removed.md` in this
repository is exactly that case — so the verdict is a declared field on the fragment,
`- Compatibility: breaking|compatible - <reason>`, documented in `changelog.d/README.md`. Required on
`removed`, optional elsewhere, and an unrecognised value is `could not decide` rather than a quiet
pass.

## Then

Fold the changelog if this repo uses fragments (`/oss:changelog`), commit with `commit_subject` —
or with `chore(release): {version}` when it is null, per the rule above — and tag. Then **verify the tag exists on the remote**:

```bash
git ls-remote --tags origin <tag>
```

A quiet `git push origin <tag>` can die inside a wrapper and read exactly like a push that worked.

## Then publish the release, if this repo publishes

A tag with no release object leaves the releases page showing a bare tag with no notes, nothing
marked `Latest`, and nobody who watches for releases notified. That surface is entirely within
reach — the notes were assembled a moment ago and it depends on nobody else — so it is closed here
rather than narrated (#58):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release_publish.py" \
  --repo . --version <the new version> --tag <the tag> --json
```

That is the dry run: it prints the command it *would* run and calls nothing. Add `--execute` to
create the release. Read the printed command before you do.

**Do not assemble the `gh` call yourself.** `--verify-tag` is the reason: without it
`gh release create` creates the tag when it is missing, which turns the `git ls-remote` check above
into a step that mints the very ref it was verifying. The script emits it on every branch that
builds a command and the suite asserts the whole argv, so it cannot be lost to an edit. `--repo`
is always passed for the same class of reason — `gh` otherwise infers the repository from whichever
directory it is standing in.

The notes are the `## [x.y.z]` section `/oss:changelog` just wrote, everything up to the next
`## [`. A heading with no body under it is **not** empty notes; it is `could not run`.

Three outcomes, exit codes because a shell reads those and never reads prose:

- **exit 0, `create` / `created`** — the command is buildable, or it ran and the release exists.
- **exit 4, `skipped`** — `release.create_release` says this repo does not publish, or has not said.
  A decision, reported as one. It never stops the release: the tag is the release for a project that
  tags deliberately without publishing.
- **exit 3, `could-not-run` / `could-not-create`** — the notes could not be extracted, `gh` is not on
  PATH, the API call failed, or `.oss.json` is not a JSON object at all. **Say so in those words.**
  This is the one that must never read as either of the other two, and above all never as a release
  that shipped: a maintainer who believes something is published stops looking at it.

Three, because those are the answers a script that ran can give. A call the harness refuses never
runs, and it is a fourth — *A denied call is a fourth answer* below. **Do not read the list above as
exhaustive.** Filing a denial under one of these three is the single mistake that section exists to
prevent, and an enumeration that looks complete is what produces it.

A `.oss.json` that parses but is not an object — `[]`, `"x"`, `null`, `42` — is exit 3 and not exit
4. It states no policy, which is a different fact from stating one that does not publish, and the
two were indistinguishable until #126: the shipped defaults answered for it and the run reported
*skipped by policy* naming a key the document could not have set. The tag shipped and the Release
silently did not.

The policy lives in `.oss.json`'s `release` block, tracked, because how a project publishes is the
project's answer and not one laptop's:

| Key | Default | Why that default |
| --- | --- | --- |
| `create_release` | `false` | Publishing a repo that never asked is not this tool's call to make. |
| `draft` | `true` | A draft is undoable. A published release has already notified everyone. |
| `latest` | `false` | `Latest` changes what the repo's landing page shows, and that page is theirs. |

Unset is a third state, not a quiet `false`: the skip reason names `release.create_release` so a repo
that never chose is told what would change it rather than silently never releasing. `draft: true`
with `latest: true` is refused by the config validator — a draft cannot be Latest, so the pair states
an outcome no release path can produce.

## A denied call is a fourth answer, and it is none of the three above

Supertool's own confirmation gate and its three opt-outs (`|force` per call,
`SUPERTOOL_NO_PUBLISH_CONFIRM=1` per environment, `no_publish_confirm` per project) are not the only
thing that can refuse a release step. The harness's permission handling sits **in front** of all
three and can deny a call before supertool or `gh` ever sees it. An allowlist entry does not
necessarily clear it, two spellings of one op are two different command strings, and it is not
stable: the identical call has come back denied and then, later in the same session with no
configuration change of any kind, been permitted. That has now been reproduced at four distinct
calls — a skill invocation, a merge op, a force-push and a rebase — so it is not a property of the
merge, which is what every other mention of this gate in the plugin is framed around (#186).

The release path is where that costs the most, because the calls most likely to be gated all sit
**after** the writing has started — `git push origin <tag>`, the `--execute` publish above, and any
force-push. By then the changelog is folded, the fragments are deleted, the version sites are bumped
and the commit is made.

**A denial is none of the three outcomes above.** `created`, `skipped` and `could-not-create` are
verdicts `release_publish.py` earned by running. A call the harness refused never ran: it
has no exit code, and nothing whatever about the repository was established. Reporting it as
`could-not-create` — or as the range gate's `could-not-run` — states a fact about the repository that
nobody measured, which is this plugin's own defect class one layer up from where it usually bites.
The word already exists in this plugin, at the merge: say the call was **denied**, name it exactly,
and hand it to the maintainer to run or to permit.

**Do not route around it.** Concretely:

- **Do not reword the call to get past the classifier.** A different spelling is a different command
  string, so a reworded call that succeeds proves nothing about the one that was refused — and
  hand-assembling the `gh release create` invocation loses `--verify-tag`, which is the whole reason
  the section above says not to assemble it.
- **Do not retry in a loop.** The denial is unstable, so re-invoking the *identical* call once is a
  legitimate probe, and its outcome is reported either way. A second denial is handed over. Retrying
  until the classifier relents is not a gate being satisfied, it is a gate being outlasted.
- **Do not read a denial as a gate that passed, and never as a release that shipped.** It stops the
  release where it stands; the report says `denied at <step>` and never reports as released.

### Where a denied release resumes

Name the write steps that landed and the ones that did not. A release stopped mid-sequence is
recoverable, and only if somebody knows the position — which is a different sentence at each step,
so do not write one that covers both:

- **denied at `git push origin <tag>`** — the fold, the version bumps, the commit and the tag are all
  still **local**. Nothing outside the clone has changed. It resumes at that push, and the publish
  after it.
- **denied at the publish** — the push already succeeded, so the tag is on the remote and only the
  release object is missing. It resumes at `release_publish.py --execute` alone. Saying a tag push is
  outstanding here sends a maintainer to re-run a step that already ran.

The ordering trade is real, and it is stated here rather than quietly taken: folding first puts the
destructive half (the fragments are deleted) ahead of the deniable half, and tagging first would make
a refusal cheaper at the cost of a tag pointing at a commit whose changelog is not folded. The order
is unchanged and the receipt above is the mitigation.

## The tag is not the delivery

Publishing the release closes one surface. It does not close the others. For plugin users the
manifest version is what the updater compares; for catalogue users the pin is a commit sha somebody
else advances. **Report which surfaces the release actually reached, in those words** — "tagged and
released, not yet in the catalogue" rather than "shipped".

And the inverse is just as real: a repo can be *released by manifest and never tagged*, which leaves
the releases page a version stale while every install is already current. Check both directions
before saying the release is done.

## Cohort

At the tag, label everything then-open as a frozen cohort — in the same minute, by hand. Nothing
joins a cohort ever, so it can only shrink. This is the maintainer's act; the triager must never
write one.
