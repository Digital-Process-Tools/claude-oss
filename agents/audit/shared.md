# Shared conventions for an audit spawn (#1071)

**Read this from `agents/auditor.md` and `agents/release-auditor.md` alike.** Both spawns share one
operating shape underneath their different jobs -- a total `Bash` grant with nothing in the harness
enforcing "read only", how a read actually happens through `supertool`, and that test behaviour is
reasoned about rather than run. This file carries that shared shape once. **It does not carry either
spine's own decision**: the worktree-boundary check `agents/auditor.md` runs against the one path it
was briefed on, and the tagging/publishing exception `agents/release-auditor.md` states for the
release it gates, are specific to what each spawn is handed and stay in that spawn's own file rather
than living only here.

## Your `Bash` grant is total -- this section is advice, not a boundary

Read it as a request, because that is all it is. The frontmatter grants you `Bash` and `TodoWrite`.
`Bash` reaches the filesystem, the forge, and shared state belonging to no repository in particular.
Nothing in the grant, the harness or this file distinguishes a read from a write.

So the request: **run only ops that read, and no bare shell that writes.** supertool publishes the
class of every op loaded here -- `supertool 'ops:roster'` prints them all, unmarked for read-only,
`*` for a write in this tree, `!` for something changed outside it or started so that it outlives
the call. Ask it rather than working from a list of names. Plain `git`, `gh`, a redirect or an
inline interpreter are `Bash` too, with nothing between them and the disk.

If a class is genuinely unreachable without acting, **report that class as one you could not
check**, and say what stopped you. That is the third state. It is never a licence to run the op.

## How you read

Everything goes through `supertool` via `Bash` -- it is on PATH from any directory. Batch 6-7 ops
per call: `read`, `grep`, `glob`, `map`, `around`, `between`, `tree`. You have no `Read`, `Grep` or
`Glob` tool, which is what makes that binding rather than advisory. `supertool 'ops'` lists
everything.

Do not pipe an op through `head`, `tail`, `sed` or `cut` -- the ops put the verdict at the top, and
both cuts select against the answer. Narrow the op instead.

## Test behaviour is reasoned, not run

You may read test files, reason about coverage, and name a test that should exist and does not.
You may not run the suite, and may not ask a spawned agent for a verdict on one (#874). A finding
resting on a claim about test behaviour says `reasoned`, never `observed`.
