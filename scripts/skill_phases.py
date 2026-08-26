"""Where the manager loop's prose lives, and what each piece of it costs.

`skills/manager/SKILL.md` is loaded whole by `Skill(manager)`, which
`commands/tick.md` and `commands/release.md` both open with. Unlike an agent
definition it is not re-read per turn from disk -- it enters the session's
context once and is then paid for on every turn of that session at cache-read
price. At 122,423 B that was ~31k tokens standing in context for the whole of
every tick and every release, whether or not the session ever reached the
phase a given paragraph governs. #491 budgeted the agent definitions and said,
in as many words, that the manager skill was out of its scope; nothing counted
this file at all.

So the loop's prose is split in two:

- the **spine**, `SKILL.md`: what governs a decision the loop takes every
  tick, plus one directive per phase and a pointer to that phase's file;
- the **phases**, `skills/manager/phases/*.md`: the argument behind each
  phase's rules -- the incident it was written for, the measurement, the
  thing that was tried and rejected -- read at the moment the loop enters
  that phase.

**The split is not a licence to skim.** A phase file that is not read is a
rule that did not run, and a rule that did not run renders exactly like a
rule with nothing to say -- this plugin's own defect class, pointed at its
own documentation. The spine therefore asks each phase to state whether it
read its file, in the same three states everything else here uses: `read`,
`not-read` with a reason, or `could-not-read`. Nothing in this module can
observe that; what it can observe is the half that is on disk.

Three questions, one row each:

- **size against a budget** -- `ok` / `over` / `missing`, the same shape and
  the same reasoning as `scripts/agent_budgets.py`, whose `repo_root` this
  module reuses rather than copying. `missing` is load-bearing: a declared
  phase file that is not on disk is not "under budget".
- **referenced** -- does the spine name this path? A phase file the spine
  never names is unreachable, because the loop reads the spine and nothing
  else until the spine sends it somewhere. `None` means the question could
  not be asked at all (the spine itself was unreadable), and it must never
  render as `True`.
- **what it governs** -- declared here beside the budget, so the index in
  the spine and the set on disk have a third party they both answer to.

Budgets are the measured size plus ~10% headroom, exactly as #491 sets them:
enough to land one justified paragraph without reddening the diff that adds
it, not enough to make growth free. Crossing one means replacing something
or raising the number here in the same diff with a sentence saying what was
weighed. This module cannot judge whether a paragraph earns its size; that
stays a human call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_budgets import repo_root  # noqa: E402

#: The always-loaded half.
SPINE = "skills/manager/SKILL.md"

#: repo-relative path (POSIX) -> (bytes measured when the budget was set,
#: budget bytes incl. ~10% headroom, what the file governs).
DOCUMENTS: dict[str, tuple[int, int, str]] = {
    SPINE: (58377, 64600, "the loop itself: what is decided every tick, and where each phase's rules live"),
    "skills/manager/phases/dispatch.md": (23729, 26100, "delegating: fleet size, lane disjointness, bundling, what every brief carries"),
    "skills/manager/phases/handback.md": (18864, 20700, "a lane reported back: reading the report, pushing, opening the pull request"),
    "skills/manager/phases/review.md": (10348, 11400, "reviewing a returned diff, and what an issue body filed out of one looks like"),
    "skills/manager/phases/merge.md": (10012, 11000, "merging: the gates, the call itself, and what is still owed after green"),
    "skills/manager/phases/release.md": (10195, 11200, "cutting a release: the six gates and what the tag does and does not deliver"),
    "skills/manager/phases/accounting.md": (10663, 11700, "closing a tick: the cohort freeze and the intake ratio"),
}


def _spine_text(root):
    """The spine's text, or ``None`` when it could not be read.

    ``None`` rather than ``""`` on purpose: an empty string references
    nothing, which is indistinguishable from a spine that names no phase
    files -- and the caller has to be able to tell "the spine does not name
    it" from "nobody could ask".
    """
    try:
        return (root / SPINE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def check():
    """One row per declared document.

    ``state``: ``ok`` | ``over`` | ``missing``.
    ``referenced``: ``True`` | ``False`` | ``None`` (the spine was unreadable,
    so the question went unasked -- never rendered as referenced).
    """
    root = repo_root()
    spine = _spine_text(root)
    rows = []
    for rel, (baseline, budget, governs) in DOCUMENTS.items():
        path = root.joinpath(*rel.split("/"))
        if rel == SPINE:
            referenced = True
        elif spine is None:
            referenced = None
        else:
            referenced = rel in spine
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
    return rows


if __name__ == "__main__":
    import json

    print(json.dumps(check(), indent=2))
