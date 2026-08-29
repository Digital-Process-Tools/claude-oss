# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.15.0] - 2026-08-29

### Added

- The status line's board field splits open issues into two counts instead of one:
  `14is / 2eis`, where `eis` is how many were filed by someone outside repository
  membership. The split reads off GitHub's own `authorAssociation` rather than
  `-author:@me`, so the number is a fact about the repository rather than about
  whoever is authenticated on the machine rendering the line, and it agrees with
  supertool's own `gh-issues` external-filer marker instead of answering differently.
  A count nobody could take renders `?eis`, distinct from a genuine `0eis` (#595).
  The vendored `.oss/statusline.py` copy in managed repositories does not pick this
  up until it is re-scaffolded.

- The status line adds a sixth-ish field, `ch`, showing whether the watch
  channel supertool's own `channel:health` reads about is delivering: `chok`
  (green) when the consumer's own counters are moving, `chx` (red) when nothing
  is listening at the socket, `chb` (yellow) when the consumer is bound and
  counting but no session is subscribed, `ch!` when the health file disagrees
  with who actually holds the socket, and `ch?` when nothing could be
  established -- no reading yet, a reading older than its own refresh interval,
  or a channel name that was not derived from this repository's own `.oss.json`
  and so cannot be attributed to this repository's fleet. `forwarded` is never
  spelled as `delivered`: the field reports which of five states the consumer
  is in, not whether an event reached a Claude session, which is not
  observable from outside that session at all. Read once per a new third
  clock, at most every 300s (an unmeasured starting guess, stated as one), by
  the status line's existing detached `--refresh`, never on the render path --
  `channel:health` is classed an acting op and spawns `claude mcp get` per
  subscription tag. On by default; set `"watch_channel": false` in `.oss.json`
  for a repository that does not run a channel at all (#613). The vendored
  `.oss/statusline.py` copy in managed repositories does not pick this up
  until it is re-scaffolded.

### Removed

- `board_from_cache`'s `state` field (`unknown`/`partial`/`measured`) is removed (#597). Nothing
  read it -- `_board_field` already renders `?` per missing value straight off `prs`, `issues`,
  `issues_external` and `checks`, so the summary could disagree with the values it summarized and
  never affect anything a maintainer sees. #595 had just added a rule to it (`issues` present but
  `issues_external` absent is `partial`) that, for the same reason, could not fire anywhere either.
  The per-field `?` on each count is the whole answer now. A repo's vendored `.oss/statusline.py`
  copy keeps the old field until that repo is re-scaffolded.
- Compatibility: compatible - `board_from_cache` is not exposed by any documented interface: it is
  a module-private function in a single vendored script, called only by that same script's own
  `gather()`, and its return value never crosses a process boundary or a README-documented
  contract. Weighed the counter-argument before choosing this over `breaking`: the file is
  vendored into managed repos as `.oss/statusline.py`, so in principle a scaffolded repo could
  hold its own caller this repo cannot see. It cannot hold one that *matters* to this verdict,
  though -- `board_from_cache` is invoked only by code inside the same file (`gather()`, which
  feeds `_board_field()`), never imported as a library elsewhere or exposed as a CLI flag or a
  documented field, so the only place a caller could exist is inside a maintainer's own hand-edit
  of that same vendored file, which this repo cannot version anyway. What #597 itself established
  -- zero readers of the field, verified by grep and by two independent review spawns -- is the
  fact this verdict rests on.

### Fixed

- README.md's `ln -sf ... ~/.local/bin/oss-workspace` step was filed as a possible
  redundancy against the plugin's own marketplace cache directory already being on
  `PATH`. Measured rather than assumed: a clean login shell carries no `dpt-plugins`
  entry at all, so the marketplace cache is on `PATH` only inside a running session --
  the one place the launcher is never run from. The symlink step stays, and README.md
  and CLAUDE.md now record the measurement rather than leaving the question open (#526).

- The supertool rule body existed twice with nothing comparing them: the tracked
  `.claude/jit-context/tools/01-oss/supertool-required.md`, which this repository's own
  sessions read, and `TOOLS_SUPERTOOL` in `scripts/oss_rules.py`, which is what gets written
  into every scaffolded repository. An edit to one and not the other used to ship silently.
  `tests/test_supertool_rule_sync_577.py` now compares the two bodies (normalised for line
  endings and trailing whitespace only, so a Windows checkout's CRLF is not read as drift),
  with a control pair proving it catches a one-sided edit and passes an edit made to both (#577).

- \`bin/oss-workspace\`'s FIND_CONSUMER heredoc -- the block that locates the supertool
  plugin's channel consumer -- ended in \`|| true\` with no captured exit status, and its
  \`json.load\` was guarded only by \`except (OSError, ValueError)\`. A \`RecursionError\` out
  of \`json.load\` on a deeply nested (but validly-formed) registry escaped that guard, the
  interpreter exited nonzero, and \`|| true\` swallowed the status -- so \`channel_script\`
  came back empty with no signal anything had crashed, and the launcher reported the SAME
  confident \"the supertool plugin's channel consumer was not found\" sentence it gives for a
  genuine absence. This was worse than the \`ASK_CONSUMER\` case #573/#588 already fixed at the
  sibling call site: there a crash at least left a traceback on stderr beside the wrong
  answer; here it read as a specific, plausible fact nobody had reason to doubt. The status is
  now captured on the heredoc's own assignment (\`&& find_consumer_status=0 || find_consumer_status=$?\`,
  the same idiom #588 established), and a crashed probe now reports its own third-state
  sentence -- \"could not determine whether the supertool plugin's channel consumer is
  installed ... UNKNOWN rather than absent\" -- distinct from both the ordinary not-found and
  found-but-unverifiable sentences already in that block (#578).

- `skills/manager/phases/dispatch.md` and `skills/manager/SKILL.md` now route the maintainer to
  `--derive-held`, the derivation `#558` shipped, instead of teaching the hand-retyped `--against`
  set as the only way to check a new lane's files against every other running lane. The hand-typed
  side stays documented as the named fallback for `could-not-derive-the-held-set`, never the
  default (#586).

- `scripts/skill_phases.py`'s undeclared-phase-file check no longer folds an
  unreadable phases directory into "no undeclared files found". `_undeclared_rows()`
  caught `(RuntimeError, OSError)` around its call to `manager_docs.documents()`
  and returned `[]` on either, discarding the `unreadable` state the module's own
  docstring promises to preserve -- guard and bypass in one function. `OSError`
  now returns an `unreadable` row instead; `RuntimeError` (no spine) still returns
  `[]`, since that is already reported by the spine document's own `missing` row.
  Found by the `v0.14.0` release gate's round-2 audit; no live route to the bypass
  was demonstrated at HEAD (#589).

- `scripts/assemble_changelog.py --check`/`--count`/`--check-links`, run with neither `--dir`
  nor `--changelog`, used to derive its target by walking up from the script's own install
  location for a `.git` — correct for the copy vendored beside the repo it serves
  (`.oss/assemble_changelog.py`), and wrong for the copy shipped inside the plugin, whose own
  checkout is always a clone unrelated to whatever repository the caller meant. That walk always
  succeeded, always on the plugin's own tree, so a bare `--check` run from any directory reported a
  clean `ok` about the plugin's own changelog fragments, never the caller's (#590). It now derives
  from the **caller's own current working directory** instead, and refuses — the same way the fold
  already did — when no `.git` is found above it, rather than falling back to a repository nobody
  asked about. The `ok`/`skipped` receipts also now name the resolved directory that was actually
  read, so the answer's subject is never implicit.
  Repositories scaffolded by this plugin are unaffected in practice: their vendored
  `.oss/assemble_changelog.py` copy is invoked with cwd inside that same repository (the generated
  CI workflow, and an ordinary local checkout), so the derived root was already correct there and
  stays correct after re-vendoring. The defect was specific to running the plugin's own bundled
  copy — as `/oss:tick` does when auditing a *different* repository's tracker — against a tree that
  is not this plugin's own.

- The tick's step-2 board read prescribed a bare `gh-issues` literal, which caps at 50 open
  issues silently -- a repo with 88 open issues read as 50 and the 38 oldest issues were
  structurally invisible to the loop's triage. `commands/tick.md` now prescribes
  `gh-issues:per=100` and teaches the reader to treat a still-capped footer as "at least N",
  never as the whole backlog (#593).

- The SessionStart auto-updater now keeps this plugin's declared dependencies current as well as
  the plugin itself. It had only ever acted on the loop plugin, while the status line already
  rendered currency for the plugin and every name in its manifest's `dependencies` -- so the
  report's subject was wider than the actor's and nothing said so. Measured instance: `remember`
  sat at 0.21.0 against a published 0.22.0 through a session restart and a `/reload-plugins`,
  beside a green three-plugin currency line (#605).
- Each plugin gets its own record in the receipt, with a fourth state a dependency can reach that
  the loop plugin cannot: `not-installed`, for a declared dependency with no install record
  applying to this project. Attempting it at a guessed scope would have collected
  `Plugin "<name>" not found` and recorded a plugin this project never had as one it might
  silently have lost (#605).
- `doctor` reports the dependencies as their own row, and tells three absences apart rather than
  rounding any of them to a pass: a receipt written before this change that says nothing about
  dependencies, a manifest whose `dependencies` key could not be read, and a manifest that
  declares none (#605).

- This repo's own `.mcp.json` -- a machine-local MCP server registration excluded
  only in one clone's `.git/info/exclude`, invisible to every other checkout -- is now
  excluded in the tracked `.gitignore` instead, so it can never be committed by
  accident from a clone nobody has touched `.git/info/exclude` in.
  `bin/oss-workspace` already registers the same channel consumer portably, at local
  scope, resolved from the installed supertool plugin rather than from a checkout, so
  a tracked copy of the file itself was not needed (#610).

- The documented development command, `python3 -m pytest tests/ -q`, failed before a
  test ran on a machine with `pytest` but no `pytest-cov` -- `pyproject.toml`'s `addopts`
  requires it and nothing declared it. `requirements-dev.txt` is now the single declared
  list of development dependencies (`pytest`, `pytest-cov`, `markdown-it-py`, `pyyaml`,
  matched against what `.github/workflows/tests.yml` already installs), and README.md and
  CLAUDE.md both state the install line beside the test command they already give (#611).

- `#611`'s own `requirements-dev.txt` reddened every leg of its pull request's CI:
  `doctor.py`'s `NOT_COMPARED_TOP_LEVEL` partition test (#415) fails on any tracked
  top-level entry it cannot place in either half of the plugin-copy comparison, and
  the new file was in neither. `requirements-dev.txt` is now classified there, on
  the same reasoning as `pyproject.toml` beside it: development and test
  configuration for this checkout, never read at runtime by an installed plugin
  copy (#611).

- `agents/developer.md`'s guard-run instruction told a dispatched developer to add every guard test
  `scripts/lane_setup.py` names under `guard` to whatever it ran, without saying that a row can also
  render `NOT IN THIS REPO` or `COULD NOT TELL` (since #566) when the named test file belongs only
  to claude-oss's own tree and does not exist in the repo actually being worked on -- so a brief
  read literally sent a lane chasing a guard test file that could not exist, the round trip #612
  measured on claude-supertool. The `lane_setup.py` receipt itself already carried the three states;
  the prose consuming it did not distinguish them. Now it does (#612).

- `doctor`'s memory check resolved the plugin's data dir by joining the repo root onto a
  fixed path, in every install layout -- so an external store configured with
  `~/.remember/config.json`'s own `data_dir` (a real remember layout, keyed by path
  slug) was invisible to it: `/oss:doctor` reported "no identity.md" about a file it
  never looked for, while `remember`'s own `doctor.sh` reported it present and read
  two seconds later. It now reads `~/.remember/config.json` as well whenever
  `.claude/remember/config.json` sets no `data_dir` of its own, and resolves a plain
  `data_dir` from either layer correctly (#614).
- When `data_dir` is keyed by a `{slug}` this check cannot compute (`session_dir_slug`
  is UTF-8-aware, hashes over-200-character paths, and folds Windows drive letters --
  reimplementing it would be a second copy of another plugin's logic going stale on
  its own schedule), the check now says it does not know rather than silently
  defaulting to a store it already knows is wrong. Same third state for an unreadable
  or malformed config, replacing a bare `except (OSError, ValueError): pass` that
  could not tell "normal for this layout" from "something is actually broken" (#614).
- `$REMEMBER_DIR`, when the current process already has it set, is read directly and
  wins over every config layer.

- `doctor`'s `latest skew` check was a permanent `WARN` in any managed repo that is not itself an installed plugin: it read the status line's cached `latest[<managed repo>]`, a key `refresh()` only ever writes for installed plugins' own source repositories, so it could never exist for an ordinary managed repo no matter how many times the cache refreshed. Now reports `not-checked` when the declared repo is not one of the installed plugins' own source repositories, instead of a `WARN` nothing can clear (#615).

- `jit rule layer`'s `could-not-determine` verdict now names it when a hook script
  enumerates its dimension directory by shell glob (`for d in "$base"/*/; do`) rather
  than by a fixed list, instead of reporting the same generic "no fixed layer list"
  sentence for that case as for one with no enumeration evidence in it at all. The
  state stays `could-not-determine` -- the glob is reported, never promoted to a
  verdict, since it says nothing about what the loop's body then does with what it
  visits -- but a maintainer reading the line can now tell a stale `unknown` (a hook
  set that already enumerates by glob, the shape the upstream fix is expected to
  take) from one with no evidence at all. Reported with reproduction against
  `claude-jit-context` 0.6.0's `common.sh` (#616).

- README's launcher install line no longer names `$PWD` as though every install were a
  checkout. On a marketplace install there is no checkout and no fixed path to write
  here -- the plugin's own `bin/oss-workspace` lives under a version-scoped cache
  directory that moves on every release -- so the README now points at `/oss:doctor`'s
  own `oss-workspace launcher` line, which computes the current, paste-ready command
  from `PLUGIN_ROOT`. The `$PWD` line stays, scoped explicitly to a clone of this
  plugin's own repository, where it is correct (#617).
- `/oss:doctor`'s `oss-workspace launcher` check no longer searches the plugin's own
  `bin/` directory on `PATH`. A running session's `PATH` always carries it, so the check
  reported `matched` about a launcher that a plain login shell -- the one the README's
  install line is actually for -- could not reach at all: measured on the reporter's own
  machine, a clean `zsh -i -l` shell carried zero `dpt-plugins` entries on `PATH` while
  the check, run from inside a session, reported the launcher installed and matching.
  With the plugin's own `bin/` excluded, an install that only exists inside a session now
  answers `not on PATH`, the same as a launcher that was never linked at all (#617).

- `bin/oss-workspace` now says when a repo has declared radar tiers but nothing has
  ever spawned on the channel it opened -- the case a verified, subscribed, forwarding
  channel with an empty fleet renders identically to a healthy board with nothing to
  report. Before this fix the launcher's only line about the board fired on the
  OPPOSITE case: a repo with no radar tiers (opted out) was warned, and a repo with
  tiers declared and no board ever raised (opted in, and blind) stayed silent (#618).

- `/oss:doctor`'s `./supertool` check now reports a link resolving into a cached but
  superseded plugin version as its own state, `stale-version`, at `WARN` -- naming both
  versions and the remedy. It used to compute the disagreement and then discard it into
  an `ok` line's parenthetical, so a shipped fix could sit unused for as long as nobody
  read the detail string: this repo's own `./supertool` stayed linked to supertool 0.47.0
  for eleven days after 0.49.0 and 0.51.0 shipped, with every pull request's check tally
  reading `NOT ALL GREEN` on a check the newer version had already fixed. This is the
  reporting half of claude-supertool#2071 -- the symlink resolves perfectly, to the wrong
  version, so nothing that checks for a dangling link can see it (#619).

- The status line's external-issue count (`?eis`) was permanent everywhere: `_gh_external_issue_count` asked `gh issue list --json` for `authorAssociation`, a field that command has never had, so the call failed on every single invocation. Routes through `gh api repos/{owner}/{repo}/issues` instead, where `author_association` exists, filtering out pull requests server-side and cross-checking the row count against the known total exactly as before (#620).

- `/oss:doctor` now checks the channel MCP registration itself, not only the channel
  name and the radar board declaration either side of it. Neither of those two answers
  whether anything actually carries a channel into a session -- `grep mcp
  scripts/doctor.py` had answered zero results for the whole life of this file, while
  `bin/oss-workspace` already asked the same question at session-open, on stderr, where
  a maintainer running the diagnostic specifically because something is not working
  never sees it. A new `channel MCP registration` line mirrors that check's own states
  -- registered and resolvable, registered with a target that no longer exists (the
  registration outliving a version-pinned path after a plugin update), registered with
  an entry that could not be parsed, not registered, and could-not-ask when `claude` is
  not on PATH or the call itself failed (#621).

- `watch channel` reported `OK` whether `.supertool.json` declared `watch_name`
  on every op supertool's watch preset actually spawns from, or on just one --
  a name declared on `radar` alone read as fully configured even though
  `channel`/`unwatch`/`watch`/`watches` stayed silent and kept resolving to the
  shared default socket, splitting the fleet without erroring anywhere. The
  check now reads the installed supertool's own `presets/watch/naming.py:
  declared_names()` (never re-derived locally) for the finer question -- which
  watch ops actually declare the name -- and reports `WARN` for a partial
  declaration, and `WARN` rather than a silent `OK` when that finer question
  cannot be answered at all. A fully-declared repo, and a repo (like this one)
  that derives its name rather than declaring it, are both unaffected (#623).

- A launcher-opened session no longer pays for `claude mcp get oss-channel` twice.
  `bin/oss-workspace` already asks this at session-open (to decide whether to
  register the channel consumer); `scripts/doctor.py`'s own registration check
  (added in #621) asked it again a few lines later, in the `doctor.sh` invocation
  the same launcher performs. `claude` is not a cheap binary to start (~1.3s
  measured on one machine): `bin/oss-workspace` now exports the raw answer it
  already computed (`OSS_WORKSPACE_MCP_CHECKED`/`_STATUS`/`_OUTPUT`), unset again
  before the session itself starts so it cannot go on answering a later in-session
  `/oss:doctor` run with a session-open-stale reading, and `doctor.py` reads that
  handoff instead of shelling out a second time. Trusted only for the launcher's
  own hardcoded channel server and only when the handoff parses; any other caller,
  or a malformed handoff, falls through to the real subprocess call unchanged.
  A standalone `doctor.sh --root .` invocation (no launcher, no handoff) is
  unaffected and still asks directly (#629).

- Fixed: the `.oss.json` jit-context rule (`.claude/jit-context/paths/01-oss/oss-config.md`,
  shipped into every scaffolded repository as `OSS_CONFIG` in `scripts/oss_rules.py`) matched
  `\.oss\.json` unanchored, so it fired on `.oss.json.bak`, `.oss.json.orig`, and any path
  carrying `.oss.json` as an inner segment -- injecting confident config prose about the wrong
  file. Anchored to `(^|/)\.oss\.json$`, the same shape the changelog-fragments rule already
  used. `tests/test_jit_oss_config_anchor_639.py` pins the must-fire and must-not-fire cases in
  the same fixture, plus that the `.md`, the `OSS_CONFIG` twin, and the built `00-index.tsv`
  all agree on the pattern (#639).

- `.supertool.json` declares `watch_name` (`Digital-Process-Tools-claude-oss`) under all five
  watch ops -- `channel`, `radar`, `unwatch`, `watch` and `watches` -- so every supertool op
  touching this repo's watch channel resolves the name from the tracked config instead of the
  environment. Previously the loop's own receipts on every tick warned that the channel name
  "came from the environment" and that the socket and poller slots "may be another project's
  fleet" -- and `radar` (the bare heal) writes into those poller slots, so the loop was forking
  pollers into a fleet it could not attribute. `tests/test_supertool_config.py`'s own #189
  guard used to refuse any declaration here at all, on the reasoning that a hand-typed name
  would copy-propagate into another repository verbatim; that guard's own docstring named the
  condition under which it expected to be revisited ("once #192 lands"), and #192 and #230 both
  landed with nobody returning to it. The guard is now a derived-equality assertion instead of
  an absence one: it requires every declared name to equal what `oss_config.watch_channel_name`
  derives from this repository's own `.oss.json`, which catches #189's copy-propagation harm
  strictly better than an absence check did -- copying this file into a repo with a different
  `repo` in `.oss.json` now fails the test, where the old guard could not tell the two repos
  apart (#648).

## [0.14.0] - 2026-08-26

### Added

- A new `/oss:install-audit` command (`--install-audit` on `scripts/doctor.py`) answers *is this
  install complete* for a repo with no issue, no pull request and no history to read -- the state
  `/oss:doctor` correctly degrades on, five checks declining with `.oss.json was not found`. This
  is a different subject -- the plugin, its declared dependencies, and what the human still has to
  do, not this repository -- so nothing here is gated on a config a fresh install has not written
  yet. Checks `.oss.json` present, valid, *and committed* (not merely present -- `git ls-files`
  answers whether a clone of this repo would ever see it); every declared dependency resolves at a
  version whose contract this plugin's own scripts can read; the `./supertool` entry point and the
  `oss-workspace` launcher; `identity.md`, wherever the install layout actually reads it; the label
  vocabulary the triager needs; and the owned files, when a config was found to render them
  against. Every question is `satisfied` / `missing-with-a-named-remedy` / `could not tell`, and
  none of the three is ever a `FAIL`: a fresh install with nothing configured yet is exactly the
  case this command is for, not a broken one (#287).
- Folds in #286's own finding as evidence this remedy is checked against, independent of the
  remedy itself: the label-taxonomy gap on a fresh repo is one of the checks above, and whether
  `${CLAUDE_PLUGIN_ROOT}` goes stale across a tick is reported to the maintainer as left open --
  it is a fact about a running session, not about a repo on disk, and nothing this command reads
  can answer it from outside one.

- `/oss:doctor` now checks whether a `pre-push` hook's push budget was ever raised above
  supertool's 300s default (#295). Four states: `not-applicable` when there is no
  `.git/hooks/pre-push` at all -- reported OK, not as a gap, since the default is correct there
  and a checker that warns on every correctly configured repo is worthless; `configured` when a
  hook exists and `.supertool.json`'s `ops.git-push.budget` is set strictly under
  `ops.git-push.timeout` from the same merged entry -- the same arithmetic supertool's own
  `git-push` op would otherwise refuse at push time, done here instead; `actionable` when a hook
  exists and either no budget was set or the arithmetic does not clear; and `could-not-tell` when
  `.supertool.json` could not be read or the block is malformed. Structural only -- the hook is
  never executed, so its actual duration is never measured, and the report says so rather than
  implying a number was checked.

- A tick now records its own plugin identity and compares it against the last one recorded
  (#477). Before this, nothing remembered which plugin version or content a tick ran under, so
  "has the version changed since last tick" was not a question the loop could answer -- one of
  its two operands was never written down. `scripts/oss_state.py` gained `--plugin-identity`
  (attach `doctor.plugin_identity()`'s reading -- version folded with a content digest, never the
  version alone, since a manifest version stays at the last released number for a whole release
  cycle -- to a `--decision` entry) and `--check-plugin-identity` (compare this tick's reading
  against the most recently recorded one, scanning back past intervening entries the same way
  `--pending-wait` already does). Three states, not two: `changed`, `unchanged`, and
  `could-not-tell` when no prior tick ever recorded one -- which must never render as
  `unchanged`. `commands/tick.md` step 1 wires the comparison; step 6 records this tick's own
  reading for the next one. Whether to auto-re-run the rest of the diagnostic on a `changed`
  verdict is left as a per-tick judgement call rather than built in.

- A dispatched lane's fleet-view label now carries the count of issues it bundles,
  not just the first one: `Lane 534 x3  auto-update path` instead of `Lane 534  auto-update
  path` for a lane that also carries #537 and #495. `scripts/fleet_label.py` composes it
  and refuses to print anything when the caller has not named every issue the lane
  carries, so a lane briefed from a script that never ran cannot fall back to the thin
  label (#539).

- A census of the places this repository states a fact whose authority is somewhere
  else -- another tool's accepted-input pattern, a forge's documented limit, a
  command's own rules -- so a new site is compared against the #180 rule instead of
  being invisible to it. `scripts/borrowed_authority.py` lists six sites, three
  already resolved (derived or measured) and three unmeasured, two of them newly
  found by this census: GitHub's Checks API vocabulary in `statusline.py` and its
  closing-keyword syntax in `report_schema.py`. A test guards against a censused site
  silently drifting -- its symbol renamed or removed with the entry left behind (#544).

- `/oss:doctor` (`scripts/doctor_check_latest_skew.py`) now cross-references the
  status line's cached `latest` for this repo against the newest published
  version read live, so the two mechanisms this plugin has for "am I current"
  are compared by something rather than by a maintainer doing it by hand. `OK`
  when they agree (with the cache's own age reported anyway -- a fresh
  agreement and an hour-old one are not the same evidence), `WARN` when they
  differ (naming both values -- a report about the cache, not a fault in the
  repo), and `WARN ... could not be determined` for a missing cache, an
  unreadable one, one that parses to the wrong shape, or a live read that did
  not answer. Never repairs the cache: doctor's contract is diagnose, exit 0,
  one VERDICT line, and clearing the cache here would destroy the evidence of
  the skew it reports (#551).

- Added a jit-context vocabulary entry, `plugin-currency.md` in the `01-oss` layer, covering the
  three readings routinely called "the plugin version" — the clone's manifest, the copy a session's
  command text resolved from, and the unpacked cache — plus what `/reload-plugins` moves that a
  restart also moves, which field each status-line currency marker prints, and how the cached
  `latest` reading is sourced and invalidated (#554).

- `lane_setup.py` can now derive the held-file set instead of accepting it retyped by hand: a new
  opt-in `--derive-held` mode (`derive_held_set`) reads every open pull request's own file list
  (`gh pr list --json number,files`) and every live lane record's own files (the lane registry
  extended to carry them, `record_lane`'s `files`), and reports a per-candidate verdict --
  `available`, `blocked` (naming the file and its holder, e.g. `PR #9` or `lane #12`), or
  `could-not-derive-the-held-set` when the forge call or the registry could not be read, which
  is never rendered as `available` or `blocked`. The local, offline `--lane`/`--against` path is
  unchanged and remains the default. The tick-level fill verdict (filled / under-filled /
  could-not-tell) is deliberately not computed here -- it needs the full candidate list a tick is
  weighing, which is a judgement this script has no way to derive from one `--lane` argument, and
  stays prose in the tick (#558).

### Changed

- The manager skill is split into a spine and one file per phase. `skills/manager/SKILL.md` is
  loaded whole by every `Skill(manager)` invocation -- `/oss:tick` and `/oss:release` both open with
  one -- and at 122,423 B it was the largest file in this repository, 1.6x `agents/developer.md`,
  standing in a session's context for the whole of every tick whether or not that session reached
  the phase a given paragraph governed. #491's budget deliberately did not cover it, so nothing
  counted it at all. The spine is now 58,377 B and carries what is decided every tick plus one
  directive block per phase; the argument behind each phase's rules moved to
  `skills/manager/phases/{dispatch,handback,review,merge,release,accounting}.md`, read when the loop
  enters that phase. A `/oss:release` session no longer loads the dispatch, handback and review
  material at all. The total prose grew 122,423 B to 142,188 B, +16%, because the spine's directive
  blocks restate each phase in short before the phase file argues it at length: what fell 52% is
  what a session loads before it knows which phase it will reach, and both numbers are recorded in
  `CLAUDE.md` so the saving is not read as free (#568).
- `scripts/skill_phases.py` declares a budget for the spine and for each phase file, on the same
  replace-don't-append terms as `scripts/agent_budgets.py`, and reports `unreferenced` for a phase
  file the spine has stopped naming -- a file the spine never names is one the loop can never reach,
  and it renders exactly like a phase whose rules were deleted. Whether a reader actually opened a
  phase file is not observable here and is not claimed to be: the spine asks each phase to state
  `read` / `not-read` / `could-not-read` beside its own result. It also reports `undeclared` -- a
  phase file on disk that no budget names, the mirror of `missing`, because reporting only the
  declared paths answers "every file I know about is fine", which is true of an empty declaration
  too (#568).
- `scripts/manager_docs.py` derives the manager loop's document set from disk and is now what every
  content guard reads, in place of opening `skills/manager/SKILL.md` directly. Left unchanged, 66
  checks across twelve modules would have gone on passing over a document that no longer held their
  subject -- the coverage-narrowed-without-saying-so shape #547 records, one directory over.
  `checklist_skew.py`'s definition derivation now matches `skills/manager/phases/*.md` alongside
  `agents/*.md` for the same reason. Two guards fired on the wider set and were fixed rather than
  waived: a config-key check triggering on `cd <worktree_root>` in a shell line, and a section
  extractor that ran past the end of its own file into the next one's heading (#568).

### Fixed

- `scripts/assemble_changelog.py`'s `collect()` no longer reports a permission-denied
  `changelog.d/` as a confident "does not exist" — `Path.is_dir()`/`Path.exists()`
  swallow `OSError` to `False` on some interpreter versions, so a directory that was
  right there but could not be probed used to raise `BadFragment` with the same
  message a genuinely absent directory earns. `collect()` now asks `os.stat()`
  directly through a three-state `_fragment_dir_state()` and raises `CannotValidate`
  (skipped, not a finding) when it cannot determine the answer. A self-review round
  found the first version of this fix trusted a bare `FileNotFoundError` as absence
  on its own, which is exactly the fold CLAUDE.md records for an over-`MAX_PATH` name
  on Windows (`FileNotFoundError, errno 2, winerror None`, indistinguishable from a
  genuine miss) — `_fragment_dir_state` now confirms absence positively via a third,
  standalone copy of `doctor._dir_state`/`lane_setup.worktree_occupancy`'s own
  ancestor-walk classifier before ever returning "absent". The sibling filter one
  loop-iteration below (`path.is_dir()`, skipping subdirectories while collecting
  fragment files) was swept and judged correct as-is: it only filters a list rather
  than printing a verdict, and even swallowed to `False` its worst case is a loud
  `read_text()` failure a few lines later rather than a silent drop.

  `scripts/lane_setup.py` was also swept — the coverage gap the previous pass on
  this issue (#463) named by name, since it was mid-review at the time. The same
  self-review round found `resolve_lane`'s glob-match filter (`p.is_file()`) was
  not the safe filter site it first looked like: `Path.is_file()` wraps the same
  version-dependent swallow, and unlike the sibling site above, a silently dropped
  match here can empty the whole `matches` list and flip the pattern's own state to
  `glob-no-match` — a printed verdict `lane_overlap` consumes for its lane-collision
  check, not a harmless filter. Fixed the same way, through `stat()` directly rather
  than the convenience wrapper. Everything else in the file was already hardened by
  #373 and #380 (`worktree_occupancy`, `lane_count`, `_absence_confirmed`).

  Also surfaced and left unfixed, for filing rather than folding into this pass:
  `repo.glob()` itself silently drops an unreadable subdirectory while walking a
  recursive (`**`) lane pattern — the same swallow class this issue is about, one
  level up, in `Path.glob`'s own traversal rather than in a bare `.is_dir()`/
  `.exists()` call beside it. Reimplementing glob-pattern matching over `os.walk`
  to close it is a design decision past this pass's blast radius.

  `scripts/oss_config.py` remains unswept — it was held by an open pull request at
  the time of this pass, same as it was at the time of #463's own pass. That is a
  gap in coverage, not a clean result, and this fragment says so rather than
  inheriting the silence (Part of #383).

- `bin/oss-workspace`'s consumer probe no longer masks a crashing registry read with
  `|| true`: a malformed `installed_plugins.json` (not a JSON object, or a plugins
  entry that is not a JSON object/array) now reaches `cannot_ask()` loudly instead of
  producing a silently-discarded `AttributeError`, matching the guards
  `scripts/doctor.py`'s `_consumer_watch_name_verdict` already carries (#546).

- `checklist_skew.py`'s definition-file comparison and `tests/test_statusline_479.py`'s
  hostile-leaf walker both derive their coverage set from what is actually consumed
  instead of a fixed list kept beside it. `checklist_skew` now compares every
  `agents/*.md` path one of its three base files names in its own prose, which was
  short by `agents/developer.md` -- the file `agents/auditor.md` delegates its
  platform band to. The statusline fixture now carries `default_branch` and
  `release`, the two top-level keys `render()` reads that its walker could never
  reach (#547).

- `plugin_update.opt_out`'s ancestor walk no longer reads `FileNotFoundError` out
  of a candidate directory's listing as "nothing declared here, keep walking" --
  Windows folds an over-`MAX_PATH` name onto that same exception, indistinguishable
  from a directory that genuinely does not exist, so a repository that opted out of
  auto-update could be silently skipped and reported as `"on"`. The walk now
  confirms genuine absence against the candidate's own parent listing before
  continuing past it, the same idea `scripts/doctor.py`'s `_dir_state` already
  applies to a different question (#548).

- `/oss:release` (`scripts/release_publish.py`) now invalidates the status line's
  cached `latest` for this repo immediately after the Release it just created --
  the publish is the event that falsifies that cache, and this is the only actor
  that knows it happened at the moment it does, rather than waiting out a refresh
  interval that cannot see it. Reported under a new `cache_invalidation` key --
  `invalidated` / `nothing-to-invalidate` / `could-not-invalidate` -- separate from
  the publish's own `state`, so an absent directory, an unreadable cache, or a
  different `XDG_CACHE_HOME` than the rendering session never renders as
  agreement. Measured: a cache stamped 17:54 holding `0.12.0` was still cached 40
  minutes after `v0.13.0` published at 18:06, read at 18:46 -- 52 minutes against
  a 60 minute refresh interval, so the reading was not stale by its own rule and a
  shorter interval would not have caught it either (#549).

- `scripts/statusline.py`: the plugin-currency comparison now carries the cached
  `latest` reading's own age to the render, so a comparison older than its own
  refresh interval folds into the existing `?` bucket instead of rendering a false
  `behind`/`ahead`. The `behind`/`ahead` unicode markers -- one codepoint apart and
  told apart reliably only by colour, while printing different fields -- now differ
  in shape (`↥` vs `↑`). This is the render-readability half of the incident fixed
  by #549; it does not by itself catch a reading that is fresh by its own rule and
  simply wrong (#550).

- The two messages that told a maintainer to `restart Claude Code` after an
  auto-update -- `doctor.check_auto_update`'s WARN and `plugin_update.update`'s own
  receipt `detail` -- now also name `/reload-plugins` as the cheap first step, matching
  the wording `scripts/doctor.py` already used in three other places. Neither message
  presents it as a full substitute: `/reload-plugins` moves the registry (which agents,
  skills and commands resolve), and both messages still say a restart is needed for
  command text already injected into the running turn. #81's whole cost traced to a
  stale registry in an unreloaded session; the message that told the maintainer to
  restart never offered the cheaper remedy first (#553).

- The census entry for `report_schema._CLOSING_KEYWORD` now records what the keyword
  list is used for -- an absence detector, never a decision about what a body will
  close -- and why a negated closing sentence ("does not close #241") is harmless
  under it: GitHub matches a closing keyword by its position relative to the
  reference, not by sentence meaning, and this checker is exactly as positional as
  the forge is. That fact is now stated beside `_CLOSING_KEYWORD` itself and pinned
  by tests, rather than left implicit in a comment that addressed a different
  question (#556).

- The `.gitignore` template `/oss:scaffold` writes into every repository ignored `.oss.json` --
  the file this loop calls tracked and authoritative -- while leaving the comment beside it
  describing the machine-specific half in name only. A second maintainer cloning a repository
  scaffolded from that template got no config at all: `git add .oss.json` silently refused. The
  template now names `.oss.local.json`, the file that actually is machine-specific, instead.
  `.gitignore` is a *defaults* file -- created once, then the managed repo's forever -- so this
  fix reaches only repositories scaffolded after it ships; every already-scaffolded repository
  keeps the stale line unless a maintainer removes it by hand. `/oss:doctor` now reports that
  case as a FAIL naming the exact `.gitignore:line` rule, so it is at least visible rather than
  permanently silent (#564).

- `lane_setup.py`'s cross-cutting guard table (`CROSS_CUTTING_GUARDS`) names test files that exist
  only in `claude-oss`'s own tree, so a lane dispatched into a managed repository was told to run a
  guard whose test file was never there -- a guard that could not run read exactly like a guard that
  passed. `guards_for_files` and `known_guards` now take an optional `repo` and report each guard's
  `status` -- `exists`, `absent`, or `could-not-tell` when the repository could not be examined -- and
  the receipt names an absent guard as "NOT IN THIS REPO, treat as uncovered" instead of a bare test
  path a lane would run and get nothing back from (#566).

- `.claude/jit-context/tools/01-oss/supertool-required.md` (and its mirror in
  `scripts/oss_rules.py`'s `TOOLS_SUPERTOOL`) claimed "Nothing. No shipped `claude-jit-context`
  release reads a `requires:` field" -- true when #524 wrote it, false since `claude-jit-context`
  0.6.0 shipped the reader. That release does honour `requires: supertool`: an installed
  `claude-jit-context` 0.6.0+ with no `supertool` on `PATH` now degrades this rule's `mode: block`
  to a named, visible advisory (`degrade_note`) instead of blocking outright, which is what left
  `tests/test_supertool_rule_requires_field_524.py` red on any developer machine with the plugin
  installed while CI, which caches nothing, stayed green. The rule body is rewritten to describe
  the shipped behaviour, measured against the installed 0.6.0 cache rather than asserted, in both
  copies. `mode: block` itself is unchanged -- the rule's own argument for keeping it declined to
  narrow only "until requires: ships"; it has, and the degrade is what answers the case that
  argument was hedging against, so the conclusion holds rather than needing revisiting (#570).

- `manager_docs.documents()` used `Path.glob("*.md")` to list
  `skills/manager/phases/`, which swallows `PermissionError` while it walks and
  silently yields nothing for a subtree it could not enter -- so a denied phases
  directory narrowed the manager loop's document set to the spine alone, with no
  raise and no signal, turning every content guard built on it (thirteen test
  modules, `MANAGER_DOC_PATHS` chief among them) into a vacuous pass over one file
  instead of seven. `documents()` now returns `(paths, unreadable)`, using
  `iterdir()` instead of `glob` so a deny can actually be reported -- the same fix
  `doctor._workflow_scan`/`_rglob_md` already apply to the identical `rglob`
  swallow one directory level down (#571).

- `checklist_skew.py`'s `matches` state used to return before the byte-for-byte
  definition comparison ran, so a repo whose installed and shipped manifest versions
  agree -- the state this repository is always in at release time -- never had its
  checklist definitions compared at all. `compute()` now runs `_compare_definitions`
  on every state where both manifests could be read, and `matches` carries
  `definitions` the same way `differs` already does: a `matches` payload carrying a
  `differs` row is a config finding the release report must quote (#572).

- `bin/oss-workspace`'s `ASK_CONSUMER` probe no longer masks a crashing consumer
  read with an unguarded `|| true`: a validly-formed but pathologically deep
  `installed_plugins.json` that raises `RecursionError` out of `json.load` (neither
  `OSError` nor `ValueError`, so uncaught by the block's own guards) now reaches the
  same "could not ask the installed supertool" message the block's `cannot_ask()`
  gives every other unreadable-registry case, instead of a traceback that a swallowed
  exit status let the launcher silently continue past. That message renders the
  (unvalidated, possibly attacker-exported) watch channel name the same way
  `cannot_ask()` itself does -- via a repr(), never interpolated raw -- and via
  `printf`, not `echo`, since this platform's `echo` builtin re-interprets the
  very backslash escapes `repr()` relies on to keep a newline or a terminal
  escape sequence in that name from reaching the receipt unescaped (#573).

- `oss_state.py`'s write-side `RECORDED plugin identity:` receipt now routes through
  `_receipt_line` like every sibling receipt in the module. A newline in `--plugin-identity`
  used to print a second `RECORDED plugin identity:` line at column 0 while only one record
  was made -- a reader, or anything parsing the receipt, saw two entries for one write.
  Found by the `v0.14.0` release gate, round 1 (#574).

- `checklist_skew.py` reported `differs` (or `matches`, by coincidence) for a
  managed repository that ships its own, unrelated `.claude-plugin/plugin.json` --
  reading the manifest was treated as proof the repo ships the `oss` checklist,
  when it can belong to an entirely different plugin. `compute()` now checks how
  many of the derived definition files actually exist in the repo tree: zero means
  the repo does not ship these definitions at all, and the version comparison has
  no subject, so the state is `could-not-tell` rather than a stale-or-matching
  claim about two unrelated numbers (#580).

- `bin/oss-workspace` no longer exits 1 and opens no session when the consumer
  probe crashes. #573 replaced the `ASK_CONSUMER` heredoc's trailing `|| true`
  with a captured `ask_consumer_status=$?`, but the `|| true` had been doing
  two jobs -- swallowing the status *and* suppressing errexit -- and only the
  first was replaced. Under `set -eu`, a crashed probe killed the whole script
  before the 34-line "could not ask" arm written to report exactly that state
  ever ran. The fix moves the status capture onto the heredoc opener itself
  (`... <<'ASK_CONSUMER' && ask_consumer_status=0 || ask_consumer_status=$?`),
  the same idiom the launcher already uses for its doctor-diagnostic call.
  Found by the `v0.14.0` release gate's round-2 audit, on this delta's own fix
  for #573 (#588).

## [0.13.0] - 2026-08-25

### Added

- `doctor` now checks `.remember/core-memories.md` on its own -- what the loop
  has LEARNED, distinct from `identity.md`'s who-it-is check and never folded
  into it. Four states: a wholly absent store reads OK (already covered by
  `check_memory`'s own warning, not doubled here); a store present with no
  core-memories.md is OK, since that is correct on a repo's first day; present
  and empty is a WARN distinct from absent; present with content is OK,
  reporting the entry count and newest entry's date structurally, never the
  entries' own words. An unreadable store or file reads as unknown, never as
  "nothing recorded" (#210).

- `.oss.json`'s `release` block gains `authority`, a per-repository grant for the two
  release Stops the loop otherwise always asks about: tagging and publishing. `"loop"`
  means the loop tags and publishes without stopping and names the grant in the release
  report; `"maintainer"` is an explicit, unconditional stop; and absent, unreadable, or an
  unrecognised value reads as `"not-declared"`, which stops the same as `"maintainer"` --
  it must never default to autonomy. `scripts/oss_config.release_authority()` is the
  single reader; `skills/manager/SKILL.md`'s Stops table and `commands/release.md` both
  read it rather than asserting the answer, and `/oss:doctor` reports which state a repo
  is in before the tag step rather than at it (#478).

- Added a `PostToolUse` hook (`scripts/batch_hint.py`) that flags a run of 3 or more
  consecutive single-op read-only supertool calls with one line naming the collapsed form.
  Measured over 612 transcripts, 21.5% of tool turns sat in exactly this kind of collapsible
  run, and a paragraph in `agents/developer.md` asking agents to batch measured at zero
  effect -- including a controlled A/B where the treatment brief made the single-op rate
  worse, not better. The hook replaces that paragraph: it costs nothing on a clean run and
  only ever emits one advisory line, never blocking (#490).

- Added a size budget for each `agents/*.md` definition (`scripts/agent_budgets.py`,
  `tests/test_agent_definition_budget_491.py`), with the current sizes recorded in
  `CLAUDE.md` so a crossing is visible instead of gradual. Turn-1 context is a median 44%
  of a whole agent's cache-read consumption and every byte there is re-read on every
  remaining turn; deduplication was measured and ruled out (1.2%-6.5% shingle overlap
  between the largest files), so the budget is paired with a replace-don't-append rule
  rather than a request to cut. The budget cannot and does not judge whether a paragraph
  earns its size -- that stays a human call (#491).

- `scripts/transcript_refusals.py` now measures the two costs #498 found in 612 agent
  transcripts: `turns_over_threshold_count`/`_share` against a 140-turn threshold (the
  measured p90 -- five of the longest lanes alone accounted for around 7% of all
  consumption), and `decile_bytes`/`first_fifth_byte_share`, the bytes-and-calls-by-decile
  split showing bytes concentrate in the first fifth of a lane while call counts stay flat.
  Both are measured after a lane completes, never surfaced to the agent mid-run -- this
  repository has measured twice already (`developer.md`'s batching paragraph, #490's A/B)
  that a judgement-shaped instruction in a brief does not change behaviour, and a metric an
  agent can see is a metric it will optimise by the cheapest route, which here means fewer
  files read or a positive control skipped (#498).

- The status line now shows two time facts instead of none: a wall-clock stamp of when the
  line was last rendered (`last 23:47`), and the age of the user's own last message (`you 4m`).
  A naive "last message age" cannot work here -- the line only re-renders on an event (a new
  assistant message, `/compact`, a permission-mode change), so that value would be computed at
  the exact instant it reads zero and then freeze there for however long the loop actually
  stalls, confirmed against Claude Code's own "When it updates" documentation rather than
  inherited from this module's docstring. The user-message age is genuinely non-zero at render
  time instead, because a render only happens after the assistant has answered it. Both fields
  carry the same three states as everything else on this line -- a scan that never reached a
  timestamped record prints `?`, never a stale zero (#504).

- The status line reports where the next release stands (#507). A `rel 4/17` field: commits landed
  since the newest version tag, over the median size of the recent releases -- both halves derived
  from this clone's own log and tags, so they are in the same unit and cannot describe different
  things. Local git rather than the forge, because the cached board counts beside it are up to five
  minutes old and a commit that just landed has to move this number now.
- Each half of that field carries its own `?`. A clone with no version tag has no boundary to count
  from and renders `rel ?/?`; one with a single tag knows exactly how much is banked and nothing
  about the usual size, and renders `rel 4/?` rather than throwing away the half that was measured.
  Zero commits since the tag stays a `0`. The log window is bounded at 500 commits because this
  renders once per message, and a window that does not reach the previous tag reports the missing
  half rather than a smaller history. A tag `_version_tuple` cannot parse is not a release boundary
  -- `wip/274-preserved` is a real tag here and shipped nothing.

- The session tells the status line when it has just changed the board (#516). A `PostToolUse` hook on
  `Bash` marks the cached board stale after a command that merges a pull request, opens one, or
  creates, closes or reopens an issue -- so the line is right in the seconds after a merge, which is
  when it is most watched, rather than at the end of the refresh interval.
- The hook never fetches. It runs after every `Bash` call and a network call there would put `gh`
  latency in front of all of them; marking the cache stale is enough, because the render path already
  forks a detached refresh when it sees one.
- The mark carries a ten-second settle delay, and the reason is the forge rather than this code:
  `search/issues` is served from an index that trails the merge that changed it, so a refresh fired
  the instant a merge returns can record the pre-merge counts under a fresh stamp -- staler than
  having done nothing.
- The classifier anchors at command position rather than matching a substring: `git commit -m 'gh pr
  merge closed it'` names a merge and runs none, and `grep -r 'gh-issue-create' docs/` is a read. A
  command wrongly matched costs one refresh and a missed one costs a stale board, so the matching is
  generous inside that anchor.
- Every failure path in the hook is silent and exits 0, including unreadable input, a directory this
  loop does not manage, and an unwritable cache. A hook that raises reaches the user as a broken tool
  call on every command they run.

- Every agent report now carries a required top-level `compliance` survey (schema version 6,
  breaking), so a lane that declines part of its own brief has a field to say so in rather than a
  sentence that only surfaces if a maintainer happens to read the transcript. The observed gap: a
  spawned reviewer misread a repository's own tracked policy file as an injected instruction,
  declined the tooling it named, and kept going -- its findings were sound, so nothing about the
  report looked degraded, and the refusal was visible only because the agent happened to mention it
  in prose. `checked` with no items means the brief was executed as written; an item naming an
  instruction with no reason is refused (`scripts/report_schema.py`, `_rule_compliance_item`), the
  same way an argued refusal is required elsewhere in this contract. Placed at the top level rather
  than nested under `review`, because the same silence is available to a developer lane declining a
  clause of its own brief, not only to a reviewer it spawns. The schema's own `x-honesty-compliance`
  names the limit this does not close: an agent that genuinely believes it is refusing an injection
  has a coherent reason not to log the refusal as a decline, so this field catches the honest cases
  only -- worth more than zero, not a guarantee (#518).

- Release gate 3's "record the checklist in effect before you spawn" step is computed rather than
  performed by hand: `scripts/checklist_skew.py` reads the installed plugin's
  `.claude-plugin/plugin.json` and this repository's own, and reports `matches` / `differs` /
  `could-not-tell`. Before this, the honest answer was always `could-not-tell` and the rendered
  answer was usually nothing, because nothing computed it and a human had to type it into the audit
  payload by hand -- which is how the `v0.13.0` release audit ran a 0.11.0 checklist against a
  0.12.0+21 tree and only knew because the dispatch payload said so (#538). `differs` also carries a
  byte-for-byte comparison of the files gate 3's spawn actually reads --
  `agents/release-auditor.md`, `agents/auditor.md`, `skills/manager/SKILL.md` -- as evidence, never
  as a verdict: a byte-identical row is not proof that nothing relevant moved elsewhere in the two
  trees. This annotates only; it never blocks the release, the same way an unscoped delta already
  does not.

### Changed

- Gate 4 of `## Releasing` in `skills/manager/SKILL.md` no longer stops on a `proposed`
  version number: it accepts the fragments' proposal and records it by default, the same
  way deriving the number was already listed as the loop's under `## Who decides`.
  Override stays available. A major bump (`1.0.0` or later) keeps its own stop, because
  that promise to users is a different promise. This is deliberately decoupled from
  `release.authority` (#478) -- the version-number decision reads no key at all, so a
  single grant cannot silently widen into a second one (#467).

- Compatibility: compatible - the receipt shape, exit codes and the `no state but
  proposed names a number` rule are unchanged; only who accepts the proposal moved, and
  overriding still works exactly as before.

- `scripts/doctor.py` was 318 KB in one file, and an agent working on one check
  paid for reading past every other check's own prose to find it -- roughly 12
  narrow probes per lane, measured across 612 transcripts. This lane moves five
  self-contained checks (`check_auto_update`, `check_statusline`,
  `check_fragments_readme`, `check_memory`, `check_merge_permission`) into their
  own modules under `scripts/`, each carrying its private helpers and its prose
  unchanged. `doctor.py` keeps `main()`, the check registry and the shared
  contract (exit 0 always, one VERDICT line) and re-exports every moved name, so
  `doctor.check_memory` and friends answer exactly as they did before. This is a
  pure move: no check's logic changed, and doctor.py's own CLI output is
  byte-identical before and after except for the plugin's own content-digest
  line, which necessarily moves when five files are added to the tree it
  digests. The remaining 17 checks are left for later lanes (#497).

- The dispatch step now looks for one or two companion issues touching the same file or module
  before naming a single-issue lane, and bundles them into one lane, capped at three and never
  four -- measured across 237 lanes in this repository's own transcripts, three issues in one lane
  cost 16% less per issue than one, while four or more is a 68%-worse cliff. A bundle of two or
  three stays two or three fixes, never one: each issue keeps its own test story and its own
  changelog fragment (#499).

- The pull-request field says what CI thinks, and stops shouting (#508). `1PR . 23IS` is now
  `4pr 2ok 1x 1... 0? . 23is` -- lowercase like the fields either side of it, and broken down by
  check-rollup state: passed, failed, still running, and unknown. One number could not tell one
  green pull request from one red one, which is the question the field exists to answer.
- Every group renders, including the ones at zero: `0x` -- nothing red -- and `0...` -- nothing on
  the way -- are two of the more useful things this line can say, and a group that vanished when
  empty would make the reader subtract to find it. What does collapse is a reading that never
  happened: rollups the forge did not answer render as a single `?`, never as four zeros.
- The rollup is computed here from each pull request's own legs rather than read off GitHub's
  precomputed `statusCheckRollupState`. Dogfooding settled it: `gh 2.50.0` answers `Unknown JSON
  field` for that one and the whole column rendered `?`. The legs are carried by both versions --
  and the mapping is a decision about what a maintainer needs to see, so computing it here is what
  puts it under test rather than in the forge.
- A rollup that is neither a pass nor a pending is counted unknown rather than green. Cancelled,
  neutral, skipped, timed out and a pull request carrying no checks at all are none of them
  successes, and folding them into the green group is how a status line comes to report a board
  that is fine. The rollups are read one page at a time and the count beside them is exact, so any
  pull request past that page lands in the unknown group -- the four groups always sum to the total.

- The status line renders the branch only when it is not the declared default (#509). In the clone
  that field read `main` on every message, and this loop does its work in worktrees, so it spent
  width in the one place it carried nothing and looked identical in the place it carries news.
- Silence there means "measured, and it is the default", and nothing else: a branch git could not
  report still renders `?`, and a repo whose `.oss.json` declares no default branch has nothing to
  compare against and renders the branch as before. The comparison is to the declared default, never
  to the word `main`.
- The branch name is folded through `_one_line` on its way to the line, like every other value the
  renderer did not produce itself. A worktree can be checked out on a ref whose name came from a
  fork's pull request, and an ESC in it rewrites what the terminal has already printed.

- The plugin block collapses to a count while everything is current (#512).
  `oss 0.12.0 ✓ · supe 0.49.0 ✓ · reme 0.21.0 ✓ · jit 0.5.0 ✓` -- 45 characters to say there is
  nothing to do -- is now `plug 4✓`, and anything not current is named beside it:
  `plug 3✓ supe⇡0.49.0`.
- The count is what makes the collapse safe rather than an absence. `plugin_facts` already argues the
  case: a plugin absent because it is fine and a plugin absent because nothing looked at it render
  identically, and only the second is a problem. `4✓` says four were looked at and four answered,
  `plug ?` says nobody looked, and a plugin whose versions could not be compared is neither -- it
  gets its own group rather than being counted current.

- The status line's cache has two clocks instead of one (#515). The board -- open pull requests, open
  issues, their check rollups -- refreshes every 60 seconds; the version each installed plugin's
  source repository publishes refreshes hourly and is carried forward in between. Four of a refresh's
  seven forge calls were the second kind, answering a question that moves on the order of weeks, and
  one shared interval meant the half a maintainer watches during a merge waited on them. Observed at
  `1pr 1✓ … 23is` against a tracker holding `0pr · 20is`, with the cache 372 seconds old.
- A carried-forward version keeps its own stamp. Stamping it at the time of the board refresh would
  make an hour-old reading indistinguishable from one just taken, and a lookup that fails now keeps
  the previous answer under the previous stamp rather than erasing a plugin's published version
  because the network was down for one call.
- A cache written before the split carries one stamp and no `latest_fetched_at`; that stamp is when
  those versions were fetched, so it is what their age is measured from. Treating the missing field
  as "just now" would freeze the version column for a full interval on every upgrade.

### Removed

- The `you` field is removed (#513). It reported how long since the user last spoke, and it counted
  tool results as the user speaking: Claude Code records a tool result as a user-role record, and
  this repository's own transcript is 103 user-type records of which 90 are tool results, so the age
  read seconds during exactly the long turns the number was worth having.
- Filtering those out was implemented, tested and then thrown away, because it fixed the wrong half.
  A message typed while a turn is running is not written to the transcript until the turn ends, so
  the honest version of this field still lags the conversation by the length of the turn -- it read
  `you 15m` against a message sent seconds earlier. A number that is wrong in a way the reader cannot
  see is worse than no number.
- `last` covers what it was for. A clock reading of when the line was last rendered says how stale
  everything on it is, in one field, without a second one to be wrong about.

- Compatibility: compatible - a status line field that nothing else reads. `.oss/statusline.py` is
  an owned file and is replaced wholesale on the next `/oss:scaffold`, so no repository carries a
  configuration naming this field.

### Fixed

- The shipped-op sweep (`tests/test_shipped_op_spellings.py`) claimed to cover
  "everything this plugin ships that a reader executes" while its four globs never
  read `bin/oss-workspace` or `scripts/doctor.py` -- 15 `supertool 'OP...'` remedies
  printed to a user's stderr at runtime, uncovered since #218. Widened to the doctor
  entry point's own execution surface (`doctor.py` and every `doctor_check_*.py`
  module) and to the workspace launcher, and narrowed the docstring's claim to match
  what is actually swept -- not `scripts/*.py` as a whole, which would misreport the
  illustrative `supertool 'op1' 'op2'` example in `scripts/batch_hint.py` as an
  undeclared spelling (#224).

- The maintainer skill now names the trap directly: never derive a commit count or a commit
  identity by parsing rendered `git log` text. The maintainer's own shell rewrites `git …` through
  an rtk proxy that renders a bare newline for an empty range, so a piped `git log … | wc -l` count
  read zero commits as one -- and zero was the load-bearing value, the difference between "nothing
  merged since the tag" and one thing having merged. A merge commit, separately, is filtered out of
  plain `git log` entirely and never appears in a scan built that way (#310, folded in as the same
  class). `scripts/release_delta.py`'s own derivation already used `git rev-list --count` and `git
  rev-parse`; the fix here is writing that rule into the shared prose so it holds everywhere this
  loop counts a range, and a guard test sweeps the governing prose and scripts for the broken form,
  with a positive control proving the sweep can actually catch it (#236).

- `doctor` now probes `gh` itself, not just the Python interpreter running it
  (#367 answers only the second). `check_gh_binary` reads the resolved binary's
  architecture with `file` and compares it against the host, and reports `gh`'s
  own version beside the `gh-pr-edit` workaround's documented bound
  (cli/cli#13069) -- both go unmeasured on non-Darwin platforms and when `file`
  is absent, and both say so rather than rendering as a clean match (#386).

- The merge gates now cover a PR that went red because its base moved: `gh run rerun <id> --failed`
  replays the check suite against the merge ref it already resolved and does not re-resolve it
  against a `main` that has since moved, so a fix landed after the run started stays invisible and
  the second red reads as a fix that did not work. The tell is the run id -- an unchanged run id
  after a rerun means the old resolution ran again, not a new one -- and the route that actually
  re-resolves the ref is `gh api -X PUT repos/OWNER/REPO/pulls/N/update-branch`, which needs no
  local worktree and no force-push (#389).

- Pre-flight now checks the code, not only the issue. A dispatched lane can be work already
  shipped -- the issue and every comment can be read correctly and still describe a fix that
  landed after the last comment was written, which cost one full agent run on part 3 of #81.
  `scripts/preflight_check.py` runs a maintainer-chosen pattern against the code path an
  issue names before a brief is written, in three states never two -- `matched`,
  `not-matched`, `could-not-search` -- and `could-not-search` must never render as
  `not-matched`, the same way `could-not-tell` must never render as `still-open` at the
  dispatch decision. Checked once per part for a multi-part issue, and once per candidate
  before it joins a bundle -- a whole-issue or whole-bundle verdict hides exactly the case
  that fired here (#457).

- A pull request closed without merging now releases its linked issue's assignment the same way
  a lane that never committed already does, so a scope change or a superseded approach no longer
  leaves the issue locked to the loop's own account with no lane behind it. The read failing must
  never render as released -- the same rule the claim step already applies in the other direction
  (#465).

- `scripts/doctor.py`'s `_rglob_md` now matches `.md` case-insensitively (`.MD`,
  `.Md`, ...), restoring what the two `Path.rglob("*.md")` walks it replaced already did
  on Windows. A jit rules directory holding only uppercase-extension files no longer
  reports as holding none (#469).

- `lane_count`'s absence receipt claimed a confirmed zero for a lane registry that existed but
  sat under a parent this process could not traverse: `os.path.isdir` swallows `(OSError,
  ValueError)` unconditionally, so it answered `False` and the printed `detail` said "either
  nothing has ever recorded itself here, or nothing is live" for a registry holding a live record.
  `lane_count` now asks `os.stat` directly and reports `could-not-run` -- a registry may exist here
  and was not examined -- rather than `unknown`, the same distinction `worktree_occupancy` already
  draws for the identical swallow (#472). The review round on this fix found the first version had
  not carried over `worktree_occupancy`'s `except ValueError` arm, so a `worktree_root` with an
  embedded null byte crashed instead of reporting `could-not-run`; that guard is now in place too.

- Two defects caught by this branch's own self-review, both fixed before landing:
  `oss_config.release_authority()` and its validator raised an uncaught `TypeError` on
  an unhashable `release.authority` value (`{}`, `[]`) instead of reporting it, which
  took `/oss:doctor`'s "exit 0 always" contract down with it; and `matched-elsewhere`
  (#519, above) could fire when this running install's own manifest version could not
  be read, rendering an unknown own-version as a CONFIRMED different install (#478).

- `release_publish.py --execute` no longer reports `could-not-create` at the API
  boundary for a release notes body over GitHub's 125,000-character limit, after the
  tag is already pushed to the remote. The dry run now measures the notes and refuses
  early, with the measured length, the limit, and the overage in the reason -- on every
  `--execute` as well, so an over-limit body never reaches `gh` at all (#483).

- `plugin_update.opt_out` collapsed three materially different situations into one
  `(bool, where)` answer: a declared opt-out, no opt-out found, and a config that exists but
  could not be read or parsed -- the last one silently fell in with "no opt-out found", so a
  user who wrote `"auto_update": false` into a config that later failed to parse had their
  installation modified anyway, with `/oss:doctor` unable to say so. `opt_out` now returns one
  of three strings -- `"off"`, `"on"`, `"unknown"` -- never a bool, and `update()` treats
  `"unknown"` the way it already treats a failed marketplace refresh or an unreadable install
  record: it stops short and reports `could-not-check`, because modifying an install nobody
  can show consented to it is the greater harm. `doctor.check_auto_update` renders the third
  state as its own WARN row rather than folding it into "off" or "current". Fixed together
  with the second defect in the same function: `opt_out` read only `Path(root)`, with no
  upward walk, so called from a subdirectory it found nothing and answered "on" about a repo
  that had opted out at its root -- it now walks upward through ancestor directories, checking
  both `.oss.json` and `.oss.local.json` at each level, before it decides there is nothing to
  read (#492).

- The status line's foreign-text fold was applied at three entry points while `render()`
  interpolated four more values that passed through nothing -- `repo_name` and `model` could
  reach the rendered line carrying a newline or an ANSI escape, forging terminal output.
  `branch` and `board` were measured unreachable (git refuses control characters in a ref name;
  the board is coerced to `int` before it is ever formatted) and are not folded for that reason.
  Fixed as a property over `render`'s own inputs -- every string-valued fact is folded, not a
  fourth enumerated case, so a field added later without its own fold is caught the same way
  rather than going stale like the first three (#493).

- `/oss:scaffold --show` never named `.claude/settings.json`, even though `--apply` writes a
  `statusLine` key into it -- found by the `v0.12.0` release audit (#494). `show()` now previews
  the pending `create`/`extend` write, both with no path given and with `.claude/settings.json`
  named directly, rendering the exact body `apply_settings` would write; a repo that already sets
  `statusLine`, or whose settings file could not be read, gets no preview line, because nothing
  would be written there. `settings.json` is still not a path-level entry in `plan()` or `OWNED` --
  it is a key inside a file whose other keys are not ours, and the fix does not change that. The
  `--apply` receipt also silently dropped the `extended` bucket `apply()` already returns; it is
  now printed alongside `created` and `ours` (replaced).

- `doctor.check_auto_update`'s "no receipt" arm read as the ordinary pre-first-run gap on every
  machine, including one that structurally can never produce one: `hooks/hooks.json` runs the
  updater via `sh "$CLAUDE_PLUGIN_ROOT"/hooks/session-start-update.sh`, so on a machine with no
  POSIX-capable shell resolvable (a Windows install without Git for Windows or WSL) that OK is
  the permanent state, not the transient one before the next session. The row now measures
  `shutil.which("sh")` on the machine `doctor` is actually running on and WARNs instead when it
  is absent. The same band's second instance -- `_statusline_windows_gap` keyed on `os.name ==
  "nt"` alone, so a Windows user whose `statusLine` runs under Git Bash (where the written
  `$VAR` syntax works) was warned about a status line that runs correctly -- is fixed the same
  way: `sh_available` is measured, never inferred from the platform name alone, so the WARN no
  longer fires on a Windows machine that does have a POSIX-capable shell on PATH (#495, found by
  the v0.12.0 release audit, round 2; graded reasoned rather than observed, since neither this
  fix nor its own test suite runs on a real Windows machine).

- This repository's own `.claude/settings.json` pointed `statusLine` at `.oss/statusline.py`,
  a path this same repository's `.gitignore` excludes (deliberately, to avoid a second tracked
  copy of `scripts/statusline.py` that would drift). `git ls-files .oss/` returns nothing, so a
  fresh clone of this repository got a status line whose target was never checked in, and the
  failure was silent. Re-pointed at `scripts/statusline.py`, which this repository does track.
  This is a fact about this repository's own checked-in settings, not about what `/oss:scaffold`
  writes into a managed repo it scaffolds -- there `.oss/` is tracked, so the same command is
  correct as it stands (#496).

- The `last` field renders the machine's local zone, not UTC (#511). Measured at `last 10:11` against
  a wall clock reading 12:15. The field renders a clock time rather than an age precisely so the
  reader can subtract it from their own clock and recover how stale the line is, and a UTC stamp made
  that subtraction silently wrong in every zone but one. The reason it shipped as UTC -- that the
  transcript's ISO stamps carry no zone -- was about parsing: `parse_timestamp` hands back epoch
  seconds, and the stamp is produced and read on one machine in the same second.
- An instant the platform cannot convert renders `?` rather than falling back to UTC under a label
  that means local, which would be the same defect one layer quieter.

- `/oss:doctor`'s `oss-workspace launcher` check gains a third `matched` state,
  `matched-elsewhere`: a resolved target whose bytes are identical to this running
  install's own `bin/oss-workspace` but that recognisably belongs to a DIFFERENT
  version-scoped plugin-cache directory now reports `WARN "PINNED ELSEWHERE"` instead of
  `OK`. Byte-identical content is a fact about today; a stale symlink kept that way
  behaves exactly like a current one until the next release that touches this file,
  which is what cost an earlier release its own security fix (#324). An ordinary
  hand-copied path that carries no plugin-cache shape, or one whose parsed version
  agrees with this running install's own, is unaffected and still reports plain
  `matched` (#519).

- The fleet floor bounded lanes and said nothing about issues per lane, so a fleet of single-issue
  lanes computed `filled` while related work sat unstarted on files those lanes already claimed.
  `filled` now reads on both axes: one developer per available file-disjoint lane, and each lane's
  brief carrying every further open issue whose files land inside its already-claimed set. Checking
  the second axis reuses `lane_setup.py`'s own intersection mechanism in reverse rather than adding
  a new one, and stays a maintainer judgement the script supports -- an issue's files are not
  derivable from its body (#267). An `under-filled` receipt on this axis now names the shared,
  already-claimed file that blocked a further issue from joining a lane and the issues queued
  behind it, not only a smaller count (#520).

- Two instruments read a plugin's newest recorded version *anywhere* on the machine,
  rather than the version resolved for the project being reported on: `installed_plugins.json`
  is one file shared by every project, and an old project's entry is never rewritten when a
  newer copy is installed elsewhere. `plugin_update.installed_version` and
  `statusline.installed_plugins` both took the newest version recorded across every entry, so a
  project pinned behind a sibling project's newer pin silently read as current -- and the
  updater's own `before`/`after` comparison, computed on the same collapsed value, reported a
  version that this session could not resolve. Both now resolve the entry that actually applies
  to the project being reported on (`scope: "user"`, or a `projectPath` matching the project),
  and report no version at all -- never the newest one lying around -- when nothing matches.
  Fixed alongside two further defects the receipt for the measured instance carried: `update()`
  reported a bare `current`/`updated` verdict even when one of several install scopes had
  failed, with the failure named only in free-text `detail`; and `doctor.check_auto_update`'s
  `current`/`updated` rows never read `detail` at all, so a run that half-failed printed a plain
  `OK`. The receipt now carries a structured `partial_failure` flag, and both rows render it as
  a WARN naming the failed scope rather than the same OK a clean run gets (#521).

- The `supertool-required.md` rule this plugin ships into every managed repo blocked every
  native `Read`/`Edit`/`Write`/`Glob`/`Grep` call unconditionally, with no way to tell a reader
  without `supertool` installed anything but "use a binary you do not have" -- reported from a
  downstream contributor's real installation (#524). The rule now carries `requires: supertool`
  in its frontmatter, so the day `claude-jit-context` ships the presence-probing degrade it has
  agreed to build (its own #203), this rule needs no further edit to benefit from it. That degrade
  is **not released yet** -- no shipped `claude-jit-context` version reads a `requires:` field, so
  the rule still blocks unconditionally today, exactly as before, and its own text now says so in
  as many words rather than leaving that silently implied. `match: ~.*` and `mode: block` are kept
  as they were: narrowing them was weighed and declined, because the absent-binary failure mode is
  what `requires:` exists to answer, without weakening the guard for a reader who already has the
  dependency.

- `/oss:doctor`'s watch channel check cleared a repo whose derived or declared name the
  installed supertool actually discards, because it compared a declaration against a
  derivation and never asked whether the name they agreed on was one supertool would
  accept as a path component. Measured against this organisation's own slugs:
  `Digital-Process-Tools/claude-jit-context` derives a 40-character name, supertool's
  cap is 32, and the repo landed on the shared default socket under a green `OK` line
  (#533). `bin/oss-workspace` already asked the installed consumer at run time rather
  than transcribing its `NAME_RE` (#231); `check_watch_channel` now asks the same way,
  through the same registry and `presets/watch/naming.py` lookup, for every state that
  used to clear on the comparison alone — `agree`, `declared-only`, `derived-export`,
  `derived`. A name the consumer discards now WARNs with the shared-socket wording
  instead of clearing, and a name that cannot be classified (no registry, no supertool
  install, no `naming.py`, an unreadable module) is its own state and never renders as
  OK — the absence this plugin is named after, reached here by the one check that used
  to skip it. `oss_config.watch_name_problem`'s docstring no longer claims to be the
  single statement of what a watch channel name may be; it is the single statement of
  what one may be as a path component, and now names both places — `bin/oss-workspace`
  and `doctor.check_watch_channel` — that ask the installed consumer whether a name
  that clears here is actually usable.

- `plugin_update.opt_out`'s upward walk (added for #492) stopped at the **first** ancestor
  directory holding either config file and answered "on" if that directory did not itself
  declare `auto_update` -- in every managed repository the nearest such directory is the repo's
  own `.oss.json`, which declares `repo` and nothing about `auto_update`, so a machine-wide
  opt-out one or more directories above it was never reached. `hooks/session-start-update.sh`
  passes the project root, which holds `.oss.json` by definition, so this defeated the opt-out
  in the entire population the upward walk exists for. `opt_out` now continues past a config
  directory that declares nothing about the key, and stops only at an explicit declaration
  (`true` or `false`), an unreadable config, or the filesystem root (#534, found by the v0.13.0
  release audit, round 1).

- The status line's own guards were each covered by exactly the values they already
  covered: the fold property test skipped every non-string fact (`board`, `tick`,
  `release`, `plugins`), and the console-encoding probe hardcoded four of the seven
  symbols the line can render. A hostile value nested inside `board` or `tick` could
  reach the line unfolded or crash `_tick_field`'s `abs()`, and a fifth or sixth
  rendered symbol could reach a console that could not encode it. Neither was reachable
  by foreign text today -- `board_from_cache` and `_next_tick_from_lines` already coerce
  before `render()` sees them -- so this closes a guard-coverage gap, not a live leak.
  The property test now walks every leaf `_facts()` carries, nested or not, and the
  console probe is built from the guarded symbol set instead of typed out beside it, so
  a new sub-field or symbol is covered the day it is added rather than the release after
  (#535).

- `/oss:scaffold --show` could exit with a raw `OSError`/`ValueError` traceback instead of a
  preview, when `.claude/settings.json` changed or errored between two reads -- `_settings_preview`
  re-read the file itself in its `extend` arm, unguarded, after `settings_plan` had already read and
  classified it (#536, found by the `v0.13.0` release audit). Fixed by reusing the document
  `settings_plan` already parsed rather than reading the file a second time, per `CLAUDE.md`'s trap
  against asking the filesystem a second question to explain why the first one failed: the second
  read is gone, not guarded. `apply_settings`'s `extend` arm did the identical unguarded second
  read, three lines below the same `settings_plan` call -- caught in review and fixed the same way,
  since the document is now carried on the entry for free.

- `scripts/batch_hint.py` hardcoded a dated, hand-copied snapshot of `supertool 'ops:roster'`'s
  own read/write classification -- exactly the second copy this repo's own `CLAUDE.md` forbids,
  and one that drifts in a single direction: an op whose class moves from read-only to write
  upstream stayed misclassified read-only here forever, since nothing re-derived or checked the
  copy. Measured at well under a tenth of a second, so the module now calls `supertool
  'ops:roster'` once per process, caches the parsed answer to disk (a few-hour TTL; the roster
  only moves with a `supertool` release) for the many separate hook invocations one session
  makes, and deletes the static lists. A roster that cannot be derived at all -- no `supertool`
  on PATH, a non-zero exit, unparseable output -- degrades every op to "no confident answer"
  rather than guessing in either direction; the `@-` payload-marker fallback still catches an
  unrecognised mutating op exactly as before (#537, found by the v0.13.0 release audit, round 1).

## [0.12.0] - 2026-08-22

### Added

- A status line for a managed repo (#479). `/oss:scaffold` writes `.oss/statusline.py` as an owned
  file and adds a `statusLine` key to `.claude/settings.json` **only when that key is absent** -- an
  existing status line is a decision and is never overwritten. It renders the model and context
  percentage, the repo, branch and declared version, open pull requests and open issues, the next
  armed tick read off the session transcript, and the installed plugin versions against their latest
  releases. Every field has a third state that prints `?`: a count nobody took never renders as `0`,
  a comparison nobody could make never renders as current, and a transcript tail that did not reach
  the top of the file reports `?` rather than "no tick armed".
- The status line asks for a plugin's latest version the way `doctor.published_versions` does -- the
  manifest on the source repository's default branch, which is what `claude plugin update` would
  install -- rather than the latest GitHub Release. The two are not the same question: a plugin whose
  tag is ahead of its last published release read as `ahead` while being exactly current.
- `/oss:doctor` gains a `statusline` row: wired to ours, wired to somebody else's (left alone), not
  wired with the block to paste, or unreadable settings -- which reports as unknown, not as absent.
- The changelog-gate detection no longer governs every owned file (#479). It answers one question --
  does a changelog gate already run here under another name -- so it now gates `scaffold.CHANGELOG_OWNED`
  alone. `.oss/statusline.py` reaches a repo that runs its own changelog gate, and `doctor.owned_drift`
  reads the same split rather than reporting a decline scaffold never made.

- The plugin now keeps itself current (#480). A `SessionStart` hook forks
  `scripts/plugin_update.py`, which refreshes the marketplace and then updates this plugin at every
  scope the install record names -- `--scope user` was the obvious default and it fails outright
  against a project-scoped install, so the scope is derived rather than assumed. The hook forks and
  returns: nothing waits on a network call at session start.
- Four states in the receipt it leaves, and none of them collapse: `off` (switched off by
  `OSS_NO_AUTO_UPDATE` in the environment or `"auto_update": false` in `.oss.json` /
  `.oss.local.json`), `updated` (naming both versions and that a restart is needed before the new
  code runs), `current`, and `could-not-check`. A run that could not refresh the marketplace never
  reports `current`: `latest` would mean whatever it meant last time.
- `/oss:doctor` gains an `auto-update` row that reads that receipt back, including the state where
  there is no receipt at all -- which says nothing was recorded, not that the plugin is up to date.

### Fixed

- The auto-updater no longer reports `current` about three situations where nothing was
  established (#484). An unreadable install record used to leave `before` and `after` both
  `None` and still fall through to `current`; it now returns `could-not-check` -- and, caught
  by this fix's own review round, so does the asymmetric case where only ONE of the two
  reads fails, not just both. A scope that failed to update used to vanish from the receipt
  the moment one other scope succeeded; the failure now reaches `detail` without changing the
  state, so `updated`/`current` still stand but say which scope was left behind. And
  `plugin_update.read_receipt` no longer collapses a corrupt receipt into the same `None` as
  no receipt at all -- a `ReceiptUnreadable` result tells `doctor.check_auto_update` the two
  apart, and it reports the broken-receipt case at `WARN` rather than the ordinary
  pre-first-run `OK`.

- `/oss:scaffold`'s `settings_plan` no longer opens with `Path.exists()`, the one call
  CLAUDE.md prohibits by name (#485). That call swallows a short list of errnos and
  re-raises everything else, and which is which moves between interpreter versions -- so
  the run could die before the `decline` its own docstring promises, or `exists()` could
  swallow to `False` and let `apply_settings` overwrite a present, unreadable
  `.claude/settings.json`. The pre-check is gone; `read_text` is attempted directly and the
  exception actually raised decides the arm, `FileNotFoundError` for `create` and every
  other `OSError` for `decline`.

- The status line no longer interpolates untrusted manifest text unfolded (#486). `version`
  (this repo's own tracked manifest), `installed` and `latest` (a plugin's manifest, the
  latter fetched over the network from another repository), and a dependency's declared
  `name` now pass through a one-line ASCII fold at the point each enters `render`, before
  this script's own ANSI colour is added -- so a newline can no longer put attacker-chosen
  text at column 0 of the terminal chrome, and an ESC can no longer rewrite what the
  terminal has already printed.

- `/oss:doctor`'s `statusline` check no longer grades a status line `OK ... wired` purely
  because its command contains the substring `statusline.py` (#487). The command this
  plugin writes uses POSIX `$VAR` shell expansion, which Windows's default command
  interpreter does not expand -- reasoned from the syntax rather than observed, since
  nobody has run a status line on Windows to confirm it -- so `check_statusline` now warns,
  naming the syntax, when that gap is detected there, for a command it wrote and for
  anyone else's. Windows CI caught this firing for real on a freshly-scaffolded repo's
  own default (there is no other statusLine to fall back to), so the WARN now also offers
  a `%CLAUDE_PROJECT_DIR%` / bare-`python` command to try -- untested and said so in the
  message, since which shell actually runs a `statusLine` command on Windows was not
  established. `commands/scaffold.md` also said "the last three" owned files where the
  table above it already lists four.

## [0.11.0] - 2026-08-22

### Added

- `scripts/lane_setup.py` now records this lane's own presence in a registry beside the
  numbered worktree directories (`worktree_root/.oss-lanes/`) and reports how many lanes are
  currently recorded live -- the payload's `lanes` field and a new receipt row. This is the
  count `#367`'s worker-sizing line in `doctor.py` could not report: no process can enumerate
  its sibling lanes, so the count has to be written down by the thing that starts a lane, not
  discovered afterwards (#385). A record older than four hours is pruned by the next reader and
  excluded from the count, and a registry that was never written to reports `unknown`, never
  `0` -- those are different facts and `0` is the wrong one. `doctor.py` is unchanged: it is
  held by a concurrent lane, and the doctor line this would need is filed for that lane to add.

- `doctor` reports whether the merge call can skip supertool's own publish-confirm gate before the merge step is where a maintainer used to meet it, in three states: `confirmable`, `needs-force` (the shipped default, reported as neutral information rather than a warning), and `could not tell` when `.supertool.json` is unreadable or malformed. The line names every op the same opt-out reaches today, not only `gh-pr-merge`, and is scoped to supertool's own gate: the harness's own permission layer sits above it and can still refuse the call regardless (#421).

- `scripts/lane_setup.py` now enumerates the cross-cutting guard tests keyed to *what a diff
  does* rather than to a module it renames -- `test_content_invariants.py`,
  `test_unwired_scripts_253.py`, `test_gate_state_consumers_328.py`, `test_claude_md_currency.py`
  and `test_python_floor_410.py` -- and reports which of them a lane's declared files trip
  (`--lane`, `guards_for_files`, and the receipt's new `guard` line). A lane's local test command
  narrowing to a handful of named files could look green while one of these failed on CI instead,
  because its own filename carries no visible relationship to the diff that trips it (#432,
  measured on PR #431). The `test_gate_state_consumers_328.py` mapping covers the two whole
  directories that guard actually scans (`commands/` and `scripts/`), not only the files that
  already call the gate producer, so a brand-new file is covered too.

- Scaffold `CONTRIBUTING.md` for the repos this plugin manages (#460). A default,
  not owned -- created once when absent and never overwritten -- generated entirely
  from `.oss.json`, addressed to a contributor rather than to this repository's own
  maintainer, and linking to `CLAUDE.md` for the reasoning. Compatibility: compatible
  - a new file created only when absent; nothing existing changes shape.

- The dispatch step of the manager loop now assigns each issue to the account running the loop
  before spawning its developer, and selection now excludes any issue already carrying a
  non-empty assignee list -- previously a lane could run for hours while its issue read
  `Assignees: none`, so a second reader of the same tracker could pick up the same work (#461).
  A lane that ends without a commit is released, so the claim never outlives the lane that made
  it.

### Changed

- `agents/developer.md` now distinguishes narration paid on every later turn from the
  report paid once (#314), so the existing "no narration turn" guidance does not read
  as licence to shrink the report too. The report's own guarantees -- the argued-down
  finding's `reason`, red and green quoted separately, every `report-for-filing`
  item's justification -- are called out by name as the half that stays full.

- `.oss.json` accepts a leading-underscore key as maintainer prose, skipped by
  `oss_config.validate()` rather than refused as an unknown key. JSON has no comment
  syntax, so a note explaining *why* a value is what it is (e.g. `_milestones_note`
  beside `milestones`) had nowhere else to live, and every place that note was written
  got the message `unknown key (typo, or a schema change nobody wrote down)` — which
  disabled `/oss:scaffold` outright, since it raises on any validation problem. A
  key beginning with `_` still is not exempt from the credential check: `_api_key`
  is refused exactly as `api_key` is. The escape also covers `release` and
  `release.triggers`, which had their own separate unknown-key checks, and a
  `_`-prefixed key placed only in the git-excluded `.oss.local.json` is reported as
  misplaced rather than silently merged in unseen by every other maintainer — the
  same "hidden in an untracked file" failure the project/local split already exists
  to prevent for every other key (#355).

- The maintainer skill now names which `gh-pr-merge` invocation spelling clears the harness
  permission classifier -- the bare `supertool 'gh-pr-merge:N:squash|force'`, never
  `python3 supertool.py 'gh-pr-merge:...'` for the merge call itself -- and reads a
  `Blocked by classifier` denial as a claim about the command string rather than about the
  merge action. Three sessions chased the wrong cause before this was written down (#445).
- *Merge gates* and `commands/tick.md`'s merge step now document `gh-pr-merge`'s own
  `|cleanup` token as the default, in place of raw `gh api -X DELETE` and
  `git worktree remove`: the token runs its three deletions only after the op's own
  `MERGED` read-back, and the worktree half is skipped with a stated reason whenever the
  board holds more than one idle tree, which a fleet-running loop is expected to reap
  itself. The raw commands stay documented only as the fallback for what the op
  deliberately refuses to touch: a cross-repository head, an unestablished branch, or the
  default branch (#446).
- *Run a fleet, not a queue* now states fleet size as a floor as well as a ceiling: each
  tick dispatches one developer per file-disjoint lane the board offers, and running fewer
  must be stated with a count and a reason. Three states -- `filled`, `under-filled`, and
  `could-not-tell`, which must never render as `filled` (#448).

### Fixed

- Fixed three `rglob`/`glob` walks in `doctor.py` that silently swallowed `PermissionError` for a directory they could not enter (#383), and three narrower unguarded `is_file()`/`is_dir()` sites of the same class found while censusing the rest of `scripts/` for it — one more in `doctor.py`, one each in `rename_changelog_fragment.py` and `release_delta.py`.

- `.supertool.json` now declares `ops.git-commit.coauthor` explicitly, as
  `Claude Opus 5 (1M context) <noreply@anthropic.com>` -- the identity this project's own commit
  history already carries far more often than any other. Every agent commit through supertool's
  `git-commit` op used to fall back to supertool's own unset default, `Max <noreply>` -- documented
  and intentional upstream, but never a value this project chose, and not a valid email address.
  Fixed forward only: the commits already merged under the old default are squash-merge subjects in
  `main`'s history, and rewriting shared history to correct a trailer on them is not a trade this
  project makes (#441).

- `--pending-wait` no longer renders a `could-not-evaluate` wait the same as nothing
  being pending. It used to fall into the same branch as `cleared` and no wait ever
  having been recorded, printing `no pending wait` and dropping the recorded `why` on
  the floor -- so a tick that could not test whether it was still blocked proceeded as
  though it was not. `could-not-evaluate` now joins `holds` on the "something is
  pending" side of the answer, distinguishable from it by the record's own `state` and
  `why` (#443).

- `scripts/rename_changelog_fragment.py` no longer reports OK when `git add` fails to
  stage the rewritten fragment, and no longer lets an `OSError` from the rewrite escape
  as a traceback -- both used to render identically to success, reproducing the amend
  defect the tool exists to close one layer later (#444). Its overwrite guard also now
  confirms absence the same way `lane_setup.worktree_occupancy` does, rather than
  trusting the exception type alone, which mattered on a platform that folds an
  over-`MAX_PATH` destination onto the same exception a genuine absence raises. A
  self-review of this same fix found and closed three adjacent gaps: an unspawnable
  `git add` still raised past the function, an embedded-null path still escaped the
  overwrite guard as a traceback, and a rewrite failure's receipt overclaimed which
  body the file was left holding on disk.

- `README.md` had been amended per-fix for many releases, so a reader met the launcher install
  command twice, a stale count claiming "all seven `oss:` skills resolve and none of the four
  `oss:` agents does" (the repo ships one skill, seven commands and four agents), and a
  `/oss:doctor` Commands-table cell of roughly 700 words narrating issue numbers and benchmark
  ratios in a table whose other rows are a sentence or two. The duplicate install block is gone,
  the count is stated with no number so it cannot go stale silently again, and the doctor cell
  points at `commands/doctor.md` for its mechanism instead of carrying it. `tests/test_readme_scope_451.py`
  guards all three, each with a positive control (#451).

- `scripts/rename_changelog_fragment.py`'s source-side overwrite guard,
  `_source_present`, no longer reports a source fragment absent on the
  exception type alone: it now confirms absence the same way
  `_destination_occupied` (#444) does, so a source folded onto
  `FileNotFoundError` by an over-`MAX_PATH` name (the Windows fold CLAUDE.md
  records) is reported as "could not be examined" rather than as a false
  "no such file" (#468). It also gained the `except ValueError` arm its
  sibling already carries, for an embedded-null path -- unreachable through
  this script's own CLI, since POSIX argv cannot carry a NUL, but a hazard
  for an importing caller.

- The reserved-underscore escape (#355) that lets a maintainer leave prose beside a
  key (`_milestones_note`) skipped the credential check in the two nested
  `release` blocks instead of running after it. `release._api_key` and
  `release.triggers._api_key` validated clean, so a real secret spelled with a
  leading underscore passed silently into a tracked, committed `.oss.json`
  instead of being refused the way `_api_key` at the top level, and every
  other credential-looking key, already was. The credential-first ordering
  now lives in one helper all three sites (top level, `release`,
  `release.triggers`) call, so the ordering cannot drift between them again
  (#471).

## [0.10.0] - 2026-08-22

### Added

- `doctor` now reports whether `<changelog_dir>/README.md` documents the
  `- Compatibility: breaking|compatible - <reason>` bullet a `removed` fragment must
  carry. `scripts/release_version.py` already refused a `removed` fragment declaring no
  compatibility verdict and quoted the bullet in full, but nothing said so before the
  release stopped -- and the fragments README is a *default* under this repository's
  ownership contract, created once when absent and never replaced, so a repository
  scaffolded before the section existed (#259) cannot receive it by re-running
  `/oss:scaffold`. The check therefore reports rather than fixes: present-and-silent
  warns, and the remedy says in as many words that `/oss:scaffold` will not fix it --
  paste the section by hand from `scripts/scaffold.py --show <changelog_dir>/README.md`.
  Absent is the ordinary state of a repository with no fragment practice and reports OK
  rather than a finding, so it does not warn on nearly every scaffolded repo. The
  directory checked is resolved the same way `release_version._fragment_dir` resolves
  it, following a nulled `changelog_dir` to the directory scaffold's own gate workflow
  polices on disk (#325) rather than defaulting to `changelog.d/` and silently checking
  the wrong file (#260).

- `scripts/lane_setup.py` can now render a fleet lane in one canonical form instead of leaving the
  maintainer to intersect a glob against a literal path by eye. Two live briefs collided this way:
  `fix/247-244`'s lane was `skills/manager/SKILL.md` and `fix/262-248`'s was `commands/*.md`, and the
  second agent's correct fix touched `commands/tick.md` -- a file assigned to a still-running agent,
  because nothing checked the intersection. `--lane PATTERN` (repeatable) and `--against PATTERN`
  (repeatable) resolve both sides to sorted, deduplicated repo-relative paths -- expanding every glob
  against what is actually on disk, keeping every literal path as asserted -- and report the overlap
  in the receipt and the `--json` payload. `skills/manager/SKILL.md` now asks for this before a second
  brief in a fleet is written, rather than after (#267).

- A recorded wait is now a claim a later tick can test, not prose it must trust (#337). Measured on
  2026-08-16: the loop recorded itself as "blocked on audit completion" at 01:15Z, ninety minutes
  after the audit had already returned and its four output issues had been filed on the tracker --
  three hours ten minutes passed with a green default branch, an empty pull request board and four
  unstarted issues, and nothing re-read the wait. `scripts/oss_state.py` gains `wait`/`check_wait`:
  a blocked tick records a dispatch, an observable and when it was recorded (`--wait-dispatch`,
  `--wait-observable`), and the next tick tests it (`--pending-wait`, `--check-wait`) into one of
  three states -- `holds`, `cleared` with what cleared it, or `could-not-evaluate` with why, never
  rendered alike. Stored on the state entry as `detail.wait`. `commands/tick.md` and the manager
  skill wire the check into step 1 of every tick, ahead of anything else.

- The supported Python floor is now declared, once, as `[project] requires-python = ">=3.9"` in
  `pyproject.toml`. Nothing stated it before: the only floor anywhere was the CI matrix, and a matrix
  says what is tested rather than what is supported. The two were read as one throughout - by
  `CLAUDE.md`'s grading paragraphs, and by a README badge that has claimed `python-3.9+` for this
  project's whole life with nothing behind it. The absence was not inert: #398's lane declined to put
  a `sys.version_info` gate in `scripts/doctor.sh`'s sentinel probe because doing so would have
  turned a working 3.8 install into `VERDICT: could not run` on the strength of a fact nobody had
  stated (#410).
- `3.9` is a support decision and deliberately wider than what the code needs. Measured over all 132
  tracked `.py` files before it was declared: every one parses at `ast.parse(feature_version=(3, 7))`,
  none carries a builtin-generic or `X | Y` annotation, and none imports or calls a standard-library
  name added after 3.9 - no `tomllib`, `functools.cache`, `Path.walk`, `contextlib.chdir` or
  `datetime.UTC`. `python3.11 -m compileall scripts tests bin` exits 0, which additionally rules out
  a PEP 701 f-string only 3.12 can tokenise. The floor is 3.9 because 3.9 is the oldest version
  anything here has ever been demonstrated on (#410).
- Four sites are derived from that one key, and `tests/test_python_floor_410.py` is what makes them
  agree, since a workflow matrix, a shields.io badge and a shell `for` list cannot read a manifest at
  parse time: the CI matrix's lowest entry, the README badge, the `Python X.Y compatible` line eight
  modules under `scripts/` carry, and the oldest explicit `python3.N` in `doctor.sh`'s interpreter
  walk. The comparison is a pure function driven by fixtures in both directions, and every real site
  asserts it *found* something before comparing it - an empty survey and a clean survey are the same
  `[]` (#410).
- `pyproject.toml` deliberately gains no `version` key and no `[build-system]`.
  `scripts/oss_config.py` probes `pyproject.toml` for exactly `[project] version`, so one would
  become a fifth version site that `.oss.json` does not list and `/oss:release` would leave stale
  (#410).
- Compatibility: compatible - the key is a declaration, not a gate. `scripts/doctor.sh` still runs on
  whatever interpreter the machine offers, and no code path refuses one below the floor (#410).

- The maintainer's manager skill now names `scripts/rename_changelog_fragment.py`, which renames a
  changelog fragment to a new issue/PR number and rewrites its own self-reference in the same
  operation -- so a fragment rename on pull-request open (`git mv changelog.d/N.section.md
  changelog.d/M.section.md`) can no longer leave the body naming the old number while the filename
  carries the new one, which the `fragment` leg refuses (#426, #335, measured on PR #338).

- A test written to assert on a specific platform can quietly start skipping there
  instead, and CI stays green -- a skip does not fail a build, and `-rs` prints the
  reason but nothing is obliged to read it. `@pytest.mark.must_assert_on("win32")`
  is a new promise a test can carry: a new pytest plugin,
  `tests/must_assert_plugin.py` (loaded for the whole suite via the new
  `tests/conftest.py`), fails the whole session if a marked test reports SKIPPED
  while `sys.platform` matches the platform the marker names. Applied to
  `tests/test_skip_symlink_265.py::test_the_real_junction_mechanism_is_measured_not_assumed`
  -- the one test #265 spent four rounds and a real Windows CI failure establishing
  observed claims on -- so a future runner image, Python version or Windows policy
  that takes the junction mechanism away turns that test's silent skip into a red
  `windows-latest` leg instead. Deliberately on the test rather than in the
  workflow, so the "must assert here" fact has nowhere to go stale against; and
  deliberately silent everywhere the marker's platform does not match the host, so
  a POSIX leg's correct, permanent skip of the same test stays green. A survey of
  every `pytest.skip` call in `tests/` (#430) found this to be the only test making
  a platform-conditional "must generally assert" claim today, so the marker ships
  as a mechanism available to future tests rather than being applied more broadly.
  A malformed marker (no positional platform argument -- e.g. a keyword
  `platform=...` spelling, or a bare `@pytest.mark.must_assert_on()`) fails
  collection loudly rather than being silently treated as absent, closing the
  same failure mode one layer up in the marker's own configuration surface.
  (#430)

### Fixed

- The symlink fixture shared by `tests/test_agent_report_schema.py` and
  `tests/test_oss_config.py` no longer skips a directory-target containment case
  on the strength of `symlink_to` alone. An unelevated `windows-latest` runner
  without Developer Mode raises `OSError [WinError 1314]` there, which is why
  both the escape assertion and its positive control skipped together on all
  four Windows legs (#234's guard therefore asserted on at most 9 of 13, with a
  skipped leg reading the same green as one that ran). The fixture, now shared
  as `tests/skip_symlink.py`, tries a Windows directory junction
  (`cmd /c mklink /J`) as a fallback for directory targets before giving up --
  junctions need no privilege and `Path.resolve()` follows one exactly the way
  it follows a symlink. There is no equivalent for a file target, so that case
  is unchanged and still skips on its own. When both mechanisms fail the skip
  names both reasons rather than one, so which of the two went untested is
  still legible from `-rs` output. `windows-latest`/3.10 in CI has since
  exercised the directory-target case for real and the junction landed, so
  "junctions need no privilege" and "`Path.resolve()` follows one" are now
  *observed* on that leg rather than merely reasoned from documented
  Windows/CPython behaviour; the mechanism's three *failure* arms (a spawn
  that fails, a non-zero `mklink` exit, a junction that lands but does not
  resolve to the target) remain unexercised by any CI run so far and are
  still reasoned only. None of the three ever raises out of the fixture on a
  wrong guess: a failed attempt just folds into the skip message next to
  `symlink_to`'s own failure (#265).

- `agents/developer.md` now names the exact local command a lane can run to check its own
  changelog fragment before committing — `assemble_changelog.py --check`, located at
  `.oss/assemble_changelog.py` or `scripts/assemble_changelog.py`, whichever exists. Every
  developer brief already required a fragment, but the checker that judges one is a CI leg
  `test_command` (`pytest`) never reaches, so a lane that ran the full suite green three times had
  checked everything it was told to check and had not checked the fragment at all (#335).

- `compare_versions` guarded a digit with `str.isdigit()` and converted with `int()`,
  and the two predicates do not agree on a domain (#388). U+00B2 SUPERSCRIPT TWO
  passes `isdigit()` and `int()` refuses it, so the guard let an uncaught `ValueError`
  through where the docstring promises `unknown`; U+0662 ARABIC-INDIC DIGIT TWO passes
  both and `int()` converts it to `2`, so `0.4.٢` compared equal to `0.4.2` and a stale
  install could report `current`. The parser now checks every character against the
  ASCII digit set directly -- `str.isdecimal()` alone would not have closed this, since
  U+0662 is also decimal. Swept the rest of `scripts/` for the same guard: one other
  site (`release_delta.py`'s `_number`, wrapping `git rev-list --count`) guards output
  git itself always emits as plain ASCII digits, so it is not reachable and was left
  alone.

- An uncommitted delete is no longer reported as a file that could not be read, at the
  three remaining sites that enumerate the git index and then read the working tree
  (#396). `git ls-files` answers about the index; the read happens in the tree, and
  between an uncommitted `rm` and its commit -- the changelog fold produces twenty-one
  at once -- the two disagree about exactly those paths. Absence is now decided from
  the exception already in hand (`FileNotFoundError`, never a second question to the
  filesystem), reported by name in its own bucket, and does not decide the verdict.
  This completes the class #395 fixed for the two sites that were firing.
  - `/oss:setup` printed *could not read, so not claimed as version sites* about a
    candidate that was simply not on disk. It now says so in its own words. The same
    note also covered a `package.json` this process had read in full and found not to
    be JSON, so `version_evidence` gains `malformed` as well: `unreadable` now means
    only what the word means -- the file is there and its bytes did not come back.
  - `tests/test_unwired_scripts_253.py` filed a deleted path under `unsearchable`,
    whose documented argument is that decoding more files can only *add* references.
    That is sound for a file that will not decode and false for a deleted one, whose
    references are lost -- so absence could manufacture an offender rather than merely
    leave one unexplained, and a script whose only mention sat in a pending fragment
    flipped from wired to unwired inside the fold window. The prose is corrected too.
  - `tests/test_gate_state_consumers_328.py` put such a path in `unreadable`, which
    sinks the consumer census's completeness claim. It was green only because its scope
    is `commands/` and `scripts/`, which the fold does not touch -- an accident of
    scope, not a property of the guard.
- The fourth site of the same class, held back from the fix above because it needed a
  decision about a *consumer* rather than an application of the settled pattern (#396).
  `_workflow_jobs` fed its problems to `gather()`'s unconditional refusal, so an
  uncommitted delete of one tracked workflow aborted probe generation for the **whole
  repository** with `could not read` -- the exact sentence the rest of this entry
  retires. The enumeration now reports absence in a bucket of its own, and the consumer
  question is answered by splitting it:
  - **A workflow that is in the index and not in the working tree declares no jobs**, so
    `gather()` proceeds. That is a measurement rather than a gap, and the "a probe is
    returned only when every field in it was measured" contract is satisfied rather than
    relaxed. `--probe` names the file in a `NOTE` on stderr, because `files` is the index
    and goes on listing it -- without the note, a probe taken mid-delete is a shorter job
    list with nothing to explain it.
  - **A workflow that is on disk and will not read still refuses**, unchanged. How many
    jobs it declares is unknown, and an unknown counted as zero understates the required
    checks -- the direction that lets a red leg through.
  - Three states here rather than the five `version_evidence` grew above, argued rather
    than copied: this is a line scan, not a parser, so it has no `malformed` to report.
    It cannot tell a workflow that declares no jobs from one whose `jobs:` block the scan
    did not match, and a state the code cannot support is a claim rather than a fact.
  - `gather()` now returns `(probe, problems, notes)`. A note is a true statement that is
    not a failure, and there was previously nowhere to put one: folding it into `problems`
    aborts the probe and folding it into silence is this repository's own defect class.
- Found by dogfooding the above rather than filed: `_doc` in the same test module said
  *could not read* about a hardcoded consumer path that had been deleted. That one reads
  a named path rather than an enumeration, so it is right to fail -- a document named in
  `GATE_STATE_CONSUMERS` that is gone means the tuple is stale. The verdict is unchanged;
  only the sentence is, and it now says what is actually wrong.

- `scripts/doctor.sh` no longer prefers a newer interpreter over the one the machine itself calls
  `python3`. The candidate walk ran `python3.14` down to `python3.9` before bare `python3`, which
  encoded "newest is best" and consulted neither the CI matrix (3.9-3.12, so the first candidate
  tried was the one no leg covers) nor the fact that a `python3.N` on PATH is no evidence it is the
  good build - measured on macOS arm64, the only 3.14 was an x86_64 build under binary translation
  while the native one answers to bare `python3`, so `bash scripts/doctor.sh` and
  `python3 scripts/doctor.py` reported different interpreter-architecture lines on the same tree.
  The walk is now `python3`, then the band CI covers newest-first, then newer-than-band, then
  `python`, then `py -3`. Nothing is removed from it: every candidate is still proved by being run
  and compared against a sentinel, which is what rejects Windows' App Execution Alias, and an
  interpreter newer than the band is still selected when it is the only one present (#398).

- `doctor` no longer reports a machine without the `hw.nperflevels` sysctl as one whose CPU-topology
  probe failed. `cpu_topology` read the value-only `_sysctl_int` helper, which discards the errno the
  same commit added to tell "this sysctl does not exist" from "the call failed" - so an absent sysctl
  became a `WARN` reading "the hw.nperflevels probe did not answer", which is false and which no
  remedy clears. It now compares the errno against `_SYSCTL_ABSENT` and reports the existing "no
  performance/efficiency core split" answer at `OK`, while every other errno keeps its `WARN` (#400).

- A cohort freeze count is no longer trusted from a single route (#407). Freezing
  `cohort-6` at the `v0.9.0` tag re-counted it immediately after the last of 22 label
  writes, all 22 exiting zero, and `issues?state=open&labels=cohort-6` read 19 -- a
  minute later the same route, and a per-issue read taken at the same instant as the
  low count, both said 22. GitHub's label filter is an index and it lags the writes
  that feed it; the manager skill's existing rule ("re-count after the last write")
  bounds ordering and says nothing about settling, and a cohort can only shrink, so a
  low freeze written down that way is never corrected by any later count.
  `scripts/oss_state.py` gains `cohort_freeze`: given two or more named routes' counts
  it reports `measured` only when they agree, `unknown` when they disagree -- never
  the lower number, never the first one given -- and `could-not-count` when fewer than
  two routes answered. Wired into the CLI as `--cohort`/`--cohort-count`, and the
  result is recorded on the state entry as `detail.cohort_freeze`. The manager skill
  now names the settling failure and the two-route rule directly, rather than leaving
  it as a rule nobody performs.

- The report schema can spell the third receipt the filing bar defines. #393 gave an item three
  outcomes - a new issue, a comment on the class issue, or a named line in the pull request - and
  `adjacent.action` and `finding.disposition` encoded two, so a lane that correctly decided a
  finding was below the bar had to label it `report-for-filing` and disclaim it in prose. The label
  said file this, the prose said do not, and the maintainer read the label first. Both enums now
  carry `below-bar`: a phrase with no verb and no tense, unlike `filed` (removed in #254 for
  reading as an act the agent performed) and unlike `report-for-filing` (which reads as an act the
  reader should perform). The two older values are unchanged, so this widens the vocabulary rather
  than renaming anything.

  The receipt is checked rather than promised. A `below-bar` item carries `pr_anchor`, a verbatim
  fragment of the pull request body where it was recorded, and `scripts/report_schema.py` refuses
  the report when the body does not carry it - whitespace collapsed so wrapping is free, case folded
  after the first real report hit a false finding on a sentence its body carried inside bold, HTML
  comments removed because a receipt nobody reads is not one - and refuses it when
  `pr_body.state` is not `written`, since a receipt needs somewhere to be. Like the closing-keyword
  check it borrows its shape from, this is an absence detector: a finding is strong and a pass is
  weak, and nothing here reads prose for substance. The contract number moves to 5, so an older
  copy of the validator meeting a report that uses the new value answers `UNVALIDATABLE` rather
  than reporting it as malformed (#411).

- Two receipts in `scripts/oss_config.py` narrated an uncommitted delete as the *cause* of an
  absent path, on the strength of a bare `FileNotFoundError` -- which CI has measured Windows also
  returns for a path it could not even look up (errno 2, no distinguishing winerror; #380). The
  bucket assignment was already right and stays right; only the sentence claiming a cause the
  signal cannot support has changed. `gather()`'s NOTE for `absent_workflows` and the
  `version_evidence` sentence for the `absent` state (#412, #408) now share one hedge -- an
  uncommitted delete is the usual cause, stated as likely rather than as fact -- instead of two
  independent copies of the same overclaim. `PROBE_SCHEMA_HELP` (printed by `--help`) carried the
  same unhedged claim about both fields and is worded the same way now (#413).

- `/oss:doctor`'s plugin-copy comparison now looks at `schemas/`, and names the contract number when
  it differs. The compared set was `agents`, `commands`, `scripts`, `skills` and the manifest -- chosen
  when the contract between two copies lived entirely in code and prose. It stopped living there once
  `schemas/agent-report.schema.json` started declaring a version that `scripts/report_schema.py`
  reads, so two copies differing *only* there were reported as carrying the same bytes while every
  agent report written against the newer one came back `UNVALIDATABLE` at exit 2 from the older. Both
  statements were true and together they misled. Measured on the copies on the maintainer's machine:
  the installed `0.7.0` and this clone now report `declares agent-report contract version 4 and the
  checkout being diagnosed declares 5`.

  The byte difference is the detection; the two declared numbers are the fact a reader acts on, so
  they ride on the existing SKEW line rather than on a second one - a separate line would have to be
  read as *the schemas match* when it was silent, which is the absence this check exists to avoid. It
  has three states, not two. When the bytes differ and the numbers do not, it says so and does not
  imply a refusal that will not happen - and says that this is what the copies **declare**, since a
  schema can change without its number moving. When either side ships no schema, or one that will not
  parse, or one declaring no version, that is *not established* rather than agreement.

  Skew stays a `WARN` and stays clearable, exactly as it already was for the other four directories:
  it fires when two copies differ and goes away when they do not.

  The class rather than the instance: a tuple cannot report a directory it does not contain, which is
  how `schemas/` went uncompared for its whole life. Deriving the set from the tree was weighed and
  refused - an install legitimately ships no `tests/` or `changelog.d/`, and scoring those as
  differences buys a permanent `WARN` no release can clear. Instead the tuple is now half of a
  partition: `NOT_COMPARED_TOP_LEVEL` carries every other top-level entry with a reason, and a test
  fails when a tracked entry lands in neither half. The next `schemas/` reddens the commit that adds
  it (#415).

- A schema bump no longer invalidates every in-flight lane's report. `scripts/report_schema.py`
  compared the report's `schema_version` against its own and answered `UNVALIDATABLE` whenever they
  differed in either direction, so the window in which every running lane's report was unvalidatable
  was exactly as long as a lane takes. Measured on `fix/410`, dispatched before the contract moved
  from 4 to 5 and refused on handing back - with `the shape pass found nothing` printed directly
  underneath the refusal.

  The schema now declares, in `x-schema-compatibility`, what each contract does to the one below it:
  `additive` means every document valid under the predecessor is valid under this version, and the
  validator walks that chain down from its own number. A report from a contract it reaches is read,
  with `ok ... read under version N` naming both contracts - a weaker claim than a plain `ok` and
  written as one. A report from a contract it does not reach still answers `UNVALIDATABLE`, and so
  does a report whose step was declared `breaking`, declared `unknown`, or never declared at all: a
  bump that forgets to declare fails toward refusing rather than toward vouching. Version 1 is never
  reachable whatever is declared, because 1 is not a contract.

  Declared rather than derived, and the reason is not caution. Deciding whether contract A is a
  subset of contract B needs both documents, and a copy of this validator holds exactly one - the
  older schema is absent, not unread. So the relation is recorded at the bump, the one moment
  anybody holds both. It is a claim about the whole contract and not about the schema document
  alone: the cross-field rules are Python and the on-disk pass leaves the report entirely, so a bump
  that adds an optional key while tightening a rule is `breaking` however additive the document
  looks. The map is inside the contract fingerprint, so editing it afterwards without moving the
  number is caught like any other enforcing change; what no fingerprint can catch is a declaration
  that was wrong when it was written, because checking that needs the other schema. The suite holds
  that every recorded contract has a declaration at all.

  Generalised from a single instance, said plainly rather than left to be inferred: 5 is the only
  additive bump this schema has ever had. What is taken from it is the shape of the question, not a
  claim that additive bumps are common or that the next one will be as easy to be sure about (#416).

- `doctor`'s "oss plugin version" line now carries a content digest alongside the version
  string, from a new `plugin_identity()` (`scripts/doctor.py`). The version alone cannot tell two
  installs apart: `.claude-plugin/plugin.json` keeps the last RELEASED number for the whole
  cycle that follows a release, so a plugin cache directory unpacked mid-cycle from `main` and
  the tag it is named for both read the same manifest version while implementing different
  contracts. Measured directly: a cache directory named `0.9.0` declared agent-report contract
  5 while the `v0.9.0` tag it was named for declared contract 4, both manifests reading "0.9.0"
  (#418). `plugin_identity()` reuses the `plugin_tree_digest` / `_tree_identity` pair
  `plugin_provenance` already uses to compare two trees, so a single install now carries its own
  discriminator without needing a second tree on disk to diff against.

- A wait recorded in one tick is no longer dropped from view by the next entry
  landing after it (#436). `--pending-wait` and `--check-wait` (#337) used to read
  only the last state entry, so a wait that still `holds` became unreachable the
  moment any other entry appended -- a cohort freeze (#407), a lane record, a plain
  intake -- and both readers then printed exactly what they print when no wait was
  ever recorded: `no pending wait`, byte-identical to the case where nothing was ever
  waiting. Found by the release-auditor as a composition defect between #337 and
  #407, neither of whose own diffs contains it. Settled as: a wait's lifetime is not
  one entry -- both readers now scan back to the most recent entry that carries a
  `detail.wait` record, skipping over entries that recorded something else, paired in
  the fixture with the control that a file which genuinely never recorded a wait
  still answers `no pending wait` after the same kind of intervening entry.
  `--check-wait`'s refusal also no longer misreports the state it found: it used to
  fill its message with the required `WAIT_HOLDS` constant regardless of what the
  most recently recorded wait actually said, so a wait already checked `cleared` was
  reported as "state holds"; it now names the state actually read off disk. Found by
  self-review of this same fix: both readers now key "was any wait ever recorded"
  off the entry the scan found rather than off the wait record's own value, so a
  hand-authored `detail.wait: null` no longer collapses into the same "never
  recorded" absence one layer down.

- `scripts/rename_changelog_fragment.py`'s `--no-git` rename path guarded against
  overwriting an existing destination with `Path.exists()`, the one call this repo
  forbids for classification: it swallows a version-dependent set of `OSError`s and
  answers `False` for a path that could not be stat'd, not only one that is absent.
  The guard now matches the `os.stat`-and-classify-from-the-exception-in-hand shape
  `oss_config._version_state` (#396/#413) already uses, and refuses the overwrite
  on either an occupied destination or one it could not look at, rather than
  guessing the second case is free. Separately, its `git mv`/`git add` argv carried
  no `--` separator, so a directory component beginning with a dash was parsed by
  git as an option cluster instead of a path; both calls now pass `--` (#437).

- `doctor`'s fragments-README WARN offered `scripts/scaffold.py --show <path>` as
  the remedy, quoting the same absolute path the diagnostic clause names -- which
  is what `scripts/doctor.sh` and `CLAUDE_PROJECT_DIR` produce. `scaffold.show`
  matches by string equality against repo-relative template keys, so the remedy
  command failed with `is not a known template, owned file or rule` everywhere
  except under `--root .`. The remedy clause now renders the path relative to the
  project root (`Path.relative_to(...).as_posix()`); the diagnostic clause above it
  still names the absolute file on disk, since it is naming a file rather than a
  template key. Found by the release-auditor at gate 3 of the v0.10.0 round-one
  audit (#438).

## [0.9.0] - 2026-08-22

### Added

- `/oss:doctor` now reports two facts about the machine it is running on that nothing printed
  anywhere, both of which were decisive in an incident that took a morning to diagnose and take
  one line each to state (#367). **`interpreter architecture`**: whether this `python3` is
  running under binary translation -- an x86_64 build under Rosetta 2 on Apple Silicon measured
  roughly 3x on interpreter startup and 3.4x on the CPU cost of a subprocess spawn, and this
  loop is subprocess-shaped, so it is the dominant term. `platform.machine()` cannot answer the
  question and neither can `uname -m` from a subprocess: an emulated process is shown the
  *emulated* architecture and so is everything it spawns, so the probe is macOS's own
  `sysctl.proc_translated` flag read in-process through `ctypes`, with the sysctl's absence read
  as Apple documents it -- this system has no translation layer, i.e. native. On Linux
  (qemu-user) and Windows-on-ARM there is no equivalent this script reads, so the line reports
  **not probed** and says so rather than folding into `native`, which would clear an emulated
  interpreter on exactly the platforms nobody checked. That gap is reported at `OK` with the
  reason named on the line, while a probe that *does* exist and fails to answer is a `WARN` --
  two states, and they were one for exactly one round of CI. Folded together at `WARN` they made
  `VERDICT: ok` unreachable on every Linux and Windows leg forever, which removes a signal rather
  than adding a finding: a verdict that always reads `usable with gaps` can no longer carry a
  real warning, so every genuine gap on those platforms is masked by a permanent one. A gap that
  is unobservable in principle is named on the line instead, which is the shape `agent_dispatch`
  already uses in the same file. The host architecture and the
  performance/efficiency split each carry the same third state for the same reason: the sysctl
  behind either returns nothing both when the answer is genuinely negative and when the probe
  failed, and folding the second into the first prints a host nobody read and a claim that the
  cores are uniform that nobody established. **`cpu topology` and `worker sizing`**:
  the logical core count, split into performance and efficiency cores where the platform exposes
  it, and what `pytest -n auto` would actually request here -- a transcription of xdist's own
  order (`PYTEST_XDIST_AUTO_NUM_WORKERS` first, then psutil's *physical* count, then
  `os.sched_getaffinity(0)`, then `os.cpu_count()`), so the cap that exists is stated rather than
  left to be discovered, and the number is `unknown` rather than an invented 0 or 1 when nothing
  answers. Every rendering state is asserted against injected values, because the machine this
  was written on is native arm64 and a test that measured the host would have tested the
  hardware.

- `scripts/review_return.py` classifies what a review spawn actually handed back, so a reviewer that
  returned nothing and a reviewer that found nothing stop being the same bytes. Six states --
  `states-findings`, `no-findings`, `referred-not-stated`, `returned-nothing`, `could-not-classify`
  and `could-not-read` -- one `VERDICT:` line, and an exit code a shell can read. `agents/developer.md`
  now tells the developer to run it and quote the verdict instead of sorting the message by hand
  (#392).
- The two prose mitigations that preceded it did not hold: #275 and #296 were closed by PR #332's
  brief language, and #392 reports the identical shape recurring twice in one day after it shipped.
  The classifier is on the caller's side of the boundary, so unlike a header, a schema or a file the
  reviewer writes, it asks the spawn for nothing and fires whichever of #392's two candidate
  mechanisms is the real one (#392).

### Changed

- A `report-for-filing` item now has three receipts instead of one -- a new issue, a comment on the
  class issue, or a named line in the pull request -- with the intake bar defined beside the intake
  metric, a one-class-one-issue shape, and the manager step that consumes the triager's proposed
  clusters. Every finding used to mint a tracker row: one defect class became seven sibling issues,
  and the board grew at ~25 rows a day with nothing in the loop able to say no (#393).

### Fixed

- `scripts/doctor.py`'s module contract stated the printable-ASCII fold unconditionally --
  "Every finding goes through `report()`, which reduces it to one printable ASCII line" --
  while `report_with_remedy()`, added in the same release for #344, is a second emitter whose
  `remedy` argument deliberately skips that fold. A reader auditing the property from the top of
  the file got the wrong answer about three arms of the launcher check (#376). Settled by
  amending the contract rather than folding the remedy: the remedy is built from `PLUGIN_ROOT`,
  this script's own resolved install location and not text the audited tree chose, and folding it
  would put a `?` -- a shell glob -- inside a command the reader is meant to paste and run, which
  is #344 reinstated. The contract now names the one exempt fragment, says what it still gets
  (the newline and control-character collapse, and `_safe_print`'s encoding net), and says that
  nothing else is exempt. `tests/test_doctor_fold_contract_376.py` holds the paragraph and the
  set of `_emit` callers to each other, so a third emitter or a contract that reverts to the
  unconditional wording fails there -- two independent readings of the file (the AST and the
  prose) rather than the same claim stated twice, each paired with a must-fire control over
  synthetic source. No output has been unprintable; every remedy string shipped so far is ASCII.

- `lane_setup.worktree_occupancy` and `doctor._dir_state` no longer read *absence* off an
  exception type. Both caught `FileNotFoundError`/`NotADirectoryError` and answered "nothing
  is there", which is right on POSIX — an over-long name arrives as a plain `OSError` and
  already reached the third state — and wrong on Windows without `LongPathsEnabled`, where a
  path past `MAX_PATH` arrives as `FileNotFoundError`, errno 2, `winerror` None: byte-identical
  to a name that is merely not there. A `worktree_root` deep enough to derive such a path was
  printed `[free]` in the receipt a maintainer pastes into a developer brief — the confident
  absence #373 exists to close, reaching it through the one exception type that fix treated as
  safe. Absence is now claimed only when something positively confirmed it: the subject's own
  deepest ancestor this platform *can* look at is stat'ed and listed, and the verdict is
  `unknown`/`unreadable` when the name is in that listing or when nothing could confirm either
  way. Not the plainly-missing same-shape control the issue proposed, which on the folding
  platform is *also* past `MAX_PATH` and answers exactly what the subject answered — a guard
  that could never fire. No errno table and no `MAX_PATH` constant: the limit is conditional on
  a machine setting and Windows folds several Win32 codes onto `ENOENT`, so neither could report
  the value it would need. The price is one `stat` and one `listdir`, paid only on the absence
  arm. Both functions changed together, which is what the agreement test between them is for
  (#380).
- Adjacent, in the same two `except` clauses: `stat` raises `ValueError`, not `OSError`, for a
  path carrying an embedded null byte, so neither function caught it and it escaped as a
  traceback — a raise path in a script whose contract is exit 0 always, one VERDICT line. Both
  values reach these functions from `.oss.json`/`.oss.local.json`, and JSON can spell a null.
  Both now answer the third state instead (#380).

- `scripts/lane_setup.py` handed `--remote` straight into `git fetch --quiet <remote> <branch>`,
  where argv position 6 is read as an option when the value starts with a dash. Measured rather
  than reasoned on git 2.46.2: `--upload-pack=<script>` in that position **runs** `<script>` --
  the injected script printed its own argv before git reported "Could not read from remote
  repository". `resolve_base` now consults a new `lane_setup.remote_problem()` before it builds
  any argv, so a dash-prefixed remote produces the `could-not-resolve` third state with its own
  sentence and no git process at all. The rule lives beside the value rather than in
  `oss_config`, because `remote` is `--remote` argv only and never config-sourced -- a verdict
  in the config validator would be a rule for a key no config carries and `doctor` would have no
  occasion to print it; `remote_problem`'s docstring names the migration if that ever changes
  (#345, one value one rule, pointing the other way from #368's `default_branch`). Reachability
  is not claimed: nothing in this repository passes `--remote`, so the value arrives only on the
  maintainer's own command line today (#381).

- The load-bearing half is the sentence beside it. `resolve_base`'s docstring claimed
  `default_branch` was "the one value here that reaches git's argv unprefixed" -- false when it
  was written, and the kind of sentence that stops the next guard sweep from looking. It now
  names both guarded values and both *un*guarded ones with the reason each is safe by the shape
  of its argv rather than by a rule: `branch_occupancy` prefixes `refs/heads/` and
  `refs/remotes/`, and `--repo` is `-C`'s argument, which git consumes literally instead of
  re-parsing it as an option. Both re-measured here rather than inherited from the audit that
  filed the issue. The docstring also records `git fetch --quiet -- <remote> <branch>` as a
  measured alternative that works, and why it was declined: it makes git the thing that reports
  the refusal, and beside a value already refused above it could never fire (#381).

- `tests/test_lane_setup_381.py` asserts on captured argv rather than on the exit code -- a
  version that ran the fetch and then failed would pass the weaker form -- with a well-formed
  non-default remote as the positive control in the same fixture. Its last test is a sweep
  rather than a case: every argument the module hands to `_git`, for a hostile value injected at
  each of the four input sites in turn, must not begin with a dash unless the module wrote it as
  a literal flag. Each site asserts its own premise -- that its value is dash-prefixed at all,
  and that it produced argv at all -- because the first draft of the `repo` site did neither and
  swept a benign input while reporting coverage for a hostile one. `--repo` is the site with no
  rule guarding it, so `_git`'s own argv is measured directly: the repository must sit in `-C`'s
  slot, where git consumes it literally. #381 exists because the previous guard was written for
  the position somebody enumerated (#381).

- `scripts/oss_state.py` folds its receipt lines, so nothing rendered into one can forge
  another. `lane_models_line` emitted `window`, a lane's model name and a `why` raw, and
  `intake_line` beside it emitted `window` and `why` the same way: a newline in any of them
  produced a second line a reader cannot tell from the tool's own, in output a maintainer
  pastes into a developer brief and which `--model-trend` reads back out of the state file.
  The module carried no fold at all while five sibling scripts had one. The guard is applied
  at the single point each renderer joins its line rather than per field — a per-field guard
  closes what somebody enumerated and leaves the next field unguarded — and a line long
  enough to be cut now says it was cut, because a truncated receipt rendering as a complete
  one is the defect class this plugin is named after pointed at its own output (#382).

- The suite no longer goes red between the changelog fold and the release commit. Two
  enumerations listed the repository with `git ls-files` and then read the working tree,
  so the twenty-one fragments the fold deletes arrived as paths that are in the index and
  not on disk — and both filed them as *could not read*: `tests/test_paginated_counts.py`
  answered `could-not-scan` about a tree it had read completely, and
  `scripts/shell_sources.py` exited 3, which is the shell CI leg refusing. Four tests
  failed on a working tree with nothing wrong with it, at exactly the gate the release
  procedure says to run, which teaches re-running until green. Absence is now its own
  bucket in both — reported by name, never dropped, because a file deleted in a diff
  nobody meant to make is worth surfacing — and only a file that is there and will not
  read still refuses. `FileNotFoundError` decides it, so no second question is put to the
  filesystem. The `shell_sources.py` change also stops a deleted `.sh` reaching
  `shellcheck` as a path that does not exist: an extension classified it without anything
  having to look (#384).

- #350's guard can tell a test that **pins** this repository's version from one that merely
  **spells** it, so a version-comparison fixture no longer blocks a release. Cutting `v0.9.0`
  reddened the suite on the release commit — reported by the very guard that exists to prevent
  that — naming `test_freshness.py:59,60,169`: the lexical-versus-numeric fixture
  (`0.9.0` against `0.10.0`, the minimal one-digit against two-digit pair) and a fixture
  record. None of the three reads the manifest and none can redden when it is bumped, so the
  guard was reporting the opposite defect from the one it was written for. The missing bound
  is provenance, which is not statically decidable, so it is over-approximated at file
  granularity: a file with no route to the repository's own declared version cannot redden on
  a bump, whatever its literals spell. The route is deliberately coarse — a `REPO_ROOT`-anchored
  one would have missed #350 itself, whose offender built its plugin root under `tmp_path` while
  the product read a global. Two errors are now possible and both cost the same event, so the
  direction was chosen on measurement rather than on symmetry: `0.9.0`, `0.10.0` and `0.11.0`
  were all already spelled in `tests/`, arming the over-report at each of the next three minor
  releases, while the under-report has never been observed once. A collision is announced as a
  warning naming the lines and saying they are not offenders, rather than being dropped
  silently, and the sweep now also runs against the **next** minor on every ordinary run — so
  the answer arrives before the release commit instead of on it. A route renamed on import is
  read off the import statement, because `from doctor import PLUGIN_ROOT as here` leaves every
  use site spelling nothing and would otherwise wave a genuine pin through (#399).

- `scripts/review_return.py` answers `could-not-read` at exit 6 when it is handed a closed or
  unopenable standard input, instead of raising `AttributeError` and exiting 1 with no `VERDICT:`
  line. The file route already computed that answer three lines away; the stdin route — the one
  `agents/developer.md` mandates — could not reach it. An open stdin carrying no bytes still answers
  `returned-nothing`: read and found nothing is not the same as could not read (#405).

### Security

- The reviewer's final message no longer reaches `scripts/review_return.py` through a stream bash
  parses on its own terms. `agents/developer.md` placed it at column zero of a quoted heredoc closed
  by a fixed one-word terminator, so a message carrying that word ended its own transport and the
  rest of it was executed as commands in the developer's session — and the classifier then returned
  `referred-not-stated` over the surviving prefix, manufacturing the failure it exists to measure.
  It needs no adversary: the first observed instance was a reviewer quoting the documented block,
  terminator included. The message is now handed over `--framed`, with every line indented by four
  spaces so a line that ends the stream cannot be constructed, and closed by `END OF MESSAGE` at
  column zero so a message that did end early answers `could-not-read` instead of being classified
  (#404).

## [0.8.0] - 2026-08-20

### Added

- `python3 scripts/transcript_refusals.py` counts refused tool calls across agent transcripts -- by class, by model, and the consecutive-single-op-read runs a batched call would collapse -- so a claim that a fix reduces refused calls is a measurement rather than an assumption. Step 1 only of #313: the jit-context rule the issue's body proposed is deliberately not built here, because its own first comment corrects the arithmetic -- a rule fires at PreToolUse and occupies the same turn the refusal it replaces already did, so it does not remove a turn (#313).

- Added `scripts/lane_setup.py`, one call for the facts a developer lane brief hand-carries and
  that rot between the moment they are written and the moment they are read: the resolved base
  commit (fetched and `rev-parse`d, never abbreviated), the branch and worktree path derived from
  `branch_pattern` and `worktree_root`, whether that worktree already exists, and the live worktree
  board condensed to one line per tree with its three occupancy states intact -- `cannot tell` never
  renders as `idle`. Wired into `commands/tick.md` step 5, run from the clone before `git worktree
  add`, since `worktree_root` only resolves where `.oss.local.json` is present (#317).

### Changed

- The developer agent's model default is now `sonnet` rather than `opus` (#316), on the
  maintainer's decision after a trial: Sonnet developer lanes cost `$10.17` mean at 200 turns
  against Opus's `$16.86` at 139, and the quadratic turn penalty this issue predicted (roughly
  1.4-1.7x the turns) does not close the 2.5x-5x rate gap on the cache-hit line that dominates
  the bill. Measured over 143 developer lanes across this project's history (15 Sonnet, 128
  Opus), the extra turns are narration -- text-only turns with no tool call -- rather than
  extra work, and Sonnet takes fewer guard refusals per turn than Opus on every class. `skills/
  manager/SKILL.md` now states the choice and its reversal conditions under *Delegating*,
  pointing at this issue for the priced numbers rather than repeating them in a file every
  managed repository loads. Every dispatched developer lane can be recorded so the mix
  stays recomputable rather than asserted: `scripts/oss_state.py` gains `lane_models`,
  `lane_model_trend` and `lane_models_line`, plus `--lane`, `--lanes`, `--lane-window`,
  `--lane-why` and `--model-trend` on its CLI, following the same three-extra-state shape as
  the existing intake metric -- a tick that dispatched no lane and a tick that recorded
  nothing about its lanes must not render alike, and an override with no reason is refused.

### Fixed

- `scaffold.py`'s own `_one_line` -- the flattener that keeps a filename from another
  repository from forging a line of a receipt this loop prints -- only collapsed
  whitespace, unlike every other copy of the function (`release_delta.py`,
  `doctor.py`, `release_publish.py`, `release_version.py`, `report_schema.py`,
  `lane_setup.py`), which also fold every character outside printable ASCII to
  `?`. Whitespace-collapse alone stops a new *line*; it does nothing to a control
  byte, since a control byte is not whitespace. So a filename carrying an ANSI
  escape sequence passed through `scaffold.py`'s copy unchanged and could repaint
  the surrounding receipt -- colour, cursor movement, erase-in-line -- during
  interactive review, without ever breaking the line-structure guarantee #204 and
  #223 established. `scaffold._one_line` (and `_join_names`, which calls it) now
  applies the same printable-ASCII fold as its six siblings. `doctor.py`'s own
  `_one_line` and `_one_line_keep_unicode` were checked and were already safe --
  both fold everything below `chr(32)`, catching ESC (0x1b) as a side effect
  (#228).

- The tick step 4 rule that heals radar on every board-membership change was examined for
  a cheaper gate that skips the heal when nothing is left bare (#302). Measured rather than
  reasoned: the only op that can answer radar's own coverage question -- `N watched` against
  `N open` -- is the bare `radar` heal itself; `radar:--state` explicitly declines to resolve
  live coverage. A probe cheap enough to gate the heal does not exist, so the rule in
  `commands/tick.md` stays unconditional and now records why, instead of being
  re-investigated cold on a future tick.

- Five documents stated the two-segment changelog fragment name (`<issue>.<section>.md`)
  with no mention of the optional slug the assembler and the release-version rule have
  both accepted since #297/#305 -- `changelog.d/README.md`, the `changelog.d/` rule
  layer scaffolded into managed repos, `commands/changelog.md`, and both fragment-naming
  sites in `scripts/scaffold.py` (the fragment README template and the generated
  workflow's own error message). All five now state `<issue>.<section>[.<slug>].md`,
  and `tests/test_docs_state_slug_grammar_308.py` reads the canonical form out of the
  assembler's own refusal message and asserts each document -- reading the *rendered*
  output for the two templated sites, not the template source -- states it, paired
  with controls proving the check has teeth rather than just matching a substring
  (#308).

- `scripts/doctor.py`'s `./supertool` check used `os.path.lexists`, which swallows every
  `OSError`, not only `ENOENT` -- so a `--root` this process could not traverse read as
  `./supertool: absent`, with a remedy telling the reader to link a file that may already be
  there. It now reuses the check's existing `unreadable` state instead, and prints the
  message that state already carries: which of present/absent/wrong-target this repo is in
  is unknown, not absent (#341).

- `scripts/doctor.py`'s `oss-workspace` launcher remedy -- the first paste-ready shell
  command it prints -- went through the same ASCII sanitiser as every other finding, which
  folds non-ASCII characters to `?`. On a non-ASCII install path (ordinary on a localised
  macOS or Windows account) `?` is a shell glob, so the printed `ln -sf`/`sh` command either
  failed against a path that does not exist or linked a file nobody named. The remedy now
  goes through a narrower sanitiser that keeps the newline/control-character defence but not
  the ASCII fold, because it is composed by the diagnostic from its own resolved install
  location rather than from text the audited repository chooses; every other finding is
  unchanged (#344). Printing that non-ASCII text can itself fail on a stream that cannot
  represent it -- a lone surrogate from an undecodable filename byte, or a character outside a
  narrow console codepage -- so the print is now defended at the point of failure rather than
  assumed safe, keeping the diagnostic's `exit 0 always` contract.

- `assemble_changelog.py` treated an empty `--dir` or `--changelog` the same as a real
  directory (#346), because `Path('')` is `Path('.')` and only `value is None` counted as
  "nothing was passed". Any caller that handed the fold an explicit empty string got a
  silent fold and delete against the current working directory instead of the refusal a
  missing flag already gets. Enumerating legitimate out-of-tree callers -- this
  repository's own test suite runs the fold from scratch directories outside any repo,
  and a REPO-derivation-keyed containment check would refuse those along with anything
  hostile -- argues against a boundary tied to `REPO`, which the module's own docstring
  already says cannot tell "the repo this file is stored in" from "the repo being
  released". Closing the empty-value gap instead protects every caller, in-tree or out,
  without guessing where a legitimately-named directory lives: an empty `--dir` or
  `--changelog` is now refused on the fold, naming the missing flag, and falls back to
  the derived default on the read-only modes -- the fold's refusal is the same verdict
  `changelog_dir_problem` already reaches for an empty `changelog_dir` at the config
  entrance (#343), which has no read-only mode of its own to fall back from. No
  containment was added beyond that;
  the reachable path was already closed by #345, and this closes the one gap that did not
  depend on trusting a caller (#349). The fallback on the read-only modes says so on stderr
  when the value it is falling back from was explicitly empty rather than genuinely absent
  -- an ordinary run passing no `--dir` at all stays silent, but a caller whose `--dir`
  arrived empty now sees which directory was used instead of a receipt that only ever names
  fragment filenames.

- `GATE_DIR_RE`'s whitespace class crossed a newline, so a bare `--dir` with no argument let its
  bare-token alternative capture the *following* flag -- `--changelog` -- as though it were the
  directory, and that value passed `changelog_dir_problem`'s character-class check because a leading
  dash is not itself refused. The same misreading also happened with no newline at all, whenever an
  unquoted `--dir` was immediately followed by another flag on the same line -- an unquoted token
  starting with `-` cannot be told apart from another CLI flag either way. `scaffolded_changelog_gate`
  now restricts `--dir`'s argument to the same line and never captures an unquoted token that starts
  with `-` as a value, answering a new sixth state, `present-bare-dir`, whenever the flag carries no
  usable argument -- distinct from `present-refused-dir`, which means a value was captured and
  rejected on content, because here nothing was captured for that rule to have an opinion about
  (#347). A *quoted* value starting with `-` is unaffected: quoting is what removes the ambiguity
  with a flag, not the character itself.

- `scripts/doctor.py`'s `oss-workspace` launcher consumer fell through a bare `else` for
  its one state without a named arm (`mismatched`), and that `else` unconditionally unpacked
  a 3-tuple. No state reaches it today, but a seventh state added later would have raised
  there instead of being reported, breaking the diagnostic's `exit 0 always` contract. The
  `else` is now a named `mismatched` arm plus an explicit unrecognised-state arm that
  reports rather than unpacks, and the same derive-the-states check this repository already
  uses for another consumer now covers this contract too (#348).

- `commands/changelog.md`'s directory resolver refuses correctly on stderr when
  `changelog_dir` names something unusable, but the block that captures it,
  `FRAGMENTS_DIR="$(...)"`, checked no exit status and had no `set -e` (#349). A reader who
  continued past a `REFUSED:` line carried an empty `FRAGMENTS_DIR` into the fold below as
  `--dir ''`, which reached `CHANGELOG.md untouched, nothing consumed` -- a report about
  the wrong file, since what had actually happened was the resolver's refusal being
  dropped. Fixed at the callee rather than at this one call site: `assemble_changelog.py`
  now treats an empty `--dir`/`--changelog` as absent, so the fold refuses loudly by
  naming the missing flag instead of quietly scanning cwd, whichever caller handed it the
  empty string (#346). `commands/changelog.md` documents the closed gap rather than adding
  shell-side error handling that would only cover this one command's own resolver.

- `agents/developer.md` never told a lane not to end its turn waiting on a suite run it had
  launched itself (#353). Three lanes in the #316 trial did exactly that -- no report, no
  commit, one lane twice -- and the fix that stopped it was typed into a resume message and
  nowhere else, so the next tick's fresh lanes hit the same failure with no document to warn
  them. The definition now says it directly: run the suite in the foreground with an explicit
  redirect, names the measured wall clock (27m36s with four lanes concurrent) so a long run
  does not look like a reason to background it, and states the consequence -- an agent that
  stops with work uncommitted notifies as `completed`, so the stop is invisible to the
  maintainer until somebody reads the worktree by hand. `tests/test_content_invariants.py`
  holds the rule in the same shape #266 already established for the `cd <worktree_root>`
  paragraph, so a future edit that drops it fails a test rather than a tick three weeks later.

- `skills/manager/SKILL.md` still instructed the maintainer to hand-derive the base commit and
  the live-worktree list before every brief, even though PR #357 merged `scripts/lane_setup.py`
  and wired it into `commands/tick.md` (#360) -- so the two documents described two procedures
  for the same step, and `SKILL.md` is the one a tick loads first. With the hand-copy procedure
  in force, `main` moved four times across two ticks and `fix/313` and `fix/341` were each
  briefed onto `README.md` forty minutes apart, because the worktree ownership list was retyped
  rather than derived. The *Run a fleet, not a queue* section and the per-brief checklist now
  point at `scripts/lane_setup.py <issue>` instead of typing a snapshot that rots between the
  moment it is read and the moment a dispatched agent reads it. `tests/test_content_invariants.py`
  gained a guard, in the same two-copy shape as #266 and #250, that fails if a document instructs
  naming the live worktrees without also naming the script.

- `scripts/doctor.py` carried six more `is_dir()`/`exists()` call sites that swallowed an
  unreadable *parent* directory the same way #341 swallowed one -- reporting a directory or
  file that may well be there as a confident "does not exist"/"no rules for this repo", with a
  remedy telling the reader to create something that already exists. `check_directory` (the
  config's `clone`/`worktree_root`), `check_jit_rules`'s rules directory, and `resolve_project_dir`'s
  own `--root` check -- the entry point where doctor's third-state contract is established rather
  than consumed -- now report a distinct "could not be checked" state instead of a confident
  absence. `merge_permission_state` now routes an unreadable settings candidate into the `unknown`
  bucket it already had and never reached. Two narrow glob filters (`jit_hook_roots`,
  `_jit_layer_verdict`) no longer let one unreadable candidate wipe every candidate already found
  in the same scan. Classified explicitly rather than relying on pathlib's own swallow, which is
  version-dependent: `is_dir()`/`is_file()` re-raise `PermissionError` on at least this repo's own
  3.9, 3.11 and 3.13 and only swallow it on 3.14 (#363).

- `agents/developer.md` stated three measurements from this repository's own trial -- the
  27m36s wall clock, the narration-turn count and the single-op share -- as if they were
  facts about every repository this plugin manages, with no label saying whose trial they
  came from (#369). The sibling document already carried the fix: `skills/manager/SKILL.md`
  scopes its own developer-model figure to "this project's own history (#316) rather than
  repeated here as a number a different installation would read as generic guidance," one
  paragraph below a sentence in `agents/developer.md` itself ("Three lanes **on this
  repository** ...") that already showed the same labelled shape. All three measurements now
  read the same way. The single-op figure was also wrong: the shipped 82% combined every
  model together and was produced by a parser that double-counted multi-invocation Bash
  calls; re-measured with `scripts/transcript_refusals.py`, the split is per model and the
  doc no longer states a specific percentage that will drift the moment another lane runs.
  `tests/test_content_invariants.py` now grades whether a measurement anchor is accompanied
  by a scoping label within its own paragraph, with a must-fire fixture reproducing the
  pre-#369 wording and a must-not-fire fixture built up one label at a time.

- `scripts/lane_setup.py`'s `resolve_base` handed `default_branch` straight into
  `git fetch --quiet <remote> <branch>`, where argv position 4 is read as an option when
  the name starts with a dash -- without consulting the problem sentence
  `oss_config.load()` had already produced for that exact value. Three renderings
  disagreed about the same input: `blocked()` returned `False` and the process exited
  `0`, `commands/tick.md` documented `could-not-resolve` as blocking with exit `3`, and
  the `config warn:` line was rendered by `receipt()` *after* `git fetch` had already
  run. `resolve_base` now calls `oss_config.default_branch_problem()` before building
  any argv and returns `could-not-resolve` carrying that sentence, so nothing executes
  and the three renderings agree. No second validation rule was added -- one value keeps
  one rule (#345), and `oss_config` still deliberately returns the offending value with a
  sentence rather than stripping it. `branch_occupancy` was and remains unaffected
  because it prefixes `refs/heads/` and `refs/remotes/`; that is now measured in
  `tests/test_lane_setup_368.py` rather than asserted in prose. Found by the
  `v0.7.0..e4d48de` release audit, class B; it needs a hostile or malformed
  `default_branch` in a tracked `.oss.json`, and nobody has been observed hitting it.
  (#368)

- `scripts/lane_setup.py`'s `receipt()` printed config values raw, so a newline in one
  forged receipt lines a reader could not tell from the tool's own -- in output that
  `skills/manager/SKILL.md` and `commands/tick.md` both instruct maintainers to paste
  verbatim into a developer brief. The file's own `_one_line` ("A newline in either
  forges a receipt line") was applied to `detail` and to the board lines and skipped
  everywhere else. Four fields were measured forging, not the three the audit reached:
  `branch_pattern` and `worktree_root` and the `--repo` argv, and -- newly found while
  fixing those -- an `oss_config` **problem sentence** built from a hostile JSON *key*,
  which needs no hostile value anywhere and which `oss_config` cannot close at its end
  without refusing to name the key that is wrong. So the guard is at the single point
  where the receipt is joined rather than on a list of fields, because a per-field guard
  closes what somebody enumerated and leaves the next field added unguarded. It folds
  every character outside printable ASCII to `?` and leaves runs of spaces alone --
  deliberately not `_one_line`, whose whitespace collapsing would destroy the column
  alignment the receipt is read by -- and marks a line it truncates, since a cut line
  rendering as a complete one is this repository's own defect class pointed at its own
  receipt. Whether `oss_config` should also grow a content rule for `branch_pattern` is
  a separate question and is deliberately not answered here (#345, one value one rule).
  Found by the `v0.7.0..be36015` release audit, class C, ranked `forges`; it needs a
  hostile or malformed tracked config, and nobody has been observed hitting it. (#372)

- `scripts/lane_setup.py`'s `worktree_occupancy()` rendered three states -- `already
  exists` / `free` / `unknown` -- and the third was unreachable for the case it exists
  for. The check was `os.path.exists`, which swallows `OSError`, so an unreadable parent
  directory came back `False` and the receipt printed `[free]`: a confident absence, in
  output a maintainer pastes into a developer brief. It now asks `os.stat` once and lets
  the exception already in hand answer -- `FileNotFoundError` and `NotADirectoryError`
  are ordinary absence, every other `OSError` is "could not look" -- with no second
  question to the filesystem and no errno table, since Windows folds several Win32 codes
  onto `ENOENT`. `doctor._dir_state` (#363, the same release delta) answers `unreadable`
  on the identical path and was deliberately **not** moved to a shared module: it asks
  "is this a directory" where this asks "is anything there", and it has four call sites
  and its own tests in a 5,000-line diagnostic, so lifting it is a refactor past this
  fix's blast radius. What holds the two together is a test that runs both classifiers
  on one fixture and fails if either changes its mind, rather than prose asserting they
  agree. Every case confirms the deny by attempting the exact operation and skips
  loudly, naming the platform and what went untested, when the platform does not produce
  it. Found by the `v0.7.0..be36015` release audit, class A, ranked `misreports`. (#373)

- `scripts/transcript_refusals.py` counted `transcripts_parsed` *after* the `--agent` filter, so a
  filtered run reported files as unparsed that were never offered to the parser: three clean
  synthetic transcripts with a filter matching one came back `transcripts_found: 3,
  transcripts_parsed: 1, unreadable_files: []`, in which the gap reads as two parse failures and
  the third state a reader would check to disprove that is empty. Against this machine's real
  transcript tree the same run reported 160 of 489 parsed, with 329 files silently rendered as
  failures. The count is now taken before the filter, so `found - parsed == len(unreadable_files)`
  unconditionally. Making the two numbers agree was only half of it and would have been the worse
  fix alone -- it erases the fact that a filter ran -- so the filtered subset is reported as its
  own number in three states: `transcripts_matched_agent_filter` is `null` when no filter was
  applied, an integer when one was, and `0` is a real finding meaning it matched nothing.
  `agent_filter` echoes the filter itself. Found by the `v0.7.0..be36015` release audit, class A,
  finding A2 (#374).

- The `CLAUDE.md` currency guard counted pending changelog fragments with its own copy of the
  fragment name grammar, and that copy predated the optional `<slug>` segment: a release cycle
  whose pending fragments were all slug-form parsed as an empty directory, so the guard skipped
  with "no unfolded changelog fragments, so no release is being prepared" — a confident absence
  produced by the parser rather than by the directory. It now takes the grammar from
  `scripts/assemble_changelog.py`, the one place that owns it, so there is one spelling fewer to
  drift rather than one more (#375).

## [0.7.0] - 2026-08-20

### Changed

- There is no good reason to stop the loop, except being asked to stop it directly. Every other
  condition — waiting on CI, waiting on an agent, waiting on a third party, a release a gate refused,
  an empty board — arms a wakeup instead. This replaces *nothing outstanding but somebody else's work
  → `stop: true`*, which asked the loop for a judgement about its own board at the moment it was
  least able to make one: a loop about to stop has definitionally stopped looking, and one did so
  while holding a belief that had been false for an hour and fifty minutes. The asymmetry is the
  argument — an idle loop is visibly idle and self-correcting, while a stopped loop is
  indistinguishable from one that was never armed and nothing inside it will ever notice. A tick
  still ends in one of three states; none of them stops the loop, and conflating the two was half the
  defect (#209).
- A recorded wait must name what it waits on in a form a later turn can re-read, in the wakeup's
  `reason` and in the state entry alike. *Blocked on audit completion* outlived the audit it named by
  ninety minutes; *blocked on the gate 3 audit dispatched at 23:12Z* is a claim the next turn fails in
  one call (#209).
- Gate 3 now says what happens after it fires: stop the tag, not the loop. Round-one findings are
  filed and their blocking rows delegated in the same tick; a blocking row puts its fix on the
  release's critical path, ahead of the general backlog, because the tag cannot move until it lands;
  `could not run` is followed by diagnosing why. It was the only gate whose failure produced work
  items and the only one with no statement of who picks them up, and a correctly blocked release sat
  three hours with a green branch and an empty board. The release auditor now labels a blocking
  finding as critical-path in the item itself, so it does not reach the caller looking like an
  ordinary filing (#209).

- `CLAUDE.md`'s "What is not proven yet" section is re-derived at `01212b0` and names `v0.6.0`.
  Reach moved for the first time in four rounds -- `claude-remember` now carries a committed
  `.oss.json` and all three owned files, so config-writing has reached four repositories and
  furniture-writing three, measured with 44 `gh api` probes across the eleven repositories the
  organisation actually lists. The owned-file drift table gains a third remote column and now reports
  two identical cells of nine. One recorded fact is retracted rather than superseded: the claim that
  `claude-jit-context` 0.5.0 introduced `subagent_type` as a subject key is false -- 0.4.0 carries the
  same parse on the same line, so the capability was never new (#235).

- The developer brief now refuses a reviewer return that *refers* to findings without stating them.
  A spawn that executes and hands back "two confirmed findings reported above" is not empty, so the
  sentinel #200 added never fired on it, and it is not `NO FINDINGS`, so it read as a delivery -- six
  times across two repositories and two days, with fourteen findings claimed and twelve of them
  unrecoverable. Both spawn briefs must now open with `FINDINGS: <n>` and state exactly that many, the
  caller's sort of a final message gains a fourth arm mapping a gesturing return to `returned-nothing`
  rather than `checked`, and the residue a lost return leaves -- a count, a subject, a filename -- is
  recorded as an `open` item and named as a handle rather than a finding. The brief says plainly that
  this is a request to the spawn and not a boundary on it: nothing this repository ships sits between
  a sub-agent's final message and its caller, so removing the class rather than the instance needs a
  structured sub-agent return from whatever does the spawning (#275, #296).

### Fixed

- A pull request payload that closes nothing is refused before it is published (#274). `pr_body`
  now carries `closes`, in three states of which only the third is a defect -- it closes
  something, it deliberately closes nothing (a `Part of #N` pull request is a real
  decision), or nobody said -- and `scripts/report_schema.py` reads the payload's body for
  a closing keyword bound to every issue the report says it closes. Measured across two
  sessions, four of seven agent-written payloads bound none: the report said `pr_body:
  written`, the validator said `ok`, and the only thing that noticed was the maintainer's
  `gh-pr-create` call, which reports and does not refuse. On the fourth the counterfactual
  was measured rather than argued -- the manual repair was separable from the merge, and
  without it the merge would have closed nothing while the board read clean.

  The body check is an **absence detector**, not a closing-reference reader, and the
  distinction is written into the schema so the weaker thing cannot be read as the
  stronger one. It reports that it could find no binding; it never decides what a forge
  will close, and `gh-pr-create` stays the authority. Every transformation it makes --
  stripping fenced and inline code spans, stripping HTML comments, requiring the keyword
  adjacent to each declared number -- can only make it report more often, so a finding is
  strong and a pass is weak. On the two traps that make a substring grep for `Closes #`
  wrong it is not merely conservative but correct, and both were observed in one night: a
  shared keyword over two numbers closes only the first, and a backticked `Closes #N`
  creates no reference while rendering as one that plainly did.

  The contract number moves to 4. Breaking in both directions: a version-3 copy refuses
  every version-4 report because `closes` is an unknown key, and a version-4 copy refuses
  every version-3 report because it is absent.

- `oss-workspace` on `PATH` is a symlink resolved once, at install time, into a
  version-scoped plugin cache directory. Nothing re-pointed it on a later release and
  nothing checked it, so a stale target that still exists behaved exactly like a
  current one -- measured twice on the maintainer's own machine, the second time
  losing a security fix landed in the file the symlink names. `/oss:doctor` now
  reports it as `oss-workspace launcher: ...`, in three states -- matched, a skew
  naming both versions (by content, not by the version segment in the target's path
  alone, since a stale git clone can carry a directory name that matches no release
  it actually contains), and not on `PATH` at all -- and its remedy line names the
  running install's own path rather than `$PWD`, so it is correct wherever you paste
  it from (#289, #288).

- Seven test files justified reading `.github/workflows/*.yml` as plain text with the
  same sentence -- pyyaml is not a dependency of this repo -- and #303/#311 made it false
  by adding pyyaml to the pytest job's own `pip install` line (#312). Each of the seven
  still asserts on what a maintainer reads in the file, or on a distinction (a block
  boundary, an absent-versus-empty `on:` block) a real parser would collapse, so the
  design decision stands; only the stated reason was stale. The false clause is removed
  from all seven and replaced with the reason that was already true. A new test,
  `tests/test_pyyaml_claim_312.py`, reads the workflow's own `pip install` line and fails,
  naming the offending files, if that sentence reappears while pyyaml is installed.

- `skills/manager/SKILL.md`'s restatement of the release gate's security-audit step fell out of
  date the moment #320 landed a grade split (`clean (read)` vs. `clean (exercised)`) and an
  attribution arm (dispatch token / unattributed / more than one completion) in
  `agents/release-auditor.md` and `commands/release.md`. The skill now restates both additions too,
  and a new test reuses `commands/release.md`'s own consumer check against `SKILL.md` so the two
  documents cannot drift again silently (#321).

- `scaffolded_changelog_gate` answered `present` from the gate workflow's existence
  alone, so a repo whose scaffolded gate polices a directory other than `changelog.d`
  (a named `changelog_dir` later nulled) got its release version proposed from the
  wrong, stale fragment directory with `problem=None` -- no refusal, no third state.
  The gate's own `--dir` argument is now read back out of the workflow: a gate naming
  the default still answers `present`, one naming another directory answers a new
  `present-other-dir` state carrying that directory, and a workflow whose `--dir`
  arguments disagree with each other answers `unknown` rather than guessing between
  them (#325).

- The `present-other-dir` state #325 gave `scaffolded_changelog_gate` reached two of the
  four documents that restate that contract. `/oss:changelog`'s embedded `FRAGMENTS_DIR`
  resolver branched on `present` and `unknown` only, so a repo scaffolded with a named
  `changelog_dir` that was later nulled -- legal, and reachable by ordinary contribution --
  got `NOT-ADOPTED` on stderr and exit 1 for fragments the gate could now locate exactly.
  `commands/scaffold.md` still described the gate as answering "present ... absent". Both
  now carry one arm per state, the resolver refuses an unrecognised state by name instead
  of inheriting whichever arm was last, and `tests/test_gate_state_consumers_328.py` joins
  producer to consumer: the state list is derived from the function's own `return`
  literals, so the next state added cannot go green in the documents it never reached
  (#328).

- The `oss-workspace` launcher check walked `PATH` with `os.path.lexists`, which
  swallows every `OSError` and not only `ENOENT`, so a `PATH` entry the process could
  not traverse was indistinguishable from one that simply did not hold the launcher --
  and if every entry answered that way the reader got exactly the `not on PATH` a
  genuinely absent launcher produces. The walk now asks `os.lstat` and lets the
  exception in hand do the classifying (`FileNotFoundError` and `NotADirectoryError`
  are absence, everything else is "could not look"), with no second question put to the
  filesystem. Entries that could not be read are returned alongside the hit rather than
  collapsed into it, and reach a sixth state, `path-unreadable`, naming each entry and
  its errno: whether the launcher is reachable is reported as unknown, never as absent
  (#333).
- Every remedy that check printed was an unconditional POSIX `ln -sf`, on Windows too,
  where it is inert -- and the README documented the same line twice, also
  unconditionally. `bin/oss-workspace` is a `/bin/sh` script that runs under Git Bash
  rather than cmd or PowerShell, and nothing puts `~/.local/bin` on a Windows `PATH`,
  so there is no command to translate it into: the Windows output now says that in as
  many words and names the route that does work (`sh <install>/bin/oss-workspace` from
  the checkout). Both arms are asserted on every CI leg, and the default arm is
  asserted against the running platform with no skip, so the claim lands on the Windows
  legs rather than skipping there while rendering green (#330).

- The developer brief now states the `pr_body.closes` duty that version 4 of the report schema made
  mandatory. This is a follow-up to PR #334 (#274) and did not ship in it: that pull request landed
  the contract, with `closes` required whenever `pr_body.state` is
  `written`, and `agents/developer.md` -- the brief every developer lane reads -- did not mention
  the field, so the next lane through would have written a report exactly as instructed and had it
  refused, with no route to the reason short of reading the schema.

  The brief points at `schemas/agent-report.schema.json` for the states and their spellings rather
  than copying them, because a field list living in two documents is the drift this repository keeps
  paying for. What it states instead is the half a pointer cannot carry: the closing keyword has to
  be **bound in the rendered body**, outside code spans and HTML comments. That is the failure no
  amount of field documentation prevents -- across two sessions four agent-written payloads declared
  their issues and bound nothing, one of them by backticking the whole line, which renders as though
  it worked and creates no reference at all. It also records that `Closes #A #B` closes only `#A`,
  so the count of `Closes` lines is the count of issues, and that the line goes in while the body is
  composed rather than after the validator refuses it, when the repair spans two files.

  No issue was filed: the gap was reported by the #334 lane as `report-for-filing` and correctly not
  fixed there, because the brief belonged to another lane at the time. Filing and immediately
  closing would have been ceremony, so this pull request (#338) is the filing.

  The fragment was written keyed to #334, the real number this change hangs off, because no number
  of its own existed until somebody opened the pull request; it was renamed on open, which the
  one-file-per-pull-request convention in `changelog.d/README.md` asks for. The rename was not the
  metadata-only operation it looked like: the gate requires the entry to name the number its
  filename carries, so renaming the file alone refused the fold and this sentence is the other
  half of it.

- `changelog_dir` had a validating guard at the `.oss.json` entrance and none at the
  second entrance #327 opened. `scaffolded_changelog_gate` read a `--dir` value back out
  of the tracked, owned `.github/workflows/oss-changelog.yml` and returned it as
  `present-other-dir` with no problem, and `release_version._fragment_dir` resolved it as
  `Path(repo) / detail` -- where an absolute string discards the repo root and a `..`
  chain walks out of it. The same two values the config entrance refuses with a paragraph
  came back clean through this one, and the directory it names is the one `/oss:changelog`
  prints as "the directory to use for every command below", the last of which is a fold
  that unlinks every fragment it consumes. The workflow is tracked, so the value arrives
  by ordinary contribution. The gate now applies `changelog_dir_problem` to what it reads
  and answers a fifth state, `present-refused-dir` -- not `present`, not
  `present-other-dir`, and not `unknown`, because the workflow was read perfectly well and
  said something inadmissible. Every consumer has a named arm for it, `_fragment_dir`
  gained named arms for `absent` and for a state it does not recognise instead of a
  trailing catch-all, and `tests/test_gate_dir_validated_343.py` asserts the two entrances
  as an equivalence over one value set rather than restating the rule a third time.

  Reviewing that fix inverted the issue's own framing, so two more holes closed with it.
  The `.oss.json` entrance, filed as the control, was **not** guarded either on the paths
  a release walks: `changelog_dir_problem` is reached from `oss_config.validate()`, and
  neither `release_version._read_config` nor `/oss:changelog`'s embedded resolver calls
  it, so `changelog_dir: "/etc"` reached `Path(repo) / named` with no complaint. Both now
  apply the rule at the point of use. And `--dir ''` was dropped as falsy before it could
  be judged, so an empty value inherited the answer belonging to a workflow with no `--dir`
  line at all and fell back silently to `changelog.d` -- a directory nobody named, which is
  #299 and #325's class rather than this one's. An empty value is now a value (#343).

- `oss_workspace_launcher_state` is handed a `plugin_root` and its content comparison
  honours it -- that is #329's whole design, deciding by bytes rather than by path
  shape -- but its version label read `plugin_version()`, a global that opens the
  running install's own manifest. Where the two diverge the SKEW warning named a
  version describing one tree beside a byte comparison performed against another, in
  the receipt the check exists to produce. The label now comes from a new
  `_manifest_version(plugin_root)`, which answers in three states -- `read`,
  `no-version-field`, `unreadable` -- and returns no version for the last two rather
  than the words `unknown` or `unreadable` standing where a version goes; the warning
  gained a clause of its own for that, symmetric with the one `their_version` has had
  since #289. `plugin_version()` keeps its signature: surveyed, its only other caller
  is the `oss plugin version` header line, which is a claim about the install the
  reader invoked and would be wrong sourced from anywhere else. It now delegates, and
  a non-object JSON manifest is `unreadable` instead of an `AttributeError` raised out
  of the one function whose contract is that its line prints when everything else has
  failed (#350).

- The assertion over that label was `ours_version == "0.6.0"`, which passed only
  because the repository was at `0.6.0` -- so it went red on the release commit that
  bumped the manifest, after the fold had already emptied `changelog.d/`, and it took
  `v0.7.0` with it. `tests/test_no_test_pins_the_current_version_350.py` now refuses
  any string literal under `tests/` that exactly equals the version
  `.claude-plugin/plugin.json` currently declares. Docstrings and comments are
  excluded, because narrative about a past release is legitimate and permanent;
  equality is exact, so an old version in a cache-path fixture stays fine; and
  deliberate exceptions live in a named list with a reason each, checked for staleness.
  Run against the pre-fix file it names five lines and it is silent on the file whose
  docstring discusses the 0.6.0 gate (#350).

## [0.6.0] - 2026-08-19

### Added

- The `01-oss` tools layer now ships a `00-README.md` recording why nothing in it is keyed on
  the `Agent` tool. A rule firing on agent dispatch was asked for so that a brief's standing
  clauses arrive at the moment they change behaviour rather than being re-typed from memory
  (#144). It could not be built at the time: the PreToolUse hook built the subject its tool
  rules match against from `command`, `skill`, `file_path` and `pattern` only, and an `Agent`
  payload carries `subagent_type`, `description` and `prompt` — so the subject was empty and the
  hook returned before the layer loop. A `tool: Agent` row would index cleanly, diagnose healthy
  and never fire, which is the defect this plugin is named after. **That blocker is gone as of
  `claude-jit-context` 0.5.0 and the record now says so** — see #307 below; it is written in the
  past tense here because both changes land in the same release. The layer enumeration that #119
  reported is genuinely fixed; this is a second blocker underneath it that neither issue knew
  about. The record ships into every managed repo rather than living in the tracker, and a
  test drives the installed hook with a `Bash` control beside the `Agent` payload so the day
  the dependency starts reading one, the suite fails and says the record has gone stale. That
  tripwire fired, and #307 below is what it caught — so it no longer exists as described here:
  the test was inverted to assert the capability rather than the gap.

- `docs/autonomy.md` records the gap between the loop as it is and "autonomous in somebody else's
  repository", and is deliberately a record rather than a design: it answers none of the four
  questions #237 raises, because each is a decision about a repository this project does not own
  (#237).
- The document's one factual claim is derived rather than asserted.
  `tests/test_unattended_triggers_237.py` reads the `on:` block of every workflow this repository
  runs and of every workflow in `scaffold.OWNED` -- the files written into a repository that
  installs the plugin -- and confirms each fires on `push` or `pull_request` and nothing fires on a
  clock or a remote dispatch. Prose asserting the tree plus a test asserting the prose would state
  one claim twice and pass whenever both were wrong together, so the test measures the tree and the
  document says what the measurement found (#237).
- The first version of that sentence read "nothing an install puts in your repository runs on its
  own", and was wrong: `/oss:scaffold` seeds a `.github/dependabot.yml` carrying a weekly
  `schedule:`. It was invisible to the sweep because the sweep read workflows and that file is not
  one -- a scope that excluded the only case able to contradict the claim, which is the sweep
  reporting the answer it was scoped to give. Both the document and the README now name it, and it
  has two checks of its own: that it is still seeded with a schedule, and that it is still a
  *default* rather than an owned file, because "yours to delete and never handed back" is the whole
  of what the document claims about consent (#237).
- The sweep fails three ways, and the third is the reason it exists: an unattended trigger appears,
  a workflow declares no human trigger either, or a workflow's trigger block cannot be read at all.
  `on: [push]` in the one-line list form is reported as unreadable rather than as empty, which is a
  known limit pinned by its own test so it stays a decision. The detector is proved capable of
  failing against a planted `on: schedule:` workflow rather than assumed to be (#237).
- `README.md` now tells an installer, in the Status section, that nothing this plugin puts in their
  repository runs on its own: the only executable file installed is a changelog gate that fires on a
  pull request, and nothing schedules a tick, a re-scaffold or an update of an owned file. A
  repository that installed the plugin and was never ticked again looks from outside exactly like a
  healthy one (#237).
- The measured reach numbers are deliberately not restated in the new document. `CLAUDE.md`'s
  `## What is not proven yet` holds them and is re-derived at each release; a second copy is the one
  that drifts (#237).

- Every `plugin copy scope` line, in all three of its states, ends by saying what it does **not**
  cover: *this is one command's copy -- nothing here says which copy answered any other command or
  skill in this session.* A command's text is resolved once, at invocation, and stays in the turn
  for its whole length; `/reload-plugins` moves the registry and does not move text already
  injected, so a session can hold a registry at one version and instructions from another. A line
  that reported the copy behind one command as though it spoke for the session would be the same
  defect one layer up, wearing a receipt (#248).
- `commands/doctor.md` says what to do with a `SKEW`, which is the half that reaches the tracker:
  nothing in the repo is broken by one, but any plugin prose quoted from the running session may be
  text the clone no longer contains -- which is how #240 came to be filed against a sentence removed
  a release earlier, correctly shaped and publicly wrong. Quote from the clone at a named sha before
  filing anything about this plugin's own documents (#248).
- No second mechanism was built for this issue, and that is a decision rather than an omission. The
  narrow fail-closed option the issue offers -- refuse to file against prose the clone does not
  contain -- is unreachable from a script: the filing happens inside an agent turn, from text
  already in context, and nothing on disk sees the quotation. The remaining half is prose in the
  filing step of `skills/manager/SKILL.md`, which this change does not touch (#248).

- `doctor` reports **which copy of this plugin answered the invocation**, and compares it to the
  checkout being diagnosed by content rather than by version. The detector everybody reaches for
  first cannot work: the manifest version does not move between releases, so an installed copy at
  the tag and a clone a whole cycle past it declare the same number and *do the versions agree*
  answers `yes` in the healthy case and the skewed one alike. Measured 2026-08-16 -- the same agent
  report validated `ok` against one copy and `schema_version: expected 1, got 2` against the other,
  both declaring `0.5.0` (#262).
- Two lines, not one, because they answer two questions and merging them would let the second vouch
  for the first. `plugin copy scope` says what this invocation *established* -- the flag or
  environment variable that named the root, a named root that is not the file that actually ran, or
  nothing at all, which is the ordinary state of a hand-run script and is reported as a gap in the
  measurement rather than as a fault in the repo. `plugin copy` says what the comparison *found*:
  identical, `SKEW` with the differing files named, the diagnosed repo not being a checkout of this
  plugin at all, a manifest that would not read or parse, or a walk that could not enter part of a
  tree. Six states, and four of them are ways of not knowing (#262).
- It reports and does not refuse, deliberately. A skew is the **normal** state for the whole window
  between a merge and a release, so a check that declined to run there would be switched off inside
  a week; what it buys instead is that a stale filing, a report an older schema refuses and a
  procedure step that silently is not there stop being unrelated puzzles (#262).
- `/oss:doctor` now passes `--plugin-root "${CLAUDE_PLUGIN_ROOT}"`, which is not redundant with the
  path already in front of it: the launcher resolves the script either way, and the flag is the
  *invocation* stating which copy it resolved -- a fact no script can observe about itself. Without
  it the scope line reports that nothing established which copy answered, rather than letting the
  script's own location speak for the harness (#262).
- A path unreadable on one side is **unknown, not different**. It is absent from that side's map,
  so a plain symmetric difference scored it as a file present on one side only and reported two
  byte-identical trees as a `SKEW` -- the loud-but-wrong answer, inside the check written to avoid
  exactly that, and found by this branch's own review rather than by the suite, because the test
  named for the case asserted only things the wrong branch also satisfies. Blocked keys are
  subtracted from the comparison by prefix, since the walk's error handler names the *directory* it
  could not enter and the files beneath it exist on the other side under their own keys (#262).
- A compared directory that is a symlink is declined rather than followed. `os.walk` refuses
  symlinked *sub*directories and always traverses the top it was given, so a tracked `scripts -> /`
  would have been an unbounded read inside a diagnostic contracted to always finish and print one
  VERDICT line (#262).
- `python3 scripts/doctor.py` run by hand now warns once more than it did: nothing names a plugin
  root there, so `plugin copy scope` reports that it could not establish which copy answered. That
  is the third state doing its job and not a fault in the repo, but it does move the bare-run
  warning floor by one, and `/oss:doctor` -- which passes the flag -- is unaffected (#262).
- The comparison folds CRLF to LF before hashing and keys files by relative POSIX path, so a
  checkout with `autocrlf` on and an installer's unpacked copy do not read as differing in every
  file, and the two sides compare equal on Windows. The cost is stated rather than hidden: a
  difference that is *only* line endings is invisible here. The walk is `os.walk(onerror=...)`,
  because `Path.rglob` swallows `PermissionError` and yields less, which would have returned "the
  trees match" for "could not read the tree" (#262).

- `bin/oss-workspace` now runs the setup diagnostic over the repo it just resolved, before the
  session starts working, so a broken setup surfaces at second zero rather than after a tick has been
  spent against it. The **verdict line is parsed and the exit status is never branched on for the
  repo's health**: `scripts/doctor.py` exits `0` always, by contract, so `doctor.sh || warn` is a
  check that can never fire — it reads a pass on `VERDICT: not usable -- 4 failure(s)` exactly as
  loudly as on `VERDICT: ok`. Six answers are told apart and none may collapse into another: `ok`
  costs one line, `usable with gaps` and `not usable` relay the diagnostic's whole output, `could not
  run` says the repo's state is unknown rather than fine, a verdict word this launcher does not
  recognise says so instead of falling through the `case` in silence, and **no verdict line at all**
  splits by the exit status into *it ran and never reached its own report* and *it could not be
  started* — the pair a naive implementation gets wrong, because a script that printed nothing and a
  script that printed `ok` are the same empty grep. `--root` is passed at the path already resolved:
  invoked without it the diagnostic prints `WARN project dir guessed from cwd` and downgrades an
  otherwise-`ok` tree, which is a warning manufactured by the invocation rather than a fact about the
  repository. It **never refuses to open** — a maintainer whose config is broken is exactly the person
  who needs a session in which to fix it — which makes this the fourth arm of the shape the watch-name
  gate already had rather than a new pattern. Measured on macOS with `supertool`, `gh` and node on
  PATH, the launcher opens in 0.45 s without the check and 2.5 s with it, so
  `OSS_WORKSPACE_SKIP_DOCTOR=1` skips it and the skip is announced with the repo's state reported as
  unknown. The diagnostic is invoked as `bash <path>` and that is measured, not stylistic:
  `scripts/doctor.sh` is tracked mode `644`, so executing it directly dies with `Permission denied` —
  the first cut of this did exactly that, was green against a fixture whose stub carried the execute
  bit, and reported `COULD NOT BE STARTED` on every real launch. The run is announced *before* it
  starts and carries the skip variable's name, because the diagnostic's network probe is bounded at
  25 s per declared dependency and 20 s per probed binary — offline, the wait is longer than the
  measured 2.5 s, and an escape hatch first mentioned in the line that prints after the wait is one
  nobody waiting has (#269).

### Changed

- Re-derived `CLAUDE.md`'s "What is not proven yet" section against `e8e75b2`, the commit `v0.5.0`
  tags, after the fold rather than before it — the first re-derivation to name the release it ships
  with. Records the currency guard's first real failure, the diagnostic's tree-dependent verdict, and
  the plugin-version skew narrowing from a whole release to a single command's resolution (#235).
- The marker's own derivation now uses `git rev-list --count`, not `git log --oneline | wc -l`: the
  latter is rewritten through a proxy that emits a bare newline for an empty result, so a range of
  zero commits counted as one (#236).

- The manager skill's op table now carries the rule the `gh-pr-edit` fix (#195) did not land: a
  sentence saying no op exists is a claim about a dependency's inventory that was true only when it
  was written, and `supertool 'ops'` settles it in one call. The two directions are argued rather
  than assumed — a named op that has since been removed fails at the call and writes nothing, while
  a stale "no op exists" routes the reader to a raw call that runs, with no closing-reference check
  and no read-back. So ops stay named, and the negative is what needs a probe (#240).
- `tests/test_manager_op_inventory_claims.py` fails the manager skill on either shape of the #195
  defect — an op asserted absent, or a fenced block making a raw call an op in the same document
  supersedes. Both are "must not fire" checks over a corpus that is legitimately empty, so both are
  paired with a positive control built from the literal pre-#195 text; the negative matcher runs on
  whitespace-collapsed text because the sentence that rotted straddled a line break (#240).
- The negative matcher's surface forms are enumerated rather than guessed, in both directions. Its
  first draft caught two of seven ways to write "supertool has no such op" and fired on `dry-run`,
  a hyphenated term that is not an op at all — so seven must-fire forms and four must-not-fire ones
  are pinned as controls, and the op token is scoped to the `gh-` shape the same file's extractor
  accepts. The fence matcher no longer anchors at column 0, which read an indented fence as absent
  rather than as unindented (#240).

- A review finding can no longer be dispositioned `filed`. The word was past tense and read as a
  completed action, while it meant *left for the maintainer to file* — twice in one day it meant
  nobody filed it. `report-for-filing` replaces it, which is the word `adjacent.action` already used
  for the same act, and it now requires a `reason`: the argument for not fixing it in this diff is
  what the maintainer needs before they can open anything. No value for a completed filing is added,
  because an agent cannot file — opening an issue is publishing and the publishing clause is
  unconditional. Compatibility: breaking — a report carrying `filed` is refused, and the report
  contract number moved to 3 so an older validator reads such a report as unvalidatable rather than
  as malformed (#254).

- The developer brief now says where a defect in the tooling goes when the loop is running as a guest
  in a project the tooling does not own: to the tooling's own board, never to the host project's,
  whose maintainer cannot patch it and cannot see it declared anywhere. The reverse is stated with
  equal weight -- the host project's own code stays theirs, and the split is who owns the code rather
  than who is standing closest to it (#290).
- That board is derived rather than inferred. Nothing declares itself as its own dependency, so the
  loop's own repository is the one name the dependency derivation cannot produce; the brief names
  `loop_repository()` and the diagnostic line that prints it, and deliberately does not restate what
  it can answer -- a second copy of an accessor's states in a document nobody diffs against it is a
  fact with two homes and one proofreader (#290, #292).
- The maintainer skill's filing section gains the arm that receives such an item. Its bound was
  declared dependencies and its `could not file` outcome covers a destination the derivation did not
  produce -- so an already-resolved tooling board would have been recorded as no tracker, which is
  the collapse that table exists to prevent, one function over (#290).

### Removed

- `scripts/coverage_gate.py` is deleted. It was a verbatim copy of another project's coverage
  gate, wired into no workflow here, and every verdict in it was about that project: its
  enforced floors named paths this repository does not have, and its "measured, not enforced"
  reason for `scripts/` described that project's git-push helpers while this repository's whole
  product lives in ours. Asked to classify `scripts/doctor.py` it answered `measured` — no floor,
  and here is the good reason — with a sentence about somebody else's repository (#253).
- The sentence the issue filed turned out not to be the defect. `bash -n` on "all twelve pytest
  legs", cited to `tests/test_ci_non_python_coverage_557.py`, is **true upstream**: that test
  exists there and that project's matrix really is 3 OS x 4 Python versions. Nothing was wrong
  with the claim, so nothing was filed upstream; what was wrong was a file with no job sitting in
  a directory readers trust (#253).
- Compatibility: compatible - nothing executed the file. The only things that named it were the
  `[tool.coverage.run]` comment and `omit` entry that excluded it from measurement, both of which
  go with it, and a historical `CHANGELOG.md` entry recording that it was vendored, which stays
  where it is because that history is true (#253).
- `tests/test_unwired_scripts_253.py` now fails on any tracked file under `scripts/` or `bin/` that
  no other tracked file references. It deliberately does not use the predicate the issue proposed --
  "a cited test path missing from this tree" fires on all six of the deleted file's citations, every
  one of them correct in its home repository, so it flags faithful vendoring rather than false
  claims (#253).
- Three kinds of mention deliberately do not count as a reference, because each would let a file
  justify its own existence: the `[tool.coverage.run]` table, which is a statement that a file is
  *not* measured; narrative sources -- `CHANGELOG.md`, `CLAUDE.md`, `changelog.d/` fragments and the
  checking module itself -- which name a file in order to record something about it, so that a
  deletion would otherwise immunise the very file it removed; and another directory's file that
  merely shares a basename. The `changelog.d/` case is the one with teeth: fragments are deleted at
  the fold, so counting them would make a script wired today and unwired the moment a release is
  cut, reddening a release branch over nothing in its own diff (#253).
- The survey covers every tracked file under those directories with **no extension test**. Selecting
  by suffix is the shape of #193 one directory over -- `bin/oss-workspace` is tracked, POSIX `sh`
  and extensionless, and a suffix filter skips it silently rather than reporting it as unknown
  (#253).

### Fixed

- `/oss:doctor` counted a layer's `00-README.md` as a rule, so the first layer to document
  itself reported one more rule than it has — in all three arms of the check, including a
  FAIL that would have named a rule the layer does not contain, and beside a drift
  comparison in the same function that had already filtered the same file out. Nothing
  showed it while no layer carried a record (#144).
- `/oss:doctor`'s jit-layer verdict rendered its dimension count as a rule count, reporting
  "3 rule(s)" about a layer holding four. Every other fixture had one entry per dimension,
  so the two numbers were equal everywhere the suite looked (#144).
- `CLAUDE.md` stated in bold that the `01-oss` rule layer was inert and that nothing in this
  repository could change that. The dependency fixed the layer enumeration in 0.4.0 and the
  layer has been live since; the note now says so and names the command that re-derives it
  rather than asking anyone to trust either version of the sentence (#144).

- The shell CI leg scoped `bash -n` and `shellcheck` with `git ls-files '*.sh'`, which returns one
  path in this repository. `bin/oss-workspace` — the plugin's user-facing entry point, tracked and
  POSIX `sh` — has no extension, so neither guard had ever read it on any leg, on any platform, in
  any release, and the leg was green throughout: a lint that ran and found nothing and a lint that
  never received the file both exit 0 (#193).
- The file list is now derived by `scripts/shell_sources.py`, by extension **or** by shebang, so a
  script added without an extension is covered by the commit that adds it rather than by somebody
  remembering to name it in the workflow. Naming the file beside the glob would have been the
  one-line fix and a fact about this repository living outside `.oss.json` (#193).
- That enumerator answers in three exit codes rather than two: `0` with the list, `2` when it
  matched nothing, `3` when a tracked file could not be read. Both refusals matter — `shellcheck`
  with no arguments exits 0, so a selection that silently matched nothing would reintroduce the same
  bug one narrowing later, and a file whose first line could not be read is not a file without a
  shebang (#193).
- First lint of `bin/oss-workspace`: clean at every shellcheck severity, so the fix ships no
  behaviour change to the launcher. That is the measurement the leg could not previously make (#193).

- `doctor` no longer reports a `.supertool.json` it read perfectly as one it could not read. `[]` is
  valid JSON: the read succeeded, the parse succeeded, and only the document's shape is wrong -- but
  both the `watch channel` and the `radar board` lines answered *".supertool.json is there and could
  not be read"*, which sends a maintainer to file permissions, a lock or an encoding when the remedy
  is to fix the document. `scaffold.check_radar` already answered that shape `malformed`; the fix went
  to `doctor`, which was the one that was wrong. This is the plugin's own defect class in the
  direction that gets forgotten -- not an absence rendered as a pass, but one failure state rendered
  as a different one, where the two send the reader somewhere different (#216).
- The same fix, one caller over from the row the issue tabulated. `{"ops": "nope"}` also read and
  parsed perfectly, and the `watch channel` line called it unreadable too -- under a comment three
  lines above it that had said absent and malformed were two answers since it was written. Both
  states now carry the sentence their shape earned, and `watch channel` gains a `malformed` arm of its
  own rather than falling through to the `default` line, which would have told a repo with a broken
  file that it declares nothing (#216).
- A third instance, found by this branch's own audit and fixed in the same lane: `.oss.json` was read
  the same way. `_derivable_watch_name` folded a parsed-but-wrong-shape config into `unreadable` too,
  and its sentence reaches the reader through the same `watch channel` line -- so before this, a
  `doctor` run could report the `.supertool.json` shape correctly and the `.oss.json` shape wrongly on
  one screen. It gains a seventh state and both reason dictionaries that render it gain the key.
  `bin/oss-workspace` needed no change: the cross-check that holds doctor's copy of the derivation
  rule against the launcher's own program only ever required the launcher to print no name here, and
  it still prints none (#216).
- Three states in the shared reader, not four. "It parsed and the key we wanted is absent" was
  considered and declined: the two callers want different keys, and each already names that absence in
  its own vocabulary -- `no-tiers` for the board, `default` and `declared-only` for the channel -- so a
  fourth state in the helper would have to know which key its caller wanted and would answer for
  whoever did not ask (#216).

- `schema_version` in the agent report schema was `const: 1` in every copy ever shipped, across at
  least three contracts that refuse each other's reports — so the field that exists to distinguish
  versions could not record one, and #212's remedy of having a validator announce its schema would
  have printed `1` from both copies and confirmed the skew rather than revealed it. The schema now
  declares `x-schema-version` and the report's `schema_version` is typed but unconstrained; `1` is
  left meaning "written before anyone counted" and `2` is the first value that carries information
  (#221).
- `scripts/report_schema.py` decides the version in three states rather than two. A report naming a
  contract this copy does not hold — newer or older, or a schema that declares no version at all —
  is `UNVALIDATABLE`, exit `2`, not `INVALID`. A copy holds exactly one contract and cannot compute
  its relationship to another version's, so both directions are the same epistemic state. The shape
  pass still runs and its findings are printed under a sentence saying which contract they answer,
  because declining to look would be the same defect one layer along. Every verdict row now names
  the contract it was decided against, on the pass as well as on the failure (#221).
- A recorded fingerprint of the schema's *enforcing* content — prose stripped, so rewording a
  description demands nothing — fails the suite when the contract moves without the number, and
  fails louder when the number moves to a value nothing recorded. A hash guard whose natural failure
  mode is "no record, nothing to compare" passes hardest at the one moment it is worth anything
  (#221).
- `agents/developer.md` teaches the third verdict. Its single-copy branch said "findings mean the
  report is wrong, fix the report", under which `UNVALIDATABLE` reads as an instruction to edit a
  correct report until an obsolete contract accepts it — the exact failure that section exists to
  prevent. Worth knowing while it lasts: the installed `0.5.0` cache still carries `const: 1`, so it
  answers `INVALID … schema_version: expected 1, got 2` on every report written against the new
  contract until a newer plugin is installed. That is the same fact in an older spelling, and the
  brief now says so (#221).

- `oss_state.py` computed and printed the intake summary before it validated the entry, so a refused
  write reached the caller as a well-formed metric line with the `FAIL` underneath it. One tick
  filtered the output for that line, read it as a record that had landed, and lost its entry — the
  loss surfaced a tick later, from an entry count. The line is a receipt now and it is only printed
  once the entry is on disk; a refusal prints the `FAIL` first and a `NOT RECORDED` line under it
  carrying the pair that went nowhere, which is deliberately a different string from the `RECORDED`
  receipt so a filter that catches one cannot catch the other. The `--trend` line is labelled
  `TREND`, because it is a computation over an existing history and stores nothing (#222).
- A write that fails is now a `FAIL` line rather than a traceback. Validation passing and the write
  then failing was a third case with no arm at all: `append` let the `OSError` past the CLI's one
  handler, so the run printed the success-shaped intake line and then a stack trace, with no `FAIL`
  for a caller to watch for (#222).
- The ordering is enforced by a flush, not by the order of the two `print` calls. stdout is
  block-buffered the moment it is a pipe and stderr is not, so a `FAIL` printed first still surfaced
  second under `2>&1` — which is how a transcript is read. `capsys` keeps the streams apart and
  cannot see it, so the test drives a real subprocess with the two merged (#222).
- A malformed `--detail` in the same run as the counts refused while the pair had not been built
  yet, so the pair was dropped with nothing said about it — the same defect one branch over. The
  record is built before `--detail` is parsed (#222).
- A `FAIL` line can carry a path, and a path can carry a character the console's codepage cannot
  hold — stdout's error handler is `strict` where stderr's is `backslashreplace` — so the one line
  this issue exists to guarantee raised at its own `print` and never arrived. It did not even crash
  loudly: `UnicodeEncodeError` is a `ValueError`, so it landed in the `--detail` handler and came
  out as `FAIL --detail is not valid JSON` on a run passing no `--detail`. Every human-readable line
  goes through a writer that cannot die on the codepage, and the JSON handler is narrowed to
  `json.JSONDecodeError` so no unrelated `ValueError` can be confidently misattributed again.
  Reproduced with `PYTHONIOENCODING=ascii`, so it is observed rather than reasoned (#222).
- `append` writes atomically — a sibling temp file renamed over the history, as `migrate` already
  did. A plain rewrite truncates at `open`, so a failure after that point left a half-file where a
  history was, and the new failure arm's claim that the history is unchanged would have been hopeful
  rather than true. Compatibility: the rename needs the state file's *directory* to be writable
  where the in-place rewrite needed only the file, so a state file inside a directory the caller
  cannot write is now a loud refusal instead of a write that risks the history (#222).

- The release command no longer claims the compatibility bullet is documented in a fragments README
  it cannot see. It was true of this repository's copy and false of the file `/oss:scaffold` writes,
  and that README is a *default* under the ownership contract — created once, then the repository's
  own file forever — so shared prose can neither know what it says nor fix it. The path was a
  per-repo fact besides: the directory is `changelog_dir`, not a name a shared document is entitled
  to spell. `commands/release.md` now writes the bullet out at the point of use and says an older
  scaffolded repository may not document it at all, and the scaffold template gains a Compatibility
  section of its own, so newly scaffolded repositories get it.
  Nobody was stranded meanwhile: `release_version.py`'s own refusal quotes the bullet in full (#225).

- Gate 1 is stated in three states, matching the op that answers it. `gh-branch` separates a
  workflow that **could not have run on this commit** — its triggers do not include the event that
  produced it — from one that **should have run and did not**; the gate had room only for the
  second, so a `pull_request`-only workflow either blocked every release the repository would ever
  cut or was waved through, taking the blocking state with it. The middle state is now named: not a
  pass, not a blocker, and contributing no coverage, so a commit where every declared workflow lands
  there is uncovered rather than green. The release report has to name it and say where its coverage
  did come from, and the verdict is re-read from the op each release rather than remembered — an
  `on:` block can change, and a remembered verdict then waves through the one case the gate exists
  for. `skills/manager/SKILL.md` carries the same three states, at the release gate and at the
  post-merge branch check, where the middle state is routinely misread as a red default branch
  (#229).

- `bin/oss-workspace` validated the **derived** watch channel name and exported the **declared** one
  verbatim — a guard and its bypass in one file. `.supertool.json` is tracked, so a declared
  `watch_name` arrives by ordinary contribution exactly the way `repo` does; measured before the fix,
  `../../../tmp/pwned` was exported as `../../../tmp/pwned` and a name carrying a newline was exported
  carrying it, while the sibling route three lines below refused the same value in as many words. The
  fix is not to run the declared name through the derived route's function — that one takes an
  `owner/name` slug and folds it, and a declared name is not a slug. Both roads produce a value of the
  same kind, so `oss_config.watch_name_problem` is now the single statement of what a watch channel
  name may be and the launcher calls it **once, after the two roads converge**. A bypass is a road
  that does not reach the gate, and there is no longer another road. What it refuses is deliberately
  narrow: only what this plugin can argue without knowing anything about supertool — a value that is
  not usable as a path component, because the consumer renders the name into a socket path and a
  poller state directory. It does **not** apply the consumer's own `NAME_RE`, which caps the length
  and constrains the first character: a copy of somebody else's rule drifts, and refusing on a cap
  would take a working private channel away from a repository whose consumer accepts the name. That
  question is asked and reported instead. Refusing, being unable to check, and having no python are
  three arms of the shape this script already had — export nothing, say so on stderr, open the session
  anyway. The receipt names the socket the session actually lands on rather than assuming: an already
  exported `SUPERTOOL_WATCH_NAME` wins over both roads, so a refusal there costs nothing and the
  session stays on that channel, where the first draft of this said *SHARED DEFAULT socket* and was
  read, believed and wrong. The comment in `scripts/oss_config.py` claiming the derivation was *the one consumer of
  `repo` that did not route through the guard* is corrected: it was read as a claim that the launcher
  had no other unguarded route, and that was false when it was written (#230).

- `bin/oss-workspace` now **asks the installed supertool** whether it will accept the watch channel
  name, and reports the answer in three states. The derivation folds `owner/name` into `owner-name`
  with no length constraint, and nothing in this plugin knew the consumer's own rule — measured
  against this organisation's real slugs on 2026-08-16 against supertool 0.46.0, and re-measured in
  this branch: `Digital-Process-Tools/claude-oss` derives a 32-character name accepted **exactly at
  the cap**, while `claude-supertool` (38) and `claude-jit-context` (40) derive names the consumer
  discards, falling back to the shared default socket — the state #191 exists to eliminate — while the
  launcher's own output implied a private channel. Two of the three repositories this plugin runs on
  were in that state, and this one works by one character, which is why nobody saw it. The rule is
  **read out of the installed `presets/watch/naming.py` at run time** rather than transcribed:
  a copy would drift, and refusing on a cap this repository carried would take a working channel away
  from a repo whose installed consumer accepts the name. Accepted is silent, because a line printed on
  every healthy launch is furniture and furniture is how the line that matters stops being read;
  rejected prints the name, its length and the rule, because *too long* without a number is
  unactionable; and **could not ask** — no `naming.py` under any install, a module that will not load,
  a `NAME_RE` that is gone — prints just as loudly, because silence there is indistinguishable from
  acceptance. With no supertool installed at all there is nothing new to say: the consumer block
  already reports that with its own remedy. The name is still exported in every case; the harm this
  fixes is the silence, not the export (#231).

- `doctor`'s `jit rule layer` check scanned every `*.sh` under the dependency's install root, so it
  was answered by that plugin's own test harness: `tests/test-layer-enumeration.sh` carries a quoted
  layer list naming `01-oss` inside a fixture, and the string is invariant under the upstream fix. A
  fabricated tree with the old broken fixed list still in the hooks printed `reads` all the same. The
  scan is now the hook set — the scripts `hooks/hooks.json` declares, plus the closure of what they
  `source` — and a layer list found only outside that set is reported as the reason the check
  `could not be determined`, rather than dropped or accepted. A missing hook manifest is a non-answer
  too, since without one nothing separates a hook from a fixture (#241).
- Three narrower states in the same check, each of which used to be reported as something it was
  not. A `hooks` path a plugin declares and this cannot resolve no longer falls back to the
  conventional location, because reading a file the plugin did not name is the same substitution one
  field over -- and where a conventional manifest happened to sit there, the fallback produced a
  confident `reads`. A manifest that will not parse now says so instead of sharing "named nothing
  this could resolve to a file" with one that parses to `{}`. And the scan of the rest of the
  install tree walks with `os.walk(onerror=...)`: `Path.rglob` swallows `PermissionError` and yields
  nothing for that subtree, so a tree that could not be read reported as a tree with nothing in it
  (#241).

- The tick healed the radar board once, at the top, so every pull request the tick itself opened was
  unwatched for its whole CI run — radar has no discovery feed (`discovery: radar ticks only`), so a
  heal only ever arms pollers for what was open at the moment it ran. `commands/tick.md` now heals
  after the pull request is opened, and states the governing condition as *board membership changed*
  rather than as a list of places to heal: a list is one entry long until somebody adds a step, and
  the red-default-branch case has no poller to heal at all, so no list could have covered it (#242).
- A tick no longer ends while the board reports a gap. `What ends a tick` reads radar's own rendered
  tokens in three states — covered, a row marked `[unwatched]`, and `watch coverage UNKNOWN` — so the
  membership rule is anchored by a measurement at the end rather than by a reminder at the top, and a
  step added later cannot escape it (#242).

- A tick that idled on a momentarily quiet board closed on the same line as one that had genuinely
  finished, so the loop handed back to the maintainer and called it done (#244). Both the manager
  skill and `/oss:tick` now require the tick to name which of three states it ended in: work
  started, blocked with every remaining item named individually, or nothing left. Only the last is
  an end, *somebody else's work* is stated never to mean the loop's own backlog, and a release is
  named as a step in that list rather than an exit from it.
- The third state is sourced rather than asserted: "nothing left" requires `gh-issues` and `gh-prs`
  to have answered and come back empty. A board that could not be read is `unknown` and is not an
  ending -- otherwise a loop that stopped because it did not look renders exactly like one that
  stopped because there was nothing to do.

- The manager skill's op table was introduced by a heading reading "Reads go through supertool.
  Writes go through `gh`", while four rows of the table directly beneath it routed writes through
  supertool -- filing, opening a pull request, correcting a published body and merging (#247). The
  heading no longer names a taxonomy at all: it defers to the rows, because a class-level claim in
  a heading is a second and coarser copy of what the table already answers one row at a time, and
  the copy that drifts is the one that gets skimmed and quoted. `tests/test_content_invariants.py`
  now fails on a heading that routes a class, with the pre-#247 heading and table as its control.

- The developer brief and the manager skill's brief template named `supertool 'edit:@-'` as the way
  to write a file and named no op that can create one. `edit` takes an `old` and a file that does not
  exist has none, so the one write every task in this repository is required to perform — the
  changelog fragment, always a new file — had no documented route, and agents fell back to a raw
  heredoc that runs no post-write validator, cannot roll back and reports nothing about what it
  wrote. Both documents now name `supertool 'paste:@-'` with `path` and `content` beside `edit`, and
  say which is for which (#250).
- Naming the op was chosen over pointing at the shipped rule layer that already documents `paste`,
  and the reason is measured rather than inherited from #240: that rule is gated on
  `Read|Edit|Write|Glob|Grep`, so a Bash heredoc never fires it. The pointer is unreachable for
  exactly the failure it would have to catch, and unlike a renamed op — which fails at the call — an
  omitted one fails nowhere, because the heredoc succeeds (#250).
- The paragraph stays in two documents on purpose: a brief pasted into a message has to be
  self-contained for an agent that never loads `agents/developer.md`. `tests/test_content_invariants.py`
  is where the fact now lives once and fails when either copy stops naming a creating op. The check
  reads op invocations off a copy with blockquote markers stripped and whitespace collapsed, so
  neither a wrap between `supertool` and its quoted argument nor a wrap inside a blockquote can turn
  the assertion into a silent pass — both are pinned by must-fire/must-not-fire pairs in the same
  fixture, and the blockquote one was found by the check firing on correct prose rather than
  reasoned about afterwards (#250).

- Every agent definition granted `Bash` now says that the grant is **total**, and says it as advice
  rather than as a boundary. `agents/auditor.md` summarised itself as *annotates, never blocks* — a
  claim about its output — and it was read as a claim about its effects: an audit spawn ran an acting
  supertool op against the live watch channel of the session that had dispatched it, mid-audit, on a
  change about that fleet's own state. Nothing in the frontmatter, the harness or the prose
  distinguished a read from a write, because every write in this system goes through `Bash`. The same
  hole made `agents/triager.md`'s withheld `Edit`/`Write` real for the harness tools and empty for the
  route actually used, and `CLAUDE.md` said so as a virtue — *prose is a request, frontmatter is the
  boundary* — which is true of tools and false of effects (#251).
- The advisories point at supertool's own published op classification (`ops:roster` — unmarked,
  `*`, `!`) instead of listing acting ops. A per-agent allow-list would have been a second copy of a
  classification the dependency already publishes, and the copy is the one that goes stale; the
  enforceable half is upstream, in the tool that owns the classification, not here (#251).
- `tests/test_agent_grant_is_total.py` holds the shape in three layers, and holds only the shape: the
  advisory is present, it carries the words `advice, not a boundary`, and it cites the authority —
  measured in CI, which has no supertool — plus a roster layer that fails if the `*`/`!` marks the
  advice names stop being the ones the tool declares, or if an advisory grows into an enumeration.
  Where `supertool` is absent that layer skips naming what went unmeasured, rather than passing
  quietly. What no test in here can hold is the behaviour: there is no read-only `Bash` to grant
  (#251).

- `doctor`'s `jit rule layer` check split a dependency's declared hook-manifest path on
  `os.sep` — the separator of the platform *running* the check — while its docstring said it
  split on the platform that wrote it. A `hooks` value authored with backslashes therefore
  resolved only when the check happened to run on Windows; on the eight POSIX legs the same
  declaration failed to find a file that was really there and reported `could-not-determine`
  blaming a missing manifest. The state was honest and the reason was wrong (#258).
- The separator is now `/` on every platform, so the answer is a property of the declaration
  rather than of the runner. A backslash-bearing value is **refused with a named reason**
  rather than split: on POSIX a backslash is a legal filename character, so treating it as a
  separator reads a file the manifest did not name whenever the guess is wrong — which would
  turn an honest non-answer into a confident one. Nothing here can tell the two intentions
  apart and there is no authority to transcribe saying which the runtime accepts, so the value
  goes to the third state carrying its reason. A plugin that wants to be read writes `/` (#258).
- Every refusal `_jit_path_parts` makes now returns why, and the caller prints it beside the
  value as the plugin wrote it. The value alone left the backslash case looking like a typo in
  a filename; the rule alone would name a policy without the value it was applied to (#258).
- Nothing in the 13-leg matrix exercised a backslash-bearing manifest value at all. Both new
  tests run under an injected `os.sep`, in both directions, with the accepting half in the same
  fixture — so a resolver that refused everything fails rather than passes, and the injection is
  asserted to have taken before anything is measured (#258).

- The developer brief required its report, note and pull request payload to be written outside every
  worktree and required every write to go through supertool, which refuses a path outside the current
  working directory — so an agent doing exactly what both halves said was refused on the one write
  the brief guaranteed, at the cost of a re-sent payload. Both the brief and the passage the manager
  skill pastes into briefs now name the refusal and the remedy: run the write from the worktree root.
  Neither points at the env var or the `allow_outside_cwd` key the refusal offers, because both widen
  every op for the rest of the session to buy one write (#266).

- Nine refusal receipts in `bin/oss-workspace` told the reader the session was on the **shared default
  socket** while it was demonstrably on a private one. An already-exported `SUPERTOOL_WATCH_NAME` wins
  over both the declared and the derived road, so a refusal costs nothing and the session stays on that
  channel — and the wrong half took the true half with it, because refusing blanks the name and the
  pre-existing *an export wins* line only fires while that name is non-empty. `7b2841c` fixed one arm by
  computing the sentence from the winning export; the rest stated it independently, which is exactly why
  one got fixed and the others did not. The sentence is now computed **once**, in the shell, and handed
  to every arm as an argument. Nine, not the three the issue names: `DERIVE_NAME` carries five refusal
  sites and one of them splits `SHARED DEFAULT` across two source lines by string concatenation, so a
  grep for the phrase does not find it — a count taken from that grep would have left it behind the same
  way. Each arm's pair is asserted **both ways**: with an export the receipt names that channel and must
  not claim the shared socket, with none it must still claim it, because a one-directional assertion
  passes against a fix that deletes the sentence everywhere. The sentence renders the exported value with
  `ascii()` rather than `repr`, so it is ASCII by construction and no console codepage can kill the
  receipt. And the argument has a third state of its own: a caller passing none — `tests/test_doctor_inprocess.py`
  extracts these blocks and runs them against its own fixtures — is told the landing was *not
  established* rather than handed a confident claim about a session it does not have (#270).

- A declared `watch_name` the console could not encode was swallowed, and `bin/oss-workspace` then
  **derived a name over a declaration that exists**. `READ_NAME` prints the declared name to stdout and
  the shell reads it back, so stdout is the transport rather than a display; stdout is strict, a name the
  stream cannot represent raises `UnicodeEncodeError`, and the block's trailing `|| true` swallowed it
  into the empty string — which reads as *declares none*, which derives. The platform axis is the point:
  cp1252 on Windows against a `.supertool.json` written on a UTF-8 machine, and that file is tracked, so
  the value arrives by ordinary contribution. Of the three candidate behaviours the honest one is the
  third state, and neither of the others states it: printing the name mangled is a receipt nobody can act
  on plus an export nobody asked for, and refusing to launch trades the product for an enhancement. So
  *a name is declared and this stream cannot carry it* is now its own tagged answer, in the same shape as
  `conflict` and `unreadable` — export nothing, derive nothing, say so on stderr with the value rendered
  through `ascii()`, open the session anyway. The check is an explicit strict encode rather than a
  `try`/`except` around the write, because `PYTHONIOENCODING` can put a `replace` handler on that stream
  and a silently mangled name would then be exported with no exception for any handler to see — the
  quiet half of the same bug. `|| true` is kept, because `set -e` would otherwise turn a bad
  `.supertool.json` into no session at all, but it no longer means *this file declares none*: a non-zero
  exit with no answer is now reported as its own state in both `READ_NAME` and `DERIVE_NAME`, which
  closes the same swallow for any other uncaught exception — a `RecursionError` out of `json.load` on a
  deeply nested file is neither `OSError` nor `ValueError`, and previously left `DERIVE_NAME` silent on
  both streams. Tested by forcing a strict encoding onto the stream and measuring that an unencodable
  print actually raises there, never by asserting a codepage from a table; a run that cannot establish
  the condition skips carrying what went untested. The previous decision to leave this was recorded in a
  test comment rather than on the tracker, which is why it survived a release (#271).

- `doctor`'s `plugin_tree_digest` declined a symlinked *directory* at the top of each compared
  tree and nothing under it. `os.walk` yields a symlinked file as an ordinary entry in
  `filenames` and `read_bytes()` follows it, so a tracked `agents/leaked.md ->` anywhere had
  that file's bytes folded into the digest while `unreadable` stayed empty — a receipt that
  could not be told from a tree with no symlink in it at all. A symlinked file is now declined
  on the same rule as a symlinked directory, and the decline is recorded in `unreadable` rather
  than dropped (#279).
- Declining was chosen over resolving the link and containment-checking the result, and the two
  produce different digests for the same repository, so it is a decision rather than a detail.
  Resolving keeps a legitimately symlinked file inside the tree measurable, and needs a
  definition of "inside" against `realpath` — `/var` against `/private/var`, case folding, short
  names — that a diagnostic cannot get right on every leg; a containment test wrong on one leg
  reads a file outside the tree with a receipt saying it did not. The cost is stated rather than
  hidden: a symlinked file inside the tree is no longer compared, and says so (#279).
- A non-regular file is refused separately, and that is the half that stopped the 0.6.0 tag: a
  FIFO inside the tree with no symlink involved blocks in `open()` until somebody writes to it,
  so `plugin_tree_digest` never returned and `doctor`'s *exit 0 always, one VERDICT line*
  contract was unreachable — from a launcher that runs the diagnostic before every session with
  no timeout. Both refusals ride on one `os.lstat`, which neither follows a link nor opens
  anything (#279).
- The same containment hole one level up, found while fixing the first: `os.lstat` refuses a
  symlinked leaf and refuses nothing above it, so `.claude-plugin ->` elsewhere still had its
  manifest read from outside the tree. Every ancestor of a compared file is now checked, and the
  compared directories need no equivalent — their tops were already checked and `os.walk`
  declines symlinked subdirectories itself (#279).
- The only symlink test this check had passed `target_is_directory=True`, so the file case had
  no positive control and the suite was green over both halves. All three new fixtures pair a
  must-not-fire with a must-fire in the same tree, confirm the symlink or the FIFO actually took
  before asserting, and skip loudly with what went untested where the platform refuses to build
  one (#279).

- A release audit could grade a class `clean` on a reading and on a fired control with the same
  word, so a class nobody exercised cleared the gate over a defect that reproduces in one command.
  A class with no findings now carries `clean (exercised)` — a control that would have failed had
  the class been present, named with its output — or `clean (read)`, which never renders as the
  measured grade, and the verdict line carries the count of classes read but not exercised. The
  count annotates rather than stopping the tag; a `read` grade never outweighs a reproduction
  (#280).
- Every release-audit completion is now joined to the dispatch it answers by a token the gate mints
  and the auditor echoes, with `dispatch token: none reached me` as its third state. An
  unattributed completion does not clear the gate **and is not discarded** — when this last
  happened two completions arrived for one dispatch and the unattributed one was the one carrying
  the real finding (#280).

- `doctor`'s memory check returned early on `not store.is_dir()`, so the branch that detects an
  `identity.md` sitting unread at `.claude/remember/identity.md` was unreachable in the one state a
  fresh install is actually in. A marketplace install on day one has no `.remember/` directory --
  nothing has saved a session yet -- and an installer who has put identity where it looks like it
  goes got `no memory store in this project ... it will create one on first save`: true, reassuring,
  and silent about the file that is the reason they ran the diagnostic. Both locations are now
  listed before anything is reported (#284).
- The two decisions #284 asked a fix to make were already made, and the issue said it was filed from
  the passing branch plus a docstring rather than from a reproduction. Observed before fixing: the
  absent message already named both consulted paths and the target, and the present-but-never-read
  message already existed and was already distinct. What was missing was the ordering that made the
  second one reachable (#284).
- `Path.is_dir` and `Path.glob` are both gone from that check, for the reason they keep coming back:
  `is_dir()` swallows `OSError` and returns True for a directory that exists and cannot be entered,
  and pathlib's glob swallows `PermissionError` while walking and yields nothing -- so a `.remember`
  nobody could read produced `no identity.md in .remember or .claude/remember`, a confident absence
  about a directory that was never listed. `os.listdir` raises, and the exception already in hand
  settles which state it is: `FileNotFoundError` is absence, anything else is unreadable. No second
  question is asked of the filesystem to explain why the first failed (#284).
- The reasoning about *which* location is read in *which* install layout stays in `memory_layout`'s
  docstring, in one copy. The messages reach the same conclusion and a test binds them, rather than
  a second user-facing copy that drifts from the first (#284).

- `doctor` now reports `./supertool`, the entry point every developer brief this plugin issues tells
  an agent to call. It had no line at all: `OK supertool: available` answers *is the binary on PATH*,
  which a reader takes for *does this repo have the path the brief named*. Two questions with
  different remedies, rendered as one OK (#285).
- Ten states, because the failure modes are not one. **absent** is every fresh clone, by design --
  `scripts/scaffold.py` gitignores `/supertool` so one developer's absolute path is not baked into
  every other clone -- and it is also every worktree an agent cuts mid-session, since the link is
  made against the directory a *session* opens in. **other-target** is a link reaching something
  that is not a `supertool.py` in the plugin cache; it was observed on this repo, and a deliberate
  local checkout looks exactly like a stale link from another machine, so the finding names the
  target rather than judging it. `not-a-symlink`, `dangling` and `unreadable` are each
  present-and-unusable with their own remedy, none of which is "create one" (#285).
- Three of the ten say "could not tell", which is the reason this is a function rather than an `==`.
  **unknown-plugin-path** is a link with no readable plugin cache to compare it against;
  **unknown-comparison** is a cache that has candidates and a filesystem that would not say whether
  any of them is that file. Reporting `other-target` in either case accuses a link that may be
  correct; reporting `ok` clears one that may not be. Neither was measured, so neither is said
  (#285).
- **The comparison is identity, not string equality, and that was settled by CI rather than by
  taste.** The first version normalised both sides with `os.path.realpath` and failed two Windows
  legs: a link pointing at exactly the right file was reported `other-target`, so every Windows
  install with a correct `./supertool` would have been told it points somewhere it should not --
  worse than the silence #285 was filed about. "Normalise both sides" is not the fix and both sides
  were already normalised by the same function: on Windows `realpath` is **prefix-preserving rather
  than canonicalising** (`ntpath.py:683` records whether the input already carried the
  extended-length prefix, `:713` strips it from the result only when it did not), and `os.readlink`
  returns a reparse point's substitute name that carries it. One function, both sides, two
  spellings. Symmetry of function is not symmetry of result when the output depends on the form of
  the input (#285).
- `os.path.samefile` replaces it, which is a transcription rather than an invention: supertool's own
  session-start hook decides the same question with `-ef`, and its comment says why -- device+inode
  through symlinks. Every string alternative is a list of spellings (the extended-length prefix, its
  UNC form, 8.3 short names, a substituted drive, a junction, case folding) and is wrong the first
  time Windows adds one, which is the same shape as a table of error codes. The residual risk is
  stated rather than hidden: `st_ino` is not meaningful on every remote filesystem, and that
  direction clears a wrong link rather than accusing a right one (#285).
- The regression test is a **hard link**, and the first draft of it was a symlinked directory that
  passed against the broken code. On POSIX `realpath` genuinely canonicalises, so no symlink-shaped
  second spelling survives it and both implementations agree -- a control that distinguishes them
  only on the platform this suite cannot run is a control that controls nothing. Two directory
  entries for one inode survive `realpath` everywhere, so the test fails on macOS and Linux before
  the fix as well as on Windows, and it asserts identity rather than branching on `sys.platform`
  (#285).
- The same defect had a second instance a few lines away, found by sweeping for the class rather
  than by CI: `_own_supertool_tree` walks from `realpath(project_dir)` while its caller held the raw
  path, so `_display` fell back to an absolute path -- `/tmp` against `/private/tmp`, an
  extended-length prefix on Windows. Only the printed string, never a verdict, which is why nothing
  caught it. The walk now returns its root beside the core and the display uses it (#285).
- Which component creates the link was open in #285 and is now settled by reading it rather than
  reasoning about it: supertool's own `hooks/session-start.sh`, which already handles every case
  correctly -- it links when nothing is there, leaves a stranger untouched, and refuses to link at
  all inside a supertool checkout. Nothing upstream is broken and nothing was filed there. The gap
  was entirely local: no diagnostic said which of those had happened (#285).
- That last refusal is transcribed into the check rather than invented, so a supertool checkout is
  told it is *right* to have no wrapper instead of being warned at. claude-supertool is itself
  managed by this loop, so without that arm the diagnostic would have fired a confident wrong
  warning in the one repository the tool comes from (#285).

- `doctor.loop_repository()` derives where a defect in *this plugin* gets filed, off the
  `repository` key in the manifest at `PLUGIN_ROOT` -- the same key, read the same way, that
  `dependency_repositories()` already reads out of every other plugin's installed manifest. The one
  board the loop could not name was the one owning everything it writes into somebody else's repo,
  and `agents/developer.md` correctly forbids improvising a slug, so a destination that could not be
  derived and a destination that did not exist rendered identically at the call site (#292).
- #292 proposed adding that key to `.claude-plugin/plugin.json`. It has been there since 0.1.0, in
  the tree and in every cached install -- checked before editing. Nothing was missing from the
  manifest; what was missing was a reader, so no manifest changed (#292).
- It is a sibling accessor rather than a row in `dependency_repositories()`, and that was settled by
  measurement instead of by taste. "Every existing caller works unchanged" was the argument for
  folding, and the one existing caller does not: `check_freshness` feeds the mapping through
  `published_versions` into `dependency_findings`, which unions `declared | installed | latest`.
  This plugin is in neither of the first two, because nothing declares itself as its own dependency
  -- so folding makes the diagnostic print `oss: declared but not installed. Run claude plugin
  install oss@dpt-plugins`. False, actionable, wrong, and printed by the plugin it is wrong about.
  A test holds the separation rather than a comment (#292).
- Three states, because two is the collapse the issue is about: read; **read and does not say**,
  which is a real state for a manifest with no `repository` key and is not *there is no tracker*;
  and **could not be read**, which is not either. A non-string value lands in the second rather than
  being formatted into a diagnostic line -- `plugin.json` is tracked and a contributor writes it
  (#292).
- `/oss:doctor` reports it, so the accessor reaches something the day it lands instead of waiting
  for a caller to adopt it. An honest accessor nobody calls is a capability that exists and cannot
  be used, which is the shape of the gap it was written to close (#292).

- The generated changelog gate no longer renders every dependabot pull request permanently
  red. Dependabot applies its own labels the moment it opens one, each label is a `labeled`
  event, and `labeled` is in the workflow's `types:` for the reason its comment gives — so
  five runs were created inside two seconds on a scaffolded repository and all five failed.
  Applying `no-changelog` afterwards makes a passing run exist and retracts nothing, so a
  merge gate that aggregates runs on the head sha refuses a pull request the forge calls
  mergeable, with no action left that would change it. The gate now exempts a pull request
  whose **author** is `dependabot[bot]` — announcing the skip rather than passing silently,
  and only in the branch that previously failed, so a bot pull request that deleted a pending
  fragment is still refused. The workflow also groups its runs per pull request with
  `cancel-in-progress`, which collapses the burst; that is a mitigation, not a fix, since
  `cancelled` is not `success` either. The remaining half is the aggregating gate itself,
  filed as `Digital-Process-Tools/claude-supertool#1792`. Reaches a managed repository only
  when `/oss:scaffold` is next run there, and nothing schedules that (#293).

- `supertool-required.md` — the `01-oss` tools rule that refuses `Read`, `Edit`, `Write`, `Glob`
  and `Grep` — told a reader without `supertool` nothing at all. It is committed into every repo
  this plugin scaffolds, so it reaches contributors who installed nothing, and it closed the gap
  by asserting it away: *"a tree that carries this layer already carries supertool"*. That
  sentence is false in exactly the situation the reporter was in, and no rule can check it — a
  rule is a text file the hook matches a subject against, and it runs no command, so it fires
  identically whether the binary is there or not. The refusal now hands the reader the probes
  that tell the situations apart, names each outcome, says plainly that the file's presence is
  evidence about a repository and none at all about their machine, and names the route to the
  dependency (#294).
- **Three outcomes, not two, and the third is the one a first draft of this fix got wrong.**
  `./supertool` is gitignored and created per clone by supertool's own session-start hook, so
  *binary installed, entry point absent* is a real and ordinary state — `doctor.py`'s
  `check_supertool_entry_point` reports it separately for that reason (#285). A rule probing only
  the binary on `PATH` would answer that reader "supertool is not installed" and send them to
  reinstall something already present, which is #294's own defect one question to the left. Both
  spellings are named, the entry-point outcome says in as many words that nothing is missing from
  their installation, and a test pins each (#294).
- The refusal is injected verbatim on every refused call, so the ops list stays **first** and the
  diagnosis sits under a heading below it. The reader who has `supertool` is the majority and pays
  the whole body every time; the reader who does not needs the diagnosis once (#294).
- Conditional scaffolding was considered and rejected for the same fix: `/oss:scaffold` runs once
  on the maintainer's machine and the rule is read on every contributor's, so a presence check
  there answers about the wrong machine at the wrong time — it would leave the reported
  contributor blocked anyway, and add a committed file whose presence flapped with whoever last
  scaffolded (#294).
- The upstream finding that came with #294 — a sibling rule using `match: ~.`, which matches every
  string, so a plain `make test` is denied — was measured against this plugin's rule rather than
  acted on. `match: ~.*` here is scoped by its `tool:` column: driven against the installed hook,
  a `Read` and a `Grep` are refused and a `Bash` `make test` and a `TodoWrite` are not. Nothing
  was widened or narrowed, and a test now pins both directions in one fixture so a change to
  either column cannot silently turn this into a rule that denies everything (#294).
- The committed copy of the `tools/01-oss` layer — the one this repository's own hook reads — now
  has a staleness guard of its own. The existing one covers `paths/changelog-fragments.md`,
  because that rule has per-repo substitution in it; the tools rules render from constants, which
  is what made them easy to leave stale, since every generator test stays green while the
  committed text is a release behind (#294, #307).

- `scripts/release_version.py` reads a fragment named `<issue>.<section>.<slug>.md`. It parsed
  two segments and nothing else, so a name `scripts/assemble_changelog.py` has always accepted
  landed in `unreadable` and the release stopped with no number named. The grammar is now
  transcribed from the assembler's own, and the two are measured against each other in a test
  rather than asserted to agree in a comment (#297).

- The `could not decide` receipt names the cause that actually fired. It used to print one fixed
  sentence offering two causes — a section outside the six, or an unrecognised compatibility line
  — whatever had happened, so the filer of #297 went looking for a malformed body in a file whose
  body was fine, renamed a correctly-named file and reported the contributor who wrote it. Four
  distinguishable causes are now kept apart, one of which (`a fragment whose bytes could not be
  read`) had never been named at all, and the `unreadable` row carries the cause beside each file
  name — with two bad fragments a single sentence cannot say which file had which (#297).

- `/oss:scaffold --apply` creates `changelog.d/` and its own gating workflow without writing
  `changelog_dir` into `.oss.json` -- deliberate (`commands/scaffold.md`), because the two
  readers that name the fallback directly, the command and the generated workflow, cannot
  drift apart. Two OTHER readers of the same key could not tell that state from a repo that
  genuinely never adopted fragments: `commands/changelog.md` refused to run at all, and
  `scripts/release_version.py` refused with `could not decide` -- both because `changelog_dir`
  was still `null`. Cost a real release gate on a repo scaffolded one commit earlier, with two
  correctly-named fragments sitting in `changelog.d/` and `assemble_changelog.py --check`
  passing on them in the same minute. Both readers now ask
  `oss_config.scaffolded_changelog_gate` -- whether THIS repo's own
  `.github/workflows/oss-changelog.yml` exists, the one signal a forge gives this plugin to
  claim a workflow by -- and recognise the fallback rather than re-guess a directory nobody
  named. `.oss.json` itself is left untouched: it is a tracked file somebody owns, and a
  default must never win against a decision a person made (#299).

- The loop filed at a bar of *noticed* rather than *cost somebody something*, and the meter that
  would have shown it carried a sentence reading as do not act on the number. Three rules now: a
  friction line names what it cost and a preference is reported nowhere (`tooling-unclear:` is the
  third state); a class is only filable if you can name an input that reaches it; and raising the bar
  on what counts as a finding is stated as a definition rather than as throttling. Issue bodies gain
  a form -- symptom, location, mechanism, what would settle it -- so a filing is readable by whoever
  picks it up rather than by whoever wrote it (#300).

- The shell CI leg exceeded its own `timeout-minutes: 10` and GitHub renders a timeout kill as
  **cancelled**, not failure, so `main` and every open pull request read as "0 failed, 1 cancelled —
  not green" with nothing broken — six times on 2026-08-19, including a deliberate re-run. The step
  fetched `shellcheck` with `sudo apt-get update && sudo apt-get install` on every run, inside the
  timed window: 5.2s on 2026-08-16, 68.4s of a 70s step earlier the same day, then a hang that
  consumed the whole cap. The fetch is gone rather than pinned or given a bigger cap — every
  successful run had logged `shellcheck is already the newest version (0.9.0-1)`, so the install had
  never installed anything; the binary ships in the `ubuntu-latest` image, and the lint itself takes
  under a second. `timeout-minutes` is unchanged at 10, now a bound on a hang rather than a budget
  the job spends (#303).
- An absent `shellcheck` used to exit 127 once per file into the same `fail` flag a real finding
  uses, so `could not lint` and `linted and found a problem` reached the leg's status identically —
  and because `set -e` does not exit on the left of an `&&`, a failed install fell through to
  exactly that. The step now checks for the binary first and exits `4` naming what is missing and
  what to do about it, distinct from `shellcheck`'s own `1` and from `shell_sources.py`'s `2`
  (matched nothing) and `3` (could not read) (#303).

- The `01-oss` tools layer's `00-README.md` recorded, as current, that a rule keyed on the `Agent`
  tool cannot fire — and this plugin writes that file into every repo it scaffolds.
  `claude-jit-context` 0.5.0 reads `subagent_type` as a fifth subject key, so the record had
  become a false statement shipped under full authority into other people's repositories: the same
  defect class as a vendored file that keeps describing the repository it came from. It now
  records what was measured instead — that the subject for an `Agent` dispatch is `subagent_type`
  and only that, `description` and `prompt` being a deliberate exclusion upstream — names the
  version the capability arrived in, so a reader on an older dependency can tell whether it
  describes their machine, and keeps the re-measurement recipe with a second `Agent` rule added to
  it so a single answer cannot say a rule fired without saying what it fired on (#307).
- **No `tool: Agent` rule is shipped, and that is now a decision rather than a blocker.** What such
  a rule would say is undecided: the standing clauses live in the agent definition being
  dispatched, a rule restating them is the copy that drifts, and one pointing at them has to name
  a path inside an installed plugin rather than anything in the repository receiving the rule. It
  would fire on every matching dispatch for a benefit that is asserted rather than observed. The
  record states both questions so the next proposal does not start from nothing (#307).
- The guard that caught this is replaced rather than deleted. `tests/test_jit_agent_dispatch.py`
  (was `..._gap.py`) now asserts the capability instead of the gap: a matching `Agent` rule fires
  and a non-matching one does not, against a single dispatch, which is the only shape that shows
  the subject really is `subagent_type`; and a dispatch carrying no `subagent_type` must be
  reported as unreached rather than answering the `{}` a genuine no-match answers. It inherits the
  same asymmetry it always had — a CI runner installs no plugin, so it skips there naming what
  went untested, and measures only where the dependency is actually present (#307).
- The harness both test files now share pins `encoding="utf-8"` on the subprocess that drives the
  hook. Text mode with no encoding decodes with the console codepage under `errors="strict"`, and
  the resulting `UnicodeDecodeError` is neither an `OSError` nor a `SubprocessError` — so it would
  have sailed past the `except` written to turn a hook that could not run into a reported problem,
  and crashed instead, on the platform whose legs never execute this path anyway (#307).
- `CLAUDE.md`'s *What is not proven yet* carries a superseded marker on the bullet that stated the
  four-key subject as an observation. The section is re-derived at each release rather than edited
  and this does not pre-empt that — but the alternative was tagging a release whose `CLAUDE.md`
  asserts the exact sentence this release describes as a false statement it stopped shipping
  (#307).

- `doctor.same_directory` answered a three-answer question with two. `os.path.samefile` raises when
  either path is absent, and the version this replaces caught that and fell back to comparing
  `os.path.abspath` strings -- so two spellings of one directory (a symlink and its target, a Windows
  extended-length prefix and its plain form) answered `False` while the directory did not exist and
  `True` once it did. The verdict moved with the filesystem's state rather than with the question
  asked, and `False` is what every caller renders as *these are two different trees* (#309).
- `compare_directories` replaces it and returns `(True | False | None, reason)`. The string
  comparison is kept for the **positive** answer only, and that asymmetry is the fix: two equal
  normalised paths denote one directory by construction, while two different ones establish nothing,
  because `abspath` does not resolve symlinks and `realpath` would not have rescued it either --
  on Windows it is prefix-preserving rather than canonicalising, so running both sides through the
  same normaliser gives two spellings back. Symmetry of function is not symmetry of result when the
  output depends on the form of the input (#309).
- The reason comes from the `OSError` already in hand, never from a second question to the
  filesystem. That is the `release_delta.py` trap: the `Path.exists()` added to tell absence from
  unreadability is the call that kills a diagnostic contracted to exit 0 (#309).
- Four call sites, and what each says in the third state was decided per caller rather than once:
  `--plugin-root` naming a path that is not there now says it could not be examined instead of
  accusing it of being a different tree; `--root` beside a `CLAUDE_PROJECT_DIR` that cannot be
  stat'd says the two could not be compared instead of reporting a disagreement it cannot see;
  the installed-copy/clone check says so and then compares both trees anyway, warning that an
  identical result there may be one tree read twice; and `config_search_path` takes the
  conservative arm with no message at all, which is a decision recorded in its docstring rather
  than an omission (#309).
- Two of the four are reachable with ordinary input -- `--root` and `--plugin-root` are paths
  somebody types, and a typo is the common case. The other two are races: the enumeration is in the
  code, because "which callers can reach this" was the half the issue left open (#309).

### Security

- The containment check on `pr_body.path` claims that *both* sides are resolved, so a symlink sitting
  inside the report's own directory and pointing out of it is refused unopened. Nothing asserted it.
  Every containment case in the suite named a path that escapes *lexically*, so swapping `resolve()`
  for a normalisation — plausible, for Windows short names or to avoid a `stat` — would have kept all
  of them green while making the claim false in the function docstring, in the schema and in the
  changelog at once. Two cases now pin it, a symlinked file and a symlinked directory inside the
  reports directory, both asserting on the *open* via the read spy rather than on the wording: a
  change that merely stopped echoing would leave the read in place and pass a message assertion.
  Demonstrated against a weakening narrowed to the one property: `(base / raw_path).resolve()` is
  still called, so every other behaviour of the line survives — the `ValueError` on a NUL byte, the
  `OSError` a `Path.resolve` injection raises — and only its *value* is discarded, for
  `Path(os.path.normpath(str(base / raw_path)))`. `2 failed, 85 passed` on
  `tests/test_agent_report_schema.py`, both failures on the open. A broader weakening that drops the
  `resolve()` call outright reddens two further cases for reasons that have nothing to do with
  symlinks, which is why the substitution is stated rather than left to be guessed at (#234).
- The fixture is a measurement rather than a given, because symlink creation needs a privilege or
  developer mode on Windows. The link is attempted and then confirmed to *resolve* to its target, and
  when either step does not take the case skips carrying the platform, the exception type, the errno,
  the winerror and a sentence naming what went untested — a link that resolved to itself would leave
  the refusal passing for a reason nobody chose. The refusal is paired with a positive control in the
  same fixture and the same directory: an ordinary sibling payload is still opened and accepted, so a
  harness that created nothing, resolved nothing or never ran the validator fails rather than passing
  quietly. The cost is stated rather than hidden: an unelevated Windows runner without developer mode
  raises `WinError 1314` here, so on those four legs this guard skips rather than asserts and the
  coverage it reports is the coverage it has. That is the deliberate trade — a case branched to pass
  trivially on Windows would claim a green leg nobody re-reads. `tests/test_oss_config.py`'s existing
  symlink skip, which said only "this platform will not create a directory symlink without
  privileges", now carries the same detail (#234).
- Re-derivation found the claim in two documents rather than the three it was reported in. The
  `pr_body.path` description in `schemas/agent-report.schema.json` described containment without ever
  mentioning symlinks, so one of the three statements of one rule had already drifted into a weaker
  one — which is the shape the rule was worth re-reading for. It now states the property and says
  what pinned it (#234).

- A managed repository's tracked `.supertool.json` reached `bin/oss-workspace`'s session-start receipt
  **raw**. When two op blocks declare different `watch_name` values the launcher lists them, and those
  strings come straight out of `json.loads` with nothing between the parse and the write: the
  `conflict` arm returns before any name is validated, so `oss_config.watch_name_problem` — which
  refuses a newline with a stated reason, and works — is simply not on that route. Measured rather
  than argued: a second declared name of `beta\noss-workspace: VERDICT: ok\r\x1b[2K` produced a
  **three-line** receipt whose second line was a column-0 `oss-workspace:` sentence the launcher never
  wrote and whose third began with a live erase-line sequence. The forged line is in a vocabulary this
  same file reads — it parses `^VERDICT:` at column 0 further down — though that parser reads the
  diagnostic's own captured output and not this stream, so the harm established is impersonation and
  terminal rewriting rather than injection into the verdict. `.supertool.json` is tracked, so the
  value arrives by ordinary contribution (#323).
- The neutralisation was already six lines up, in the sibling arm of the same `if`/`elif`: `ba766ba`
  (#283) added `ascii()` to the `unencodable` arm with a written rationale and rewrote the `conflict`
  arm's message in the same hunk without applying it. `ascii()` is now applied **per name** rather
  than around the join, which is not cosmetic — quoting the joined string once still lets a value
  containing `", "` forge a list separator and read as two declared channels, so the count of channels
  is now a property of the code instead of the input. `ascii()` and not `%r`, for the reason the
  neighbouring arm gives: repr leaves non-ASCII alone and this line goes to a console whose codepage
  may not carry it (#271, #323).
- Pinned by a pair in the same fixture, because the negative half is the one with teeth: an assertion
  that no forged `oss-workspace:` or `^VERDICT:` line appears also passes when the block printed
  nothing at all. The control is an ordinary `alpha`/`beta` conflict that must still emit its one
  honest line naming both channels. Both drive the `READ_NAME` heredoc extracted from the launcher
  rather than reconstructing shell quoting inside a `bash -c` string, which would measure the test's
  own escaping; output is compared as bytes, because `universal_newlines` translates a lone CR into a
  newline and would have hidden half of what is asserted. The forgery is counted as **lines beginning**
  with `oss-workspace:` rather than as occurrences of the substring — a substring count graded the
  fixed code a forgery, since the escaped text survives inside the quoted name (#323).
- The fixture's first version carried an assertion no red state could reach. It spelled the forged
  line `oss-workspace: VERDICT: ok`, which begins with the launcher prefix, so the `startswith
  ("VERDICT:")` check passed against the unfixed launcher -- a tick over a question never asked, in a
  test whose whole subject is that defect class. Found by evaluating the six assertions one at a time
  against the parent commit rather than by running the test, which stops at the first failure and
  cannot say whether the rest are reachable: four fail pre-fix and pass post-fix, and the two
  must-fire guards pass in both worlds, which is what they are for. The impersonated line and the bare
  verdict line are now separate forgeries in the same value (#323).
- The control-character assertion strips the message terminator first, and that is a construction
  rather than an argument. Whether a child's `sys.stderr` translates its own LF to `os.linesep` is a
  question about CPython's std-stream setup that a suite running on one platform has no standing to
  settle, so it is not asked: stripping CR and LF from the right removes a terminator of either shape
  and leaves an embedded CR -- the one under test -- alone. Raised by the audit as a probable red on
  the four Windows legs; unobserved either way, and answered by removing the dependency instead of by
  taking a side (#323).
- Not closed, and named rather than implied: this is a per-site call, the sixth in a file that already
  had five and one miss. A single chokepoint of the kind `scripts/doctor.py` uses is not available
  here without changing the launcher's process shape — the file renders through five independent
  Python heredocs, each its own interpreter with no shared module, and `READ_NAME` deliberately takes
  no scripts directory, so a shared helper would add a *validator could not be loaded* failure mode to
  the one block whose whole job is reading a JSON file. Until that is decided, a seventh rendering site
  added to this file is protected by nothing but review (#323).

## [0.5.0] - 2026-08-16

### Added

- An agent's report now carries a `docs` survey: one line per path in the repo's `docs_targets`,
  each `updated`, `no-change-needed` or `not-read`. `docs_targets` was required by both agent-facing
  documents and read by no code at all, so a docs duty performed and one skipped rendered identically
  in a merged pull request. The key is required rather than optional, because an absent survey was
  the exact state being closed (#164).
- `no-change-needed` and `not-read` are refused without a `why`, and the schema publishes both
  refusals in `x-enforced` with a mutation proving each. "No change needed" with no reason is the
  sentence a run that never opened the file also writes; an unread doc is a gap somebody can act on
  rather than the absence of a finding (#164).
- The matching CI gate was **measured and rejected** rather than assumed, against this repository's
  own last thirty merged pull requests. Six of them changed `README.md` for the docs duty. The
  trigger `.github/workflows/changelog.yml` already computes fires on 27 of the 30 and is right about
  6; the best rule anybody proposed is wrong two times in three; the narrowest one — a new file under
  a product path — fires on none of the thirty at all. A gate wrong that often earns a blanket
  override label within a week, converting an unmeasured duty into a measured and routinely
  overridden one, and a gate that never fires cannot be told from one that is broken. The counts sit
  in `agents/developer.md` and `tests/test_docs_duty.py`, with a pointer and no second copy of the
  numbers beside the gate that tempts the symmetry (#164).

- The changelog fold takes `--title`, so a repository whose release headings carry a sentence can
  keep them without forking `.oss/assemble_changelog.py` — an owned file that `/oss:scaffold
  --apply` replaces wholesale, which made the fork lose itself silently at the next update. The
  default stays `## [x.y.z] - YYYY-MM-DD`, Keep a Changelog's own shape; a title is written after
  the date. The convention is read out of the changelog rather than declared in `.oss.json`,
  because a heading style is a per-release editorial choice and has no single value a file written
  once could hold: with the flag omitted against a file whose newest release heading carries a
  title, the fold refuses instead of quietly writing a plainer one, and `--title ''` cuts a
  deliberately untitled release and is recorded as the decision it is (#170).

- `scripts/release_version.py` proposes the release number from the changelog fragments, in three
  states: `proposed` (exit 0) carries the number with its evidence — the section counts, the change
  class, the line and the fragments that declared a compatibility verdict; `could not decide`
  (exit 3) and `no baseline` (exit 4) **name no number at all**, because a default bump over a
  breaking change is indistinguishable in the tag from a considered one. It proposes and never
  writes, bumps or tags: the maintainer accepts it or overrides the proposal and records which
  (#171).
- The rule is written down rather than decided per release: **in a `0.x` line a breaking change is a
  minor, and at `1.0.0` or later it is a major.** In a `0.x` line that makes `breaking` and
  `feature` the same number, so the receipt says the fold happened — a maintainer who wants `1.0.0`
  has to override rather than notice nothing (#171).
- A `removed` fragment now declares whether it breaks compatibility, as an ordinary bullet:
  `- Compatibility: breaking|compatible - <reason>`. It is required on `removed` and optional
  everywhere else, an unrecognised verdict or one with no reason is `could not decide` rather than a
  quiet pass, and the fragments that declared nothing are reported by count instead of being folded
  in silently. #171's own evidence was `changelog.d/113.removed.md`, whose author knew the answer and
  wrote it in the one place a checker could not see (#171).
- `commands/release.md` and `skills/manager/SKILL.md` both carry the rule, and the release gate that
  sweeps `version_sites` now says where the number it sweeps for came from (#171).

- `/oss:release` now has an answer for a call the harness refuses. The plugin documented supertool's
  own confirmation gate and its three opt-outs and said nothing about the permission layer in front of
  them, which can deny a call before supertool or `gh` sees it, is not cleared by an allowlist entry,
  and is not stable — the identical call has come back denied and then been permitted with no
  configuration change, now reproduced at four distinct calls rather than only at the merge. The
  release path is where that costs most, because every deniable call sits after the changelog has been
  folded, the fragments deleted and the version sites bumped (#186).
- A denial is now named as a fourth answer and never as one of `release_publish.py`'s three.
  `created`, `skipped` and `could-not-create` are verdicts the script earned by running; a refused
  call has no exit code, so reporting it as `could-not-create` — or as the range gate's
  `could-not-run` — would state a fact about the repository nobody measured. It reuses the word the
  loop already uses at the merge: **denied**, named exactly, handed to the maintainer to run or to
  permit. The three-outcome list above it now says out loud that it is not exhaustive (#186).
- Three refusals go with it: do not reword the call past the classifier (a different spelling is a
  different command string, and hand-assembling the `gh` call loses `--verify-tag`), do not retry in a
  loop (one re-invocation of the identical call is a probe, reported either way; a second denial is
  handed over), and never read a denial as a gate that passed or as a release that shipped (#186).
- A denied release now says where it stopped and where it resumes, per step rather than in one
  sentence covering both: a denial at the tag push leaves everything local, and a denial at the
  publish leaves the tag already on the remote and only the release object missing. Otherwise a
  refusal lands in the *released by manifest and never tagged* state by accident. The ordering trade
  behind that — fold first, or tag first — is stated rather than quietly taken (#186).

- `/oss:doctor` now answers whether anything publishes to this repo's board, in seven states. A
  radar tier has to be registered in `.supertool.json` *and* the op reading it has to be routed
  here, each half is silent about the other, and neither was diagnosed anywhere: the question lived
  as one line of session-start stderr in `bin/oss-workspace`, decided by a `grep` that also matches
  the word inside an unrelated key. This repository was measured with neither half in place while
  the diagnostic printed OK (#191). Registered-but-unroutable, never-registered, edited-and-broken
  and could-not-read are four different answers with four different remedies, and a `presets` list
  that cannot be read is reported as unknown rather than as unrouted.

### Changed

- The manager skill now states its own authority. It said what to decide and how to evidence it and
  never who decides, and the omission had a direction: every ambiguity resolved toward stopping and
  asking. A new *Who decides* section names the test — who has to be involved to undo it, not
  whether the act is reversible, which mis-sorts a squash merge and an issue close — and then writes
  out **both** lists, because a principle without a list is where the stalling comes back. It also
  says what replaces asking: decide, state the assumption, act, report it prominently, which
  preserves the reversal rather than the question. Two things that look like stops are argued off
  the list: filing on a dependency's own tracker is a duty the skill already carries, and a blocking
  row stops the *release*, which the loop does to itself without asking. `agents/developer.md`
  points at the section rather than copying it — the agent's boundary was written down and the
  maintainer's was not, and that asymmetry is the issue (#185).
- The caution against assuming a preset op now names the probe that answers it. `radar:--state` is
  read-only — it spawns nothing, reaps nothing, calls no API — and it answers in three states. A
  caution naming no probe was read as permission to skip the reading entirely, which produced a
  whole tick with no reading of the watcher fleet at all; `commands/tick.md` carries the ordered
  half of the same fix, and this is the skill half (#187).

- This repository's own `.supertool.json` loads the `watch` preset and declares the `gh-prs` radar
  tier, so a maintainer session receives pull-request and CI state as it changes instead of polling
  it with a `sleep` loop in the orchestrator's shell. `scripts/scaffold.py`'s `check_radar` had
  reported this repo as `no-tiers` since radar shipped — a session able to receive channel events
  with nothing publishing any — and now returns clean against it. No `ops.radar.watch_name` is
  declared beside it, deliberately: a repository name hand-typed into a tracked file travels into
  the next repository somebody copies that file to, and both then bind one watcher socket with a
  declaration each. Until #192 lands the derivation in `bin/oss-workspace`, this repository is on
  the shared default socket that #191 describes, which is where it already was — but with the
  `watch` preset now live there is traffic to lose, so #192 is the one to merge first. Nothing
  about the `.supertool.json` that `/oss:scaffold` writes into a managed repo changes (#189).

- The manager skill now states that the manager never writes the diff. A maintainer who implements
  has not saved a delegation, they have removed the only independent read the change will get: the
  review gates all assume two parties, and reviewing your own diff renders identically to reviewing
  somebody else's while checking nothing (#191).
- README no longer tells you to run `oss-workspace` twenty-eight lines before the symlink that puts
  it on `PATH`, and its Status section no longer claims no issue has gone from triage to a merge —
  which stopped being true well before anyone edited it (#191).

### Fixed

- **`/oss:scaffold`'s preview reported a write-nothing run for a run that writes** (#182). The
  `01-oss` rule layer is replaced wholesale on every single `--apply`, and it was the only
  wholesale-replaced target neither `plan()` nor `--show` reached: against a repository that already
  had every default and already ran a changelog gate under another name, the plan printed `PLAN: 0 to
  create, 11 already present, 3 declined` for a run whose entire effect was to delete and rewrite six
  files of markdown that a hook injects into a model's context on a match. The owned trio has had
  `replace` rows out of a bare `--show` since #5 precisely because that is the destructive half of
  apply; the layer had none of that treatment.

  It now previews like the trio, one row per file — the layer's file count is not stable across
  plugin versions, which is an argument for showing it rather than against — and the `PLAN:` line
  counts it. `--show` prints the rule bodies in full, which is the content most worth reading before
  it lands, and takes a rule path for a single one.

  Two things the trio did not need. A file in the layer today that this version no longer ships
  previews as `remove`, because `install()` deletes the layer before rewriting it, and `--apply`
  prints a matching `removed` line so the promise and the receipt agree. And the changelog rule's
  body depends on a gate read and an assembler lookup that `--apply` performs *after* its own writes,
  so the preview renders against the tree as it will be **after** those writes — `oss_rules.rules()`
  takes an `assembler` override for it — and prints a `layer` line saying which input came from the
  plan rather than from disk. That the two reads agree is a claim about `_detect_changelog_gate`
  excluding this plugin's own files by name, so it is measured rather than asserted: the suite
  renders the preview, runs `--apply`, and compares the bodies byte for byte down both branches.

  Three states, not two. A layer directory this process cannot list is reported as unreadable rather
  than as holding nothing to delete, and a layer that cannot be rendered at all — `oss_rules` refuses
  a gate state it has no sentence for — makes the summary say `rule layer not previewed` instead of
  silently omitting the rows, which would have put the plan straight back where the issue found it.
- **A filename in the inspected repository could start a line of its own in `/oss:scaffold`'s
  output** (found reviewing #182). `_detect_changelog_gate` builds its detail out of paths it found
  while walking somebody else's tree, and that string is printed by `plan()`'s three `decline` rows,
  by the `changelog` finding, by #182's new `layer` note and by `/oss:doctor`'s owned-files line. A
  newline is a legal POSIX filename character and nothing upstream refused one, so a file named
  across two lines ended the line it was printed on and put the rest at column 0 of a CI log --
  #173 and #180's shape reaching a receipt rather than a generated file. Names are now flattened
  where the detail is built, so every consumer is covered including the one in a file this change
  did not touch; they are flattened rather than dropped, because the name is the evidence a
  maintainer needs in order to judge whether the detected gate is real.

- **`--show` refused a path typed with the local separator** (found reviewing #182). Every generated
  path this plugin knows is built with `/` on every platform, and `--show`'s lookup is string
  equality, so `--show .github\ISSUE_TEMPLATE\bug_report.md` was answered "is not a known template,
  owned file or rule" -- indistinguishable, to the caller, from the file not existing. Separators are
  normalised before the lookup. #182 is what made this worth fixing now: it is the first change to
  advertise a path (`.claude/jit-context/paths/01-oss/oss-config.md`) deep enough that anybody would
  type one.

- `/oss:tick` step 2 now orders the two board readings the loop was deciding from without ever
  taking. `git-worktrees` joins the batched board call unconditionally — it is available wherever
  supertool is and boards every tree whether or not `worktree_root` is set, so gating it on that
  key would have reproduced the very absence being fixed — and the three-state reading rule travels
  with it, so `cannot tell` cannot become `idle` and `merge unknown` cannot become `merged` in the
  one place the loop actually reads. The watcher fleet gets its own call because it is conditional
  and because the bare `radar` heals and forks pollers: the read-only `radar:--state` probe is
  ordered first, in three answers. Both omissions produced an absence that read as a clean result —
  a fleet nobody checked renders as a quiet channel, a worktree board nobody read renders as no
  worktrees (#187).

- The manager skill's one verification call pointed at `pr_body.path`, so the documented way to see
  the check rather than the claim reported `INVALID` with fourteen missing keys and three unknown
  ones on a completely correct pull request payload. It now names the report path, which is the only
  file that can answer the check the paragraph relies on: `payload.head` is compared against the
  report's `branch`, and handed the payload alone there is no branch to compare against. Validating
  the report opens the payload too, so one path still covers both. `scripts/report_schema.py` now
  recognises a payload handed to it and refuses it by name with the call to run instead of
  enumerating the report keys a payload was never going to have — an accurate wall that reads as a
  finding about the file and whose next move is hand-writing `head`, the one value nothing
  downstream verifies (#190).

- `bin/oss-workspace` now derives the watch channel name from `.oss.json`'s `repo` when
  `.supertool.json` declares none, instead of exporting nothing and leaving the session on the
  shared, unnamed `/tmp/supertool-watch.sock`. A second channel-capable consumer could win that
  socket, and every event the session emitted was then read, forwarded and discarded with no
  failure anywhere: `channel:health` reported FORWARDING throughout, correctly, because it cannot
  see which server holds the socket. A declaration still wins over the derivation, an existing
  export still wins over both and now names where the loser came from, and a repo with nothing to
  derive from is told it is on the shared socket rather than put there quietly (#191).
- Op blocks that declare *different* watch names are a fourth case and stay refused: nothing is
  exported and nothing is derived, because those ops are already on two channels and a name derived
  from `repo` would be a third one that nothing in the repo publishes to — an uncontested socket
  carrying no events, which reads as healthy. Undeclared and contradictory reached the derivation
  identically for one commit on this branch, so the refusal was printed to stderr and a derived name
  exported anyway; the two are now distinct states and the message says which one you are in and
  that the session is on the shared default socket (#191).
- A `.supertool.json` that exists and will not parse is refused on the same grounds: what it
  declares is unknown rather than absent, so nothing is derived from it either, and its message no
  longer promises the default channel while exporting a derived name. A repo with *no*
  `.supertool.json` is absence, and still derives (#191).
- `/oss:doctor` no longer reports the shared default watch socket as `OK ... Nothing is broken`. It
  is a WARN, because it is the state #191 measured with five events read, five forwarded, zero
  dropped and none delivered. The diagnostic also knows about the derivation the launcher now
  performs: nothing declared and nothing exported is two states, not one — a repo whose `.oss.json`
  carries a `repo` gets its own socket and is told the derivation only covers sessions the launcher
  opens, and a repo with nothing to derive from is told which of three reasons it was. Whether the
  process holding that socket is the server the session subscribes to is stated as *not
  established*, here or by `channel:health`, rather than left unmentioned (#191).
- `/oss:scaffold` writes a `.supertool.json` registering a `radar` tier, and the preset list it wrote
  beside it did not enable `watch` — which is what provides `radar`. Every repo this plugin
  scaffolded therefore received a board with no route to it: the ops load, a session opens,
  `channel:health` reports FORWARDING, and nothing can ever publish. That is byte-identical to a
  healthy board, shipped as the plugin's own default. The template now enables `watch`, and the
  plugin's own diagnostic reads the template in a test, so the two cannot drift apart quietly
  (#191). Found while implementing the diagnostic; outside that change's own footprint.
- `/oss:doctor` no longer accuses every managed repo of a hand-copied `SUPERTOOL_WATCH_NAME`. Once
  `bin/oss-workspace` began deriving that export from `.oss.json`'s `repo`, an export with no
  `watch_name` beside it became the ordinary state of the loop — and it is precisely the shape the
  `undeclared-export` warning was written to accuse, so the diagnostic started naming a remedy it
  would be wrong to follow. The state is split rather than deleted, because the copied case is real
  and must keep firing: an export equal to what this repo's own `repo` derives to is reported as the
  launcher's own export, one that differs is still the filed case, and a repo with no `.oss.json`,
  an unreadable one or no `repo` gets a third answer that accuses nobody and clears nobody. Neither
  this change's diff nor the launcher's shows the seam; it existed only in their composition (#191).

- The manager skill told a maintainer to record a verification with raw `gh pr edit --body-file`,
  and said in as many words that no op existed for it. Both halves were wrong. That call resolves the
  pull request through a GraphQL query that also asks for `projectCards`, a Projects (classic) field
  GitHub now refuses: it exits non-zero naming a field the caller never asked for and leaves the body
  unchanged. The command is loud and the *edit* is silent, so it reads as deprecation noise rather
  than as an unwritten body — and an unrecorded verification is indistinguishable from one nobody
  performed. Worse in the case the skill sends you there for: `gh-pr-create` refuses a body with no
  `Closes #N` at the earliest point anything can see it, and the documented repair then no-ops, so
  the pull request merges with the issue still open and the board reading clean. The section now
  names `gh-pr-edit:<N>:@FILE`, which already existed and was built for this: it writes through REST,
  re-parses the published body for the closing reference *before* writing in three states — survived,
  dropped, or could not be read at all — and compares the response against the bytes it sent
  *afterwards*, so only a write it read back exits `0`. The op table gained the row, and gained
  `[:full]` on `gh-pr:N`, because a plain read truncates a long body and an appended section sits at
  the end — the cheap read is the one that cannot see what it was called to confirm. Two facts the
  issue filed as unknown were measured rather than assumed, and both argue against the workaround it
  proposed: the field is refused for **every** repository, so this does not depend on classic project
  cards existing anywhere, and it is a `gh` version accident already fixed upstream (cli/cli#13069),
  so the raw call will start working again on its own and pinning a hand-rolled REST replacement as
  doctrine would have outlived the defect it routed around (#195).

- The shipped `01-oss` rule that blocks `Read`, `Edit`, `Write`, `Glob` and `Grep` handed a blocked
  agent `supertool 'write:PATH'` as the remedy for a refused `Write`, and there is no `write` op --
  so the one rule whose job is to answer "now what" answered with a call that does not resolve, at
  the moment the agent had just been stopped. The row now names `paste`, in both the payload form
  (`paste:@-`, fields `path` and `content`) and the inline one, and says what a reader needs to know
  to stop probing: `paste` creates missing parent directories and rewrites an existing file, so it
  covers both halves of a `Write` rather than only the create half (#197).
- Fixed in **both copies** — `scripts/oss_rules.py`, which is what `/oss:scaffold` installs into
  every managed repository, and this repo's own installed copy under `.claude/jit-context/`. A fix
  to one and not the other reaches nobody, or everybody except here (#197).
- `tests/test_shipped_op_spellings.py` closes the class rather than the line: every
  `supertool 'OP...'` spelling in shipped prose — skills, agents, commands, both copies of the rule
  layer — must be declared in an inventory carrying where it resolves, and every declaration must
  still be named by shipped prose, so a stale entry cannot sit there blessing a spelling nobody
  ships. It found two spellings beyond the reported one that no earlier sweep had read, because the
  extractor reads *every* argument of a batched call (#197).
- The check is three-state on purpose. `ops:roster` lists the ops **loaded here**, and which load
  depends on which presets a project enables, so an op absent from a roster is not an op that
  resolves nowhere: preset-gated declarations are measured only where that preset is loaded, and a
  roster that could not be read — no `supertool` on PATH, which is every CI leg — **skips naming
  how many spellings went unmeasured** rather than passing quietly. The declaration layer runs
  everywhere and is what fails in CI (#197).

- A self-review that ran and handed back an empty final message no longer renders as a review that
  found nothing (#200). `review.classes` and `review.findings` carry a fourth state,
  `returned-nothing` — distinct from `checked`, which claimed a clean review, and from
  `not-checked`, which claims nobody looked — and `scripts/report_schema.py` refuses it without a
  reason naming which spawn went quiet and what was lost. No other survey can spell it: a docs
  sweep has no second party to go quiet. `agents/developer.md` now says how to detect the empty
  return, allows exactly one fresh re-spawn that does not erase the first outcome, and records the
  decision against granting `SendMessage` to ask a reviewer to repeat itself.

- A workflow filename can no longer forge a row of `/oss:scaffold`'s receipt. `check_test_ci` built
  its `unreadable` detail with a bare `", ".join(...)` over paths walked out of the *managed*
  repository, four hundred lines from the `_join_names` flattener that shipped in the same delta for
  exactly this — so a file whose name carries a newline followed by
  `changelog OK: this repo already runs a gate.yml` (a self-referential symlink, which git tracks,
  and which reaches that arm through `ELOOP`) ended the `tests` line and put an invented `changelog`
  verdict at column 0. The paths now go through `_join_names`, and the whole `path (cause)` pair is
  flattened rather than the path alone, so the cause staying line-break-free is a property of the
  construction rather than of a fact continuing to hold. Every one of the four rows is now also
  flattened at the point it is printed, because #204 was a builder that forgot and a fifth row added
  later would be another. The same commit excused `check_changelog_label` on the grounds that forge
  label names "cannot carry a newline through the forge": that claim about GitHub's API was never
  established, and it is aimed at a value this function never prints — no label name is interpolated
  into either detail. What does reach the line is the `reason` from `_forge_label_names`, built out
  of `--root` and whatever `git` or `gh` wrote to stderr, and that is now flattened, which needs no
  claim about anyone's API (#204).

- `scaffold.check_radar` reads both halves of the question, and the remedy it prints no longer
  produces the state `/oss:doctor` refuses. Registration (`ops.radar.radar_tiers`) is half of a
  working board; the `watch` preset that routes the `radar` op reading it is the other, and this
  checker asked only the first — so a repo carrying tiers and no preset was called clean by the one
  thing that could still reach it, `.supertool.json` being a default that is never replaced. Worse,
  the remedy printed here named the tiers and not the preset, so a maintainer who followed it landed
  in exactly the `route-unknown` state `doctor` reports. `check_radar` now answers in six states —
  `unreadable`, `malformed`, `no-tiers`, `route-unknown`, `no-route`, clean — and the comment in
  `doctor.py` claiming its remedy was "the same remedy `scaffold.check_radar` names", false when it
  was written, is replaced by a test that writes scaffold's remedy to disk and asks *both* checkers
  about the result: a measurement rather than a second assertion that two strings match. A
  `.supertool.json` that parses as JSON and is not a config is now reported as `malformed` instead
  of raising `AttributeError` out of `/oss:scaffold` from a file any contributor can edit, and the
  absent-config arm is decided from the exception in hand rather than from a `Path.exists()` that
  returns False for a config it merely could not read. The `radar` row of the receipt, which nothing
  in the suite printed, is now covered (#205).

- `bin/oss-workspace` derived `SUPERTOOL_WATCH_NAME` from `.oss.json`'s `repo` with a character class
  of its own that permitted `.`, `..` and a leading `-` — the one consumer of that value in this
  plugin that did not route through `oss_config.repo_problem`, and the one that runs at session start,
  before `/oss:tick`, before `doctor`, before anything else validates it. `repo: ".."` derived the name
  `..` and `repo: "../../etc"` derived `..-..-etc`, each of which the consumer turns into a socket path
  and a poller state directory. `.oss.json` is tracked, so the value arrives by ordinary contribution.
  The derivation now lives in `oss_config.watch_channel_name`, which validates before it folds and
  **refuses rather than sanitises** — the fourth arm of a shape the launcher already had: no
  `.oss.json`, an unreadable one and one declaring no repo each derive nothing, say so on stderr and
  open the session anyway. Exiting over a bad config would trade the product for an enhancement, and
  substituting another name would invent a private socket nobody publishes to. Two consequences worth
  knowing: a `repo` with whitespace around it is now refused where it used to be folded into a name,
  and `scripts/doctor.py` no longer carries the second spelling of the fold its own docstring asked to
  have deleted — it reads the same function, and reports two new states, `refused` (the value is
  invalid, so the remedy is to correct it rather than add a key) and `no-validator` (the diagnostic
  could not import the validator, which is a hole in the tool rather than in your config) (#207).
- Whether such a name would have *traversed* was left unestablished by the report, and it is now
  measured rather than assumed: supertool 0.46.0 applies a name pattern of its own to
  `SUPERTOOL_WATCH_NAME` and refuses `..` outright. So the harm that is observed is not traversal — it
  is a launcher handing its consumer a name the consumer discards, putting the session on the shared
  default socket by a route nothing reported. Which of the two it is depends on a version of somebody
  else's package; that the value was never validated does not (#207).
- `/oss:doctor`'s `refused` message escapes the offending repo value before it reaches `report()`.
  That funnel replaces anything outside printable ASCII with `?`, which is the right guard and stays
  the authority — but a CJK repo then rendered as `repo-??`, a receipt reporting that a value is
  wrong while making that value unidentifiable, and the remedy is to correct that exact value (#207).
- The doctor suite popped `SUPERTOOL_WATCH_NAME` for the same reason it already pins `PATH` and
  `HOME`. `doctor.main()` reads the real environment and `bin/oss-workspace` exports that variable into
  every session it opens, so `test_verdict_says_ok_only_when_nothing_warned` was red for anybody
  running the suite from inside a maintainer session — correctly, about their machine — and green in
  CI, which exports nothing. Found while fixing #207 and unrelated to its mechanism (#207).

- `/oss:tick`'s watcher step now runs the heal as well as the probe, and the heal carries its own
  three outcomes. #187 ordered `radar:--state` and left the bare `radar` in prose with no outcome
  named for it, so every state the step could report was a state of the *probe*: a heal that
  errored, a heal that refused for want of a registered tier, and a heal that found nothing to
  repair all left the tick with nothing to say, which is indistinguishable from a fleet already up.
  The step now invokes `supertool 'radar'`, and reports *raised* with its counts, *not configured*
  as the correct state for a repo that never opted in rather than as a failure, or *could not
  raise* naming which — the `watch` preset absent from `presets`, which `/oss:doctor` reports as
  `no-route` and not as its `route-unknown`, or a spawn that errored. Two readings travel with it:
  a resolved tier over an empty poller list is the case the heal exists for and not the absence of
  a fleet, and the probe's warning that an undeclared `watch_name` leaves the channel named by the
  environment is relayed rather than swallowed, because the heal is a write into whatever that name
  resolves to (#208).

- The documented report-validation command ran the *installed plugin cache* against a report written
  to the *clone's* schema, so a correct report was refused and the refusal read as a finding about
  the report (#212). `${CLAUDE_PLUGIN_ROOT}` resolves to whatever version was last installed —
  measured here, the cache at `0.3.0` answered `<report>: unknown key 'docs'` where the clone at
  `0.4.0` answered `ok`, naming as an error the field the current schema requires. An agent that
  trusted it would have edited a correct report until an obsolete schema accepted it.
  `agents/developer.md` now tells the agent to run **both** copies when both exist and separates the
  outcomes that are about the report from the ones that are about the tooling. The ordinary managed
  repository, where only the cache exists, is named first and is unchanged: that copy's answer is
  the answer. Where two copies both ran, a disagreement is named as schema skew, recorded as an
  `adjacent` `tooling:` item, and never absorbed into the report; and *neither copy ran* is a third
  state with a recording duty of its own, because a run that could validate nothing and a run that
  validated clean otherwise reach the maintainer as the same silence. Which copy is authoritative is
  decided by `.claude-plugin/plugin.json` naming this plugin, not by a local
  `scripts/report_schema.py` merely existing — a coincidence of filename is not a claim of
  authorship, and in a managed repository the cache is correct and is the only copy there is.

- A filename in the managed repository's own `01-oss` rule layer can no longer forge a row of
  `/oss:scaffold`'s receipt — including the run's own `WROTE:` summary. `plan_rules` built its
  `remove` rows from a bare `"{}/{}".format(...)` over names walked out of that repository, and
  two print statements put those rows on stdout without flattening, so a file whose name carries a
  newline followed by `WROTE: 0 template(s), replaced 0 file(s) in the 01-oss rule layer` produced a
  second `WROTE:` line eleven lines above the real one — and a reader taking the first was told
  nothing had been written by a run that wrote 14 files and replaced 7. This is #204's class a
  second time: `1f6232b` (#182) added these rows, `d02e95a` (#204) flattened four *other* rows and
  its message said every receipt row was covered — each commit correct alone, the defect only in the
  composition. Fixed at the chokepoint rather than at the two prints: the repository-derived name
  is flattened at the one place it enters `plan_rules`' `entries`, so every consumer — both
  prints, `--show`, `doctor` — inherits a single-line `path` without having to remember, and the
  next print statement added is not in the position these two were. Flattened after the
  `present - shipped` comparison rather than before it, so a name differing from a shipped one only
  in whitespace cannot collide with it and silently lose its removal row. The tests assert the
  rendered receipt on both the plan and the `--apply` path — every line begins with a label the
  receipt really uses, and there is exactly one `WROTE:` line, reporting non-zero counts — paired
  with a must-fire assertion that the filename is still reported, since a fix that dropped the name
  would satisfy every negative assertion and tell a maintainer nothing. The fixture is a
  measurement: a newline in a filename is refused by some filesystems and by Windows, and each arm
  skips carrying the errno and what went untested rather than asserting against a table of platform
  error codes (#223).

### Security

- Report validation is contained to the directory of the report it was handed. `pr_body.path` is
  written by an agent and the file it names is opened, parsed and quoted back by the maintainer's
  own process — an unknown key is echoed by name, and a value is echoed wherever a `const`, an
  `enum` or a type mismatch fires — so the path decides which files that process reads and reports
  on. It is now resolved against the report's own directory and refused, without being opened, when
  it lands anywhere else. An absolute path is still accepted, which is what an agent working in a
  worktree writes: what is checked is where the path resolves to, not how it is spelled, and both
  sides are resolved, so a symlink pointing out of the directory is refused too. Containment that
  cannot be decided — no directory to anchor against, or a path that will not resolve — is a
  refusal carrying a sentence rather than a read that nothing objected to. The refusal names the
  path through a one-line sanitiser, since a receipt whose rows are `ok <file>` and `INVALID
  <file>` can be forged by a newline in a value chosen elsewhere. No `pattern` was added to the
  schema: containment depends on where the report itself is, which a regex cannot see, and a second
  checker answering a narrower question about the same input is its own defect. The capability
  predates `v0.4.0`; what changed in this range is that the documented verification call moved from
  the payload path to the report path (#201), which is the route that reaches it — so the delta
  contains this and neither commit does (#232).

## [0.4.0] - 2026-08-15

### Added

- `/oss:doctor` now reports whether the installed `claude-jit-context` actually reads this plugin's
  `01-oss` rule layer, measured against the hook scripts on disk rather than inferred from a version
  string. Four states, and the third is the point: *reads it*, *does not read it* — a WARN, because
  every rule in the layer is then written, indexed, listed by the check above it and read by nothing
  — *could not determine*, and *this repo has no such layer*. The negative arm requires a complete
  read: a hook file that would not decode, a dependency missing from the install record, or an
  unpacked tree that is not there yields *could not determine*, never a verdict (#119).
- The check looks for a *fixed layer list* by shape — a quoted run of layer-shaped tokens — not for
  the string the hooks hold today. When the upstream fix (Digital-Process-Tools/claude-jit-context#176)
  removes that list, the answer becomes *could not determine* rather than a permanent false *does not
  read it*, which would be #119 inverted and harder to notice because it is the answer everyone
  already expects (#119).

- A repository can declare its untagged releases in `.oss.json` under `changelog_untagged`, a list
  of `x.y.z` versions, and the scaffolded `oss-changelog.yml` renders them into its `--check-links`
  invocation. Before this the declaration had exactly one home — a command line — and the workflow
  that needed it is an owned file rewritten in full by every `/oss:scaffold --apply`, so a managed
  repository carrying a `## [x.y.z]` section for a version that was never tagged had three options
  and all three were bad: edit an owned file and lose it, fork the workflow out of `.oss/` and give
  up every upstream fix to it, or delete real history to satisfy a linter (#121, #101).
- The key carries three states rather than two, and they stay three all the way to the receipt.
  Absent or `null` is "nobody declared anything"; `[]` is "this repository has declared that every
  release section was tagged"; a list names the exempt versions. The first two audit the file
  identically and only one of them is a decision, so `--check-links` now names which of the three it
  was given — on `ok` and on a refusal alike, because a finding about a missing link ref means
  something different depending on whether anybody had answered the question. The generated workflow
  and the shipped `changelog-fragments` rule both say which state they were rendered from.
- The value is refused at validation rather than escaped at the template: it is interpolated into a
  `run:` line of a workflow written into somebody else's repository, and a version is `x.y.z` and
  nothing else. `v0.1.0`, a bare string where a list belongs, and anything a shell reads as an
  instruction are each named and refused, the same treatment `changelog_dir` has had since #31.

- `agents/developer.md` states four rules about *doing* the work that it previously only
  discharged when writing it up: build the third state rather than only reporting it, with the
  loud-bug-for-quiet-bug and shadowed-defect traps beside it; when to fix an adjacent finding and
  when to file it, in the vocabulary `adjacent.action` already enforces; two cross-platform rules
  about the fix, placed inside the section the auditor is handed verbatim; and that a supertool
  payload is parsed and never evaluated, so `chr(10)` in a `new` field writes seven characters
  (#141).

- `/oss:doctor` reports which watch channel a repo actually resolves to, in eight states rather
  than two. A `watch_name` declared in `.supertool.json` while `SUPERTOOL_WATCH_NAME` resolves to
  something else is invisible today, and so is the case that was actually filed: several repos
  declaring nothing at all with one hand-copied export between them, sharing a single poller slot
  while each board renders as its own fleet (#150).
- The states are kept apart on purpose. `unreadable` is not `declares none`, an export over a repo
  that declared nothing is not the shared default, and an explicit `SUPERTOOL_WATCH_SOCK` or
  `SUPERTOOL_WATCH_STATE_DIR` is reported as overriding the name rather than folded into a green
  line about a comparison that decides nothing (#150).
- Channel configuration itself stays out of `.oss.json`. That file describes a repo's release and
  review process and a watcher socket is neither; `.supertool.json` already carries the name to
  supertool's own ops with no plumbing on either side, so a second home for it would only be a
  second thing to disagree. What was missing was the report, not the setting (#150).

- The manager skill now states the pull request payload contract it consumes, rather than leaving it
  only in `agents/developer.md`. `title`, `body`, `head` and `base` arrive filled in, so retyping
  them is redundant work — and the hand-written value is the only one nothing downstream verifies.
  Measured before the fix: ten pull requests in one day where `head` and `base` were both
  overwritten and all twenty values were already correct (#161).
- The same section says how far the validator actually gets, because "already checked" was not one
  claim but two: `head` is compared to the agent's own reported branch, which is internal
  consistency rather than ground truth, and `base` is checked for presence only — nothing compares
  it to `default_branch`, and it is the field whose corruption merges into the wrong branch. Nothing
  in the loop runs the validator either, so the maintainer is reading a claim rather than observing
  a check, and the section names the one call that turns the first into the second (#161).
- Reading `pr_body` is documented as three answers rather than two, in the skill and in
  `commands/tick.md`, which sequenced only the `written` case. A payload that could not be read is
  neither `written` nor `not-written`, and it is never "no pull request to open" (#161).
- A maintainer who verified something the agent could not now has somewhere to put it: a
  `## Verified by the maintainer` section appended at review time with `gh pr edit --body-file`.
  The existing rule that the person who did the work writes the record left rewriting the agent's
  text as the only way to record a verification, which is what that rule forbids. An absent section
  says nobody verified independently, not that verification found nothing (#161).
- Two ways a pull request body silently references less than it appears to are named where the body
  is published: a backticked issue number does not autolink at all, and a closing keyword binds one
  issue, so `Closes #A #B` links both numbers and closes only the first. The merge-gate bullet
  advising "each with its own `#`" was describing the other case and read as a remedy for this one;
  both now say the keyword is what repeats (#161).
- `tests/test_content_invariants.py` joins the consumer to `schemas/agent-report.schema.json` rather
  than to the prose example, so a required payload field the manager skill never names fails the
  suite — and a join between two prose copies cannot stay green while both drift off the schema
  (#161).

### Changed

- The two class vocabularies the plugin ran are now joined. `agents/auditor.md` searches by letter
  (A/B/C, the platform band) and the manager skill ranks by row (`destroys`, `discloses`, and the
  rest), and nothing connected them — so a row could be ruled on in the ranking and searched for
  nowhere, which is this plugin's own defect class one layer up. They stay two vocabularies on
  purpose, because a search strategy and a severity are different things and the map between them is
  many-to-many; what is new is the join at the report, where every finding now carries both the
  letter it was found by and the row it ranks in (#83).
- The ranking table gained `containment (write)`, `forges`, `ships-local-state`, `misdirects` and
  `splices`, and `containment` split into a read row and a write row. Each is justified against a
  route this plugin actually has — a fold that rewrote the wrong repository's changelog, a
  machine-local value shipped in a release, a config value reaching `git describe --match` — rather
  than imported from another project's audit history (#83).
- The rule that decides which row a finding belongs in is written down for the first time: each row
  earns its place because each invites a different fix. Rows are a record of what has already gone
  wrong, never a partition of what can, so a brief must not be tuned toward the table. The rule is
  what makes "say so if a finding fits none of these" a ruling rather than an opinion (#83).
- `unranked` and `could not rank` are now separate answers in both audit briefs. A finding nobody
  could rank because the table never reached them used to render exactly like one that was ranked
  and fitted nothing (#83).
- The two-round audit cap no longer quietly outranks the ranking table. Gate 3,
  `agents/release-auditor.md` and `commands/release.md` all ended round two by filing whatever
  remained and shipping over it, while the table said some classes block unconditionally; the later
  sentence won. A finding in a blocking row is now not carry-forward material and stops the tag in
  either round (#83).
- `agents/triager.md` no longer carries its own copy of the class table. It had five rows, no
  read/write split on `containment`, and a sentence saying "the first three outrank everything" —
  which the moment the table grew was a confident, complete-looking taxonomy that no longer matched
  the one the release gate reads. It now reads the table where it lives, and states what to do if it
  could not (#83).

- `/oss:setup` now ends by *running* scaffold's read-only plan rather than naming `/oss:scaffold` in
  a closing paragraph, so the furniture gap arrives as a measured per-file list — `create`,
  `present`, `replace`, `decline` — instead of a recommendation to go and look. The plan writes
  nothing; every write still happens only under `/oss:scaffold`, on a branch, with a diff. A plan
  that could not run is reported as **unmeasured** and never as *nothing to do*, and it does not turn
  a successful config write into a failed setup — the `.oss.json` is already on disk. Those per-file
  lines are read from the filesystem and answer with no network; the `label` finding is the one line
  that asks the forge, and it degrades to its own stated `unknown` rather than to silence (#136).
- `tests/test_command_references.py` now asserts that `commands/setup.md` carries a scaffold
  invocation, that it is never the writing one (`--apply` / `--force-owned`), and that the file
  states all three plan outcomes. The identical seam at `/oss:scaffold` to `/oss:tick` stays prose:
  a tick is not read-only and cannot be previewed, so there is nothing to measure, and
  `commands/scaffold.md` now says that out loud rather than leaving one closed seam reading as two
  (#136).

- The triager knows that `gh api -X PATCH .../issues/N -f 'labels[]=…'` **replaces** the label set
  rather than adding to it. The brief prescribed `gh issue edit --add-label` and said nothing about
  the PATCH form, so nothing warned an agent off the call that removes every label it does not name —
  silently, exit 0, output indistinguishable from a successful add. Measured on another tracker: a
  PATCH setting an issue's priority and lane deleted its cohort label, and a freeze verified minutes
  earlier was wrong with nothing anywhere saying so. The additive routes are now named explicitly
  (`--add-label`, or `POST issues/N/labels`), and the triager is told to take any label tally *after*
  its own last write, since a count taken before it describes a board that no longer exists (#137).
- The triager gained the cluster duty: name every set of two or more issues that one change would fix,
  with one test story, the numbers, the sentence they share and the issue that should survive as the
  parent. **Propose only** — and that constraint is prose because it has to be: the withheld `Edit`
  and `Write` tools close the filesystem, but `gh issue close`, `gh issue edit --body` and
  `gh issue comment` are ordinary `Bash` calls and stay reachable, so the tool grant does not enforce
  it. Clustering is on the mechanism and never on the title, each cluster states whether it rests on a
  mechanism the triager verified or a cross-reference taken on trust, and a cluster crossing a cohort
  boundary is reported rather than proposed, because a duplicate-merge is a write to a frozen
  burn-down under another name. Scoped for a small single-package board on the way in: where every
  issue touches the same handful of files, a shared filename is not a shared failure, and a cluster
  that cannot state its shared failure in one sentence is not proposed (#137).
- The triager's `Clusters` row has three answers, not two — the clusters, `none`, or `could not look`
  with its reason and its numbers. A board with no clusters and a board nobody finished reading render
  identically as an absent row (#137).
- The triager reports the cohort burn-down every run, with the limit it counted under beside the
  number, because a partial read renders as a total and a cohort that appears to shrink when it has
  not is worse than no number. It also never *removes* a cohort label, only ever reports one: a label
  on an issue filed after the freeze is a finding, not a correction (#141).
- Three further triager rules the brief had been leaving to the model: a shipped milestone ends at
  zero and anything still open on one rolls forward; checking whether something shipped means grepping
  the issue number with a word boundary after it rather than a paraphrase of the title; and a grep
  answers about the working tree it stands in, so the tree wants updating first — **unless another
  agent is working in it**, where the triager states which commit its grep answered about instead of
  moving `HEAD` under somebody's running suite (#141).
- The triager may argue with the ranking table. A model handed a table and never told it may disagree
  applies the table; the developer brief has always had `Push back` and this one had no equivalent
  (#141).
- The loop measures its own intake: **filings per merged pull request**, recorded in the state entry
  every tick. The cohort labels measure the drain and nothing measured the fill, so the board's
  growth was a feeling. `scripts/oss_state.py` gains `--filings`, `--merged-prs`, `--window` and
  `--trend`, and it **stores the pair rather than the quotient** — 1/2 and 3/4 do not average to the
  ratio over six pull requests, so a history of quotients cannot be re-added, and a metric nobody
  can recompute is a claim. The denominator is stated with the number every time: pull requests
  merged since the last tick, against issues the loop itself filed in that window, because folding
  in a maintainer's own filings inflates a numerator the loop has no lever on. Four states, and the
  interesting ones are the last two: a ratio of `0.0` is `measured` and is a finding, nothing merged
  is `no-denominator` rather than a ratio of zero, a count nobody could take is `could-not-count`
  and carries its reason, and a `--trend` mixing counted and uncounted ticks is `partial` rather
  than a sum passing as the range's total. **No target ratio is claimed anywhere and none may be
  added from one sample** — one project measured roughly 3 and one day of another measured roughly
  0.6, and whether that gap is a healthier codebase, a shallower review or the two ends counting a
  "filing" differently is not knowable from either number (#137).
- A sweep for the counting trap that sits beside that metric: `gh api … --paginate --jq 'length'`
  runs the filter once per page and prints **one number per page**, never a total — measured `98`
  then `13` against a real total of `111`, correctly formatted, at exit 0. **Nothing in this tree
  does it today**, which is exactly why the sweep exists rather than a comment: a trap documented
  against code that does not exist is one nobody recognises when it arrives.
  `tests/test_paginated_counts.py` reads every tracked *and* untracked-but-not-ignored script,
  workflow and fenced Markdown block — a sweep of only what is committed answers clean about a
  script somebody just wrote — and it distinguishes a command from a sentence about one, so the
  triager's own documentation of the trap is not a finding. Three outcomes, with the vacuity case
  folded into the failure: a sweep over nothing is trivially clean, and `clean` is what it must not
  be allowed to say (#137).

- The ranking table gained a second verdict column, and the two upstream-filing passages route on it.
  `skills/manager/SKILL.md` and `agents/developer.md` both sent a finding in a **release-blocking**
  row down the embargo path when reporting a defect to a dependency, and those are not the same set.
  Blocking a tag asks what this project may ship; an embargo asks whether a reporter should hold
  disclosure while a fix is written. `ships-local-state` blocks a tag precisely because the release
  is the mechanism by which it takes effect — which makes it public the instant it ships, so there is
  no window of private knowledge for an embargo to protect, and routing it privately over-applies a
  promise about somebody else's disclosure timing. The fix keeps the instruction that was already
  correct beside it — *read the rows off the table when you route* — and points it at the right
  column: the table now answers **Blocks a release?** and **Embargo when reported upstream?**
  separately, with the one disagreeing row carrying its reason in the cell. Neither document
  enumerates the classes, which is what a restated copy would do and what the sentence was warning
  against. `tests/test_embargo_routing.py` parses the table rather than grepping for a sentence — a
  prose anchor passes against a document that contradicts itself three lines later — and pins the
  difference to exactly the one recorded row, so a class joining or leaving either set fails here
  (#139).

- The triager's cohort burn-down has a third state. #148 gave it the duty, the counting trap and the
  limit to state beside the number, and stopped at two answers — a count, or nothing. A run that
  could not take the count had nowhere to say so, so the only shape left for it was silence, and an
  omitted burn-down reads exactly like a backlog that has finished. It now answers in three:
  the count with its limit, `no cohort label exists on this board` as a measurement, or
  `could not count` with the reason — and a could-not-count must never render as `0 open`. The row
  is required in `Report format` beside `Clusters`, rather than only described under what to
  surface, because a duty nobody has to render is one that renders as nothing (#141).
- `commands/triage.md` told the maintainer the triager's report had four parts and never named the
  burn-down among them, so the one number that says whether the backlog terminates was something
  only the agent had been told about. It is the fifth part now, with its three answers, the
  after-freeze `cohort-*` finding beside the other board-level ones, and the rule that a number
  arriving without the limit it was counted under is not an answer (#141).

- The manager skill and the developer agent now state that a defect found in a **declared
  dependency** is filed on that dependency's own tracker, and that doing so is part of finishing
  the work rather than a decision about somebody else's roadmap — the refusal that left a
  confirmed, reproduced cross-repo defect unreported. Which trackers those are stays data: the
  skill points at `declared_dependencies()` and `dependency_repositories()` in `scripts/doctor.py`
  instead of naming any repository. The rule is bounded to declared dependencies, splits a
  dependency the same maintainer owns from an arbitrary third-party one where a public tracker is
  a disclosure channel, routes a finding in a blocking ranking row to the security policy's
  embargo path instead of a public issue, and carries three outcomes — filed, could not file, and
  deliberately not filed with the reason. The developer reports upstream defects to the maintainer
  in `adjacent` and never opens the issue itself, because opening one is publishing (#143).
- The manager skill's freeze step now says that `gh api -X PATCH issues/N -f 'labels[]=…'` replaces
  the whole label set, so a later priority or lane write silently deletes a cohort label with exit
  0 — and that the cohort is re-counted after the last label write of the tick, not before it. The
  release gate now resolves the commit with `git rev-parse` before asking which workflows ran:
  `gh run list --commit <short-sha>` answers `[]` and exits 0 where the full 40-character sha
  returns the runs, and an empty run list is indistinguishable from a commit no workflow ran on
  (#137).
- The developer agent now states that the full suite is optional while the targeted red-then-green
  is not, with the criteria for when the full run is worth the wall-clock, an unconditional
  mandatory run after a rebase onto the default branch, and the anti-pattern of re-running the
  whole suite to watch a failure already seen. It also carries the UX-friction duty: every friction
  hit while using the ops is reported, one line each, in `adjacent` — signal nobody else can see
  (#141).
- Both documents now tie a file-convention change to the repo's own diagnostic: a convention is not
  finished until `scripts/doctor.py` reports the new convention, satisfied either by editing it or
  by a derivation it already consumes — which the developer must name rather than assume — and with
  a third arm for the diagnostic being held by another lane, where the required change is written
  out for the maintainer to sequence instead of being reached for or dropped. The maintainer's
  review list gains one line in the blast-radius check rather than a new item. The failure this
  prevents lived in the composition of two individually correct commits and no per-diff review
  could see it (#126, #143).

- The manager skill now names the op that answers worktree ownership, in the reads table and in both
  places the loop asks the question. The removal gate reads occupancy and merge state before it
  reaps — three states each, where `cannot tell` is not `idle` and `merge unknown` is not `merged` —
  and carries the squash-merge blind spot the branch bullet beside it already named, since ancestry
  cannot see a squash merge for a worktree branch either. It also carries the exit-code caveat
  measured against the op: supertool collapses the script's exit to 0/1, so `cannot tell` arrives
  indistinguishable from `occupied`, and a shell that has to tell them apart runs the preset script
  itself. Until now the skill's own instruction routed the reader into a raw listing the tool refuses,
  and the recovery was hand-typing a path list (#145).
- The liveness hazard keeps every piece of its doctrine and gains the op as the thing that implements
  part of it: an agent is live until it says otherwise, an empty scan is no evidence rather than weak
  evidence, and a task notification is the only thing that ends a run. The op is named as the scan,
  not as the verdict — `idle` is a reading of the tree at one instant and never a statement about the
  run — because replacing the reason a rule exists with a tool name is how the rule stops being
  followed once the tool answers something unexpected (#145).

- `CLAUDE.md`'s "What is not proven yet" section is re-derived rather than rewritten, claim by
  claim, against the tree at seventeen merged pull requests past `v0.3.0`. It opens with the release
  and commit it was measured at, and grades every claim `observed` or `reasoned`. The headline ratio
  "one real use, two findings" is retired: the repository it was computed from carries no committed
  `.oss.json`, so that run is unobservable from outside and the ratio was a measurement only in
  presentation. What replaces it came out weaker, not stronger — `/oss:setup` has reached three
  repositories, `/oss:scaffold --apply` has reached one (#159).
- The section's claim that nothing tells a maintainer to re-run `/oss:scaffold` is split rather than
  deleted: false as written, since #147's setup plan and `/oss:doctor`'s `owned_drift` both say so
  now, and still true in that nothing schedules either. The failure mode itself stays unobserved,
  because no repository outside this one has owned files that could go stale (#159).
- `tests/test_claude_md_currency.py` asserts that the section names the release and the commit it
  was measured at, and that the release has a `CHANGELOG.md` heading. It cannot assert that a claim
  is true and does not try — it converts a section that goes stale silently into one that goes stale
  visibly. Checked by shape and against the changelog rather than by asking git, because the test
  workflow checks out at depth 1 and no tag or historical sha resolves there. Each detector is
  exercised against prose that carries a marker and prose that does not, in the same fixture (#159).
- One entry in the traps list is corrected in the same pass: `release_delta.py`'s `_read_config` was
  annotated "grep it there until that merges", and #76 merged as `3e5f6c4`. The rest of the list was
  checked referent by referent and every entry still names something in the tree (#159).

- `CLAUDE.md`'s "What is not proven yet" is re-derived at `9aed28e`, twenty-eight merged pull
  requests past `v0.3.0`, rather than patched where it had gone false. The section's own instruction
  is to re-derive it at each release; #159 exists because the alternative was taken once already
  (#181).
- **The rules are no longer inert.** The section stated, graded observed, that every rule under
  `.claude/jit-context/*/01-oss/` was unread and that nothing in this repository could change it. The
  second half was right: `claude-jit-context` 0.4.0 reads layers off disk in byte order instead of
  joining a fixed list, so `01-oss` fires. `doctor`'s jit-layer check — added by #156 in the same
  delta as the sentence it contradicted — reports it reachable, and firing `pre-tool-hook.sh` here
  blocks a `Read` and passes a `TodoWrite` in the same tree. `Read`, `Edit`, `Write`, `Glob` and
  `Grep` are refused in this repository; every file operation goes through supertool (#181).
- **Furniture-writing has reached three repositories, not one, and it was three when the last
  measurement said one.** That survey selected its population as the repos carrying a committed
  `.oss.json` and reported a conclusion about every repo, so a repository scaffolded two days before
  `v0.3.0` was never in the sample — the plugin's own defect class, inside the section that guards
  against it (#181).
- **Owned files going stale in the field is no longer unobserved.** Both scaffolded repositories
  carry a `.oss/assemble_changelog.py` that differs byte for byte from what `/oss:scaffold` would
  write today. The failure mode is measured; the repair is not, since nothing schedules either
  command (#181).
- Two smaller corrections in the same pass: the dogfooding verdict is `4 failure(s), 5 warning(s)`,
  not six, and the marker names `v0.3.0` because the release commit is a descendant of the commit
  measured and does not exist yet (#181).
- No test was added. `tests/test_claude_md_currency.py` is presence-only by design and could not have
  caught this; a test asserting the prose agrees with a `doctor` check would state the same claim
  twice and pass whenever both were wrong together. What caught it was a second measurement, not a
  second assertion. The one claim a local test could hold — the drift table's "would write today"
  row — is named in the section as a declined guard rather than an impossible one, because it would
  fail every unrelated pull request touching `scripts/assemble_changelog.py` until somebody edited a
  number in `CLAUDE.md` to go green (#181).

### Removed

- `ci.required_checks` is gone from `.oss.json`. It was a measurement that cannot be taken:
  the only quantity derivable without a run is the workflow *job declaration* count, and this
  repo's own config was the proof that this is not the merge gate's number — three declarations
  against fourteen check runs, because a 3x4 matrix expands one declaration into twelve. A guard
  asserting agreement between the two would have gone green over a value wrong by eleven. Beyond
  a static matrix it is worse: a reusable workflow declares nothing locally, an organisation- or
  app-level check never appears in `.github/workflows/` at all, and a run that has not happened
  declares nothing either. `/oss:setup --probe` no longer emits the key or the NOTE that used to
  caveat it, and `/oss:scaffold` no longer reports it as stale. Count the legs live, off the pull
  request they apply to (#113).
- Removing the key is not a breaking change: an `.oss.json` already carrying it still validates,
  and `/oss:doctor` names it as safe to delete rather than leaving a dead measurement on disk
  looking exactly like a live one (#113).

### Fixed

- A spawn whose `subagent_type` does not resolve is now `could not run` in the documents that
  dispatch one, with a named fallback rather than a dead end. `commands/release.md` sent the
  release-blocking security audit to `oss:release-auditor` and `agents/developer.md` sent each
  developer's self-review to `oss:auditor`; when a name does not resolve the spawn errors, and an
  error nobody quoted reads exactly like an audit that found nothing — so a release could pass a
  gate that never ran. Both now say to quote the spawn error, re-dispatch to `general-purpose` with
  a pointer to the definition file, and stop if that does not run either (part of #81).
- `/oss:doctor` says something about agents, having previously said nothing at all. It names every
  shipped agent file, confirms every `oss:` name the plugin's own documents spawn has a definition,
  and states in the same line that whether this session can dispatch to them cannot be determined
  from a script — plus `/reload-plugins` as the remedy for the one failure anyone has observed. An
  installed-but-unreloaded session resolves all seven skills and none of the four agents, which
  reads as a working plugin with a broken `agents/` directory and has already produced two wrong
  bug reports against this repo. `README.md`'s install step names the reload for the same reason
  (#140).

- `commands/changelog.md` documents `--untagged`, which it had never mentioned — the flag that
  decides whether the link-ref audit refuses was absent from the one surface a maintainer reads
  before running it. A new guard in `tests/test_command_references.py` reads the flags
  `assemble_changelog.py`'s parser actually accepts and holds them against that file, so a flag the
  script gains and the docs never mention is a failure here rather than a discovery in someone
  else's pull request. It has three outcomes: documented, exempt with the reason written down, or a
  finding — an exemption list with no reasons is the same silence one indirection further away
  (#101).

- The git-ignore probe in `scripts/oss_config.py` answers about paths whose bytes the locale cannot
  decode, instead of raising out of a function whose whole contract is three states. It ran
  `git check-ignore -v` with `universal_newlines=True` — the legacy spelling of `text=True`, so
  `subprocess` decoded with the locale encoding, strictly — under an `except OSError`, and
  `UnicodeDecodeError` is a `ValueError`. What that call carries is **pathnames**, the one place a
  byte the locale cannot decode is ordinary rather than exotic, so `--split` crashed on a repository
  whose paths are fine and whose bytes are not. The fix reads bytes and decodes UTF-8 with
  `errors="replace"` at the point of use rather than catching the error: the exit code already
  carries ignored/clear/unknown, and the `-v` detail this function returns is the source rule before
  the tab while the undecodable pathname is everything after it — so the answer is now *correct*
  rather than merely well-reported as `unknown`, which would have rendered a limit of the tool as a
  fact about the repository. The two sibling calls in the same file with the same spelling — the
  shared `_run` helper, which carries `git ls-files` output, and the test-command probe, which
  carries an arbitrary suite's output — are fixed the same way. `unknown` gains a second, distinct
  reason for the `ValueError` that stays reachable: a name subprocess will not put in an argument
  vector at all is not a missing git binary, and folding the two together sends someone to install
  something that is already there (#112).

- The `01-oss` jit-context rule layer stops describing changelog machinery that the same run
  deliberately did not install. `/oss:scaffold` declines the owned changelog trio when a repo already
  runs a gate under another name, and then installed a rule whose could-not-locate branch told the
  reader that `/oss:scaffold` vendors the checker and would rewrite the rule — the command that had
  just declined, and that declines again. The clause was false in exactly the repository the decline
  produces, and it rendered identically to the same sentence in a repository where it is true. Neither
  the commit that taught the scaffold to decline nor the commit that taught the rule to name the
  assembler contains that defect; only the pair does. `oss_rules.install()`, `rules()` and
  `changelog_fragments()` now take the `(state, detail)` pair from the same gate detection the decline
  was made from, and the branch renders four sentences rather than one: no gate found (the scaffold
  vendors it — unchanged), a gate found under another name (it will not put one here, it does not know
  that gate's command, read the workflow it names, `--force-owned` installs ours alongside), the tree
  could not be fully read (why it is missing is *unknown*, which is not the same as this repo having
  no gate), and no gate argument at all (why it is missing *was not established* — the default, and
  the honest answer for a caller that did not look). The layer still ships whole: omitting the rule in
  the declined case leaves the reader with no statement at all, where the defect was a statement about
  a different repository. `--force-owned` deliberately passes no gate state, because the trio was
  written and reporting a decline there would be the same false sentence pointing the other way. A
  state this module does not recognise raises rather than falling through to the branch that claims
  nobody looked, and the repo-derived detail is flattened and stripped of backticks before it is
  dropped into a Markdown code span (#117).

- `/oss:scaffold` and `/oss:doctor` can now report a directory they were not allowed to read, instead
  of crashing on one and silently mistaking the other for an empty repository. `Path.is_dir()` answers
  True for a directory that exists and cannot be entered, so the guard passed and the `iterdir()`
  behind it raised `PermissionError` through doctor's *exit 0 always, one VERDICT line* contract;
  separately, `Path.rglob` swallows a permission error while walking and yields nothing for the
  subtree, so the `except OSError` written to catch that could never fire, and "read the whole tree,
  no changelog gate here" and "could not finish reading the tree" were the same answer — with the
  owned changelog trio written into the repo on the strength of it. The workflow scan now returns what
  it could not read alongside what it found, the tree walk is `os.walk` with an `onerror` callback,
  and the plan `decline`s rather than replacing. The `ci` and `tests` findings gained the same third
  state from the same scan, so an unlistable `.github/workflows/` no longer reads as a repo with no
  CI (#124).
- The changelog-gate scan stops counting a bytecode cache as evidence that a gate runs. A
  `__pycache__/assemble_changelog.*.pyc` is gitignored, so it cannot reach anyone else's checkout,
  and a tree whose assembler was deleted while its cache survived declined the owned trio on the
  strength of the stale artifact alone. The skip list already said derived trees are not evidence —
  it named `dist` and `build` and was missing the Python one — and it is now matched at every depth
  rather than on the first path component, without which the entry would do nothing, since
  `__pycache__` is never top-level. A dangling symlink is likewise no longer a signal, and a name
  that cannot be stat'd at all reports as unreadable rather than as a gate (#124).

- `scaffold.py --force-owned` is honoured by the plan and the preview, not only by `--apply`. It was
  a parameter of `apply()` alone, so a repo with a changelog gate of its own printed three `decline`
  lines each advising the flag that had just been passed, and `--show` previewed nothing at all for
  the three files the next command was about to overwrite — which is the preview a maintainer runs
  precisely because they are about to force past a collision. `plan()` takes the flag and decides
  once; `apply()` and `show()` both read that decision, so the three can no longer disagree. Forcing
  past a detected gate and forcing past a tree that could not be fully read are both allowed and
  carry different reasons, and the `changelog` finding printed afterwards no longer says the trio
  "was NOT written" in the same run that wrote it (#125).

- `/oss:doctor` no longer tells a repo that declined the owned changelog trio to run the command
  that declined it. A repo already running a changelog gate under another name has those three
  files absent by design, and every run printed a `WARN` whose stated remedy — `/oss:scaffold` —
  provably changed nothing. `absent` and `declined` are now separate states with opposite
  remedies, and `declined` reports at `OK`. This plugin's own repository was one of the repos
  being warned (#126).
- A gate check that could not answer reports `unknown`, not `declined`. `/oss:scaffold` also
  declines when it could not look, and a decline nobody took must never be relayed as a decision
  somebody made (#126).
- `release_publish.py` reports a `.oss.json` that is not a JSON object as `could-not-run`, exit 3,
  rather than *skipped by policy*, exit 4. `[]`, `"x"`, `null` and `42` all fell through to the
  shipped defaults, which do not publish, and produced a receipt naming `release.create_release`
  as unset — about a document that could not have set it. The tag shipped and the GitHub Release
  silently did not, which is the one outcome that script's three states exist to prevent (#126).
- A `.oss.json` containing exactly `null` is no longer reported as an unreadable file with an
  empty reason. `json.load` returns `None` for it with nothing wrong, and the reader used `None`
  as its failure signal (#126).

- `scripts/doctor.py`'s dependency probe survives a `--version` banner the runner's locale cannot
  decode. `check_tool` ran the probe with `universal_newlines=True` — the legacy spelling of
  `text=True`, so `subprocess` decoded with the locale encoding — under an `except (OSError,
  subprocess.SubprocessError)`, and `UnicodeDecodeError` is a `ValueError`, so one stray byte in a
  banner killed a script whose whole contract is *exit 0 always, one VERDICT line*, with the
  function's own `WARN` arm for "found on PATH but would not run" sitting right there and
  unreachable. Unlike the four sibling instances, **nothing ever read the decoded output**: both
  arms branch on `returncode` alone and `stderr` is merged into the pipe only to keep a banner off
  the diagnostic's own stdout. So the decode had no consumer, and the fix removes it rather than
  widening the guard or adding a decoding helper — an `except ValueError` here would be unreachable,
  and would newly report a malformed probe, a bug in this file, as a finding about the user's
  toolchain. The 20-second timeout is unaffected either way: `TimeoutExpired` carries its partial
  output as raw bytes even in text mode, measured on 3.11, 3.13 and 3.14 rather than assumed (#131).

- `release_publish.py` ran two vocabularies under one `state` key: the changelog notes answer
  (`found` / `empty` / `missing`) and the publish lifecycle (`create` / `skipped` / `could-not-run`
  / `created` / `could-not-create`). `receipt` and `_exit_code` read `state` off any dict handed to
  them, so a notes payload reaching either printed `state: FOUND` at the top of a release receipt.
  `notes_section` now answers under `notes`, and the receipt names a state it does not recognise
  instead of upper-casing it into a verdict (#134).
- Every `state` vocabulary in `scripts/` is now swept by a registry test. A state name emitted from
  more than one site in one vocabulary has to be listed with a sentence saying why the sites mean
  one thing; a new distinct state costs nothing. The sweep has three outcomes, and *could not
  enumerate* — a module that would not read or parse, or a scan that found no vocabularies at all —
  never renders as *no collisions found* (#134).
- `scaffold.check_metadata` returned two vocabularies in one list under one `state` key: `missing`
  meant *no description* and also *no topics*. The sweep read it as clean because the second site
  lives in a helper, so a per-function scan split one vocabulary in two at a function boundary. The
  registry now folds a declared helper into its caller before looking for collisions — and checks
  that the caller really does call it, so a stale declaration cannot invent one either. The state
  itself is kept rather than renamed: this vocabulary is keyed by the pair `(field, state)`, and a
  test drives both sites to prove every finding carries a `field` (#134).
- `check_test_ci`'s `unreadable` is one state reached by three situations — `.github/workflows/`
  would not open, a name in it would not stat, or a file would not read. Two of them named the same
  path and rendered byte-identically, so the distinction was discarded where it was recorded. The
  cause now travels with each path and on the finding as a machine-readable `causes` list. The state
  stays single because all three share a remedy; nothing static can see a fan-in behind one literal,
  so the registry records that one is there and names the test that drives all three (#134).

- `/oss:tick` can now record a tick in a repo that ran a maintainer loop before this plugin existed.
  Those state files are a JSON object keyed `tick_<ISO timestamp>`; `oss_state.py` requires a list of
  entries, so every step of a tick succeeded and the one that writes the history failed at the end,
  after the work. `scripts/oss_state.py --migrate` converts such a file in place, losslessly — the
  original object is kept whole under each entry's `detail`, a decision the old shape never carried
  is said to be missing rather than guessed at, and the file it started from is kept beside it at
  `<state_file>.pre-migration` as the original bytes rather than a re-encoding of them, which it
  refuses to overwrite. It refuses outright on any value it
  would have to invent an entry for. Reading both shapes was the alternative and was declined: a
  pre-plugin entry is an arbitrary object of named facts, so normalising one into an entry means
  guessing which field was the decision, and appending into a timestamp-keyed dict collides when two
  ticks land in the same second (#149).
- The state file now has three states everywhere it is read, not two. `oss_state.describe()` answers
  `ok` / `absent` / `unreadable` and never raises, `/oss:doctor` reports the third one instead of
  calling any present file OK — present was never the question — and step 1 of `/oss:tick` reads the
  file with `--last` rather than printing `--help`, so a file the loop cannot use is refused before
  the tick's work rather than after it. Absence is told from unreadability by the exception already
  in hand: `FileNotFoundError` is absence, every other `OSError` is not, and nothing asks the
  filesystem a second question. This suite's own "fully configured repo" fixture had carried the
  unusable shape and been graded `VERDICT: ok` on it (#149).

- `agents/auditor.md` no longer lets a class be graded `clean` on a comparison nobody performed. A
  real spawn graded two classes clean on sentences asserting that two blocks of text were the same —
  that a brief's copy of a referenced section matched the file's, and that a fixture was the actual
  pre-fix text — having run only an `ls -l`, which returns a size and an mtime, and a grep for two
  phrases. A fabricated verification and a performed one rendered identically, which is the defect
  the auditor exists to catch, arriving in the agent written to catch it. Any sentence in a verdict
  that asserts a comparison now has to carry the command that produced it, `ls` and a byte count and
  a grep for one phrase are named as existence checks rather than reads, and a comparison no command
  performed makes the class `could not check`. The requirement stops at comparison claims: most of
  the checklist is answered by reading the diff, and demanding a command everywhere would teach the
  agent to name one it did not run. The third state was not the gap and was not widened — `could not
  check` was already required, already declared never to render as clean, and the platform-band
  paragraph already routed a missing section to it; the auditor had somewhere honest to put "I could
  not compare these" and asserted the comparison instead. Two rules in that file already sent the
  auditor to text shipping elsewhere — the platform shapes and the ranking table — telling it to read
  the section or work from a verbatim copy in its brief; one rule now covers both and says that
  confirming the path exists is not reading it (#165).

- A trailing newline can no longer pass `.oss.json` validation and then break the workflow this
  plugin writes into other people's repositories. Python's `$` matches *before* a trailing newline, so
  `^\d+\.\d+\.\d+$` accepted `"0.1.0\n"` and `^[A-Za-z0-9._-]+$` accepted `"changelog.d\n"` — and
  `.oss.json` is tracked, so either arrives through an ordinary contributor pull request. The harm
  was not shell escape: a newline cannot leave a single-quoted string. It ended the `run:` block
  scalar the assembler command sits in, so `.github/workflows/oss-changelog.yml` stopped parsing,
  the changelog gate stopped running, and nothing blocked the pull request — a guard turned off,
  rendering exactly like a guard that found nothing, in somebody else's repository. `changelog_dir`
  was the wider and older instance, corrupting four lines of the generated workflow rather than one,
  and it is the idiom `changelog_untagged` was copied from. A sweep of all 28 compiled patterns in
  `scripts/` found a third, `REPO_RE`, whose value reaches the H1 of the generated `CLAUDE.md`;
  the remaining 25 are clean by construction — either already `\Z`-anchored, matched against a
  single line whose newline is the delimiter, or returning a literal rather than the matched input.
  All three are now anchored `\A…\Z`, in the pattern rather than at the call site so a later caller
  reaching for `.match` or `.search` cannot lose them. Nothing that validated before is refused now:
  the character classes are untouched, and the fix removes exactly one byte from what they admit.
  `tests/test_generated_file_injection.py` asserts the harm rather than the regex — the rendered
  workflow has no line at column 0 that is not a top-level key — and pairs every refusal with a
  positive control that restores the pre-fix pattern and proves the check can see the corruption.
- `repo` is now refused at the moment CLAUDE.md is rendered, not only inside `validate()`. The two
  values that reach the generated workflow each re-check at their own render-time funnel, with a
  comment saying why — `render()` reaches them without going near `plan()` — and the third had no
  funnel at all, so a caller rendering CLAUDE.md directly wrote whatever `.oss.json` carried into
  its H1. `scaffold.repo_slug()` closes that asymmetry, and `oss_config.repo_problem()` is the
  shared sentence both layers now report (#173).

- `oss_state.py --migrate` no longer destroys the history it says it left alone. The failure receipt
  read *the original is unchanged and a copy of it is at `<state_file>.pre-migration`*, and
  `Path.write_text` truncates the file at open — so on every path where the write failed after that
  point the original was gone while the sentence said it was intact, and said it in the direction of
  "nothing to do here" about a file that cannot be recomputed. The converted history is now written
  to a sibling temp file and moved onto the original with `os.replace`, which either happens or does
  not, so the claim is true on every failure path; a temp file a failed write left behind is removed,
  and named in the receipt if it could not be (#174).
- The backup `--migrate` points a maintainer at is now **read back and compared to the original
  before anything is written**, because a write that returned without raising is not evidence the
  bytes landed. A copy that does not match, or cannot be read, stops the conversion with the original
  untouched — and is not offered as the copy to fall back on: the receipt names its path as something
  to move aside, and never deletes it (#174).

- The release gate has an arm for an audit finding that arrived without a ranking row. It blocked on
  membership in a blocking row — a positive test, so a finding with no row at all was in no blocking
  row, the exception never fired, and the two-round cap carried it forward and shipped it. A rank
  that could not be computed rendered exactly like a rank that is not blocking. The two rowless
  answers the audit agents already define are now answered separately, in both documents that decide
  the gate, because collapsing them re-creates the same defect a layer down: `unranked` — classified
  and no row fits — is ranked at the gate before the cap is applied to it, and the cap does not reach
  a finding that has no row yet; `could not rank` — the ranking table never reached the agent — is
  an audit that did not complete, which is `could not run` and stops the tag, with a re-dispatch
  carrying the table as the way an answer gets computed rather than an extra round. The maintainer
  skill had said both since the gate was written and the command doc said neither, which is the
  divergence itself: `could not rank` had no arm of its own even in the skill, and a test now joins
  the vocabulary where it is defined to every document that acts on it (#175).

- The release path records the **checklist in effect** before it spawns the audit — the version of
  the plugin definitions the gate is about to be performed with, compared against the repository's
  own when that repository is the one shipping them. The gate is loaded from the installed plugin and
  the installed plugin is updated *by* releases, so an improvement to the checklist cannot audit the
  release that ships it and will not audit the next one either unless the install is refreshed. One
  release was audited by definitions two versions old and it was visible only because the agent
  volunteered it. Three states: it matches, it differs — which annotates rather than stopping, since
  a repo that merely installed the plugin legitimately runs whatever it installed, while for the
  repository that ships them it is a config finding — or **could not tell**, which never renders as a
  match and never as a clean audit. The auditor states which checklist reached it in every round,
  which is the half nothing else can measure, and the line has a slot in the report template it
  copies rather than only a sentence above it (#176).

### Security

- The security policy and the release gate no longer disagree about what this project treats as
  serious. `SECURITY.md` promised embargoed handling for three classes while the ranking table in
  `skills/manager/SKILL.md` had grown to six blocking rows, so a reporter with a `forges` finding read
  a policy that did not cover them. The mismatch ran the safe way -- the gate was stricter than the
  promise -- but it left a reporter unable to tell that their finding would stop a tag, and could be
  read as permission to disclose publicly first (#139).
- The embargo list and the release-blocking list are now stated as two lists, because they answer two
  questions. Blocking a tag asks what this project may ship; an embargo asks whether a reporter should
  hold disclosure. `forges` joins the embargo list -- the delivery channel for it *is* a public
  tracker, so a public writeup is the payload -- and `ships-local-state` deliberately does not: it is
  already readable in the artifact it ships in, so there is no window of private knowledge to protect,
  and it is fixed just as urgently in the open. `SECURITY.md` now says that in as many words, so its
  list no longer reads as the complete set of what this project takes seriously (#139).
- `containment` in the policy now covers reads *and* writes in one bullet. The ranking table splits it
  into two rows because they invite different fixes; a reporter does not choose our chokepoint, so the
  policy keeps one class and the mapping is many-to-one on purpose (#139).
- A new guard keeps the two in step without either document referencing the other. `SECURITY.md` is a
  scaffolded **default** -- created once in somebody else's repo and theirs forever, where the manager
  skill does not exist at all -- so it cannot point at the table, and a policy that redirected a
  reporter into a maintainer-facing process file would be worse to read anyway. Instead the suite
  carries a declared mapping from blocking rows to policy classes: a seventh blocking row goes red
  until somebody decides whether a reporter should hold it, and a row deliberately left out carries
  its reason rather than a bare absence. When either list cannot be parsed, the check reports that
  rather than agreement (#139).
- Note for repos already scaffolded: `SECURITY.md` is a default, so nothing overwrites it. An existing
  repo keeps the three-class list until its maintainer edits it themselves (#139).

- `test_command` and `default_branch` can no longer restructure the `CLAUDE.md` this plugin writes
  into another repository. `_render_claude_md` substitutes three `.oss.json` values into that file —
  the one every agent in that repository reads first — and #173 gave `repo` a render-time chokepoint
  while leaving the other two with nothing but a `str` type check, in the same function and the same
  commit. `.oss.json` is tracked, so both arrive through an ordinary contributor pull request. A
  `test_command` carrying a newline followed by a fence marker, a blank line and a heading ended its
  own code block and landed at column 0, indistinguishable from prose the maintainer wrote;
  `default_branch` broke out of its code span the same way.
- Fixed at both layers, because they close different halves. A refusal is a claim about the value
  and holds wherever it goes next; render-time escaping covers a value nobody thought to validate —
  a `test_command` consisting of a bare fence marker broke the block with no line break in it at
  all. `oss_config.test_command_problem()` refuses every character that ends a line, measured
  against `str.splitlines()` rather than transcribed (a newline and a carriage return are two of
  ten), plus the C0 controls, and nothing else: a test command legitimately carries quotes, pipes,
  `$`, `&&`, `#` and backticks, and a fence cannot be closed from mid-line.
  `oss_config.default_branch_problem()` transcribes `git check-ref-format`, so a branch name git
  would accept is still accepted — with five stated exceptions, each carrying its reason: a
  leading `-`, which argv reads as an option, `@` alone, and the three Unicode line terminators
  git tolerates and Markdown does not. The transcription is *measured* against `git
  check-ref-format` in both directions over a corpus that includes one name per printable ASCII
  character, rather than asserted: the first version of it borrowed a control set that carves tab
  out for `test_command`, and git refuses a tab in a ref name, so the claim was already one byte
  false when review found it. At render time the code block's fence and the code span's delimiter
  are each widened past the longest backtick run in the value they carry.
- The substitution sites are now enumerated rather than the patterns. #173's sweep covered all 28
  compiled patterns in `scripts/` honestly and in both directions, and a value with no pattern
  cannot appear in a sweep of patterns — which is how the guard and the bypass came to sit in one
  function. Every `.oss.json` value reaching a generated file was walked instead: the three in
  `CLAUDE.md`, `changelog_dir` and `changelog_untagged` in the generated workflow and the `.oss/`
  README, and `changelog_untagged` in the `01-oss` rule layer. That last one had the same shape of
  gap in a milder form — real, but sitting at `plan()` rather than at the render funnel — and now
  re-checks at `scaffold.untagged_versions()`.
- `tests/test_claude_md_injection.py` asserts the rendered document's structure rather than a
  regex's return value: no heading the template did not emit, no unclosed code block, no column-0
  line the template does not produce. Every refusal is paired with a positive control that renders
  through a verbatim copy of the pre-fix expression and proves the check can see the corruption.
  It also pins the template's placeholder set, so a fourth substitution site added later fails a
  test instead of shipping (#180).

## [0.3.0] - 2026-08-15

### Added

- A third agent, `oss:auditor`, audits one committed diff against a fixed four-class checklist and
  reports one verdict per class. The classes are the band a reviewer can see and CI cannot fail on:
  an absence a caller cannot read (`[]`, `None`, a bare `return` on an error path — the largest class
  in the census by a factor of five), a guard nominally on and effectively off, untrusted text
  rendered at column 0, and the platform band of separators, encoding and line endings. It annotates
  and never blocks, because a gate with false positives gets routed around inside a week and lands
  the repo in the second of those classes. `could not check` is a required word in its report and
  never renders as clean: a class it did not reach is stated, not omitted. Platform findings are
  graded against what the repo's own workflow matrix covers — `covered`, `not covered`, or
  `could not determine`, the third of which is reported at full weight and labelled rather than
  collapsed into either neighbour, since a matrix is a fact about one repository and a repo with no
  Windows leg has no such coverage at all. The five recurring cross-platform shapes are not recopied
  into it; they already ship in `agents/developer.md` and the manager skill, and the auditor reports
  the whole platform band as `could not check` when neither reached it rather than reconstructing a
  third copy that drifts (#33).
- `agents/developer.md` spawns the auditor beside its existing generalist reviewer, both in one
  message so they run concurrently, and hands the auditor its own cross-platform section verbatim.
  Two spawns rather than one added bullet, because a checklist folded into a generalist's ask leaves
  no way to tell a class that was checked and clean from a class that was never read — which is the
  guard-that-did-not-run defect, reproduced in the wiring of the agent pointed at it (#33).

- A repo cutting its genuine first release is cut, not refused. `assemble_changelog.py` inserted a
  release section above the newest `## [x.y.z]` heading, and a repo that has never released has no
  such heading — so every repo this plugin scaffolds hit a refusal naming the missing `## [x.y.z]`
  heading exactly once, at the least forgiving moment, and the documented way out was to
  hand-write a release section for a version that never shipped: a maintainer inventing history to
  satisfy a parser. There is now a first-release path, and it fires only when the document holds no
  release heading at all — a repo with releases keeps the anchor rule unchanged. The position is not
  "the top", which is a preamble, a Keep a Changelog blurb or a link-ref block depending on the file;
  it is directly below the `## [Unreleased]` heading, where every later release will also go, with
  the body between folded in exactly as it is on every later release. The receipt says which of the
  two paths ran and on which line, so a first release reads as detected rather than assumed (#41).
- The three states hold: a file with no `## [Unreleased]` heading, or with more than one, is still
  refused, and the refusal names what would make it decidable rather than picking a position it
  cannot defend. A first release has no earlier tag, so there is no `compare/vX...HEAD` line to
  advance and the old receipt reported `links none — ... left alone`, which reads as "there was
  nothing to do" for a table that is a release behind the file. The base URL is read off whatever
  `[Unreleased]` does point at — `commits/HEAD` is what Keep a Changelog's own template writes for a
  project with no releases — and both definitions are written as every later release writes them, so
  the file passes its own `--check-links` immediately after its first cut. Where no base can be
  derived, nothing is written and the receipt names which of the three reasons it was and what to
  add (#41).
- A release cut on Windows says it happened. `assemble_changelog.py` wrote CHANGELOG.md, deleted the
  fragments it had consumed and then died printing its own `ok` receipt: the summary carried a `→`,
  and Python encodes stdout with the locale codepage, which is cp1252 on the Windows runners and has
  no such character. The traceback left the process at exit 1 — which this script's own contract
  defines as `SKIPPED`, "nothing to do, or nothing provable" — so the release was cut, the fragments
  were gone, and the exit code said neither had happened. Every non-Windows leg was green throughout,
  because a UTF-8 console prints the character fine. The three arrows are ASCII now, and two tests
  pin it: one drives a real cut with `PYTHONIOENCODING=cp1252` on both ends so the reproduction runs
  on every platform rather than only the one that breaks, and one scans the script for characters
  that codepage cannot represent, which covers the summary strings no test reaches. The scan carries
  a positive control, because an empty finding list is also what a scan that looked at nothing
  returns. The bar is cp1252 rather than ASCII deliberately: the file's 76 em dashes are cp1252
  characters and have shipped green through every Windows leg, so widening it is a repo-wide prose
  change and a separate decision (#41).

- `/oss:setup` now settles the merge permission, and `/oss:doctor` reports whether it is settled.
  `gh-pr-merge` is the only op the loop uses that writes, and the harness decides at call time
  whether it may run — so a tick could satisfy every gate, spend the whole review, and stop dead at
  the merge because nobody had ever told the harness about the call. `skills/manager/SKILL.md` said
  "arrange this at setup, not at the merge" and nothing acted on it. Setup now names the rule, the
  file it belongs in (`.claude/settings.local.json`, machine scope and untracked, for the same
  reason `.oss.json` and `.oss.local.json` split), both binary spellings the loop uses (`./supertool`
  from the clone, an absolute path from a worktree), the fact that `gh-pr-merge:N:squash` and
  `gh-pr-merge:N:squash|force` are different literal strings, and that the harness permission is a
  separate **fourth** gate in front of supertool's three opt-outs — because the obvious move when a
  merge is denied is to widen a supertool setting that was never the thing refusing. Doctor reports
  four states and not two: a rule naming the op is present, a deny rule names it, none names it, or
  the settings files could not be read — and an unreadable file is never reported as an absent rule,
  because that sends you to add a rule you may already have. Deny wins over allow, and every
  settings file is read before anything is decided. Neither the command nor the
  check writes a permission grant: arranging an irreversible action without asking is not this
  tool's job. The passing state says what it measured
  and no more — reading a settings file is a file read, not a probe of the harness, so an `OK`
  states that the rule exists and explicitly not that the merge will be permitted (#45).

- The release gate that demands a security audit of the delta since the last tag now has something
  that performs it. `scripts/release_delta.py` computes the range mechanically in three states and
  `oss:release-auditor` reads it; `commands/release.md` and the manager skill both name them, so the
  gate stops being a sentence a human reads and forms a judgement about. It had no implementation at
  all, which meant its own third outcome — `could not run` — was the permanent state and invisible,
  because nothing ever tried and so nothing ever reported that it could not (#48).
- `could not run` is decided by the script, not by the agent, and it stops the release. A shallow
  clone, a repository with no commits, an unlistable tag list, or tags HEAD cannot reach each exit
  `3` with the reason named. Asking a language model whether it could compute a range produces a
  plausible-looking range either way, which is the class this plugin is named after appearing inside
  the check written to catch it (#48).
- A repo with no tag at all is a `first release`: a named state whose delta is the whole history
  reachable from HEAD, audited like any other range, and permitting the tag once it has been. An
  empty delta and an uncomputable one are the two things this gate exists to keep apart, so neither
  may render as the other — and the workaround a refusal would force, inventing a tag so a previous
  one exists, is a history nobody made (#41, #48).
- `oss:release-auditor` is deliberately a second agent rather than a wider `oss:auditor`. They split
  by slot: one PR's diff, annotating, every PR versus the whole delta, blocking, once per release.
  Its own lens is composition — the defect assembled from two individually clean PRs, which no
  per-PR review can see by construction. The four classes and the cross-platform shapes are
  referenced, never recopied, and the two-round hard cap is stated as load-bearing rather than as a
  budget: after round two the rest is filed against the next milestone and the release ships (#48).

- The cross-platform checklist carried in `agents/developer.md` and the manager skill gains a sixth
  shape: a character the console's codepage cannot represent. The five that were there are all about
  what a program **reads or invokes** — separators, drive letters, POSIX literals in assertions,
  exception types, unspawnable binaries — and none about what it **writes**. An arrow in a receipt
  string raised `UnicodeEncodeError` on the Windows runner's cp1252 console after the script had
  already written `CHANGELOG.md` and deleted every fragment, and the agent that shipped it had
  audited its change against all five items correctly and run the full suite green, because the
  character prints fine on a UTF-8 console. So this was never a skipped item; there was no item to
  skip, which is the one state a checklist cannot report. The ordering ships with it: the process
  dies reporting work it has already done, so the exit code describes the crash and not the mutation
  (#56).
- `tests/test_content_invariants.py` pins the sixth item in both copies and nowhere else — five
  anchors, each a half of the item that would make it useless if dropped, with the five-item list as
  it stood on the day the crash shipped as the positive control. `codepage` joins the anchors the
  no-third-copy guard watches, so an agent that restates the item is reported like any other third
  copy. The bar stays cp1252-encodable rather than ASCII: `scripts/assemble_changelog.py` carries em
  dashes that are valid cp1252 and have shipped green through every Windows leg, and raising the bar
  repo-wide is a separate decision (#56).

- `/oss:release` now creates the GitHub Release for the tag it just verified, via
  `scripts/release_publish.py` (#58). The tag was previously the end of the road: the releases page
  showed a bare tag with no notes, nothing was marked `Latest`, and nobody watching for releases was
  notified — in a command whose own section argues that the tag is not the delivery, so it explained
  the difference between tagging and shipping and then did the first while narrating the second.
- The notes are the `## [x.y.z]` section the changelog fold just wrote, taken up to the next `## [`
  heading, the end of the file when it is the last section, and matched on the whole version label so
  `0.3` never announces `0.3.0` and `0.3.0` never announces `0.3.0-rc1`. A heading with no body under
  it is `empty`, not an empty string: blank notes on a real release are the absence the tool produced
  rendered as the notes somebody wrote.
- `--verify-tag` is emitted on every branch that builds a command, and the suite asserts the whole
  argv rather than that a mock was called. Without it `gh release create` creates the tag when it is
  missing, which turns the `git ls-remote` verification two paragraphs earlier into the step that
  mints the ref it was checking for. `--repo` is always passed for the same class of reason: `gh`
  otherwise infers the repository from whichever directory it is standing in.
- Three outcomes, kept apart on a path where a quiet failure leaves a maintainer believing something
  shipped: `created`, `skipped` because policy said not to, and `could-not-run` / `could-not-create`
  when the notes could not be extracted, `gh` is absent, or the API call failed. Exit 0, 4 and 3
  respectively, because a shell reads codes and never reads prose.
- Publishing is policy and the policy is the project's, so it is three new keys in the tracked
  `.oss.json` `release` block rather than in the machine-scoped `.oss.local.json`: `create_release`,
  `draft` and `latest`. The shipped defaults are the conservative ones — do not publish, draft when
  you do, do not mark `Latest` — because publishing notifies watchers and is not undoable the way a
  draft is, and `Latest` changes what somebody else's landing page shows. Unset is a third state and
  not a quiet `false`: the skip reason names `release.create_release`, so a repo that never chose is
  told what would change it instead of silently never releasing.
- `draft: true` with `latest: true` is refused by the config validator. A draft cannot be marked
  Latest, so the pair states an outcome the release path can never produce, and refusing it in the
  validator beats finding out from a failed release.
- This repository's own `.oss.json` states the choice explicitly — published, marked `Latest` — so
  the value it releases under is one somebody chose rather than one it inherited.

- `scripts/doctor.py` takes `--root`, so it can be pointed at a repo the way every other script here
  can. It was the only one resolving its target solely from `CLAUDE_PROJECT_DIR` or the current
  directory — the same exposure this repo already recorded for `assemble_changelog.py`, reached
  through a different mechanism: an environment variable set by something else, or a `cd` that
  persisted, and the diagnostic answers a well-formed question about the wrong tree (#63).
- Precedence is decided rather than defaulted. `--root` wins outright; `CLAUDE_PROJECT_DIR` answers
  when no flag is given; the working directory is last and is still announced as a guess. A `--root`
  that disagrees with `CLAUDE_PROJECT_DIR` is reported even though the flag wins, naming the tree
  that was not looked at — the disagreement is itself the finding (#63).
- The exit-0 contract survives the flag. A `--root` at a path that is not a directory is a `FAIL`
  line and the run continues to a VERDICT; a directory with no `.git` is a `WARN`; an unrecognised
  argument is a `FAIL` line rather than argparse's exit 2 and usage message, which would leave a
  diagnostic with no findings and no verdict. `scripts/doctor.sh` forwards its arguments, because a
  flag that only works when you bypass the launcher is a flag nobody has (#63).

- `oss_config.resolve_config_path` and `oss_config.load_from` take a `start` directory, so a caller
  can ask "is there a config for *this* tree" about a tree it is not standing in (#70). The search
  used to be expressible only about the process's own directory: the relative path handed in was
  appended to the enclosing clone verbatim, so only a bare `.oss.json` resolved anywhere a config
  lives. `/oss:doctor --root` wants exactly the missing capability and declines instead, which is
  the honest answer and not the useful one. `start` defaults to the current directory, so no
  existing caller changes.
- The parameter is deliberately a directory rather than a path for the caller to compute. Bridging
  the gap with `os.path.relpath` -- the obvious alternative -- produced
  `search: ../../../../../tmp/oss-sym/clone/sub/.oss.json` and a clean-looking `FAIL` with the
  config sitting in that clone the whole time, because two spellings of one directory differ
  whenever `/tmp` is a symlink to `/private/tmp`, which on macOS is the default. With `start`
  nothing is resolved against the current directory at all, so that path cannot be constructed
  (#53, #69, #70).
- A fourth outcome, `unsearchable`, is now told apart from `missing`: the config is absent AND there
  was no enclosing clone to search, or git could not be asked whether there is one. Both already
  printed different sentences, so the split was there for a human reader; a caller branching on the
  returned `origin` saw one value for "the clone has no config" and "no clone was searched", which
  is this project's own defect class inside its own API. `unsearchable` does not subdivide further
  into "git is absent" and "this is no repository" -- that line can only be recovered by matching
  git's stderr text, and a state derived from a string match goes wrong silently (#70).
- The reclassification is unconditional, not scoped to callers that pass `start`: the same arm now
  answers `unsearchable` for a caller standing in a directory in no repository, where it used to
  answer `missing`. The printed sentence is byte-identical either way, and both in-tree callers --
  `scripts/doctor.py` and `scripts/scaffold.py` -- branch only on `clone` and print the detail
  verbatim, so nothing a maintainer sees moves. A third-party caller keying on `missing` would (#70).
- An explicit `start` that is not a directory reports `unsearchable` rather than falling back to the
  process's directory. The cwd form falls back to `.` so that an excluded `configs/.oss.json` with no
  `configs/` in the worktree is still found; under `start` that same fallback is how a `--root` at a
  path that does not exist came back describing the caller's own repository instead (#62, #70).
- A relative path carrying an anchor of its own is refused rather than joined. Only Windows has such
  a shape -- `C:x` is drive-relative and a leading separator with no drive is root-relative -- and
  pathlib joins both by discarding the left-hand side, which would turn an explicit `start` back into
  "the process's own directory" silently. The predicate is asserted against `PureWindowsPath` so the
  POSIX legs measure it too, since no POSIX runner can build a fixture that reaches the branch (#70).
- `/oss:doctor --root` is not wired to `start` here: `scripts/doctor.py` is owned by another change in
  flight, so its `config_search_path` still documents and performs the samefile/bare-name workaround
  this parameter replaces. Adopting it is a follow-up, and until then doctor still declines (#70).

- A `tools` dimension: `Read`, `Edit`, `Write`, `Glob` and `Grep` are now `mode: block` in every
  repository this plugin's `01-oss` layer reaches, with the refusal naming the supertool op that
  replaces the call ("reads go through supertool" was enforced for an agent and merely advised for
  the maintainer session that carries the credentials). No exception for an image, a PDF or a
  notebook cell -- none exists in this repository, and one gets an exception when it appears, not
  before. `block` rather than `remind`: a rule with no exception that only reminds teaches the
  reader to dismiss it. `oss_rules.index_rows()` now writes the six-column shape `rebuild-tsv.sh`
  produces for a tools row (`tool<TAB>match<TAB>filename<TAB>mode<TAB>require<TAB>forbid`),
  re-derived from that script rather than trusted from the issue that first described it -- #80
  found the same list wrong when it was only reasoned about (#106).
- **Not proven end-to-end.** `claude-jit-context`'s hooks read exactly four layer names --
  `00-manual/`, `10-auto/`, `20-grouped/`, `30-crosscutting/` -- and `01-oss` is none of them. Driven
  against a copy of this rule under `tools/00-manual/`, it fires correctly on every path this issue
  asked for; driven against the actual shipped `01-oss` layer, through the real hook chain, it does
  not fire at all, and neither do the two rules that already shipped there before this change. That
  is a pre-existing defect in the layer name this plugin has used since before this issue, not
  introduced here and not fixed here -- it needs a maintainer decision this change does not make.

### Changed

- `/oss:doctor` now says what re-running `/oss:scaffold` would change in an owned file, rather
  than that something would. A drifted `.github/workflows/oss-changelog.yml` reads
  `would change what it does -- on.pull_request.types, jobs.fragment.steps.name.run`; a file
  whose comments moved reads `would change comments and prose only -- nothing it does
  changes`. That distinction is the whole decision: owned files are replaced wholesale on
  every scaffold run and nothing schedules the run, so this line is the only signal a
  maintainer gets that a repo scaffolded last week is carrying a changelog gate that a
  contributor can satisfy by deleting somebody else's pending fragment (#26).
- The line names at most four regions and says `and N more` when it named fewer than it
  found, because a list of four reads as the whole answer whether or not four was all there
  was (#26).
- The drift line no longer promises that "nothing you wrote is at risk". Nothing in a managed
  repo records which plugin version wrote an owned file, so a stale copy and one the
  maintainer edited are the same observation from inside — and the old wording answered it
  wrongly in the case it could not rule out. It now states the effect, which holds either way:
  re-running replaces the file wholesale, and an edit made here goes with it (#26).

- `/oss:scaffold` closes by naming `/oss:tick`, which completes the chain rather than half of it. No
  command doc named `/oss:tick` as the next step from anywhere — the only mentions were tick's own
  wakeup prompt referring to itself and the README command table — so scaffold ended on the generated
  CLAUDE.md's test-command paragraph and said nothing about what the furniture was for. A maintainer
  who reached scaffold and stopped was exactly where one who reached setup and stopped had been. Said
  whatever the scaffold run reported, including one where every file was already present (#43).
- The test behind that chain asserts the chain rather than its edges: setup names scaffold, scaffold
  names tick, each with a positive control in the same fixture, plus a control showing the detector
  firing when exactly one link is removed. An edge asserted on its own passes while the documented
  path still stops one link short, which is how half of this shipped and read as done (#43).
- `/oss:doctor` reports owned files that are missing or drifted as one finding per distinct fact,
  naming every file it covers, instead of one line per file. A repo that was never scaffolded printed
  three warnings ending in the same `Run /oss:scaffold.` and counted three against the verdict — one
  gap with one fix, read as three unrelated findings. `absent`, `drifted` and `unknown` are still
  never folded together, `unknown` still reports a check that could not look rather than a pass, and
  grouping never moves a clean file ahead of a gap listed before it (#43).

- `CHANGELOG.md` stays the sole source of truth for `assemble_changelog.py`, decided rather than
  defaulted, and the first-release receipt now says so. The first-release path fires when the file
  carries no `## [x.y.z]` heading at all, which is evidence about a *file* supporting a claim about a
  *repository* — a changelog rewritten, truncated or regenerated by hand while tags exist has exactly
  the same shape and was cut rather than refused. Consulting `git tag` was weighed and refused on
  three grounds: the script is handed a `--changelog` path and a `--dir`, not a repository, and the
  root it could derive is the one above its own file, which under a plugin is a different repo than
  the changelog it was pointed at; tags are not release headings, so a repo that tags release
  candidates or nightlies, or that adopted a changelog after it had already shipped, sits in "tags
  exist, no release heading" legitimately; and the only remedy such a refusal could name is
  hand-writing a release heading for a version that already shipped, which is the invented history
  the first-release path exists to abolish (#54).
- What that decision owes the reader is a stated limit rather than silence. The receipt carries a
  second line naming the source it read, naming `git tag` as the source it did not, and saying what
  to do about it before pushing — at the moment of the claim, which is where a limit is worth a
  sentence. A test pins it, with a repo that has a release heading as the control, so the disclosure
  cannot quietly start printing on every path and pass for a reason unrelated to the branch it is
  about (#54).

- The developer agent now hands back **one JSON report file plus a path and at most two lines**,
  instead of a prose document the orchestrator pays for on every later turn of the session (#96).
  The schema is `schemas/agent-report.schema.json` and `python3 scripts/report_schema.py REPORT.json`
  validates it. A report is queried field by field -- the refused findings when a maintainer is
  reviewing, the platform grades when they are not -- so the parts nobody needed yet cost nothing.
- **The pull request body is written by the agent that holds the evidence**, to a file, and named in
  the report. The orchestrator reads that file and hands the path to the forge rather than
  re-narrating the work into a body of its own, which is the larger of the two savings and the one
  that used to lose detail on the way. Judgment does not move: the body is still read before anything
  is opened. Not writing one is a state in the report with a reason, not a missing file discovered
  later.
- **Every list in the report is a survey carrying its own state**, because an empty array cannot say
  whether anyone looked. `checked` with no items is a review that ran and found nothing; `not-checked`
  is a review that never ran and has to say why. Every audit class carries a verdict including
  `not-applicable` and `not-checked`, and a refused or argued-down finding carries its full sentence
  and its argument rather than a boolean -- a structured summary is easier to accept unread than a
  paragraph is, and that is exactly where the review step's value would leak away.
- The validator checks shape, never truth: it cannot tell a review that ran from one that says it
  did. The schema publishes `x-enforced` and `x-convention` so the split is written where the next
  person meets it, and every name in `x-enforced` is paired with a mutation test that proves the
  refusal actually happens (#96).
- The validator refuses a JSON Schema keyword it does not implement rather than walking past it: a
  `minLength` or a `oneOf` added to the schema and silently ignored is a constraint that reads as
  enforced and is not, which is the defect the report format exists to make visible, one layer down
  (#96). A schema that cannot be resolved is reported as unusable and exits 1, never as a report with
  nothing wrong with it.
- Validator output survives a console whose codepage cannot represent the report (#96). Every line it
  prints can echo a value out of the report, and on Windows that text is encoded with the console's
  codepage rather than the file's, where one accented character raises `UnicodeEncodeError` and ends
  the process at the print -- after the validation the print was reporting already ran. The character
  is mangled instead, which is the outcome a maintainer can act on.
- `pr_body.path` names a file the forge can consume unchanged -- JSON carrying `title`, `body`, `head`
  and `base` -- rather than a markdown body (#96). Markdown is the shape the next step refuses, and
  the refusal arrives after the agent's session has ended, so the recovery is somebody reading the
  body, wrapping it, and inventing a title: the re-narration this change exists to delete, one layer
  down. The title is the sentence most people read and the only part of a pull request that survives
  a squash into the log, so it belongs to whoever did the work.
- The validator opens that payload and checks it -- the file exists, parses, carries a non-empty
  title and body, and names a `head` that matches the report's own branch. It is the one check that
  leaves the report, so it lives in its own function under its own list (`x-enforced-on-disk`), never
  runs inside the shape pass, and the command line prints `shape only: the pull request payload was
  not read` when it was asked to skip it (#96).

- **The maintainer loop now consumes what #96 produces** (#99). `skills/manager/SKILL.md` and
  `/oss:tick` described a world where an agent's work arrived as prose in the maintainer's context, so
  the plugin shipped a producer with no consumer and the saving existed only on paper. The skill now
  says an agent replies with a path, that the maintainer pushes the branch and hands `pr_body.path`
  to `gh-pr-create:@FILE`, and that the body is **read before it is published** -- the step that makes
  this a saving rather than a trick, because the orchestrator stops writing a document it still has to
  read. The op rather than `gh pr create`: it parses the body's closing references with the same
  reader `gh-pr` uses, so a missing `Closes #N` is caught at creation instead of after the squash,
  when the issue quietly stays open and the board reads clean.
- Most of the maintainer's closed review list is mapped onto the fields that answer each item -- check
  arithmetic from `gh-pr:N:status`, the review outcome from `review.findings` and `review.classes`,
  blast radius from `files[].path` -- so the list is a query rather than a read, and the platform
  table nobody needed that round never arrives (#99). The two items that are not fields are named as
  such: the premise is pre-flight and yours, and **the red re-run is still a run** -- `tests.red` is
  the agent's claim about what it saw, which is precisely the claim the re-run exists to test. The
  list itself does not widen: `claims`, `adjacent` and `blocked` are fields you open when something
  sends you there, not new items on it.
- **Fewer tokens must not become fewer things checked**, and the skill now says so against the
  structured form rather than only against prose (#99). `"disposition": "refused"` reads identically
  whether the refusal was argued or lazy, so the argument lives in `reason` and a load-bearing
  argued-down finding still gets checked by hand. The existing rule that a review which did not
  execute must never render as a review that found nothing is restated where a reader meets an empty
  `findings` array: the two are the same bytes, and the survey's `state` beside its `items` is the
  only thing that tells them apart. Read the state before the items.
- The skill points at `schemas/agent-report.schema.json` and `scripts/report_schema.py` rather than
  restating either, in the skill or in a brief -- a fact living in two documents diverges, and a brief
  is the copy nobody proofreads (#99).

### Fixed

- An owned file that is not valid UTF-8 makes `/oss:doctor` report `your copy could not be
  read`, its third state, instead of raising `UnicodeDecodeError` out of a diagnostic whose
  contract is to exit 0 and print its findings (#26).
- A CRLF checkout of an owned file is no longer a candidate for drift. `Path.read_text` already
  translated on read, so this was not reachable — the comparison now normalises line endings
  explicitly and a test holds it, because a switch to `read_bytes` would have turned every
  Windows repo into permanent drift and a warning that always fires is one nobody reads (#26).

- The README stops counting agents. It said "one skill, two agents" and "both agents" while a third
  agent definition was being drafted on a branch, and nothing failed — a count written into prose is
  a fact about the filesystem, duplicated, and it goes stale silently. The two sentences now name the
  agents without numbering them, so they stay true whatever lands next, and a new check pins the rule
  rather than the number: any agent count README does commit to must equal the number of
  `agents/*.md` on disk. Stating no count stays legal, because prose that does not duplicate the tree
  cannot disagree with it (#33).

- The per-repo config is now two files, because its keys had two different owners. `.oss.json` is
  the project's half and is tracked: `repo`, `default_branch`, `branch_pattern`, `test_command`,
  `version_sites`, `changelog_dir`, `docs_targets`, `labels`, `ci`, `milestones` and the whole
  `release` block. `.oss.local.json` is the machine's half and stays git-excluded: `clone`,
  `worktree_root` and `state_file`, the only three values that name a directory on one person's
  disk. `/oss:setup` writes both via a new `oss_config.py --split`, which also repoints
  `.git/info/exclude` and is idempotent, so it is equally the migration for a repo that already has
  a combined config. `load()` merges the two halves, so nothing downstream changed shape; where they
  disagree about a project key the tracked value wins and the override is reported by name.
  Previously the entire `release` block lived in one untracked file on one laptop, and
  `.git/info/exclude` is not copied by `git clone` — so the second maintainer to cut a release had
  no `tag_pattern`, was asked for one by the release command's own stop-and-ask, and could answer
  differently. A repo tagged `v1.2.3` could acquire `1.2.4`: the second tag namespace this plugin
  warns about, opened by the plugin (#34).
- `commit_subject: null` has defined behaviour instead of none. `/oss:release` said "commit with
  `commit_subject`" and stopped there, so a null reached an agent that invented a subject line —
  while the adjacent `tag_pattern: null` two paragraphs earlier got an explicit stop-and-ask. The
  null subject now resolves to `chore(release): {version}`, stated in the command and returned by
  `oss_config.release_commit_subject()`; `tag_pattern` keeps its stop. The two stay asymmetric on
  purpose and both now say so: a wrong subject line is cosmetic and the next commit fixes it, a
  wrong tag opens a namespace that is permanent. The default carries `{version}` rather than the
  more obvious `{tag}` because `validate()` refuses any subject without that placeholder (#34).

- `assemble_changelog.py` answers a `--changelog` path it cannot read instead of raising. The file
  was read with a bare `Path.read_text()` and nothing above it established the file existed, so an
  absent `CHANGELOG.md` surfaced as a raw `FileNotFoundError` traceback — the one path in that script
  that escaped the three-state receipt discipline every other failure follows, and the state every
  repo scaffolded by this plugin is in until somebody writes the file by hand. `--dry-run` raised
  identically, so the read-only way to find out what a release would do failed the same way. The read
  is now guarded and reports `skipped`, naming the path, the reason the filesystem gave, and that
  nothing was written and no fragment consumed; the detail lines state what a usable changelog needs
  — a `## [Unreleased]` heading, and either a `## [x.y.z]` release heading to insert above or none at
  all, which is the first-release case that #41 cuts directly below `## [Unreleased]`.
  `OSError`, not `FileNotFoundError`: a directory at that path or a mode we cannot read is the same
  answer. The scaffold deliberately still does not write a `CHANGELOG.md` (#35).

- `/oss:setup` says that `identity.md` describes the **agent**, not the human maintainer. The
  bullet read as if the file recorded whose sessions these are, and the only noun it attached
  identity to was a developer — so following it produced a file about the human: name, email, org,
  role. Nothing failed. The file was written, `git status` stayed clean, and every check in the loop
  reported the identity gap as closed, which is this repo's own defect class one layer up. The
  subject is now stated before the hazard, and the command points at the memory plugin's
  `identity.example.md` instead of describing the format a second time. `scripts/doctor.py` already
  said it correctly; the surface that instructs the writing did not. The per-user and
  tracked-location hazard paragraph is unchanged — it is about where the file lives, and it was
  right (#42).

- `/oss:setup` and the README both name `/oss:scaffold` as the next step. Setup used to close on
  "run `/oss:doctor`", and the README described the launcher path as setup → loop with scaffold
  absent from it — so a repo onboarded exactly as documented ran ticks with no CLAUDE.md, no
  security policy, no issue templates and no changelog gate. The sequencing existed only as a side
  effect of doctor warning about three missing owned files, and only in a repo where those files
  happened to be missing: a repo scaffolded before the owned files existed had no warning to trigger
  on at all. Both surfaces now state the split rather than just naming the command — setup writes
  nothing tracked, which is what makes it safe to run anywhere and also what leaves the repo
  half-furnished, and scaffold is separate because tracked files want a branch, a diff and a review.
  Setup says it whatever the verdict reports (#43).

- `--split` no longer claims the project half is trackable without checking (#44). `.git/info/exclude` is the only ignore source it may rewrite — a `.gitignore` belongs to the maintainer — so repointing the exclude file establishes nothing on its own. It now asks `git check-ignore` and reports three states: nothing ignores it, still ignored by a named `file:line`, or could not ask. This repo's own `.gitignore` carried a stale `.oss.json` rule, so the config #39 made tracked could not be committed here at all.

- `/oss:scaffold` now reads the repo's label list before reporting on the `no-changelog`
  escape hatch its generated workflow depends on. The three-state check existed but its
  only caller passed a hardcoded `None`, so `missing` was unreachable and every run
  printed the same reminder whether the label was there or not — a check that could not
  look, rendered as a check that found nothing (#46).
- The label is still not created for you, and the read degrades rather than guessing: when
  `gh` is absent, `.oss.json` names no repo, the checkout's `origin` is not that repo, or
  `gh` is unauthenticated, the line says which. The read is gated on those local facts, so
  scaffolding an arbitrary `--root` never fires a request about a repo it is not standing
  in (#46).
- One consequence worth knowing before upgrading: `/oss:scaffold`'s plan-only preview runs
  the same checks the apply does, so it is still read-only but no longer strictly offline —
  it can make one `gh` call, capped at 20 seconds (#46).

- `scripts/scaffold.py` now finds the config from inside a git worktree. `.oss.json` may be
  git-excluded, so it lives in the clone and in none of its worktrees — and the invocation the
  command documents, run from the directory a developer actually stands in while working an
  issue, failed with `not found. Run /oss:setup to write it.` for a repo that plainly had one.
  Acting on that advice would have written a second config into a worktree that must not carry
  one (#53).
- The search is now four states rather than two, and each prints a different sentence: found
  here; found in the enclosing clone, named in a `NOTE` line so the file being read is never a
  guess; checked the clone and it has none; and could not check, because git said this is not a
  repository. A search that could not run no longer renders as a search that came back empty
  (#53).
- `oss_config.resolve_config_path` and `oss_config.load_from` are the new seam. `load` is
  unchanged and still reads exactly the path it is handed, and an absolute `--config` is never
  widened — a path typed in full is an answer, not a starting point (#53).

- A release that is cut can no longer report itself as a release that never happened. Every mutation
  in `assemble_changelog.py` — the write to `CHANGELOG.md` and the deletion of the consumed fragments
  — happened before the receipt that reports it, and the receipt could fail. When it did, the process
  died in its own reporting and left exit 1, which this script's contract defines as `SKIPPED`,
  "nothing to do, or nothing provable": the one value that tells a wrapper or a workflow step to carry
  on past a tree that has already changed under it. The measured instance was a single character on a
  cp1252 console, and removing the character narrowed the trigger without changing what happens when
  it fires — a closed pipe, a full disk on a redirect, or a cp437 or cp850 console with no byte for
  the 76 em dashes the cp1252 guard deliberately permits all do the same thing (#55).
- Two changes, because either alone leaves the hole open. The receipt can no longer fail on encoding:
  a character the console cannot represent is written as an escape rather than raised, so one glyph
  is lost instead of the whole report, whatever the codepage. And the mutation now runs inside a guard
  whose only failure exit is `REFUSED` — never `SKIPPED` — with an alarm on stderr naming what the run
  established and nothing beyond it: whether the write completed, how many of the consumed fragments
  were actually deleted, and the fact that re-running is the wrong move. That guard wraps the write
  as well as the receipt, so it also answers a write that never landed — and it says so in those
  words rather than announcing a release that does not exist, because reporting a mutation that did
  not happen is the same defect as denying one that did. Measured end to end against a closed stdout:
  the old script cut the release, printed no receipt at all and exited 120 on `Exception ignored
  while flushing sys.stdout`; the new one cuts the same release and exits 2 with the alarm (#55).
- `stdout` is flushed inside that guard rather than left to the interpreter, because a receipt that
  only reached a buffer has not been delivered and a pipe that closed under it raises at shutdown,
  after the exit code has been decided. The script entry point flushes once more and points the
  descriptor at the null device if that raises, so CPython's own shutdown flush cannot replace the
  chosen exit code with 120 — kept out of every callable function, because `os.dup2` on stdout is
  process-wide and this file is also imported and called in-process. The tests pair every "must not
  be `SKIPPED`" assertion with a run that must be `OK` and a run that must be `SKIPPED`: an assertion
  that a value is not 1 also passes when the code under it never ran (#55).
- The two cp1252 tests gained an assertion, because the fix took their teeth out. They caught a
  character the console could not print by watching for the traceback it caused, and a receipt that
  degrades instead of crashing no longer produces one — so each now asserts the receipt carries no
  escape either. A green test whose detector was removed by the change it guards is the same defect
  one layer up: an absence produced by the tool, read as an absence in the world (#55).

- Five of doctor's checks stop going silent when the config is not found. `clone`, `worktree_root`,
  `state_file`, `CI enforcement` and the owned-drift half of the freshness check all depended on
  `.oss.json`, and `main` skipped them without a word when it was absent — so a check that never ran
  and a check that found nothing printed the same thing, which is nothing. Each now prints its own
  `not checked -- .oss.json was not found, so there was nothing to check it against`, and an
  unimportable `scripts/scaffold.py` gets a different sentence again, because two reasons a check
  could not run are not one reason. Filed as four checks printing findings derived from no config;
  measured before implementing, they printed no findings at all. Same defect, opposite symptom (#62).
- Doctor reads its config through `oss_config.load_from` rather than `load`, and says so when the
  answer came from somewhere else: `.oss.json read from the enclosing clone at <path>, not from this
  directory`. That seam existed and doctor was not using it. It also could not have used it as it
  stood — `resolve_config_path` never widens an absolute path, deliberately, and doctor only ever
  built absolute ones, so the clone lookup was unreachable from the one caller written for it.
  Measured from this repo's own worktree: the absolute form answered `missing` while the config sat
  in the clone one directory up (#62).
- A project directory that does not exist no longer searches the caller's clone. The widening starts
  its git query from `.` when the directory the path points into is absent, so `--root /nowhere`
  reported `Not in the enclosing clone at <the repo you were standing in> either` — a sentence about
  a repository nobody asked about, inside a report about one that does not exist. Found by running
  it, not by reading it (#62).
- `doctor.main()` no longer reads `sys.argv` when called as a library. Its own in-process suite
  imports it, and the host's command line was parsed as doctor's: every test path came back as an
  unrecognised argument. The script entry point passes arguments in explicitly (#62).
- The clone is only searched with a path the clone can answer, and says so when it is not searched at
  all. `resolve_config_path` widens a relative path by appending it to the clone exactly as given, so
  only a bare `.oss.json` asks for `<clone>/.oss.json`; anything carrying directory components asks
  for a path no config lives at. `os.path.relpath` returns exactly that whenever the project
  directory is not the current one — and also when it merely arrives under a different spelling of
  it, which on macOS is the default, `/tmp` being a symlink to `/private/tmp`. Measured: a config
  sitting in the clone reported `not found` from a subdirectory reached by the symlinked name, which
  is #53 reintroduced by its own fix. The bare name is now used only when the project directory *is*
  the current directory, proved with `samefile` rather than by comparing strings, and when it is not,
  a `WARN` says the enclosing clone was not searched — because `Run /oss:setup to write it` is the
  wrong advice in a worktree, and a clone nobody looked in must not read as a clone with nothing in
  it (#62).
- Two spellings of one directory stop reading as a conflict. `--root .` beside a `CLAUDE_PROJECT_DIR`
  naming the same place compared `Path` objects and warned that they disagreed. A warning that fires
  on agreement is what gets a real disagreement scrolled past (#62).

- The fold command in `/oss:changelog` passes `--dir` and `--changelog`, which the check command four
  lines above it already did (#65). The file stated the rule and then broke it on the one invocation
  that rewrites `CHANGELOG.md` and deletes every fragment: given neither flag,
  `assemble_changelog.py` walks up from its own location for a `.git` and finds **the plugin's own
  repository**, so a release cut by following the doc folded the wrong tree and reported success.
- The prose stating that rule is accurate about what the assembler now does. It said the default
  resolved "somewhere above whatever repo you are in", from a fixed parent count that has since
  become an upward `.git` walk; it names the repository the walk actually lands in, and says that a
  guessed root only reads the wrong tree under `--check` while the fold writes to it (#65). The same
  stale claim stood in `CLAUDE.md`'s trap list, which is the file that exists to stop this recurring,
  and it now describes the derivation the code has.
- `tests/test_command_references.py` sweeps `commands/`, `skills/` and `README.md` for every
  documented `assemble_changelog.py` invocation and fails on one missing either flag, with a detector
  control in the same fixture showing the sweep firing on a flagless line and staying quiet on a
  complete one -- a prose guard whose pattern stopped matching reports the same clean board as one
  with nothing to report (#65).

- The changelog fold will not choose its own target. `assemble_changelog.py` finds a repository
  root by walking up from its own file for a `.git`, which answers "which repo am I stored in" and
  not "which repo is being released". Inside the plugin those differ and the walk still succeeds,
  so a fold given neither `--dir` nor `--changelog` rewrote the plugin's own `CHANGELOG.md` and
  deleted the plugin's own fragments, under a receipt that said `ok` — the clean refusal for an
  underivable root was unreachable in exactly the deployment where the guess was wrong. The fold
  now requires both flags, exits `2` and prints the invocation to run instead of the flag names
  alone. `--check`, `--check-links` and `--count` keep the derived default: they only read, and
  every scaffolded repo's CI calls the vendored `.oss/` copy bare. The requirement is
  unconditional across both copies rather than detected per copy, because which repository the
  caller meant is not on disk — a wrong detection writes to a repository nobody named, while a
  needless refusal costs one line the receipt already prints (#67).

- The changelog rule installed into every scaffolded repo names the fragment checker where **that**
  repo keeps it, instead of where this one does (#68). The template carried a single constant,
  `scripts/assemble_changelog.py`, which is this repository's answer -- a scaffolded repo has the
  script vendored to `.oss/assemble_changelog.py`, so the one command the rule existed to give named
  a path that was not there. `oss_rules.assembler_path()` reads it off the tree being written into,
  and the two populations now get different commands out of the same generator.
- The invocation it emits passes `--dir` and `--changelog`. Given neither, the assembler derives its
  own root by walking up for a `.git`, which under a plugin finds the plugin's repository rather than
  the one being checked (#68, the same defect as #65).
- A tree with no assembler in it gets no command at all. The rule says the checker could not be
  located and names `/oss:scaffold` as the way to get one, rather than emitting a plausible path: a
  guess fails the first time somebody runs it and reads as their repository being wrong rather than
  as this generator never having looked (#68).
- The rule matches the fragment directory that repository actually uses rather than the `changelog.d`
  default, so a repo whose `changelog_dir` is spelled otherwise gets a rule that can fire (#68).
- `tests/test_oss_rules.py` asserts against the **generated** rule for both populations -- a
  scaffolded fixture and a plugin-shaped one -- that the path it names resolves to a file in the tree
  the layer was written into, with a control that the two commands differ, so a generator that went
  back to emitting a constant fails rather than passing on whichever tree the constant matched (#68).

- `/oss:scaffold` no longer quotes the origin URL verbatim when it refuses to ask the forge about a
  repo the checkout is not (#72). `git remote get-url` answers with the userinfo included, and
  `https://x-access-token:TOKEN@github.com/o/r.git` is an ordinary remote spelling -- what a CI
  checkout leaves behind and what several credential helpers write. The refusal is the line most
  likely to be pasted into an issue or a chat, because it is the one that needs explaining, so it was
  the worst place in the report for a token to land. `scripts/doctor.py` already stated the contract
  one module over: never echo a value that could be a credential.
- Userinfo is redacted rather than the URL suppressed, so the message still names the host and the
  slug a maintainer needs in order to fix their remote. The rule is "redact userinfo", not "redact
  userinfo that looks secret" -- a forge accepts the token as the whole username, with no password
  field to key off. The redacted span runs to the *last* `@` before the path, since an email as
  the username is an ordinary spelling and splitting on the first one leaves the password printed;
  a query string is dropped whole, because `?access_token=` is the other place a URL holds a
  secret. The scp-style `git@host:owner/repo` spelling is kept intact, and a backslash bounds the
  span so a Windows path is never mistaken for userinfo; a URL whose `@` belongs to no recognised
  shape is reported as not shown rather than passed through (#72).
- The same redaction runs over git's own stderr on the unreadable-origin arm, which is interpolated
  into a second message and which git can fill with the URL it was handed (#72).

- The release gate now scopes the delta to this repo's own tag namespace. `release_delta.py` derives
  the glob from `release.tag_pattern` in `.oss.json` -- `v{version}` becomes `v*` -- instead of asking
  `git describe` about every namespace at once (#73). The parameter and the value both existed and
  were never joined: in a repo that also tags nightlies or release candidates, the newest tag of any
  namespace became "the last release", the gate reported `delta` with full confidence over a fraction
  of the real range, and `could-not-run` never fired, because the script answered -- it just answered
  a narrower question than the gate asked. Invisible in this repository, which tags only `vX.Y.Z`.
- The glob is derived by the script rather than interpolated into the call by the command prose, and
  `commands/release.md` and `agents/release-auditor.md` both say so in those words (#73). A value a
  command tells an agent to substitute is a value an agent can substitute wrongly, and a wrong glob
  does not fail -- it answers.
- A range that could not be scoped says so instead of running unmatched in silence. Every payload
  carries `scope` and `scope_reason`, the receipt prints `UNSCOPED` with the cause, and the causes
  are distinct sentences: a null `tag_pattern`, an absent one, no `.oss.json`, a config that will not
  parse, or a pattern like `{version}` whose glob is `*` (#73). **It does not block.** A repo that has
  not said how its tags are spelled is common and legitimate, and refusing it would trade a quiet
  reporting gap for a release nobody can cut -- so the states are scoped, unscoped-and-said-so, and
  could-not-run.
- `release.tag_pattern` now decides the audited range and not only the tag being written, so a
  pattern that disagrees with how a repo actually tagged its last release anchors the audit somewhere
  else -- possibly on `first-release` in a repo that has releases (#73). Both call sites say that a
  `scope` which does not match the expected tag is a config finding rather than a delta.
- `_read_config` tells an absent config from an unreadable one by the exception it already caught,
  instead of calling `path.exists()` from inside the except (#73). That was a second filesystem call
  where nothing catches it, and `Path.exists()` swallows only a short list of errnos -- `ENAMETOOLONG`
  is not on it and neither is `EACCES`, so a config path with an over-long component, or one under a
  directory the process cannot traverse, killed the gate with a traceback instead of reporting the
  unscoped range. The list is also a moving target: observed on one machine with one fixture, 3.11 and
  3.13 raise where 3.14 returns `False`, so which arm ran depended on the interpreter.
- A `FileNotFoundError` carrying a `winerror` of 206 or 123 is reported as a config that could not be
  read rather than as one that is not there (#73), and `_read_config` now states the limit that
  remains. Windows folds several distinct Win32 codes onto `ENOENT` before Python picks the exception
  class, and one of them means the name was too long to look at -- which, called absence, is this
  project's own defect class arriving through the operating system rather than through our code.
  `getattr(exc, "winerror", None)` is the whole platform test; on POSIX it is `None` and nothing
  changes. **No input in the suite is known to reach that branch**, and it is marked as such where it
  sits rather than left looking load-bearing: the guess that Windows reports 206 for an over-long
  component was tested on CI and is false -- it answers `FileNotFoundError`, errno 2, `winerror`
  None, exactly what it answers for a file that is simply missing. So on Windows a config path this
  process could not look at is reported as a config that is not there, because by the time Python
  sees it the two are one event. The consequence is bounded and identical either way -- unscoped
  range, path in the reason, no traceback and no silent scope -- and only the choice of sentence is
  lost.
- The test that pins the reason against a long path builds the length from many short components
  (#73). Two limits, and the fixture was bitten by each from opposite directions: `MAX_PATH` caps the
  whole path at 260 on Windows, `NAME_MAX` caps a single component at 255 bytes on POSIX. Four nested
  directories failed all four Windows legs; one 256-byte component failed all eight POSIX legs. Short
  components joined by separators cannot violate either -- a construction rather than an assertion
  that a construction is safe -- and the assertions on both limits are tripwires on it. Which
  *sentence* that path earns is no longer asserted unconditionally, because it is not a
  platform-independent claim: the test measures what the operating system returned for the path and
  skips the classification with that measurement -- exception class, errno and `winerror` -- when the
  OS itself offered nothing to tell "could not look" from "nothing is there" -- decided by comparing
  the measurement against a plainly missing file of the same shape, not against a list of error codes.
  The list came first and was the same bug one level up: it could not report a value it did not
  contain, so a `winerror` of None read as "the OS distinguished this" and the failure it produced
  claimed a distinction while printing the evidence against it. The pair that claim
  exists for no longer needs a long path at all and now runs everywhere. The one case
  that wants a real deep checkout keeps it and carries a third state: it attempts the path and skips
  with the length, the errno and what went untested when the platform refuses, rather than shortening
  the names until they fit and deleting the case on the platform where paths are longest.
- The config is read tolerantly here rather than through `oss_config.load`, so an unrelated validation
  problem in `.oss.json` cannot stop a release the gate only consults that file for a glob (#73). A
  `tag_pattern` carrying a control character is refused as a tag spelling, and so is a `--match`
  carrying one, because a config value reaching git's argv also reaches the receipt's own lines at
  column 0 -- and `UnicodeDecodeError` is caught beside `OSError`, since it is a `ValueError`, so a
  `.oss.json` saved in another encoding leaves the range unscoped instead of killing the gate with a
  traceback and no receipt (#73).

- `_read_json_object` (`scripts/oss_config.py`) caught only `OSError` around its read, so a
  `.oss.json` or `.oss.local.json` saved in another encoding (cp1252, latin-1, UTF-16) raised
  `UnicodeDecodeError` -- a `ValueError` -- instead of being reported as a finding. It now catches
  both, and the reason text says which happened: "could not read" for a filesystem problem,
  "could not decode" for an encoding one, since the two want different fixes (#78).

- `/oss:doctor` no longer states a conclusion about jit-context index *content* from a measurement of
  index *mtime* (#80). A layer whose entry files were touched after the last rebuild was told, in the
  imperative, that "its row says something else. Rebuild the index." -- on repos where every row was
  byte-identical to what a rebuild would write, because the edits were to entry bodies and only
  frontmatter is indexed. Measured on the reporting repo: two warnings before, two OK lines after,
  with 11 paths rows and 5 tools rows re-derived and matching.
- The rows are now derived from each entry's frontmatter and compared, so the check has the three
  states this plugin exists to keep apart: rows that provably differ are the only thing that says
  **rebuild**; rows that match are OK, with a line naming how many entry files changed anyway; and a
  row the check *cannot* derive is named with its reason rather than judged. Timestamps are demoted to
  what they are -- a reason to look, and the only evidence left when the derivation declines.
- The derivation mirrors `claude-jit-context`'s `rebuild-tsv.sh` rather than the description of it:
  six tools columns with the entry filename third, not the five the report named; `mode` defaulting to
  `remind`; the frontmatter reader's wrapped-quote rule; and an invocation macro declined by name,
  because the index carries its expansion and a second implementation of somebody else's anchor is a
  confident wrong answer. Vocabulary is compared as a subset in one direction only -- the builder
  drops generic keywords against a project-configurable blacklist, so an unindexed keyword is
  documented behaviour and only an indexed keyword the frontmatter can no longer produce is proof.
- A row naming an entry that is no longer on disk is drift too: deleting a rule leaves its row behind,
  and the row is what runs (#80).

- `agents/developer.md` spawns its diff reviewer as `Explore` instead of `general-purpose` — a
  brief telling a `general-purpose` reviewer not to edit was not a tool grant, and twice in one
  session it edited the tree anyway. `Explore` has no `Edit`/`Write`, but it keeps `Bash`, a
  complete write path already used mid-run to redden an author's own concurrent suite, so the
  brief now says three things instead of one: spawn `Explore`; still tell it not to mutate the
  tree; and read the author's own suite figures as possibly contaminated by a concurrent reviewer
  (#82).

- The reviewer brief now states that a spawn's final message IS the return value — a reply ending
  in "findings reported above" returns empty, and an empty return used to read as a clean review.
  Reviewers must say `NO FINDINGS` and name what they checked when there is nothing to report, and
  the developer treats an empty return as `did not run`, reporting it as such rather than silently
  omitting the review (#84).

- `oss_config.py --build` no longer emits four wrong values at exit 0 with no warning: a root-level
  Python module carrying a `VERSION` or `__version__` constant (e.g. `_supertool.py`) is now measured
  as a version site the same way manifests are, instead of being invisible to the fixed candidate
  list. `ci.required_checks`, `worktree_root` and `state_file` are still derived the same way as
  before — they cannot be measured any more precisely without a CI run or an existing on-disk layout
  to read — but `--build` now prints a `NOTE` on stderr for each: `required_checks` counts workflow
  job declarations, not actual check runs, and a matrix or a reusable workflow can raise the real
  count well above it; `worktree_root` and `state_file` are a naming-convention guess, not something
  measured on disk. `/oss:setup` already told agents to relay every `NOTE` line, so the three new ones
  reach the same audience the first two always did (#85).

- `/oss:scaffold` no longer writes a second changelog gate onto a repo that already runs one under a
  different name. `present` used to be computed per path: `.github/workflows/oss-changelog.yml` being
  absent was enough to plan `replace`, even when the same repo already ran its own assembler through a
  workflow with a different filename -- two jobs both named `fragment`, two assemblers, and
  `ci.required_checks` moving by one with nothing pointing at it. The run now looks for another
  workflow mentioning `assemble_changelog`, naming the fragment directory, or referencing the
  `no-changelog` label, or an `assemble_changelog*` file anywhere in the tree, before writing the owned
  trio -- a hit **declines** it instead, and a new `changelog` finding names what it found. A workflow
  that could not be read is treated the same as one that matched: the risk here is one-directional, so
  "could not tell" is not the same as "none found." `--force-owned` writes the trio anyway, for a
  maintainer who checked the match by hand (#86, #105).

- The scaffolded `oss-changelog.yml` fragment gate is no longer satisfied by DELETING a
  fragment. `git diff --name-only` lists a deletion identically to an addition, so a pull
  request that changed product code and removed somebody else's pending fragment passed
  green and printed the deleted filename as the evidence one was present. The gate now
  takes two diffs — added-or-modified apart from deleted — and refuses deletions that are
  not accompanied by a rewritten `CHANGELOG.md`. `--diff-filter=AM` alone would have
  closed the bypass and turned every release cut red, since a release deletes every
  fragment it folds in and adds none; that case is now recognised and passes by name
  (#87).

- The scaffolded `oss-changelog.yml` now lists `types: [opened, synchronize, reopened,
  labeled, unlabeled]`. Its own failure message tells a contributor to label the pull
  request `no-changelog`, and under GitHub's default event set applying that label started
  no run at all — a re-run replays the original payload, so the label was invisible to
  that too. It does not retract the run that already failed; that is a repository setting
  and an API call, and the workflow says so where a reader will look (#88).
- The scaffolded `oss-changelog.yml` runs `assemble_changelog.py --check-links` as well as
  `--check`. The assembler had implemented it all along and nothing invoked it, so
  `CHANGELOG.md`'s link-reference definitions were audited for the first time by the run
  cutting the tag (#88).

- `CHANGELOG.md` carries the link-reference block it never had. Every `## [x.y.z]` heading this
  repository published rendered as literal bracketed text and `[Unreleased]` linked nowhere, for two
  releases, because `--check-links` was implemented from the start and no CI leg ever called it — a
  check nothing invokes reports exactly what a clean file reports. The changelog workflow now runs it
  on every pull request (#93).
- `0.1.0` gets no `releases/tag/v0.1.0` link, because it was never tagged and has no release page:
  that URL is a 404 that renders as a working link, which is the failure the audit exists to find
  rather than one to commit. It is declared instead, through a new `--untagged` flag on
  `--check-links` — per-repository, so it is a flag rather than a constant in a script that is
  vendored into repositories whose release history is not ours. A value that is not `x.y.z` is
  refused rather than dropped, and a declared version that does carry a link ref is still a finding
  (#93).
- The fold refuses, instead of reporting `ok`, when it is cutting a release into a file whose link
  refs it cannot write: it would add a heading that renders as literal bracketed text, and it used to
  say so on a `links none — ... left alone` line filed under a state meaning there was nothing to do.
  The refusal names which of the three shapes it found — no trailing block, a block with no
  `[Unreleased]` definition, or one that is not a `compare/vX.Y.Z...HEAD` line — because each is
  fixed differently, and it lands before the write and before any fragment is consumed. A genuine
  first release still writes nothing and still says so; there is nothing on disk for it to derive a
  URL from (#93).
- The fold keeps the line endings the changelog already had. `read_text` normalises CRLF to LF on the
  way in and text-mode `write_text` re-encodes to the platform's ending on the way out, so a fold
  rewrote a CRLF changelog as LF on POSIX and an LF changelog as CRLF on Windows — a diff of every
  line in the file, from a tool that edited three of them (#93).

- The release gate's config read carried a documented gap for the case Windows folds onto plain
  absence, and one untested sibling: `.oss.json` under a directory this process cannot traverse
  (`EACCES`). `_read_config` was already correct for it -- `PermissionError` never subclasses
  `FileNotFoundError`, so it lands in the plain `OSError` arm and is classified "could not be
  read" -- but nothing measured that, so it was an assumption wearing the shape of a fact (#94).
- `test_an_eacces_parent_directory_is_measured_not_assumed` chmods a directory to `000` and checks
  the classification against a real `PermissionError`, skipped as root -- root ignores the mode
  bits, and a test that passes under root while proving nothing is this repo's own defect class
  arriving through the test suite instead of the OS. It follows the existing control-based guard
  rather than a table of error codes, so it can only assert what this platform actually
  distinguished.
- `_WINERROR_COULD_NOT_LOOK` stays. The new fixture does not reach it -- `EACCES` never goes
  through the `FileNotFoundError` arm it guards -- so it gives no evidence either way about
  whether that branch is reachable; only a Windows fixture producing a distinguishable read
  failure can answer that, which remains open and is CI work, not a change to this function.

- `paths/01-oss/changelog-fragments.md`'s `match:` fired on a fragment being opened -- the moment
  someone is already doing the right thing -- and never on `CHANGELOG.md` itself, the one moment its
  main instruction ("do not hand-edit `CHANGELOG.md`") actually applies. The pattern now fires on
  both: `(changelog.d/|(^|/)CHANGELOG\.md$)`, a plain awk ERE with no `\s`/`\d`/`\w`/`\b`, which
  compile to something that matches nothing while awk exits 0. The check command it names already
  resolves per-tree since #68 -- `scripts/assemble_changelog.py` here, `.oss/assemble_changelog.py`
  in a scaffolded repo -- so that half of the report was already fixed and needed no further change
  (#108).

- None of the three shipped `01-oss` entries carried a `description:`, so under
  `JIT_CONTEXT_INJECT=summary` a match injected only a title and named the entry rather than
  saying what it holds -- the fragment naming convention, the do-not-hand-edit warning, `.oss.json`'s
  re-derive-before-acting rule and the tick state file's two refusals were all unreachable in that
  mode. All three now carry one (#109).

### Security

- `doctor.py` no longer lets the tree it is diagnosing write its own output lines. A
  `permissions` entry in `.claude/settings.json` containing newlines was interpolated into a
  finding and printed raw, so a managed repo -- where that file is tracked and a pull-request
  contributor can edit it -- could put attacker-chosen `OK` / `WARN` lines and a forged
  `VERDICT: ok` at column 0 of the maintainer's next `/oss:doctor` (#71). `--root` widened it to
  any tree doctor can be aimed at, including a clone nobody has read.
- The merge-permission check now reports **how many** entries matched and **which file** they are
  in, never the entry text (#71). The text was never needed to answer the question -- "is there a
  rule, and where do I change it" -- and the file it comes from is the one an attacker controls.
  The report still names every settings file it read, so the diagnostic did not get quieter.
- Sanitisation lives in `report()` rather than at the call site that was exploited, because every
  finding doctor prints is built from something the audited tree chose -- a settings entry, a
  path, a config value, a subprocess's stderr -- and a sanitiser at one of several call sites
  leaves the next one to rediscover this (#71). It is `release_delta.py`'s `_one_line`, adopted
  with its reasoning: a copy rather than an import, because both callers are security controls
  and neither may depend on an import that can fail. Findings truncated at the limit now say so,
  since a partial answer rendered as a whole one is the defect this plugin is named after.

## [0.2.0] - 2026-08-14

### Added

- `skills/manager/SKILL.md` — the maintainer loop, carrying process only. Every repo-shaped fact
  reads from `.oss.json` instead of being asserted in prose.
- `agents/developer.md` and `agents/triager.md`. Neither is granted `Read`/`Grep`/`Glob`:
  reads go through supertool via `Bash`, which makes the batching instruction binding rather than
  advisory. The triager is additionally denied `Edit`/`Write`.
- Content guards asserting no repo slug, clone path, worktree root or maintainer handle appears in
  any skill or agent, and that every document reading a public tracker keeps its untrusted-input
  clause.
- `scripts/oss_config.py` — reads, validates and derives `.oss.json`. Invents nothing: no labels
  means empty lists, no milestones means none, an undetectable test command stays `null`. Path
  containment refuses separators, drive prefixes and traversals before resolving, and returns the one
  resolved path the caller reuses.
- `scripts/doctor.py` and its bash launcher. Exit code 0 on every path, `OK`/`WARN`/`FAIL` lines, one
  `VERDICT`, no colour, and no config value that could be a credential is ever echoed. The launcher
  proves each interpreter candidate by running it and comparing a sentinel for equality.
- Commands `/oss:setup`, `/oss:triage`, `/oss:changelog`, `/oss:doctor`, with a guard that every
  script path they reference exists.
- `scripts/assemble_changelog.py` and `scripts/coverage_gate.py`, verbatim copies from
  claude-supertool, omitted from the coverage floor because they are maintained and tested there.
- Coverage floor at 85%; the suite earns 92%.
- `/oss:tick` — one pass of the maintainer loop. State first, board second, finish what is open
  before starting anything new, one state entry, arm the next tick and keep working in this one.
- `scripts/oss_state.py` — the tick state file. A corrupt file raises rather than starting fresh; an
  over-long decision is refused rather than truncated; timestamps are arguments, never a clock read.
- `/oss:scaffold` and `scripts/scaffold.py` — CLAUDE.md, security policy, code of conduct, issue and
  PR templates, dependabot. Never overwrites; the plan is the default and writing is opt-in. Also
  checks the repo's description and topics, and proposes neither.

- `scaffold.py` had no way to preview a generated file's content, though `/oss:scaffold`'s own
  instructions require showing it before writing. `--show` now prints the body of every file
  `apply` would actually write — both what it would create and what it would replace, labelled
  which is which — or `--show PATH` for one file; nothing is written, and it refuses to run
  together with `--apply` (#5).

- `bin/oss-workspace` registers the channel consumer itself, at local MCP scope, resolving its path
  from `installed_plugins.json` rather than by globbing the plugin cache — a glob answers with
  whichever version sorts last, which is a version the session is not running. The channel flag is
  passed only when that registration held: naming an unregistered server refuses the launch
  outright, and a session with no board beats no session (#13).

### Fixed

- `oss_config.py` gained `--probe REPO`, which measures a repo directory into a probe itself, and
  `--help` now prints the probe schema it writes. The schema had one implementation and it was
  undocumented, so `/oss:setup` assembled the probe by hand and got `files` wrong in a way nothing
  could detect — top-level directory entries instead of `git ls-files` output produced
  `test_command: null` and the wrong `version_sites`, with no error at any layer (#1).
- `--build` now refuses a probe that is not the documented shape instead of deriving around the
  gap. `probe.get("files") or []` made a typo'd key and an empty repo identical; absent is now a
  named failure and empty stays a measurement (#1).

- A version site is now a file that was read and found to carry a version, not a file that exists.
  `README.md` was listed on every repo that has one, including the repos where it carries no
  version at all, and `/oss:release` was told to bump a file with nothing to bump. Structured
  candidates get a key lookup, prose candidates a semver match, and a candidate that could not be
  read is reported rather than folded into "carries no version" (#2).

- The `/oss:setup` recipe that called `gh-labels` — a supertool preset op, which does not load in a
  repo with no `.supertool.json`, the state of every repo setup is pointed at — is gone. It was
  removed by the `--probe | --build` rewrite rather than repaired in place; `--probe` calls `git` and
  `gh` through subprocess and touches supertool nowhere, so the precondition conflict cannot recur in
  the recipe (#3, fixed by #19).
- What survived that rewrite was the rule the recipe existed to serve: *never write a label name you
  have not seen in `gh-labels` output*. Still unsatisfiable for the same reason, and still the rule an
  agent is asked to obey while onboarding a repo where that op cannot run. It now names the probe's
  `labels`, which carries them as the repo spells them, and says why it is not `gh-labels` so nobody
  puts it back (#3).
- A regression guard pins setup.md against calling a preset op, with a positive control beside it.
  The recipe is fixed, but the precondition did not change: whatever setup grows next still runs
  before `.supertool.json` exists (#3).

- `/oss:setup` said never write identity into the target repo while `/oss:doctor` warned that it was
  missing and told you to write it, and in a repo where the memory store is inside the repo those are
  the same directory. Both now name one measured location — `<repo>/.remember/identity.md` — and state
  why it is safe: the memory plugin writes a `.gitignore` containing `*` there, so the store is
  untracked by construction. The publication hazard is real, and it lives in tracked locations like
  `.claude/`, which setup now says outright instead of leaving the reader to adjudicate (#4).

- `/oss:scaffold` creates the changelog fragment directory it installs a workflow to
  police, with a README explaining the naming. The checker reads an absent directory as a
  failure rather than an empty one, so the workflow used to be red on the very pull
  request that added it (#6).
- The scaffold run now names the `no-changelog` label the generated workflow relies on as
  its escape hatch, and the command that creates it. The label is not created for you:
  writing a file into a checkout is revertable from a diff, and changing a repository's
  labels on the forge is not something a file-writing command should do (#6).

- `/oss:scaffold` creates `.supertool.json`, which is the file that decides which supertool ops exist,
  and never said so. The op listing the running agent works from was captured at session start, before
  that file existed, and is never refreshed — so the session that installs the config is the one that
  cannot see what it installed, and learns its new inventory one rejected raw command at a time. The
  command now lists every file it writes, tells you to re-read the inventory with
  `supertool 'ops-compact'` right after `--apply`, and warns that `gh-issue-create` takes its repo
  target in the payload rather than from a `repo:` op (#7).

- `check_metadata` read topics from a `topics` key of flat strings, but `/oss:scaffold` feeds it
  `gh repo view --json description,repositoryTopics` directly, which carries topics as
  `repositoryTopics: [{"name": "..."}, ...]`. The key never matched, so every repo reported its
  topics as missing regardless of how many it had, and hands over a ready-made
  `gh repo edit --add-topic` for a repo that was already well tagged. `check_metadata` now reads
  either shape, and a probe carrying neither key or an unrecognised entry shape is reported as
  `unknown` rather than folded into a confident `missing` (#8).

- The doctor's identity warning named `.remember` and read `.claude/remember`, so seeding the file
  exactly where the message said left the warning byte-for-byte unchanged, with nothing to tell a
  wrong path from wrong content. It now names every directory it consulted, relative to the repo (#9).
- The lookup itself was in the wrong directory, which the message was hiding. Measured against the
  memory plugin's session-start hook rather than reasoned about: it resolves `identity.md` against the
  data dir, then the data dir's parent, then the plugin's own directory. In a dependency install —
  which is how this plugin declares the memory plugin — the plugin's own directory is outside the
  repo, so `<repo>/.claude/remember/identity.md` is never injected at all. The check consulted only
  that path, so a repo with a working identity was told it had none (#9).
- An identity file that exists and is never read is now its own finding rather than a pass. The
  data dir is `OK`; a copy beside `config.json` is `OK` only when the plugin is installed there —
  a `scripts/` directory is the tell — and otherwise `WARN`, because that state looks configured
  from every angle except the one that matters. Two of our own repos are in it (#9).

- `package.json` and `Cargo.toml` are version site candidates. `TEST_COMMANDS` already detected
  both ecosystems, so a Node repo was told to bump `README.md` and never told about `package.json`
  — a false positive and a false negative cancelling into a config that looked populated (#10).
- Priority and lane labels are matched across the spellings in the wild: `priority/high` — GitHub's
  own namespaced convention — `prio:`, bare `P1`, and `area/` and `type/` as lanes (#10).
- `--build` names, on stderr, every label that matched no pattern. No pattern list covers every
  convention, so the durable fix is making a miss visible rather than making it rarer: "9 labels, 4
  unclassified: priority/high, priority/low, area/api, P1" reads nothing like "9 labels, 0 matched",
  and only one of them can be told apart from a repo that genuinely has no priorities (#10).

- `/oss:scaffold` and `/oss:doctor` report when `ci.required_checks` is 0 in a repo that
  has workflow files, naming both facts. The number is deliberately not re-derived:
  counting workflow jobs cannot see an organisation-level required workflow, a branch
  protection rule or an app posting a status, so the count would be wrong wherever those
  exist — and a guessed number on disk is indistinguishable from a measured one. The
  report names the observation that settles it,
  `gh api repos/OWNER/NAME/commits/<sha>/check-runs`, and a value already set by hand is
  left alone (#11).

- `/oss:scaffold` and `/oss:doctor` report a verified `test_command` that no workflow
  runs. A repo in that state goes green with its changelog fragment checked and its tests
  not run at all, and `/oss:manager` merges on green — so green was an absence rather than
  a result. Three states are reported, not two: the command is run verbatim by a workflow,
  or nothing mentions it, or a workflow mentions the runner and whether that is the same
  suite cannot be told from here. No test workflow is generated — the runner, the matrix
  and the language version are decisions nothing here has measured (#12).

- `bin/oss-workspace` put its prompt after `--dangerously-load-development-channels`, which is
  variadic and swallowed it, so the first real use of the launcher died on
  `entries must be tagged: /oss:tick` instead of opening anything. The prompt goes first now and the
  flag last (#13).
- The launcher looked for `python3` by name, which Windows does not ship, so the channel name and
  the consumer path were both silently unreadable there. Each candidate is now proved by running it
  (#13).
- `verify_test_command` read only 127 as "command not found", which is the POSIX shell's code.
  cmd.exe answers 9009, so every missing runner on Windows reported as a failing suite — sending
  someone to debug a suite that was never installed (#13).

- `/oss:tick` and the manager skill both instruct the agent to merge on green, and the op they name
  merges nothing: without a `|force` suffix `gh-pr-merge` evaluates its gates, prints the preview and
  exits `requires explicit confirmation`. So a tick reached the merge step with every gate satisfied,
  the whole review already spent, and could not finish. The skill now carries a *Before the first
  tick* section stating the three opt-outs and their reach — `|force` per call,
  `SUPERTOOL_NO_PUBLISH_CONFIRM=1` per environment, `no_publish_confirm` per project — and recommends
  the narrowest, because the gate is shared with the publishing ops rather than specific to merging.
  It also states the part that is not a permission rule at all: the harness can deny the call before
  supertool sees it, the plain and `|force` forms are different command strings so approving one does
  not carry to the other, and routing around a denied merge via raw `gh` is worse than the call it
  replaces (#14).

- `agents/developer.md` had no answer for material worth keeping as evidence but not worth
  paying for on every later turn of the maintainer's session -- the full reviewer exchange, a
  caller inventory, sweep output behind a one-line claim. It now writes that to
  `<worktree_root>/notes/<branch>-<timestamp>.md`, a sibling of the numbered worktree
  directories so it can never enter the diff and needs no `.gitignore` entry -- the same reason
  `.oss.json` is excluded via `.git/info/exclude` rather than committed. The report keeps the
  judgment calls and ends with the note's absolute path plus one line on what the split cost,
  so the saving stays a measured claim (#15).

- `bin/oss-workspace` decided the channel was ready on the *existence* of an `oss-channel`
  registration and never on where it pointed. The path `claude mcp add` stores is absolute and
  version-pinned, and the plugin cache drops the old version directory on auto-update: the
  registration outlives the file, `claude mcp get` still exits 0, the launch still passed
  `--dangerously-load-development-channels`, and `bun` started nothing — a board that looks armed and
  delivers nothing, which is the state the launcher's own header exists to prevent. The registered
  command and path are now compared against the freshly resolved consumer, and a mismatch is
  re-pointed (#16).
- A re-point names both paths on stderr. Repairing the entry quietly is the other half of the same
  defect: the user's MCP config changed and the output held no way to find out from what (#16).
- A registration that exists while the consumer path could NOT be resolved — no working python, an
  unreadable `installed_plugins.json` — no longer reports as a missing consumer, and no longer counts
  as ready. It cannot be checked, and that is what it says. The same goes for a `claude mcp get`
  whose output carries no `Command`/`Args` lines to compare (#16).

- The generated `oss-changelog.yml` installs the parser the vendored fragment checker
  needs, before running it. Without that step the checker reported `skipped` and exited
  non-zero — correctly; the defect was entirely in the workflow calling it. A scaffolded
  repo did not show this on its own pull request, because with zero fragments the checker
  reaches a verdict without needing a parser, so the job only turned red on the first
  pull request that carried one — after the scaffold had been verified as working. The
  dependency is declared once in `scaffold.py` and the test suite holds that declaration
  against the guarded imports in the checker, so a new dependency fails our tests rather
  than somebody's first pull request. `.oss/README.md` names it too, for the maintainer
  running the check locally (#17).

- `scripts/assemble_changelog.py` derived its default `--dir`/`--changelog` from
  `Path(__file__).resolve().parents[2]`, which is one level above the repo root for a script that
  lives at `scripts/` — so a bare `--check` failed on every checkout, and from inside a git worktree
  produced a concatenated relative-plus-absolute path in the finding text. The root is now found by
  walking up from the script for a `.git` entry (a directory in a clone, a file in a worktree), which
  answers correctly at any vendoring depth instead of assuming one; when no `.git` is found above the
  script, the tool now says so and asks for `--dir`/`--changelog` explicitly rather than composing a
  path out of a guess. `.github/workflows/changelog.yml` no longer passes the flags explicitly, so CI
  now exercises the same bare invocation documented in `changelog.d/README.md` (#20).

- `changelog.d/README.md` carried a section saying this repo has no tracker yet and that
  `CHANGELOG.md` stays hand-edited until one exists — while the fragments beside it were already
  keyed to real numbers under the naming convention the section said was not in use. Replaced with a
  note on the actual ambiguity a contributor hits: issues and pull requests share one numbering, and
  most fragments here are keyed to the pull request that shipped the fix rather than a separate
  tracking issue (#21).

- `.oss/assemble_changelog.py` -- vendored into every scaffolded repo -- cited issue numbers
  and a `changelog.d/README.md` pointer from this project's own history. A bare `#NNN` resolves
  against whichever tracker the reader is standing in, so those citations pointed at an unrelated
  issue in the scaffolded repo, or at nothing. The reasoning each citation stood in for was already
  stated in prose, so the numbers and the pointer were dropped rather than replaced (#24).

- Changelog fragments are now refused for where their links and images point, not only for
  their shape. Links may use `http`, `https`, `mailto` or a path inside the repository;
  images may use a repository path only, because a link waits to be clicked and an image is
  fetched by whatever renders `CHANGELOG.md`, turning an off-repo one into a beacon that
  reports every reader of the release notes. The checker refused every other way of getting
  content into a released changelog and never looked at a destination, and a checker that
  closes the rest of a class silently is read as closing the class — so the `ok` receipt now
  says destinations were checked, and the re-parse of the written file refuses any the
  release added (#30).
- The scan parses with the Markdown library's own link sanitiser disabled. It refuses a
  `javascript:` destination by declining to build a link at all, so there was no token for a
  scheme allowlist to inspect and the obvious fix would have refused nothing while passing
  CI — while the fragment text still reached `CHANGELOG.md` verbatim, to be rendered by tools
  this repository does not choose. The same blind spot hid a `javascript:` link-reference
  definition indented under a bullet, which passed `--check` clean until now (#30).

- `changelog_dir` is now checked for shape, so a value carrying a command substitution can no
  longer be substituted unquoted into the `run:` body of the workflow the scaffold writes into
  another repository. `validate()` refuses anything that is not a relative path of plain
  segments, the scaffold refuses it again at the point of substitution, and a non-string is
  refused with a sentence instead of crashing the renderer. Nested directories such as
  `docs/changelog.d` keep working (#31).

- Every workflow now declares `permissions: contents: read` — this repo's changelog and tests
  workflows, and the changelog workflow the scaffold generates for other repositories. Without
  it a job inherits the repository default, which is read/write until somebody changes it, and
  both changelog workflows execute the assembler from the pull request's own checkout (#32).

- The test workflow installs `markdown-it-py`, so the suite covering the changelog assembler
  now runs on a runner at all. It installed `pytest pytest-cov` and nothing else, and the
  assembler refuses to work without its parser rather than falling back to text scanning —
  so every test touching it errored on every platform and every Python version. The heading
  refusal, the raw-HTML refusal, the fence state machine and the unclosed-fence check had
  therefore never been exercised in CI; they passed locally only because the package happened
  to be installed there (#38).
- The package name is declared in one place, `scaffold.ASSEMBLER_DEPENDENCIES`, and was
  already held against both the assembler's guarded imports and the workflow generated for
  scaffolded repos. It was never held against the two workflows this project runs on itself,
  which is why the plugin guaranteed the parser for every repo it scaffolds except the one it
  lives in. Both are now checked, along with any workflow added later that reaches the
  assembler (#38).
- The message printed when the parser is missing no longer suggests `pip install -e .[dev]`,
  which fails here: this repository declares no installable package, so the advice shown on
  the exact failure it was written for was advice that could not be followed (#38).

## [0.1.0] - Scaffold

### Added

- Plugin manifest, Community License, cross-platform CI matrix (3 OS x Python 3.9-3.12).
- Version guard tying `.claude-plugin/plugin.json` to the newest CHANGELOG release and the README badge.

<!--
0.1.0 has no link reference on purpose. It was never tagged and has no release
page -- `git ls-remote --tags` and `gh release list` both name v0.2.0 and
nothing else -- so `releases/tag/v0.1.0` would be a 404 that renders as a
working link, which is the failure the audit exists to catch rather than one to
commit. It is declared to the audit instead, with `--untagged 0.1.0`, in
.github/workflows/changelog.yml and in the command that runs it by hand (#93).
-->

[Unreleased]: https://github.com/Digital-Process-Tools/claude-oss/compare/v0.15.0...HEAD
[0.15.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.15.0
[0.14.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.14.0
[0.13.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.13.0
[0.12.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.12.0
[0.11.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.11.0
[0.10.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.10.0
[0.9.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.9.0
[0.8.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.8.0
[0.7.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.7.0
[0.6.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.6.0
[0.5.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.5.0
[0.4.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.4.0
[0.3.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.3.0
[0.2.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.2.0
