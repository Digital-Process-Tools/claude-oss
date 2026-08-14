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

1. **The default branch is green at leg level for the exact commit being tagged.** Count the
   *workflows*, not the runs — one declared in `.github/workflows/` but absent from the run list is
   `UNKNOWN`, never a pass. `supertool 'gh-branch'`, which is conjunctive over every workflow on the
   head SHA.
2. **Nothing in flight is mid-review.**
3. **A security audit of the delta since the last tag passed.** Three outcomes: clean, findings, or
   **could not run**. An audit that did not execute must never render as an audit that found nothing.
   **Two rounds, hard cap** — a competent audit of any non-trivial delta always finds something, so
   an unbounded "findings, therefore stop" makes every release hostage to diminishing returns. After
   round two, file the rest against the next milestone and ship.

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

   Then, and only for the two computable states:

   ```
   Agent(subagent_type: "oss:release-auditor", run_in_background: false)
   ```

   Hand it the payload verbatim and the round number. It writes nothing and it does not tag. **A
   spawn that did not run is `could not run`**, never a clean audit — if the agent fails to start or
   comes back empty, that is the third outcome and the same stop applies.
4. **Every site in `version_sites` bumped**, swept **unfiltered**:

   ```bash
   git grep -n "<the new version>"
   ```

   A sweep keyed on the *outgoing* version only finds sites that are half-bumped. It cannot find one
   frozen at some third value, which is the one most likely to be wrong. A README is not a `.json`,
   so an allowlist by extension cannot see it.

## Then

Fold the changelog if this repo uses fragments (`/oss:changelog`), commit with `commit_subject` —
or with `chore(release): {version}` when it is null, per the rule above — and tag. Then **verify the tag exists on the remote**:

```bash
git ls-remote --tags origin <tag>
```

A quiet `git push origin <tag>` can die inside a wrapper and read exactly like a push that worked.

## The tag is not the delivery

For plugin users the manifest version is what the updater compares; for catalogue users the pin is a
commit sha somebody else advances. **Report which surfaces the release actually reached, in those
words** — "tagged, not yet in the catalogue" rather than "shipped".

And the inverse is just as real: a repo can be *released by manifest and never tagged*, which leaves
the releases page a version stale while every install is already current. Check both directions
before saying the release is done.

## Cohort

At the tag, label everything then-open as a frozen cohort — in the same minute, by hand. Nothing
joins a cohort ever, so it can only shrink. This is the maintainer's act; the triager must never
write one.
