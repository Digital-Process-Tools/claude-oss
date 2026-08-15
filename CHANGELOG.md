# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Digital-Process-Tools/claude-oss/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.3.0
[0.2.0]: https://github.com/Digital-Process-Tools/claude-oss/releases/tag/v0.2.0
