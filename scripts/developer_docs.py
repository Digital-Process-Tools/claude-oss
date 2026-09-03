"""The developer brief, wherever it currently lives.

`agents/developer.md` used to be the whole brief. It is now the spine, and the
three late phases -- self-review, review returns, the report -- live in
`agents/developer/*.md`, read when a lane reaches that phase
(`scripts/developer_phases.py` carries the index and the budgets). Nothing
about *what the brief says* changed in that move (#939) -- but every check
written as "does `agents/developer.md` contain X" silently became a check over
part of its subject, which is the coverage-narrowed-without-saying-so shape
#547 records for the auditor's checklist and `scripts/manager_docs.py` records
for the manager loop's own split.

So the question those checks were always asking -- **does the developer brief
say X** -- gets one answer here, derived from disk rather than listed, so a
phase file added later is covered the moment it exists rather than when
somebody remembers a list.

`documents()` refuses to return an empty set: a helper that answered `[]` would
turn every content check built on it into a vacuous pass, which is the same
defect one layer further out again.
"""

from __future__ import annotations

from pathlib import Path

SPINE_REL = ("agents", "developer.md")
PHASES_REL = ("agents", "developer")

#: Two newlines, so a check anchored on a line start still anchors at a file
#: boundary -- the same joiner `manager_docs` uses, for the same reason.
JOINER = chr(10) * 2


def repo_root():
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError("developer_docs: no .git found walking up from {0}".format(here))


def documents(root=None):
    """``(paths, unreadable)``: every file the developer brief is spread across,
    spine first, plus one message per reason the phases directory could not be
    listed.

    Raises rather than returning an empty list for a missing spine -- see the
    module docstring. The phases half uses `iterdir()` rather than `glob`,
    because `Path.glob` swallows `PermissionError` while it walks and yields
    nothing for a subtree it could not enter (#571): a denied
    `agents/developer/` would otherwise narrow this to `[spine]` with no raise
    and no signal.
    """
    root = repo_root() if root is None else Path(root)
    spine = root.joinpath(*SPINE_REL)
    if not spine.is_file():
        raise RuntimeError("developer_docs: no spine at {0}".format(spine))
    phases_dir = root.joinpath(*PHASES_REL)
    unreadable = []
    try:
        entries = list(phases_dir.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        entries = []
    except OSError as exc:
        entries = []
        unreadable.append(str(exc))
    phases = sorted(p for p in entries if p.suffix.lower() == ".md")
    return [spine] + phases, unreadable


def text(root=None, sep=JOINER):
    """Every document's text, concatenated in `documents()` order.

    Raises rather than silently concatenating a narrowed set -- discarding
    `unreadable` here would reopen the defect `documents()` closes, one call
    further down.
    """
    paths, unreadable = documents(root)
    if unreadable:
        raise RuntimeError(
            "developer_docs: phases directory could not be listed, so its text "
            "cannot be included: {0}".format(unreadable)
        )
    return sep.join(p.read_text(encoding="utf-8") for p in paths)


class DeveloperBrief:
    """A stand-in for the old `agents/developer.md` Path in a content check.

    `.read_text()` answers for the brief as a whole. `__fspath__` and `__str__`
    still resolve to the spine, because a failure message naming a file a
    reader can open is more useful than one naming a set.
    """

    def __init__(self, root=None):
        self._root = root

    @property
    def paths(self):
        paths, unreadable = documents(self._root)
        if unreadable:
            raise RuntimeError(
                "developer_docs: phases directory could not be listed: "
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
        return self.spine.relative_to(other)

    def is_file(self):
        """Every document is on disk -- one present file out of four is not a yes."""
        return all(p.is_file() for p in self.paths)

    def exists(self):
        return self.is_file()

    def __fspath__(self):
        return str(self.spine)

    def __str__(self):
        return str(self.spine)

    def __repr__(self):
        return "DeveloperBrief({0} document(s), spine {1})".format(
            len(self.paths), self.spine
        )
