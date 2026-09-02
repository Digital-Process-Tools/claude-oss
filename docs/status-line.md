# Status line

`/oss:scaffold` writes `.oss/statusline.py` as an owned file, and Claude Code renders its output
in the corner of the terminal. Every field is separated by ` | `; a field this repository could not
measure renders `?` rather than a guess, per this repository's own rule that a check which did not
run must never look like one that ran clean.

Left to right:

| field | example | means |
| --- | --- | --- |
| model · context | `Opus · 42%` | Claude Code's own session facts, passed straight through. |
| repo | `claude-oss✓ main v0.15.0` | repo name, glued to a glyph for whether the *default branch's own head commit* is currently green (`✓`/`✗`/`⋯`/`?`; `#856`), then the current branch (only when it is not the declared default) and the tracked version. |
| board | `4pr 2ok 1x 1... 0? · 23is / 2eis` | open pull requests, then a CI breakdown (green/red/running/unknown, every group shown even at zero), then open issues and how many of those arrived from outside repository membership. |
| release | `rel 4/17` | commits banked since the last release, over what a release here usually costs. Either half is `?` on its own when only one could be measured. |
| tick | `tick 4m` / `tick due` / `tick off` / `tick -` / `tick ?` | when the next maintainer tick fires, if one is armed at all. |
| last | `last 12:34` | a wall-clock stamp of when this line was last rendered — frozen like the rest of the line between renders, but a frozen clock time stays readable against your own watch. |
| plugins | `plug 3✓ oss↥0.15.0 1?` | how many of this repo's declared plugin dependencies are current, then each one that is not, named. `↥`/`>` shows the **latest published** version behind a plugin marked `behind`; `↑`/`+` shows the version **installed** for one marked `ahead` — two markers that print two different fields, not two colours of the same one (#549/#550). `?` counts a plugin whose version could not be compared at all. |
| ch | `ch✓` / `ch✗` / `ch◐` / `ch!` / `ch?` | whether supertool's watch channel is delivering — green when the consumer's counters are moving, red when nothing is listening, yellow (`◐`) when the consumer is bound but nobody is subscribed, `ch!` on a contradiction, `ch?` when nothing could be established. Set `"watch_channel": false` in `.oss.json` to turn it off — the field then disappears entirely rather than showing `ch?`, because an operator's deliberate off switch is not the same absence as a question this line asked and could not answer. |

Colour, where the terminal supports it, adds a second signal on top of the marker shape rather
than replacing it — every state above is told apart by its glyph alone, in monochrome.

The `repo` field's marker maps `gh-branch`'s own four states down to `_symbols`' four glyphs:
`✓` for GREEN, `✗` only when a leg on the head commit has actually failed, and `⋯` for both
"still running" and NO RUN — nothing has concluded yet, including the moment right after a
merge, when the branch has a fresh commit and no run against it at all. `?` covers UNKNOWN and
a reading older than its own refresh interval, folded the same way `plug`'s own `behind`/`ahead`
comparison folds a stale one (#550) — a stale `✓` about a commit that may no longer be green is
worse than an honest `?`. The marker is absent entirely, not `?`, when `.oss.json` declares no
`default_branch` to compare against — a deliberate absence of the question, the same convention
`ch`'s own off switch above uses.
