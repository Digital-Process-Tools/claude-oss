# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.1.0] - Scaffold

### Added

- Plugin manifest, Community License, cross-platform CI matrix (3 OS x Python 3.9-3.12).
- Version guard tying `.claude-plugin/plugin.json` to the newest CHANGELOG release and the README badge.
