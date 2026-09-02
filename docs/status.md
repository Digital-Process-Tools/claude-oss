# Status

**Tested, not proven.** The claim this section used to make — that no real issue had gone from
triage through to a merge — stopped being true some time before anyone edited it: the loop now
maintains this repository, and the triage-to-merge round trip has run many times over, including
the releases cut with `/oss:release`.

What that does *not* establish is the part most users care about. Almost everything this plugin
claims about a repository it has **scaffolded** still rests on tests and scratch runs rather than on
a repo somebody maintains through it; owned files are known to have gone stale in the field, in
every repository carrying them, with no observed repair in any of them.

The measured version of that, with each claim graded observed or reasoned and dated to the commit
it was taken at, is **[What is not proven yet](../CLAUDE.md)** — re-derived at each release rather
than edited. It is deliberately not restated here: a second copy is the one that drifts, and this
section is the proof of it.

**Installing this plugin does not put a maintainer loop in your repository.** The workflow it
installs is a changelog gate that fires on a pull request; every other step of the loop is a slash
command somebody types. The one thing it starts on a clock is a `.github/dependabot.yml`, seeded
once if you do not already have one and yours to delete — and nothing here reviews or merges what
that opens. The gate exempts pull requests **opened by `dependabot[bot]`** from the fragment
requirement, announcing the skip in its own log rather than passing silently: a bot cannot use the
`no-changelog` escape hatch, because its own labels fail the run before a human can apply one
(#293). If you point dependabot at a runtime ecosystem rather than `github-actions`, a bump that
*is* user-visible will announce nothing, and that log line is where it shows.
Nothing schedules a tick, a re-scaffold or an update of an owned file, so a repository
that installed the plugin and was never ticked again looks, from here, exactly like a healthy one.
What that would take is recorded in
**[Autonomy: what the loop reaches, and what it does not](autonomy.md)**, which is a record of
the gap and deliberately not a design.
