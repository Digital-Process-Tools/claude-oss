"""The `01-oss` rule layer: knowledge about this plugin's own artifacts, injected on touch.

Layers are the ownership boundary. `00-manual/` belongs to whoever maintains the repo.
`01-oss/` belongs to this plugin, and that is what makes updating safe: the layer is
replaced wholesale on every install, because nothing a human wrote lives in it, and the
human's layer is never read or written.

Why copies rather than a link into the plugin checkout: a linked layer is refused by the
rules engine on purpose. Git tracks symlinks, a clone recreates them, and a linked layer
carries its own index -- so one committed link would be enough to point a stranger's
rules at anything on the machine. Copies into an owned layer are the supported shape.

Rows are written in the same format a rebuild would produce (`pattern<TAB>filename`), so
regenerating the index is a no-op rather than a diff.

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
match: __FRAGMENTS__/
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


def changelog_fragments(assembler, fragments_dir):
    """The fragment rule, rendered for one tree.

    `assembler` is a repo-relative path or `None`; `fragments_dir` is that repository's
    fragment directory, which is not `changelog.d` everywhere and is what the rule has to
    match on or it never fires at all.
    """
    if assembler:
        # Both `--dir` and `--changelog` on every invocation. Given neither, the assembler
        # derives its own root by walking up for a `.git`, which under a plugin finds the
        # plugin's repository rather than the one being checked.
        check = (
            "Check before pushing:\n"
            "\n"
            "```bash\n"
            "python3 {} --check --check-links --dir '{}' --changelog CHANGELOG.md\n"
            "```\n"
        ).format(assembler, fragments_dir)
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
match: \\.oss\\.json
---

Per-repo settings for the maintainer loop: `repo`, `default_branch`, `clone`, `worktree_root`,
`test_command`, `version_sites`, `labels`, `ci.required_checks`, `state_file`, `release`.

**Re-derive anything load-bearing before acting on it.** This file records what a probe observed on
the day it ran. Two values rot first:

- **`ci.required_checks`** is the merge gate's arithmetic. Read it off the pull request every time.
  Any leg that is not a success gets named before merging -- cancelled, skipped, timed out and
  neutral are none of them passes and none of them pendings.
- **`labels`** are spellings, and they differ between repos: one spells it `priority-high`, another
  `priority:high`. Read them off the repo before writing one, and never invent a label that is not
  already there.

**`null` is an answer, not a gap.** `test_command` and `changelog_dir` may be null and mean "the
probe could not tell". Everything else null is a hole -- the probe found nothing and said nothing.

**No key here holds a credential.** The file is committed; tokens live in the forge CLI's own auth.
"""

STATE_FILE = """---
title: "The tick state file"
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

def rules(repo_root=None, fragments_dir=None):
    """dimension -> {filename: body}, rendered for the tree it is going into.

    `repo_root` is what makes the changelog rule correct in more than one repository: the
    assembler's path is read off that tree rather than baked in. Called with no root, the
    changelog rule renders its could-not-locate form -- which is the honest answer to
    "what do the rules say" asked without a repository to say it about.
    """
    return {
        "paths": {
            "changelog-fragments.md": changelog_fragments(
                assembler_path(repo_root) if repo_root is not None else None,
                fragments_dir or DEFAULT_FRAGMENTS_DIR,
            ),
            "oss-config.md": OSS_CONFIG,
        },
        "vocabulary": {
            "oss-state.md": STATE_FILE,
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
    """`pattern<TAB>filename`, the shape a rebuild produces.

    Paths index one row per `match`; vocabulary indexes one row per keyword.
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
        else:
            match = _field(body, "match")
            if match:
                rows.append("{}\t{}".format(match, name))
    return rows


def install(repo_root, fragments_dir=None):
    """Replace this plugin's rule layer. Returns the paths written.

    The layer is removed first: a rule we stopped shipping would otherwise survive an
    update and keep firing with nobody maintaining it.

    The rules are rendered against `repo_root`, not copied from a constant, so the
    changelog rule names the assembler where **this** repository keeps it. `fragments_dir`
    is that repository's `changelog_dir`; the caller has it and this module does not.
    """
    root = Path(repo_root)
    if root.exists() and not root.is_dir():
        raise RulesError("{}: not a directory".format(root))

    written = []
    # Rendered once, against this tree, before anything is removed.
    rendered = rules(root, fragments_dir)
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
