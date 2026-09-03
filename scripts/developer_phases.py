"""Where the developer brief's late phases live, and what each costs (#939).

`agents/developer.md` is an agent definition: it enters a lane's context as
the system prompt and is re-sent on every turn the lane runs -- a median 55
turns, observed max 329. Measured on one live tick, a developer lane's first-
turn floor was 57.8-58.3k tokens, nearly double the sub-manager's 31.6k, and
`agents/developer.md` at 89,714 B was the difference; across three lanes the
floor re-sent was 84-96% of everything each lane read. #491 budgeted the file
and could only stop growth from being invisible; the byte count is not the
cost, bytes x turns x lanes is.

So the brief is split the way `skills/manager/SKILL.md` was (#568):

- the **spine**, `agents/developer.md`: what governs a lane from its first
  call -- where to work, the tool route, how to work, the third state, what to
  do with an adjacent finding -- plus one directive block per late phase;
- the **phases**, `agents/developer/*.md`: the argument behind each late
  phase's rules, read at the moment the lane reaches it. Self-review is
  reached after the commit, review returns after the spawns reply, and the
  report last of all -- so each is held in context for the turns after that
  point rather than for every turn from the first.

**The split is not a licence to skim.** An unread phase file is a rule that
did not run, and that renders exactly like a rule with nothing to say. The
spine asks the lane to name an unread or unreadable phase file under the
report's `compliance` survey. Nothing in this module can observe that; what it
can observe is the half that is on disk, in the same three questions
`scripts/skill_phases.py` asks of the manager's phase files:

- **size against a budget** -- `ok` / `over` / `missing`;
- **referenced** -- does the spine name this path? `None` when the spine
  itself could not be read, never rendered as `True`;
- **undeclared** -- a phase file on disk this module does not budget, the
  mirror of `missing`.

The spine's own budget stays in `scripts/agent_budgets.py`, where every
`agents/*.md` file is held -- it is still an agent definition, and declaring
it twice would be two numbers to keep in sync for one file.

Budgets are the measured size plus ~10% headroom, on #491's terms: replace,
don't append, or raise the number here in the same diff with a sentence
saying what was weighed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_budgets import repo_root  # noqa: E402

# scripts/developer_docs.py -- the path is spelled here, not only imported.
# tests/test_unwired_scripts_253.py counts a full tracked path or a bare
# `name.py`, and an `import name` matches neither, so a module a dozen tests
# import reads to that guard exactly like a file nothing uses. That is the
# guard's own gap rather than this module's, and it is filed as one; naming
# the path here is what keeps this file from being reported dead meanwhile.
from developer_docs import documents  # noqa: E402

#: The always-loaded half; budgeted in `agent_budgets.BUDGETS`.
SPINE = "agents/developer.md"

#: repo-relative path (POSIX) -> (bytes measured when the budget was set,
#: budget bytes incl. ~10% headroom, what the file governs).
DOCUMENTS: dict[str, tuple[int, int, str]] = {
    "agents/developer/review.md": (12806, 14100, "self-review: spawning the two reviewers, the tree snapshot receipt, dispositions"),
    "agents/developer/review-return.md": (15440, 17000, "review returns: classifying a spawn's final message, returned-nothing, the re-spawn, a spawn that fails"),
    "agents/developer/report.md": (20665, 22700, "the note, the JSON report and its validator, the pull request payload"),
}


def _spine_text(root):
    """The spine's text, or ``None`` when it could not be read -- `None` rather
    than `""` so "the spine names nothing" and "nobody could ask" stay apart.
    """
    try:
        return (root / SPINE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def check():
    """One row per declared document, plus one per undeclared or unreadable.

    ``state``: ``ok`` | ``over`` | ``missing`` | ``undeclared`` | ``unreadable``.
    ``referenced``: ``True`` | ``False`` | ``None``.
    """
    root = repo_root()
    spine = _spine_text(root)
    rows = []
    for rel, (baseline, budget, governs) in DOCUMENTS.items():
        path = root.joinpath(*rel.split("/"))
        referenced = None if spine is None else rel in spine
        try:
            size = len(path.read_bytes())
        except FileNotFoundError:
            rows.append(
                {
                    "path": rel,
                    "state": "missing",
                    "size": None,
                    "budget": budget,
                    "baseline": baseline,
                    "governs": governs,
                    "referenced": referenced,
                }
            )
            continue
        rows.append(
            {
                "path": rel,
                "state": "over" if size > budget else "ok",
                "size": size,
                "budget": budget,
                "baseline": baseline,
                "governs": governs,
                "referenced": referenced,
            }
        )
    rows.extend(_undeclared_rows(root, spine))
    return rows


def _undeclared_rows(root, spine):
    """A row per phase file on disk that `DOCUMENTS` does not declare, and one
    per reason the phases directory could not be listed -- never folded into
    "no undeclared files found", which is what an empty listing looks like.
    """
    try:
        on_disk, unreadable = documents(root)
        on_disk = on_disk[1:]
    except RuntimeError:
        # No spine on disk: `agent_budgets.check()` already reports that as
        # its own `missing` row, and saying it twice in two vocabularies
        # helps nobody.
        return []
    except OSError as exc:
        return [_unreadable_row(str(exc))]
    rows = [_unreadable_row(message) for message in unreadable]
    for path in on_disk:
        rel = path.relative_to(root).as_posix()
        if rel in DOCUMENTS:
            continue
        rows.append(
            {
                "path": rel,
                "state": "undeclared",
                "size": len(path.read_bytes()),
                "budget": None,
                "baseline": None,
                "governs": None,
                "referenced": None if spine is None else rel in spine,
            }
        )
    return rows


def _unreadable_row(detail):
    return {
        "path": "agents/developer",
        "state": "unreadable",
        "size": None,
        "budget": None,
        "baseline": None,
        "governs": None,
        "referenced": None,
        "detail": detail,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(check(), indent=2))
