# Self-review: the two spawns against your own committed diff

**Read this when** you have committed and are about to spawn the reviewers -- before the first `Agent` call.

**Say whether you read it.** A phase file you did not open, or could not, is a clause of your brief
that did not run: name it as an item under the report's `compliance` survey, with the reason. A rule
that did not run renders exactly like a rule with nothing to say, so the absence is stated, never
silent.

After you commit, spawn **two agents against your own committed diff, in the same message** so they
run concurrently:

```
Agent(subagent_type: "Explore",     model: "sonnet", run_in_background: false)
Agent(subagent_type: "oss:auditor", model: "sonnet", run_in_background: false)
```

Give each the diff, the issue number, and one line on what the change is meant to do.

**The reviewer** is asked for: correctness bugs, a test that would still pass if the code did
nothing, anything the change makes worse that nobody filed, and **stale prose adjacent to the
diff** — that last one is where the real findings come from; a plain diff-scan lens routinely finds
nothing. Ask for the answer compact: per finding, the mechanism in one line and the reproduction
command or its output, severity and class; clean areas named rather than described; retrospectives
cut, except a genuine disagreement with the brief, which earns full prose because it is usually
right.

**The auditor** works a fixed checklist and reports one verdict per class, so a class it could not
reach is visible rather than absent. Hand it §4 of the spine's *How you work*, **Cross-platform is not your machine**,
verbatim in the brief — that list already ships in two places and a third copy drifts, so the auditor
carries none of its own and reports the whole platform band as `could not check` if neither the
section nor the file reached it.

Two spawns rather than one added bullet: a checklist folded into a generalist's ask leaves no way to
tell a class that was checked and clean from a class that was never read.

**Tell both explicitly that they must not edit anything.** The reviewer is spawned as `Explore`,
not `general-purpose`, because a tool grant is what binds and a sentence in the brief is not.
`Explore` carries no `Edit`/`Write`. **It does not close every channel, and the brief must say
so rather than promise more than it delivers: `Explore` still has `Bash`, a complete write path.**
Tell it explicitly, in addition, that it must not mutate the tree. The brief already saying so is
not a mechanism (#769: told twice, two different agents mutated the tree in the same run anyway, and
**neither left a ref movement or a reflog entry**). So take a receipt instead of relying on luck, and
read your own suite figures as possibly contaminated by a concurrent reviewer until you have one:
snapshot the tree before you spawn, and compare after both return.

```
BEFORE=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tree_snapshot.py" snapshot)
printf '%s' "$BEFORE" | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["root"], s["branch"])'
# ^ read this line back NOW, against your own known worktree path and branch, before
# spawning anything -- three incidents (#1024, #1078, #1096) reported this call landing on a
# *sibling* lane's worktree even from one shell call. If root or branch is not yours, stop and
# pass --root <your worktree path> explicitly to both calls below, and say so in your report.
# ... spawn both agents, wait for both final messages ...
printf '%s' "$BEFORE" | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tree_snapshot.py" compare --before -
```

Neither call needs an explicit `--root`. `snapshot` reads the calling process's actual cwd at that
call -- there is no glob/mtime-based cross-worktree GUESS anywhere in the module's own code -- and
`compare` defaults to re-snapshotting the root `snapshot` recorded, not whatever cwd the later,
separate Bash call happens to be standing in (#971). That is a fact about the code; it is not a
promise that the process's own cwd is always what the shell line said it was, which is exactly what
the three incidents above report and the verification step above exists for.

`clean` (exit 0) means nothing persisted. `mutated` (exit 1) names what changed — restore it
(`git checkout -- <path>`, or delete a leftover scratch file), re-run whatever suite you already
ran, and record it under `adjacent` as `tooling:` rather than silently absorbing it.
`could-not-compare` (exit 3) means the check itself failed; treat that as `could not check`, never
as clean. **It cannot see a write created and deleted before the `compare` call runs** — a
self-cleaning mutation is invisible to any before/after comparison by construction, so `clean` here
means nothing persisted, not that nothing happened.

**Your final message is the only thing that reaches you — everything a spawn wrote before that line
is invisible to the caller.** State this in both briefs: the final message IS the return value, and
if a reviewer found nothing it must say `NO FINDINGS` and name what it checked, because a reply
ending in "findings reported above" returns empty, and an empty return is indistinguishable from a
clean one unless the brief forces the reviewer to say which it means.

**The sentinel does not cover the third failure: a message that *refers* to findings without stating
them.** Not empty, so nothing looking for an empty return fires on it; not `NO FINDINGS`, so it is
not clean; and it reads like a delivery — *"two confirmed findings reported above"* — with the
findings themselves nowhere in the return value. Put this in both briefs, in these words: **a finding
you refer to but do not state is a finding that does not exist.** No "reported above", no "as
noted", no "detailed earlier".

**Ask for the shape that makes the omission arithmetic rather than a judgement.** Require that each
spawn's final message **opens with `FINDINGS: <n>` and then states exactly that many findings, in
full** — or opens with `NO FINDINGS` and names what was checked. **Do not count them by hand.** Since
#392 the comparison is `scripts/review_return.py`'s, and `agents/developer/review-return.md` tells you how to run it;
counting by eye is the step that fails silently. `FINDINGS: 2` followed by one stated finding is not
a review with one finding, it is a review that lost one.

**Tell both spawns not to open with the sentinel string used as a denial, even rhetorically.** A
message opening "`NO FINDINGS` would not be accurate here" before its real `FINDINGS: 3` header
carries both strings, and the classifier cannot tell a quoted negation from a genuine claim — it
reads two candidate headers and reports `could-not-classify` rather than guess which one governs
(#1248, observed in another managed repo's own self-review). State the real verdict header —
`FINDINGS: <n>` or `NO FINDINGS` — as the message's first line, plain, and argue anything else only
after it.

**Say plainly what this is: this fix is a request to the spawn, not a boundary on it.** Nothing this
repository ships sits between a sub-agent's final message and your context. A tool grant is what
binds and a sentence in a brief is not, so the header is a convention the reviewer may simply not
follow. What it buys is real: it moves *your* half of the check from reading tone to comparing two
numbers. **Removing the class rather than the instance would need the return itself to be
structured** — that belongs to whatever spawns the agent, and it is the thing to ask for upstream
rather than to claim here.

The caller's side needs nothing from the reviewer: **you already hold the string.**
`scripts/review_return.py` classifies it, and `agents/developer/review-return.md` tells you to run it
rather than to read it. Be exact about what it buys: it does not recover a lost review and it does
not stop one being lost. It removes the step where a *less careful* agent reads a confident paragraph
and records `checked`. The residual failure is *nobody ran the classifier*, which is an absent
verdict in a report somebody reads, rather than a wrong verdict nothing can see.

**Independence lives in the reviewer; judgment stays with you.** Argue down a finding that is wrong
and say why — that is an outcome no bounce-and-repush loop produces. Report all three under
`review.findings`, each with its disposition: what it flagged, what you fixed, what you refused.

**`report-for-filing` is the blocking-or-unranked case only (#1275).** Rank a real, out-of-scope
finding against `findings.md`'s table before you reach for this disposition: a row that blocks a
release, or fits none of the rows, is `report-for-filing`; a non-blocking row is written to
`trap.d/` instead and reported as `fixed`, `below-bar`, or logged-to-`trap.d/` in the pull request
body, never `report-for-filing`.

**A disposition is not a filing.** A finding you judged real, out of this diff's scope, and
blocking (or unranked) is `report-for-filing`, and `report-for-filing` is a request addressed to the
maintainer — it says *this should be filed, by you, and nothing has happened yet*. **You never file
it yourself**: your publishing clause is unconditional, opening a tracker issue is publishing under
somebody else's credentials. So there is no word here for a completed filing and there is not meant
to be (#254).
Give every `report-for-filing` item a `reason` saying why you did not simply fix it -- and if what
you hold is another instance of a class the tracker already carries (the brief's sibling-issue list
is usually where you would know it from), name that issue in the `reason`: the maintainer's receipt
is then a comment on it rather than a new row. The `reason` is otherwise the same judgment the
spine's *fix it or file it* asks of an `adjacent` item, and **not the same contract**: `adjacent` has
no `reason` field, so there the argument rides inside `text` and nothing checks that it arrived,
while here it is refused when empty.

**A reviewer finding can be real and still below the bar, and that is `below-bar` here too** — same
word, same `pr_anchor`, same check, because a finding is below the bar or it is not and who noticed
it does not change that. It is not `refused` and not `argued-down`: both of those say the finding was
*wrong*, and this one says it was right and has no reachable caller. The `reason` is refused when
empty for a reason opposite to the filing one — you are asking the maintainer **not** to open
anything, so what they need in order to leave it closed is your argument that the class cannot be
reached.

**Do not shell out to a headless `claude` CLI.** If a capability is genuinely unreachable, say so and
stop.

**A review that did not execute must never render as a review that found nothing.** That holds for
both spawns, for an empty final message from either one — treat it as `did not run`, never as
clean, and say so in your own report rather than silently omitting the review — and for each of the
auditor's classes separately: report `did not run` where it did not run. An absence you produced is
not an absence in the world.
