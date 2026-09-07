"""Budget for the loop's first multi-parent fragment (#1071).

`agents/audit/shared.md` is read by two independent agent definitions --
`agents/auditor.md` and `agents/release-auditor.md` -- neither of which is a
spine over the other the way `skills/manager/SKILL.md` is over
`skills/manager/phases/*.md`, or `agents/developer.md` is over
`agents/developer/*.md`. Every extraction before this one had exactly one
parent, so neither `agent_budgets.BUDGETS` (keyed to a real frontmatter-
bearing agent definition, and checked 1:1 against `agents/*.md` on disk by
`tests/test_agent_definition_budget_491.py::test_every_agents_markdown_file_
is_budgeted`) nor `developer_phases.DOCUMENTS` (one spine, `agents/
developer.md`) is the right registry: this fragment lives at `agents/
audit/shared.md`, one directory down, for the same reason `agents/
developer/*.md` does -- so a directory-level (non-recursive) glob over
`agents/*.md` never sees it and never expects it to declare a `tools:`
grant it does not have.

Budget = the size measured when the budget was set, plus ~10% headroom, on
the same replace-don't-append terms as every other budget in this repo.
"""

from __future__ import annotations

from pathlib import Path

from agent_budgets import repo_root

#: repo-relative path (POSIX) of the fragment itself.
FRAGMENT = "agents/audit/shared.md"

#: The two agent definitions that read it. Neither owns it.
PARENTS = ("agents/auditor.md", "agents/release-auditor.md")

#: (bytes measured when the budget was set, budget bytes incl. ~10% headroom).
#: Re-baselined for #1210: the fragment gained one sentence pointing at the
#: two parents' own restored copies of "test behaviour is reasoned, not run"
#: (see CLAUDE.md's #1210 note), 2576 B became 2899 B -- 1 B under the old
#: 2900 B ceiling, so the ceiling moved with it rather than being left with
#: no headroom at all.
BASELINE = 2899
BUDGET = 3190


def check() -> dict:
    """One result for the fragment: state, size, whether each parent names it.

    ``state``: ``ok`` | ``over`` | ``missing``.
    ``referenced``: ``{parent: True | False | None}`` -- ``None`` when that
    parent's own text could not be read, kept apart from "read fine and does
    not mention it".
    """
    root = repo_root()
    path = root / FRAGMENT
    referenced = {}
    for parent in PARENTS:
        try:
            text = (root / parent).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            referenced[parent] = None
            continue
        referenced[parent] = FRAGMENT in text or Path(FRAGMENT).name in text

    try:
        size = len(path.read_bytes())
    except FileNotFoundError:
        return {
            "path": FRAGMENT,
            "state": "missing",
            "size": None,
            "budget": BUDGET,
            "baseline": BASELINE,
            "referenced": referenced,
        }
    return {
        "path": FRAGMENT,
        "state": "over" if size > BUDGET else "ok",
        "size": size,
        "budget": BUDGET,
        "baseline": BASELINE,
        "referenced": referenced,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(check(), indent=2))
