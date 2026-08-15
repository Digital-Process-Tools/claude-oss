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
paths and vocabulary, the six-column shape for tools (see `index_rows()`) -- so regenerating
the index is a no-op rather than a diff.

Python 3.9 compatible.
"""

import shutil
from pathlib import Path

LAYER = "01-oss"
INDEX = "00-index.tsv"


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

**Name:** `<issue>.<section>.md`, where the section is a Keep a Changelog heading, lowercased:
`added`, `changed`, `deprecated`, `removed`, `fixed`, `security`.

**Body:** a single top-level `-` list. No headings, no raw HTML, no unclosed fences. Name the issue
in the text as well as the filename -- the filename is metadata, and metadata does not survive being
read out of context.

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


def changelog_fragments(assembler, fragments_dir, untagged=None):
    """The fragment rule, rendered for one tree.

    `assembler` is a repo-relative path or `None`; `fragments_dir` is that repository's
    fragment directory, which is not `changelog.d` everywhere and is what the rule has to
    match on or it never fires at all. `untagged` is that repository's
    `changelog_untagged`, in the three states `_untagged_clause` keeps apart.
    """
    if assembler:
        # Both `--dir` and `--changelog` on every invocation. Given neither, the assembler
        # derives its own root by walking up for a `.git`, which under a plugin finds the
        # plugin's repository rather than the one being checked.
        flag, declaration = _untagged_clause(untagged)
        check = (
            "Check before pushing:\n"
            "\n"
            "```bash\n"
            "python3 {} --check --check-links{} --dir '{}' --changelog CHANGELOG.md\n"
            "```\n"
            "\n"
            "`--check-links` refuses when a `## [x.y.z]` section has no link reference "
            "definition. If the\n"
            "version it names was never tagged, the missing link is the correct state: there "
            "is no release\n"
            "page to point at, and a `releases/tag/vX.Y.Z` URL written for one is a 404 that "
            "renders as a\n"
            "working link.\n"
            "\n"
            "{}"
        ).format(assembler, flag, fragments_dir, declaration)
    else:
        # Named as a third state rather than filled with a guess. No path appears here on
        # purpose: a plausible one is indistinguishable, to whoever runs it, from a path
        # that was checked.
        check = (
            "**The fragment checker could not be located in this repository**, so this rule\n"
            "names no command. `/oss:scaffold` vendors it; run that and this rule is\n"
            "rewritten with the invocation. A path guessed here would fail the first time\n"
            "anybody ran it, and read as this repository being wrong.\n"
        )

    return CHANGELOG_FRAGMENTS.replace("__FRAGMENTS__", fragments_dir).replace(
        "__CHECK__", check
    )


OSS_CONFIG = """---
title: ".oss.json is config, not truth"
description: "Per-repo settings for the maintainer loop. Re-derive labels before acting; the CI leg count is not in here; null is an answer, not a gap."
match: \\.oss\\.json
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

**No key here holds a credential.** The file is committed; tokens live in the forge CLI's own auth.
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

TOOLS_SUPERTOOL = """---
title: "Read, Edit, Write, Glob and Grep go through supertool"
description: "supertool has an op for every one of these; the call is refused and the reader is told which op replaces it."
tool: Read|Edit|Write|Glob|Grep
match: ~.*
mode: block
---

`supertool` is a declared dependency of this plugin and installs alongside it, so this rule ships
unconditionally rather than behind a presence check frontmatter has no way to express -- a tree
that carries this layer already carries `supertool`.

There is no read, edit, write, glob or grep that cannot go through it. Use the op that replaces
the call just refused:

- **Read** -- `supertool 'read:PATH'`
- **Edit** -- `supertool 'edit:@-'` (a TOML payload on stdin) or `supertool 'edit:::OLD:::NEW:::PATH'`
- **Write** -- `supertool 'write:PATH'`
- **Glob** -- `supertool 'glob:PATTERN'`
- **Grep** -- `supertool 'grep:PATTERN:PATH'`

No exception for an image, a PDF or a notebook cell: none exists in this repository today. If one
appears, that is when it gets one -- not before.
"""

def rules(repo_root=None, fragments_dir=None, untagged=None):
    """dimension -> {filename: body}, rendered for the tree it is going into.

    `repo_root` is what makes the changelog rule correct in more than one repository: the
    assembler's path is read off that tree rather than baked in. Called with no root, the
    changelog rule renders its could-not-locate form -- which is the honest answer to
    "what do the rules say" asked without a repository to say it about.

    `untagged` is the same kind of fact as `fragments_dir`: it belongs to one repository,
    the caller has read it out of that repository's `.oss.json`, and this module has no
    way to derive it. `None` here means the same as `None` there.
    """
    return {
        "paths": {
            "changelog-fragments.md": changelog_fragments(
                assembler_path(repo_root) if repo_root is not None else None,
                fragments_dir or DEFAULT_FRAGMENTS_DIR,
                untagged,
            ),
            "oss-config.md": OSS_CONFIG,
        },
        "vocabulary": {
            "oss-state.md": STATE_FILE,
        },
        "tools": {
            "supertool-required.md": TOOLS_SUPERTOOL,
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
    `tool<TAB>match<TAB>filename<TAB>mode<TAB>require<TAB>forbid` -- six columns, measured
    against claude-jit-context's `rebuild-tsv.sh` rather than reasoned about (#80 found the
    same list wrong when it was only reasoned about).
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
                rows.append("\t".join([tool, match, name, mode, require, forbid]))
        else:
            match = _field(body, "match")
            if match:
                rows.append("{}\t{}".format(match, name))
    return rows


def install(repo_root, fragments_dir=None, untagged=None):
    """Replace this plugin's rule layer. Returns the paths written.

    The layer is removed first: a rule we stopped shipping would otherwise survive an
    update and keep firing with nobody maintaining it.

    The rules are rendered against `repo_root`, not copied from a constant, so the
    changelog rule names the assembler where **this** repository keeps it. `fragments_dir`
    is that repository's `changelog_dir` and `untagged` its `changelog_untagged`; the
    caller has both and this module has no way to derive either.
    """
    root = Path(repo_root)
    if root.exists() and not root.is_dir():
        raise RulesError("{}: not a directory".format(root))

    written = []
    # Rendered once, against this tree, before anything is removed.
    rendered = rules(root, fragments_dir, untagged)
    for dimension, layer_rules in rendered.items():
        layer = root / ".claude" / "jit-context" / dimension / LAYER
        if layer.exists():
            shutil.rmtree(layer)
        layer.mkdir(parents=True)

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
