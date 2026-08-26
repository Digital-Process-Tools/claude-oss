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
    """Every file the manager loop's prose is spread across, spine first.

    Raises rather than returning an empty list -- see the module docstring.
    """
    root = repo_root() if root is None else Path(root)
    spine = root.joinpath(*SPINE_REL)
    if not spine.is_file():
        raise RuntimeError("manager_docs: no spine at {0}".format(spine))
    phases = sorted(root.joinpath(*PHASES_REL).glob("*.md"))
    return [spine] + phases


def text(root=None, sep=JOINER):
    """Every document's text, concatenated in `documents()` order."""
    return sep.join(p.read_text(encoding="utf-8") for p in documents(root))


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
        return documents(self._root)

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
