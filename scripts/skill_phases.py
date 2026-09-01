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

And one question about the set rather than about a file: **is there a phase
file on disk that this module does not declare?** `scripts/manager_docs.py`
derives the loop's documents from disk, so the two views can be compared, and
an `undeclared` row is the mirror of `missing` -- a phase file nobody budgeted,
which is how the whole measurement quietly stops covering its subject again.
Reporting only the declared paths would answer "every file I know about is
fine", which is true of an empty declaration too.

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
from manager_docs import documents  # noqa: E402

#: The always-loaded half.
SPINE = "skills/manager/SKILL.md"

#: repo-relative path (POSIX) -> (bytes measured when the budget was set,
#: budget bytes incl. ~10% headroom, what the file governs).
DOCUMENTS: dict[str, tuple[int, int, str]] = {
    SPINE: (58377, 64600, "the loop itself: what is decided every tick, and where each phase's rules live"),
    # Raised (#725): measured 26,052 B against the prior 26,100 B budget -- 48
    # B of headroom, and a lane in this same tick had already been forced to
    # place a new directive in SKILL.md instead of here solely because of that
    # margin (see CLAUDE.md's "The manager skill is a spine plus one file per
    # phase" section, the paragraph beside this table, for the receipt).
    # A split was weighed and declined: dispatch.md's content -- fleet size,
    # lane disjointness, bundling, what every brief carries -- is one subject
    # in one section, not two phases wearing one name, and a fresh split is a
    # larger, separately-reviewable change this issue does not warrant.
    # Re-baselined silently was declined too, per this file's own rule that a
    # raise carries a sentence about what was weighed. This is the file's
    # third budget change; the margin should be re-measured at the next one
    # rather than assumed still adequate.
    "skills/manager/phases/dispatch.md": (26052, 28700, "delegating: fleet size, lane disjointness, bundling, what every brief carries"),
    "skills/manager/phases/handback.md": (18864, 20700, "a lane reported back: reading the report, pushing, opening the pull request"),
    "skills/manager/phases/review.md": (11637, 12800, "reviewing a returned diff, and what an issue body filed out of one looks like"),
    "skills/manager/phases/merge.md": (10012, 11000, "merging: the gates, the call itself, and what is still owed after green"),
    "skills/manager/phases/release.md": (10195, 11200, "cutting a release: the six gates and what the tag does and does not deliver"),
    "skills/manager/phases/accounting.md": (15093, 16600, "closing a tick: the cohort freeze, the intake ratio, and what a tick costs to carry"),
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
    rows.extend(_undeclared_rows(root))
    return rows


def _undeclared_rows(root):
    """A row per phase file on disk that `DOCUMENTS` does not declare.

    `state` is `undeclared`: it is on disk, so it is not `missing`, and it has
    no budget to be `over`. `referenced` is still answered, because a phase
    file the spine names and nobody budgeted and one nothing names at all are
    different problems.

    A tree with no phases directory contributes nothing rather than raising:
    that is the `missing` rows' answer to give, and giving it twice would say
    the same absence in two vocabularies. An *unreadable* phases directory
    (#571) is different from a missing one and is reported as its own row --
    `state: unreadable` -- rather than silently folded into "no undeclared
    files found", which is what an empty `on_disk` would otherwise look like.
    """
    try:
        on_disk, unreadable = documents(root)
        on_disk = on_disk[1:]
    except RuntimeError:
        # `documents()` raises this when `spine.is_file()` says the spine
        # is not a file -- the ordinary case is a genuinely absent spine,
        # already reported by that document's own `missing` row in
        # `check()`'s main loop. `is_file()` also folds a stat failure
        # (e.g. `PermissionError` on a parent directory) into the same
        # `False`, and `check()`'s own spine `read_bytes()` call only
        # catches `FileNotFoundError` -- so that narrower case reaches
        # here after `check()` has already raised uncaught, rather than
        # after a `missing` row was emitted. Out of scope for #589: it
        # predates this fix and is not the fold this issue is about.
        return []
    except OSError as exc:
        # `documents()` itself could not be asked, rather than answering
        # with an `unreadable` message in its own return value (#571's own
        # shape, handled below) -- this must still surface as `unreadable`,
        # not fold into "no undeclared files found" (#589).
        return [
            {
                "path": "skills/manager/phases",
                "state": "unreadable",
                "size": None,
                "budget": None,
                "baseline": None,
                "governs": None,
                "referenced": None,
                "detail": str(exc),
            }
        ]
    rows = []
    for message in unreadable:
        rows.append(
            {
                "path": "skills/manager/phases",
                "state": "unreadable",
                "size": None,
                "budget": None,
                "baseline": None,
                "governs": None,
                "referenced": None,
                "detail": message,
            }
        )
    for path in on_disk:
        rel = path.relative_to(root).as_posix()
        if rel in DOCUMENTS:
            continue
        spine = _spine_text(root)
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


if __name__ == "__main__":
    import json

    print(json.dumps(check(), indent=2))
