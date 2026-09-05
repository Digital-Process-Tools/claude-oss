"""The `01-oss` rule layer: knowledge about this plugin's own artifacts, injected on touch.

Layers are the ownership boundary. `00-manual/` belongs to whoever maintains the repo.
`01-oss/` belongs to this plugin, and that is what makes updating safe: the layer is
replaced wholesale on every install, because nothing a human wrote lives in it, and the
human's layer is never read or written.

Why copies rather than a link into the plugin checkout: a linked layer is refused by the
rules engine on purpose. Git tracks symlinks, a clone recreates them, and a linked layer
carries its own index -- so one committed link would be enough to point a stranger's
rules at anything on the machine. Copies into an owned layer are the supported shape.

Rows are written in the same format a rebuild would produce -- `pattern<TAB>filename` for
paths and vocabulary, the seven-column shape for tools (see `index_rows()`) -- so regenerating
the index is a no-op rather than a diff.

Python 3.9 compatible.
"""

from pathlib import Path

LAYER = "01-oss"
INDEX = "00-index.tsv"


def owned_shape(name):
    """True if `name` is a shape `install()` could have written, any version.

    Only two shapes, and they have not changed across a version of this plugin: a `.md`
    rule file, or the layer's own index filename. Anything else present in the layer was
    written by something other than this plugin's own `install()` -- see #755, #1042.
    `scaffold._rule_layer_shape()` used to carry this same check as a private copy for
    its own preview; it now delegates here so the preview and the write agree on the one
    fact both are stating.
    """
    return name.endswith(".md") or name == INDEX


class RulesError(Exception):
    """The rules could not be installed."""


#: The default when the caller has no `changelog_dir` to give. Held against
#: `scaffold.DEFAULT_FRAGMENTS_DIR` by the suite: two spellings of one default drift, and
#: the rule would then match a directory the scaffold never creates.
DEFAULT_FRAGMENTS_DIR = "changelog.d"

#: Where the fragment assembler can be, most-owned first. `.oss/` is the vendored copy
#: `/oss:scaffold` writes into a managed repo -- CI checks out that repo and nothing else,
#: so the script has to live there. `scripts/` is where it lives in this plugin's own
#: repository. A tree holding both is a plugin checkout scaffolded onto itself, and the
#: owned copy is the one this plugin keeps current.
#:
#: Written with forward slashes on every platform. The value ends up in a shell command,
#: python3 accepts `/` on Windows, and a backslash in Markdown is an escape to whatever
#: reads it next.
ASSEMBLER_LOCATIONS = (".oss/assemble_changelog.py", "scripts/assemble_changelog.py")


def assembler_path(repo_root):
    """Where the assembler is **in this tree**, or `None` if it is not in this tree.

    The correct answer differs between this repository and a repository this plugin
    manages, so it cannot be a constant in shared code -- a constant ships one
    population's answer to the other, and this template used to ship this repo's (#68).

    `None` is the third state and it is load-bearing. A generator that cannot find the
    script must not emit a plausible path: the command then fails on first use and reads
    as the repository being broken rather than as this rule never having looked.
    """
    root = Path(repo_root)
    for relative in ASSEMBLER_LOCATIONS:
        if (root / relative).is_file():
            return relative
    return None


CHANGELOG_FRAGMENTS = """---
title: "Changelog fragments"
description: "One file per pull request; do not hand-edit CHANGELOG.md while changelog.d/ exists -- the fold overwrites it and deletes the fragments."
match: (__FRAGMENTS__/|(^|/)CHANGELOG\\.md$)
---

One file per pull request, so two open PRs never touch the same file. `CHANGELOG.md` is assembled
from these at release time and the fragments are deleted.

**Name:** `<issue>.<section>[.<slug>].md`, where the section is a Keep a Changelog heading,
lowercased: `added`, `changed`, `deprecated`, `removed`, `fixed`, `security`. `<slug>` is optional
and lets one issue file two entries in one section without two pull requests colliding on a path.

**Body:** a single top-level `-` list. No headings, no raw HTML, no unclosed fences. Name the issue
in the text as well as the filename -- the filename is metadata, and metadata does not survive being
read out of context.

**A `removed` fragment must declare compatibility**, as one more bullet in that list:

    - Compatibility: breaking - <reason>
    - Compatibility: compatible - <reason>

`/oss:release` reads it to propose the version. A removal that declares nothing stops the proposal
and names the file, rather than being read as a quiet minor -- whether a removal breaks anything is
the question the number turns on, and an author who knows the answer and writes it as prose puts it
where nothing can read it. The reason is part of the field: a bare verdict is the same unsourced
answer one field further along. Other sections may carry the bullet and are read as compatible when
they do not.

The fragment check reads this line too, so a declaration that will not parse -- a word that is
neither verdict, a verdict with no reason, both at once, or a `removed` fragment carrying none --
is a finding on the pull request that introduced it rather than a stopped release days later.

**Do not hand-edit `CHANGELOG.md`** while this directory exists. The fold overwrites it and deletes
the fragments; an entry written directly into the file is lost at the next release, silently,
because the fold has no way to know it was meant to stay.

__CHECK__"""


def _untagged_clause(untagged):
    """The `--untagged` half of the command this rule prints, in three states.

    `None` is "this repository declared nothing", `[]` is "it declared that nothing is
    exempt", and a list is the declaration. The rule used to explain the flag
    generically and name no version, which is a rule about a tool rather than about the
    repository it was installed into -- and a reader following it had to go and work out
    their own answer, which is the work the config key exists to have done once (#101).
    """
    if untagged is None:
        return "", (
            "This repository declares no untagged versions in `.oss.json`, so every "
            "`## [x.y.z]`\nsection is expected to carry a link ref. If one of them was "
            "never tagged, add it to\n`changelog_untagged` and re-run `/oss:scaffold "
            "--apply` — the CI leg reads the same key,\nso the two cannot disagree. "
            "Declaring `[]` says the same thing deliberately.\n"
        )
    if not untagged:
        return " --untagged ''", (
            "`changelog_untagged` is declared empty in `.oss.json`: every release "
            "section here was\ntagged, and that is a decision on record rather than a "
            "question nobody asked.\n"
        )
    return " --untagged '{}'".format(",".join(untagged)), (
        "The declaration above is not written here: `changelog_untagged` in "
        "`.oss.json` names {},\nand the CI leg reads the same key, so the command you "
        "run and the one that gates the pull\nrequest cannot disagree. Add a version "
        "there and re-run `/oss:scaffold --apply`.\n".format(", ".join(untagged))
    )


#: The three answers `scaffold._detect_changelog_gate` can give about a changelog gate
#: already running under another name. `None` -- no pair at all -- is the fourth, and it
#: is the one that says nobody looked; it is the default because a caller that did not
#: pass a gate did not check one.
GATE_STATES = ("none", "found", "unknown")


def _inline(detail):
    """A repo-derived detail, safe to drop inside a Markdown code span.

    The detail is built from filenames in somebody else's repository, so it is data.
    A backtick in one would close the span and spill the rest of the sentence into the
    rendered rule; a newline would end the paragraph. Neither survives.
    """
    flat = " ".join(str(detail).split()).replace("`", "'")
    return "`{}`".format(flat) if flat else "no detail was given"


def _no_assembler_because(gate):
    """Why the checker is not in this tree -- or that this was never established.

    Four answers, because the caller has four (#117). The pre-#117 rule had one: it told
    every reader that `/oss:scaffold` vendors the checker and would rewrite this rule.
    That sentence is false in exactly the repository the decline produces -- `/oss:scaffold`
    is the command that declined, and it declines again -- and it renders identically to
    the same sentence in a repo where it is true. A rule that cannot describe the
    repository it is in has to say so rather than describe a different one.
    """
    if gate is None:
        return (
            "**Why it is missing was not established**: whatever wrote this rule did not\n"
            "check whether this repository already runs a changelog gate under another\n"
            "name. `/oss:scaffold` vendors this plugin's checker when it finds no other\n"
            "gate and declines when it does, so running it may or may not rewrite this\n"
            "rule -- which of the two is unknown here.\n"
        )

    state, detail = gate
    if state == "none":
        return (
            "`/oss:scaffold` found no changelog gate of any other name here, and it\n"
            "vendors the checker: run that and this rule is rewritten with the\n"
            "invocation.\n"
        )
    if state == "found":
        return (
            "**`/oss:scaffold` will not put one here.** A changelog gate already runs in\n"
            "this repository under a different name ({}), so the owned checker was\n"
            "declined rather than written on top of it -- and running `/oss:scaffold`\n"
            "again declines again. **This rule does not know that gate's command.** Read\n"
            "what the parentheses above name -- one file or several, and possibly a note\n"
            "about part of the tree that could not be read: that is the gate this\n"
            "repository actually runs.\n"
            "`/oss:scaffold --force-owned` installs this plugin's checker alongside it,\n"
            "after which both gates run on every pull request.\n"
        ).format(_inline(detail))
    if state == "unknown":
        return (
            "**Why it is missing is unknown, which is not the same as this repository\n"
            "having no gate of its own.** Part of the tree could not be read ({}), so\n"
            "`/oss:scaffold` declined the owned checker rather than write it over a gate\n"
            "it could not rule out, and it declines again until that read succeeds.\n"
            "Check by hand; `/oss:scaffold --force-owned` overrides.\n"
        ).format(_inline(detail))

    # Not a state this module knows how to describe. The branch it would otherwise fall
    # through to is the one claiming nobody looked, and somebody did -- so refuse rather
    # than render the most plausible sentence to hand.
    raise RulesError(
        "unknown changelog gate state {!r}; expected one of {} or None".format(
            state, ", ".join(GATE_STATES)
        )
    )


def changelog_fragments(assembler, fragments_dir, untagged=None, gate=None):
    """The fragment rule, rendered for one tree.

    `assembler` is a repo-relative path or `None`; `fragments_dir` is that repository's
    fragment directory, which is not `changelog.d` everywhere and is what the rule has to
    match on or it never fires at all. `untagged` is that repository's
    `changelog_untagged`, in the three states `_untagged_clause` keeps apart.

    `gate` is what the caller established about a changelog gate already running under
    another name -- `(state, detail)` from `scaffold._detect_changelog_gate`, or `None`
    for a caller that did not look. It is consulted only when there is no assembler,
    because it answers one question and one only: why not. It is orthogonal to
    `untagged`: that one shapes the command when there IS an assembler, this one
    explains the absence when there is not.
    """
    if assembler:
        # Both `--dir` and `--changelog` on every invocation. Given neither, the assembler
        # derives its own root by walking up for a `.git`, which under a plugin finds the
        # plugin's repository rather than the one being checked.
        flag, declaration = _untagged_clause(untagged)
        # Two commands, and the split is not cosmetic. The assembler refuses `--check`
        # and `--check-links` in one call: together they used to run the links audit
        # alone and print a single confident `ok` naming only the half that ran. This
        # rule published that combination for as long as it was merely misleading, and
        # kept publishing it after the script turned it into a hard refusal -- so the
        # documented pre-push command audited nothing, in a repository that had done
        # nothing but refresh its scaffold. Both files are `ours` and are replaced in
        # the same run, which is why nothing connects the two events for the reader.
        #
        # `--dir` and `--changelog` on both lines rather than one each: that is what
        # `scaffold.CHANGELOG_WORKFLOW`'s two steps pass, and this rule closes by
        # promising the reader that their command and the CI leg's cannot disagree.
        check = (
            "Check before pushing. **Two commands, not one:** the checker refuses both "
            "audits in a\n"
            "single call, and says so. They used to be combinable, and the combination "
            "quietly ran the\n"
            "link audit alone while printing one confident `ok` for it -- so each flag "
            "now gets its own\n"
            "invocation, and each audits its own thing completely.\n"
            "\n"
            "```bash\n"
            "python3 {0} --check --dir '{1}' --changelog CHANGELOG.md\n"
            "python3 {0} --check-links{2} --dir '{1}' --changelog CHANGELOG.md\n"
            "```\n"
            "\n"
            "Those are the same two commands the scaffolded changelog workflow runs as "
            "its own two\n"
            "steps, so the pair you run before pushing and the pair that gates the pull "
            "request cannot\n"
            "disagree.\n"
            "\n"
            "`--check-links` refuses when a `## [x.y.z]` section has no link reference "
            "definition. If the\n"
            "version it names was never tagged, the missing link is the correct state: there "
            "is no release\n"
            "page to point at, and a `releases/tag/vX.Y.Z` URL written for one is a 404 that "
            "renders as a\n"
            "working link.\n"
            "\n"
            "{3}"
        ).format(assembler, fragments_dir, flag, declaration)
    else:
        # Named as a third state rather than filled with a guess. No path appears here on
        # purpose: a plausible one is indistinguishable, to whoever runs it, from a path
        # that was checked. Why it is not here is a separate question and the remedy
        # depends entirely on the answer, so it is asked of the caller rather than guessed.
        check = (
            "**The fragment checker could not be located in this repository**, so this rule\n"
            "names no command. A path guessed here would fail the first time anybody ran\n"
            "it, and read as this repository being wrong.\n"
            "\n"
        ) + _no_assembler_because(gate)

    return CHANGELOG_FRAGMENTS.replace("__FRAGMENTS__", fragments_dir).replace(
        "__CHECK__", check
    )


OSS_CONFIG = """---
title: ".oss.json is config, not truth"
description: "Per-repo settings for the maintainer loop. Re-derive labels before acting; the CI leg count is not in here; null is an answer, not a gap."
match: (^|/)\\.oss\\.json$
---

Per-repo settings for the maintainer loop: `repo`, `default_branch`, `clone`, `worktree_root`,
`test_command`, `version_sites`, `labels`, `state_file`, `release`.

**Re-derive anything load-bearing before acting on it.** This file records what a probe observed on
the day it ran. `labels` rots first: they are spellings, and they differ between repos -- one spells
it `priority-high`, another `priority:high`. Read them off the repo before writing one, and never
invent a label that is not already there.

**The CI leg count is not a key here, and must not be added as one.** There was a
`ci.required_checks`; it counted workflow job declarations, which a build matrix, a reusable
workflow or an organisation/app-level check multiplies or adds to invisibly, so the number on disk
was never the merge gate's. Count the legs on the pull request they apply to, every time. Any leg
that is not a success gets named before merging -- cancelled, skipped, timed out and neutral are
none of them passes and none of them pendings. A config still carrying the block is harmless and
safe to delete; nothing reads it.

**`null` is an answer, not a gap.** `test_command` and `changelog_dir` may be null and mean "the
probe could not tell". Everything else null is a hole -- the probe found nothing and said nothing.

**`changelog_untagged` has three states and they are three.** It lists the `## [x.y.z]` sections in
`CHANGELOG.md` that were never tagged, so the link-ref audit does not demand a `releases/tag/v...`
URL that would 404. Absent or `null` means nobody declared anything and every section is expected to
carry a link ref -- a default reading, not a statement. `[]` means the repository has declared that
every section was tagged: the same audit, and a decision on record. A list names the exempt versions.
The scaffolded CI leg and the fragment rule both render from this key, so the answer is written once.
Versions, not tags: `0.1.0`, never `v0.1.0`. A declared version with no matching section is a finding.

**`user_visible_paths` has the same shape as `changelog_untagged`, and the empty-list case is the
one to get right.** It lists regexes naming which changed paths this repository considers
user-visible, so the generated changelog gate can exempt a pull request that touches none of them.
Absent or `null` means nobody declared anything -- the gate stays unconditional, exactly today's
behaviour. Unlike `changelog_untagged`, `[]` is NOT a legal "declared, and nothing is user-visible":
it is refused at validation, because reading an empty list that way would silently turn the gate off
for the whole repository. A list names the patterns; `oss_config.user_visible_paths_problem` is
where all three states are decided.

**No key here holds a credential.** The file is committed; tokens live in the forge CLI's own auth.
"""

#: Added to this repository's own layer by `655c9a4` and, until #702, declared nowhere in
#: this module -- so it was deleted by the next `/oss:scaffold --apply` (`install()` removes
#: the layer before rewriting it) and had never reached a single managed repository. The
#: divergence was invisible because the only sync guard in this repository compared one
#: hand-named pair; `tests/test_jit_layer_set_sync_702.py` now compares the sets.
#:
#: It ships rather than being deleted here, because its subject is the plugin, and the
#: plugin is present in every repository this layer is written into: which of three copies
#: answered, why `/reload-plugins` is not a restart, and which number each statusline marker
#: prints are all questions a maintainer of a MANAGED repo asks, with the same wrong answers
#: available. The one sentence that was true only here -- `ahead` being normal for "this
#: repo's own clone" -- was corrected in both copies rather than carved out, so the two stay
#: byte-identical and a plain comparison can hold them together.
PLUGIN_CURRENCY = """---
title: "Which copy of the plugin answered, and which version is current"
description: "Three different things are called 'the version' and they routinely disagree. Reading the wrong one, or reading the statusline marker backwards, has cost this repo whole sessions."
keywords: reload-plugins, plugin version, plugin copy, plugin currency, statusline, oss-workspace, plugin cache
---

Three readings, three different questions. They disagree normally, not exceptionally.

| reading | where | answers |
| --- | --- | --- |
| **clone / tree** | `.claude-plugin/plugin.json` in the checkout | what the source says today |
| **registry / session** | the path inside an injected slash-command's own text | which copy this command resolved from |
| **installed cache** | `~/.claude/plugins/cache/dpt-plugins/oss/<version>/` | every version ever unpacked |

**Old directories in the cache mean nothing.** `claude plugin update` unpacks a new one and leaves
the rest. Ten directories is normal; it is not evidence about what resolves.

**`doctor`'s `plugin copy` line compares content, not version numbers.** The manifest version does
not move between releases, so an installed copy at the tag and a clone a cycle past it declare the
same number. A `SKEW` is a report, not a fault -- it is the normal state between a merge and a
release. What it costs you: plugin prose quoted from the running session may be text the clone no
longer contains.

## `/reload-plugins` vs restart -- not interchangeable

| | moves the registry (which agents/skills/commands resolve) | moves command text already injected in this turn |
| --- | --- | --- |
| `/reload-plugins` | yes | **no** |
| restart | yes | yes |

So a session can hold a registry at one version and instructions from another, and that is not a bug.

- `Agent type not found` -> `/reload-plugins`, then retry. This is the whole fix.
- Never conclude "the agent files do not register" from inside an unreloaded session. #81 spent ten
  cohorts and four retracting comments on exactly that: a description-length hypothesis with a
  measured character boundary, a false regression report, all retracted, cause was a stale registry.

## Statusline markers -- they print different fields

| state | unicode | ascii | colour | the number shown is |
| --- | --- | --- | --- | --- |
| `behind` | `↥` | `>` | yellow | **latest** published |
| `ahead` | `↑` | `+` | green | **installed** |
| `current` | counted in `N✓` | | green | -- |
| `unknown` | `N?` | | dim | nothing was comparable |

`ahead` is the normal state in a clone of the plugin itself (unreleased work), and normal for any session
in the window after a release before the cache refreshes. It is not a problem.

`version_status` folds a stale comparison into `unknown` rather than inventing vocabulary -- so a
`?` means either half was missing **or** the reading was too old to trust.

## The cached `latest`

- Lives at `cache_dir()/<slug>.json` -- outside the repo. Never re-derive that path; call
  `statusline.cache_path`.
- Source is the newest **published GitHub Release**, via `_latest_release` -- *not* the manifest.
  A tag with no Release does not move it.
- `LATEST_REFRESH_AFTER` is the long clock; the board half refreshes far more often. Two clocks.
- `/oss:release` calls `invalidate_latest_cache` the moment a Release is created, because the
  publish is what falsifies the reading.
- **A reading fresh by its own rule can still be wrong.** The falsifying event can land one minute
  after a poll. Do not diagnose this by shortening the interval.

Force a re-read: delete the cache file. `doctor` never does this -- it reports the skew and leaves
the evidence.
"""

STATE_FILE = """---
title: "The tick state file"
description: "Written every tick, read first every tick. A corrupt file raises rather than resetting; an over-long decision is refused rather than truncated."
keywords: state file, oss-watch, tick state, handoff, oss state
---

Written every tick, read first every tick. The decision and the one reason for it -- reasoning that
only matters to a pull request belongs in that pull request.

**The handoff is not the repo.** This file records what was *believed* when it was written. The
first call of a session is the repo itself: the last commit, the open pull requests, the open issues.

Two refusals worth knowing before editing the file by hand:

- **A corrupt file raises rather than starting fresh.** A silent reset destroys the history the file
  exists for, and the tick that did it looks exactly like a first tick.
- **An over-long decision is refused, not truncated.** A truncation drops the half that mattered and
  leaves something that still reads as a record.
"""

#: Why this ships unconditionally rather than being written only into a tree where the
#: binary was found (#294).
#:
#: Both halves of the alternative fail. A presence check is not expressible in frontmatter
#: and a rule runs no command -- it is a text file a subject is matched against -- so the
#: rule cannot answer the question for itself. And a check made by the installer answers
#: about the **wrong machine at the wrong time**: `/oss:scaffold` runs once, on the
#: maintainer's machine, and writes a file that is committed and then read on every
#: contributor's. Skipping the rule there leaves the reported contributor blocked anyway,
#: and adds a committed file whose presence flaps with whoever last scaffolded.
#:
#: So the third state is handed to the reader as commands to run, rather than computed.
#:
#: The ops list stays FIRST. The reader who has `supertool` is the majority and pays the whole
#: body on every refused call, because the hook injects the file verbatim; the reader who does
#: not needs the diagnosis once. Putting the diagnosis on top charged the common case for the
#: rare one, forever.
TOOLS_SUPERTOOL = """---
title: "Read, Edit, Write, Glob and Grep go through supertool"
description: "supertool has an op for each of these; the refusal names the replacement, and 00-README.md covers the rest."
tool: Read|Edit|Write|Glob|Grep
match: ~.*
mode: block
requires: supertool
---

No read, edit, write, glob or grep bypasses `supertool`. Use the op that replaces
the refused call:

- **Read** -- `supertool 'read:PATH'`
- **Edit** -- `supertool 'edit:@-'` (TOML on stdin) or `supertool 'edit:::OLD:::NEW:::PATH'`
- **Write** -- `supertool 'paste:@-'` (TOML on stdin, `path`/`content`) or
  `supertool 'paste:::PATH:::CONTENT'` -- creates missing dirs, rewrites an
  existing file, so it covers both halves of a Write
- **Glob** -- `supertool 'glob:PATTERN'`
- **Grep** -- `supertool 'grep:PATTERN:PATH'`

If none of those run, triage with `./supertool 'ops'` then `supertool 'ops'` --
see `00-README.md` here for what each answer means and why this rule stays
this wide.
"""

#: The default for `rules(assembler=...)`, and it has to be a sentinel rather than `None`
#: because `None` is a value a caller must be able to ask for: it is "there is no
#: assembler in the tree these rules are going into", which renders the could-not-locate
#: form. `_DERIVE` is the separate statement "read it off `repo_root` for me".
_DERIVE = object()

#: The decision not to ship one yet, recorded where the decision applies (#144, #307).
#:
#: `00-README.md` is the one filename the dependency's index builder skips, in every one of
#: its builders, and `doctor.JIT_ENTRY_SKIP` skips the same name -- so this ships beside the
#: rules, is read by a person opening the layer, and is indexed by nobody. It declares no
#: `tool:` and no `match:`, so `index_rows()` writes no row for it either.
#:
#: Under #144 this recorded a gap: a rule keyed on `Agent` could not fire at all, because the
#: hook built its subject from four keys and an `Agent` payload carried none of them.
#: `claude-jit-context` 0.5.0 closed that -- it reads `subagent_type` as a fifth -- so the gap
#: record became a false statement this plugin was writing into other people's repositories,
#: which is the vendored-document defect class exactly. #307 is that filing.
#:
#: What survives is the reason for recording anything here at all: a decision nobody wrote
#: down reads as an oversight and gets proposed again, with no memory of the measurement.
#: So this is now a record of what was measured and what is still undecided, not of a gap.
TOOLS_AGENT_RULE_DECISION = """---
title: "There is deliberately no rule keyed on the Agent tool -- yet"
description: "A tools rule on Agent can fire as of claude-jit-context 0.5.0, matched against subagent_type. What one should say is undecided, so this layer ships none."
---

**Nothing in this layer is keyed on `Agent`. That is a decision, and the reason for it has
changed** -- so if you have read an older copy of this file, read this one instead.

A rule that fired on agent dispatch would be worth having: it would put the standing clauses
of a brief in front of the dispatcher at the one moment they change behaviour, instead of
being re-typed from memory.

## What the hook does, measured

The PreToolUse hook builds the subject its tool rules match against from five `tool_input`
keys, taken in this fallback order:

| key | carried by |
| --- | --- |
| `command` | `Bash` |
| `skill` | `Skill` |
| `file_path` | `Read`, `Edit`, `Write` |
| `pattern` | `Glob`, `Grep` |
| `subagent_type` | `Agent` |

`subagent_type` is the fifth and it is **the only one of an `Agent` payload's three fields
that is read**. `description` and `prompt` are a deliberate no upstream: they are
author-written prose, so a `forbid`/`require` rule written about commands would trip on a
prompt that merely mentions one, and a prompt is large enough to cost real time in the
matcher. So a `tool: Agent` rule matches against the dispatched agent's name and nothing
else -- it *can* key on one kind of dispatch, and it can see nothing about what was asked.

**This was not always true.** Before `claude-jit-context` 0.5.0 the subject was built from
the first four keys only, an `Agent` payload produced an empty one, and the hook exited
before the layer loop: a `tool: Agent` row indexed cleanly, listed healthy in every
diagnostic, and never once fired. If the version installed where you are reading this
predates that, everything below is still blocked. A subjectless dispatch is no longer
silent either -- the hook now names the rules it could not reach, rather than answering the
`{}` that a genuine no-match also answers.

## Re-measure rather than trusting this file

Point `CLAUDE_PROJECT_DIR` at a tree holding a layer with an `Agent` rule and a `Bash` rule,
and drive the hook twice:

```
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | bash .../pre-tool-hook.sh
printf '%s' '{"tool_name":"Agent","tool_input":{"subagent_type":"x","prompt":"y"}}' | bash .../pre-tool-hook.sh
```

The `Bash` call is the control. If it says nothing either, the harness is blind and the
second answer means nothing. Give the `Agent` rule a `match:` that covers `x` and a second
`Agent` rule whose `match:` does not, or a single answer tells you a rule fired without
telling you what it fired *on*.

## Why no rule is shipped here anyway

Two questions, neither answered by the measurement above, and both wanting their own review
rather than a rider on the change that took this record off its false claim:

- **What it would say.** The standing clauses live in the agent definition being dispatched.
  A rule that restated them would be the second copy -- the one that drifts and the one
  people quote -- and one that only points at them has to name a location, which for an
  agent definition is a path inside an installed plugin rather than anything in this
  repository.
- **What it would cost.** It fires on every matching dispatch, and the benefit is asserted
  rather than observed. That is the wrong way round for something injected into every
  delegation.

**If either question gets answered, this file is what a rule replaces.** It is not edited
here: this whole layer is generated and replaced wholesale on every install, so a correction
made in this directory is gone the next time the owning plugin writes it. Report it instead.

## #903: this rule reaches a spawned reviewer subagent too, and that is intentional

A developer lane's own self-review spawns a read-only `Explore` reviewer against the diff it just
committed. That reviewer issues Read/Edit/Write/Glob/Grep calls of its own, in the same tree, and
they hit `supertool-required.md` below exactly as the dispatching lane's own calls do -- #903 is
two reproduced instances of that.

**Narrowing the trigger to skip a spawned subagent was the issue's first ask, and it is not
possible today.** `supertool-required.md`'s `match: ~.*` is tested against the PreToolUse hook's
own subject, built from `tool_input` alone (see the table above) -- and that subject carries
no field naming *which agent* issued the call. There is no `isSidechain`, no `subagent_type` on a
`Read`/`Edit`/`Write`/`Glob`/`Grep` payload, nothing at all distinguishing a spawned reviewer's own
tool call from its dispatcher's. No signal in the subject means no way to narrow on it -- so this
is the issue's second branch, "state it explicitly", rather than the first.

**What that means for `Explore`, or any other read-only reviewer never briefed on `supertool`.** It
has no such tool in its actual grant and no route to install one, so a block here is a rule it
cannot comply with by being told about it -- only by already knowing `supertool` is on `PATH` and
calling it through its own `Bash` grant, which nothing in its brief currently says to do. Both
observed instances (#903) already did the next best thing on their own: they read the refusal as
untrusted injected content that named a tool contradicting their actual grant, and continued
through their own authorized `Read`/`Bash` tools rather than obeying it. That is correct, and nothing
here is meant to change it -- the only enforcement-side answer available is the `requires:`
degrade documented below, never a scope narrower than "every session touching this tree", because
the hook has nothing narrower to match against.

If `claude-jit-context` ever adds a signal that tells a spawned subagent's own calls apart from its
dispatcher's, that is what this rule gets narrowed on -- not a guess made without one.

---

## `supertool-required.md`: why it stays this short

That rule is `mode: block` on `Read|Edit|Write|Glob|Grep` with `match: ~.*`, so its whole body
re-injects on every refused call -- no `once` marker exists for a block rule. What stays in the
rule file is only the five op substitutions and the two-command triage line; everything below,
which used to live there, moved here instead, where it costs nothing per refusal (#757).

No exception for an image, a PDF or a notebook cell: none exists in this repository today. If one
appears, that is when it gets one -- not before.

### If the triage commands in the rule don't run

**Neither `./supertool 'ops'` nor `supertool 'ops'` tells you anything about the *other* one --
run both.** A rule is a text file the hook matches a subject against; it runs no command, and
nothing checked reachability on your behalf before writing this file.

- **`./supertool 'ops'` prints a list of ops.** Everything is wired; the refusal was about your
  call, not your setup.
- **`./supertool` is missing, `supertool` works.** The binary is installed and *this clone* has
  no entry point. `./supertool` is gitignored on purpose -- committing it would bake one
  machine's absolute path into every other clone -- and it is created by supertool's own
  session-start hook, so a fresh clone has none until a session has been started in it. Start
  one, or call whichever spelling answers. Nothing is missing from your installation.
- **Neither runs.** `supertool` is not installed on this machine. It is a Claude Code plugin and
  a declared dependency of the plugin that wrote this layer, so installing that plugin resolves
  it from the same marketplace.

### The `requires: supertool` frontmatter line, and what it does today

**It is honoured.** `claude-jit-context` 0.6.0 shipped the reader `claude-jit-context#203`
asked for: `jit_missing_requires()` in `common.sh` probes every `requires:` value on `PATH` once
per hook invocation, and `pre-tool-hook.sh` folds the result into `requires_missing` per row --
`can_refuse = would_refuse && !requires_missing`, so a `mode: block` row naming a binary that did
not resolve cannot enforce its own block. It falls through to the advisory branch instead, and
the degrade is said out loud rather than happening silently: the injected `degrade_note` reads
*"[jit] This rule would normally refuse this call, but `<bin>` was not found on PATH, so it has
degraded to advisory instead of blocking. Install `<bin>` to restore enforcement."*

So on a reader's machine running `claude-jit-context` 0.6.0 or later with no `supertool` on
`PATH`, this rule no longer blocks -- it warns, by name, with the remedy in the message. On a
machine with `supertool` on `PATH`, or running an older `claude-jit-context`, nothing changes.
**Measured against the installed cache, not asserted.** Re-measure before trusting this
paragraph -- `#524` and `#570` (this repository) and `claude-jit-context#203` are the history,
and the field's meaning can move again the same way it just did.

### Why `match: ~.*` and `mode: block` are not narrowed

The same issue that asked for a smaller body (#757) also inherited an older question (#524):
whether blocking all five tools outright is too large a hammer even where `supertool` **is**
installed -- proposing `mode: warn` for some of them, `block` reserved for calls that would
genuinely bypass a validator. That was weighed and declined, not overlooked: the absent-binary
failure mode above is the one that turns a guard into an outage, and `requires:` answers exactly
that, without touching what this rule says to a reader who has the dependency. Weakening `block`
to `warn` for a reader who already has `supertool` would trade a working guard for a softer one
to hedge against a case `requires:` already covers -- the shape this project itself argues
against elsewhere: a `remind` on an absolute rule teaches the reader to dismiss it.

**That argument's own precondition has now been met, and the conclusion does not move.** #524
declined narrowing on the grounds that the absent-binary case would be answered "once
`requires:` ships" -- it has (#570), and the degrade described above is what answers it: a
reader without `supertool` is no longer blocked, without this rule's `block` weakening for the
reader who has it. Revisiting `block` again would be re-litigating a question `requires:` was
written to close.
"""


#: #245 step 1: the "Merge gates" section skills/manager/SKILL.md carried in full on every
#: tick, keyed instead on the one tool call it actually governs -- a `command` matching
#: `gh-pr-merge`. `mode: remind` rather than `block`: refusing the merge call outright is
#: not what this asks for, only surfacing the gates at the moment they apply. The full
#: argument -- the `|force` opt-outs and their blast radii, the rerun-vs-moved-base trap,
#: the branch-deletion rules -- stays in `skills/manager/phases/merge.md`, which this rule
#: points at rather than restates.
TOOLS_MERGE_GATE = """---
title: "Before gh-pr-merge: gates, cleanup, and the check that comes after"
description: "Never-failing checks are not green -- count the legs. gh-pr-merge writes nothing without |force. Cleanup and branch deletion are the op's own |cleanup token, not a second call."
tool: Bash
match: ~gh-pr-merge
mode: remind
---

Merge only when: CI fully green **at leg level** (the state counts must sum to the number of
legs; name any leg not `SUCCESS` before merging), the review passed, and the change is a
bugfix / docs / test / chore. Never auto-merge feature scope, a public API or behaviour
rename, an external-contributor PR, or anything irreversible.

- **`gh-pr-merge` writes nothing without `|force`.** One call:
  `supertool 'gh-pr-merge:N:squash|force|cleanup'`, never merge and cleanup as two calls.
- **Cleanup is gated on the op's own verified `MERGED` read-back**, not a second call. On a
  fleet-running loop its worktree half reports `skipped: reason` when more than one tree is
  idle -- correct, not a failure; reap the rest via `git-worktrees`, whose two columns
  (`cannot tell`, `merge unknown`) are never a yes.
- **One `Closes #N` per issue, the keyword repeated.** `Closes #A #B` links both and closes
  only `#A`. Read the whole line; a fragment match cannot audit either failing case.
- **After merge, check the default branch's own run with `gh-branch`** (GREEN / NOT GREEN /
  NO RUN / UNKNOWN) -- a green PR is a statement about its merge-base, not about `main` after
  the squash.
- **Do not route around a denied merge.** Say the call was denied, name it exactly, and let
  the maintainer run or permit it.

Full argument, the `|force` opt-outs and their blast radii, the rerun-vs-moved-base trap, and
the branch-deletion rules: `skills/manager/phases/merge.md`.
"""


#: #245 step 3: the "What comes back, and opening the pull request" section
#: skills/manager/SKILL.md carried in full on every tick, keyed instead on the one tool
#: call it actually governs -- a `command` matching `gh-pr-create`. `mode: remind` for the
#: same reason `TOOLS_MERGE_GATE` is a reminder rather than a block: this surfaces the
#: don't-retype and Closes-#N argument at the moment the call is about to run, it does not
#: refuse the call. The full argument -- the fragment-rename procedure, the three states
#: of `pr_body`, how far the validator gets on each field, and the two ways a body
#: silently references less than it appears to -- stays in
#: `skills/manager/phases/handback.md`, which this rule points at rather than restates.
TOOLS_PR_CREATE_GATE = """---
title: "Before gh-pr-create: don't retype what already arrived right"
description: "title, head and base arrive filled in from the report -- retyping any of them is the one move that makes things worse. Publish gh-pr-create:@FILE, never a hand-built body."
tool: Bash
match: ~gh-pr-create
mode: remind
---

Pushing and opening is one read plus one call, not a document you write:

- **Read the published body before anything else touches it.** A body you have not read
  is your name on text you did not see -- argue it or send it back, never rewrite it
  quietly, because the person who did the work writes the record.
- **Hand the payload path to `gh-pr-create:@FILE`.** Not `gh pr create`, not a body of
  your own. The op refuses a body with no working `Closes #N` -- nothing is created --
  and the error names the remedy: fix the reference, or set `no_close = true` at the
  payload's top level for a `Part of #N` pull request that closes nothing.
- **Do not retype `title`, `head` or `base`.** They arrive filled in and measured right;
  a hand-written value is the only one nothing downstream verifies at all.
- **Spend one call on the check, not the claim:**
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report_schema.py" <the report path>` -- the
  report path, never the payload path. Three answers: `ok`, a finding, and
  `UNVALIDATABLE` at exit 2, which is a statement about the validator and not the report.
- **Release what a lane did not finish.** A lane with no commit, or a pull request closed
  without merging, both leave an assignment behind: `gh issue edit <N> --remove-assignee
  @me`. *Could not read the pull request state* must never render as released.

Full argument -- the fragment-rename procedure, the three states of `pr_body`, how far
the validator actually gets on each field, and the two ways a body silently references
less than it appears to: `skills/manager/phases/handback.md`.
"""


def rules(
    repo_root=None, fragments_dir=None, untagged=None, gate=None, assembler=_DERIVE
):
    """dimension -> {filename: body}, rendered for the tree it is going into.

    `repo_root` is what makes the changelog rule correct in more than one repository: the
    assembler's path is read off that tree rather than baked in. Called with no root, the
    changelog rule renders its could-not-locate form -- which is the honest answer to
    "what do the rules say" asked without a repository to say it about.

    `assembler` overrides that read, for the one caller whose question is about a tree
    that does not exist yet: `scaffold.plan_rules()` previews what `--apply` would put
    here, and `--apply` installs the layer AFTER writing the vendored assembler. A
    preview that read the tree as it stands would answer for a repository that is one
    command out of date -- and would answer confidently, which is the defect it exists to
    fix. The override is passed in rather than guessed at here because which files this
    run is about to write is knowledge only the caller has, exactly like `gate`.

    `untagged` is the same kind of fact as `fragments_dir`: it belongs to one repository,
    the caller has read it out of that repository's `.oss.json`, and this module has no
    way to derive it. `None` here means the same as `None` there.

    `gate` says why the assembler is not there when it is not there (#117). Called with
    no gate, the rule says that this was not established -- also honest, and the reason
    the parameter defaults to `None` rather than to "no gate found".
    """
    if assembler is _DERIVE:
        assembler = assembler_path(repo_root) if repo_root is not None else None
    return {
        "paths": {
            "changelog-fragments.md": changelog_fragments(
                assembler,
                fragments_dir or DEFAULT_FRAGMENTS_DIR,
                untagged,
                gate,
            ),
            "oss-config.md": OSS_CONFIG,
        },
        "vocabulary": {
            "oss-state.md": STATE_FILE,
            "plugin-currency.md": PLUGIN_CURRENCY,
        },
        "tools": {
            "supertool-required.md": TOOLS_SUPERTOOL,
            "merge-gate.md": TOOLS_MERGE_GATE,
            "pr-create-gate.md": TOOLS_PR_CREATE_GATE,
            # Not a rule: no `tool:` and no `match:`, so `index_rows()` writes no row and
            # the dependency's builder skips the name outright. It ships so that the
            # recorded decision reaches every managed repo, not just this one -- the layer
            # is replaced wholesale on install, so anything not listed here reaches nobody.
            "00-README.md": TOOLS_AGENT_RULE_DECISION,
        },
    }


#: The structural shape -- which rules exist, in which dimension, with what frontmatter.
#: **Not what any repository receives**: the changelog rule here is the form that names no
#: command, because nothing has been looked at. `install()` renders per tree.
RULES = rules()


def _frontmatter(body):
    return body.split("\n---\n", 1)[0]


def _field(body, key):
    for line in _frontmatter(body).splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return None


def index_rows(dimension, rules):
    """The shape a rebuild produces, per dimension.

    Paths index one row of `match<TAB>filename`; vocabulary indexes one row of
    `keyword<TAB>filename` per keyword; tools indexes one row of
    `tool<TAB>match<TAB>filename<TAB>mode<TAB>require<TAB>forbid<TAB>requires` -- seven
    columns, measured against claude-jit-context's `rebuild-tsv.sh` rather than reasoned
    about (#80 found the same list wrong when it was only reasoned about). The seventh
    column was added by #665: `requires` was declared in `TOOLS_SUPERTOOL`'s frontmatter
    by #570 and read by `claude-jit-context` 0.6.0's `jit_missing_requires()`, but this
    function never emitted it, so the shipped index disagreed with the rule body it
    indexes and the field it names was never enforced anywhere it was scaffolded. The
    six-column shape recorded a considered decision in `CHANGELOG.md` at #106 (v0.3.0) --
    before `requires:` existed at all -- and `rebuild-tsv.sh` itself has since grown the
    same seventh column, so widening the row here does not overturn that decision so much
    as catch up to what it was already describing when it was written.
    """
    rows = []
    for name in sorted(rules):
        body = rules[name]
        if dimension == "vocabulary":
            keywords = _field(body, "keywords") or ""
            for keyword in keywords.split(","):
                keyword = keyword.strip()
                if keyword:
                    rows.append("{}\t{}".format(keyword, name))
        elif dimension == "tools":
            tool = _field(body, "tool")
            match = _field(body, "match")
            if tool and match:
                mode = _field(body, "mode") or "remind"
                require = _field(body, "require") or ""
                forbid = _field(body, "forbid") or ""
                requires = _field(body, "requires") or ""
                rows.append(
                    "\t".join([tool, match, name, mode, require, forbid, requires])
                )
        else:
            match = _field(body, "match")
            if match:
                rows.append("{}\t{}".format(match, name))
    return rows


def install(repo_root, fragments_dir=None, untagged=None, gate=None):
    """Replace this plugin's rule layer. Returns the paths written.

    Every file the layer currently holds in a shape `install()` could have written --
    a `.md` rule or the index -- is removed first: a rule we stopped shipping would
    otherwise survive an update and keep firing with nobody maintaining it. A file in
    neither shape is not ours to begin with, however it got there, and is left alone
    (#1042) -- see `owned_shape()`.

    The rules are rendered against `repo_root`, not copied from a constant, so the
    changelog rule names the assembler where **this** repository keeps it. `fragments_dir`
    is that repository's `changelog_dir` and `untagged` its `changelog_untagged`; the
    caller has both and this module has no way to derive either.

    `gate` is the same shape of fact one level further out: whether a changelog gate
    already runs here under another name, which is knowledge only the caller has and is
    what decides whether a missing assembler is a gap or a decision (#117). The whole
    layer ships either way -- omitting the rule would leave the reader with no statement
    at all, where the defect was a statement about a different repository.
    """
    root = Path(repo_root)
    if root.exists() and not root.is_dir():
        raise RulesError("{}: not a directory".format(root))

    written = []
    # Rendered once, against this tree, before anything is removed -- which is also what
    # makes an unrenderable gate state a refusal rather than a half-replaced layer.
    rendered = rules(root, fragments_dir, untagged, gate)
    for dimension, layer_rules in rendered.items():
        layer = root / ".claude" / "jit-context" / dimension / LAYER
        if layer.exists():
            for child in layer.iterdir():
                if child.is_file() and owned_shape(child.name):
                    child.unlink()
        layer.mkdir(parents=True, exist_ok=True)

        for name in sorted(layer_rules):
            target = layer / name
            target.write_text(layer_rules[name], encoding="utf-8")
            written.append(target)

        index = layer / INDEX
        index.write_text(
            "\n".join(index_rows(dimension, layer_rules)) + "\n", encoding="utf-8"
        )
        written.append(index)

    return written
