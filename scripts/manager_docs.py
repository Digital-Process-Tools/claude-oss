"""The manager loop's prose, wherever it currently lives.

`skills/manager/SKILL.md` used to be the whole loop. It is now the spine, and
each phase's argument lives in `skills/manager/phases/*.md`, read when the loop
reaches that phase (`scripts/skill_phases.py` carries the index and the
budgets). Nothing about *what the loop says* changed in that move -- but every
check written as "does `SKILL.md` contain X" silently became a check over part
of its subject, which is the coverage-narrowed-without-saying-so shape #547
records one level up in `checklist_skew.py`.

So the question those checks were always asking -- **does the manager loop say
X** -- gets one answer here, derived from disk rather than listed, so a phase
file added later is covered the moment it exists rather than when somebody
remembers a list.

`documents()` refuses to return an empty set: a helper that answered `[]` would
turn every content check built on it into a vacuous pass, which is the same
defect one layer further out again.
"""

from __future__ import annotations

from pathlib import Path

SPINE_REL = ("skills", "manager", "SKILL.md")
PHASES_REL = ("skills", "manager", "phases")

#: Two newlines, so a check anchored on a line start still anchors at a file
#: boundary -- concatenating with nothing would join the last line of one file
#: to the first of the next and invent a line that appears in neither.
JOINER = chr(10) * 2


def repo_root():
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError("manager_docs: no .git found walking up from {0}".format(here))


def documents(root=None):
    """``(paths, unreadable)``: every file the manager loop's prose is spread
    across, spine first, plus one message per reason the phases directory
    could not be listed.

    Raises rather than returning an empty list for a missing spine -- see the
    module docstring. The phases half is different: `Path.glob` swallows
    `PermissionError` while it walks and silently yields nothing for a
    subtree it could not enter (CLAUDE.md's own `Path.rglob`/`Path.is_dir`
    bullet, #124/#383) -- so a denied `skills/manager/phases/` used to narrow
    `documents()` to `[spine]` with no raise and no signal, which is the
    coverage-narrowed-without-saying-so shape #547 records one file over
    (#571). `iterdir()` is used instead because it is the operation that can
    actually report a deny -- `doctor._workflow_scan`/`_rglob_md` solve the
    identical swallow the same way, one directory level down, with
    `os.walk(onerror=...)`; this directory has no subdirectories of its own,
    so a single `iterdir()` call is the whole of the walk needed here.
    """
    root = repo_root() if root is None else Path(root)
    spine = root.joinpath(*SPINE_REL)
    if not spine.is_file():
        raise RuntimeError("manager_docs: no spine at {0}".format(spine))
    phases_dir = root.joinpath(*PHASES_REL)
    unreadable = []
    try:
        entries = list(phases_dir.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        # Not there, or not a directory -- "nothing found", not "unreadable":
        # a phases directory that plainly does not exist is not the same fact
        # as one this process could not read.
        entries = []
    except OSError as exc:
        entries = []
        unreadable.append(str(exc))
    phases = sorted(p for p in entries if p.suffix.lower() == ".md")
    return [spine] + phases, unreadable


def text(root=None, sep=JOINER):
    """Every document's text, concatenated in `documents()` order.

    Raises rather than silently concatenating a narrowed set: discarding
    `unreadable` here would reopen the exact defect `documents()` closes
    (#571) one call further down -- every `ManagerLoop`-based content check
    reads through this function, and a denied phases directory would
    otherwise still narrow their coverage to the spine alone with no signal.
    A caller that wants the partial set anyway calls `documents()` directly
    and handles `unreadable` itself.
    """
    paths, unreadable = documents(root)
    if unreadable:
        raise RuntimeError(
            "manager_docs: phases directory could not be listed, so its text "
            "cannot be included: {0}".format(unreadable)
        )
    return sep.join(p.read_text(encoding="utf-8") for p in paths)


class ManagerLoop:
    """A stand-in for the old `SKILL.md` Path in a content check.

    `.read_text()` answers for the loop as a whole. `__fspath__` and `__str__`
    still resolve to the spine, because a failure message naming a file a
    reader can open is more useful than one naming a set -- and every message
    that used this object was written to name a file.
    """

    def __init__(self, root=None):
        self._root = root

    @property
    def paths(self):
        """Raises when the phases directory could not be listed (#571) --
        `is_file()` below relies on this being the *whole* set, not a
        narrowed one: `all(p.is_file() for p in [spine])` would answer `True`
        for a loop six files short of complete, which is exactly the
        one-present-file-out-of-seven-is-not-a-yes shape its own docstring
        warns against.
        """
        paths, unreadable = documents(self._root)
        if unreadable:
            raise RuntimeError(
                "manager_docs: phases directory could not be listed: "
                "{0}".format(unreadable)
            )
        return paths

    @property
    def spine(self):
        return self.paths[0]

    @property
    def name(self):
        return self.spine.name

    def read_text(self, encoding="utf-8"):
        return text(self._root)

    def relative_to(self, other):
        """The spine's path, relative to `other`.

        Used only to build failure messages. A reader handed a set cannot open
        it; handed `skills/manager/SKILL.md` they can, and the spine's index
        names the phase file the text actually lives in.
        """
        return self.spine.relative_to(other)

    def is_file(self):
        """Every document is on disk.

        A caller asking this of the loop is asking whether its prose exists to
        be checked at all, and one present file out of seven is not a yes.
        """
        return all(p.is_file() for p in self.paths)

    def exists(self):
        return self.is_file()

    def __fspath__(self):
        return str(self.spine)

    def __str__(self):
        return str(self.spine)

    def __repr__(self):
        return "ManagerLoop({0} document(s), spine {1})".format(
            len(self.paths), self.spine
        )
