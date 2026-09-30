#!/usr/bin/env python3
"""Which open pull requests a tick's own dispatch never opened, and that
nothing else in the tick cadence will ever pick up -- #1798.

A curate pull request (#1789, 2026-09-29) sat unmerged across three
consecutive sub-manager ticks in the same `/oss:run` window, 10/10 checks
green, MERGEABLE, no conflicts. Each tick reviewed and merged only the pull
requests its own lanes opened; none of the three handbacks named #1789 at
all -- not merged, not skipped with a reason, not out of scope. It was
eventually folded in by an unrelated commit, never through a step that names
this mechanism.

`agents/sub-manager.md`'s own CI-wait shape reaches `oss:tick-review` "with
exactly the pull request number(s) open this tick... plus any pull request
`skills/manager/phases/handback.md` named from a lane's own `superseded_by_pr`
field this tick... nothing else." A pull request opened outside a tick's own
dispatch step -- a `curate/*` or `doctor/*` branch a scheduler-step spawn
pushed and opened on its own, per `commands/run.md`'s own repair-and-PR
paragraph -- has no reviewer and no merger by construction, not by accident.
`commands/run.md` promises "the ordinary dispatch/review/merge cadence picks
it up on a later tick" for exactly these two branch prefixes; nothing in the
cadence kept that promise until this module.

This closes the one step the incident showed missing: given the open pull
requests and the numbers a tick already knows about (its own dispatch, plus
any `superseded_by_pr`), which of the rest are loop-authored orphans safe to
fold into the same `oss:tick-review` call. It reuses
`release_gate2.is_loop_authored_branch()` rather than a second copy of the
same two prefixes -- one list, not two that can drift apart.

**Deliberately conservative, never a false positive.** A pull request whose
branch does not match a known loop-authored prefix is never swept in, even
when the caller could not establish its branch at all -- an ordinary
developer-lane or human-authored PR is not this sweep's to touch, and a
missed sweep costs one more tick's wait, not a silent merge of the wrong
thing. This is the opposite asymmetry from `release_gate2.py`'s own gate,
which refuses to clear on an unread signal -- there, guessing wrong ships a
release; here, guessing wrong reviews a stranger's PR. So this module has no
`could-not-tell` verdict for a single PR's own missing branch field, only for
the two inputs that must be established before it can look at any PR at all:
the open-PR list itself, and the set of numbers this tick already knows
about (an empty list is a real, confirmed fact there -- "this tick dispatched
nothing" -- and must not collapse into "was never checked").

Exit codes, because a shell reads those and never reads prose:

  0   determined -- ``orphans`` may be empty
  2   could-not-tell, or an argparse usage error
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from release_gate2 import is_loop_authored_branch
except ImportError:  # pragma: no cover -- direct script invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from release_gate2 import is_loop_authored_branch

UNKNOWN = "unknown"

EXIT_OK = 0
EXIT_COULD_NOT_TELL = 2


def orphan_numbers(open_prs, known_numbers):
    """Return this sweep's own disposition.

    ``open_prs`` is a list of dicts, each carrying at least ``number`` and
    ``branch`` (the head ref name) -- the same per-PR shape `gh pr list
    --json number,headRefName` already gives. ``known_numbers`` is a list of
    ints: every pull request number this tick already knows about (its own
    dispatch, plus any ``superseded_by_pr``).

    Either argument may be ``None`` or the literal string ``"unknown"`` when
    the caller never established it -- that is a *different* fact from an
    empty list, which means the fetch was made and confirmed to hold
    nothing, and must not collapse into the same answer.

    Returns ``{"status": "determined", "orphans": [...ints...], "reason": ...}``
    or ``{"status": "could-not-tell", "orphans": [], "reason": ...}``.
    """
    if open_prs is None or open_prs == UNKNOWN:
        return {
            "status": "could-not-tell",
            "orphans": [],
            "reason": "the open pull-request list itself was never "
            "established -- an unperformed fetch must not render as a "
            "confirmed-empty one",
        }
    if known_numbers is None or known_numbers == UNKNOWN:
        return {
            "status": "could-not-tell",
            "orphans": [],
            "reason": "this tick's own known pull-request numbers were "
            "never established -- without that set, every loop-authored PR "
            "would look orphaned, including ones this tick already "
            "dispatched",
        }

    known = set(known_numbers)
    orphans = [
        pr.get("number")
        for pr in open_prs
        if is_loop_authored_branch(pr.get("branch"))
        and isinstance(pr.get("number"), int)
        and pr.get("number") not in known
    ]

    if orphans:
        return {
            "status": "determined",
            "orphans": orphans,
            "reason": "{0} loop-authored pull request(s) open with no "
            "reviewer or merger from this tick's own dispatch".format(len(orphans)),
        }
    return {
        "status": "determined",
        "orphans": [],
        "reason": "no open pull request is both loop-authored "
        "(doctor/*, curate/*) and outside this tick's own known set",
    }


def _load_json_or_unknown(raw, flag_name, parser):
    stripped = raw.strip()
    if stripped.lower() in ('"unknown"', "unknown"):
        return UNKNOWN
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        parser.error("{0} did not parse as JSON: {1}".format(flag_name, exc))
        return None  # pragma: no cover -- parser.error exits


def _read_arg(value, flag_name, parser):
    if value == UNKNOWN:
        return UNKNOWN
    try:
        raw = (
            sys.stdin.read()
            if value == "-"
            else Path(value).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError) as exc:
        parser.error("{0} could not be read: {1}".format(flag_name, exc))
        return None  # pragma: no cover -- parser.error exits
    return _load_json_or_unknown(raw, flag_name, parser)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Which open pull requests this tick's own dispatch did not "
            "open and nothing else will ever pick up -- fold the answer "
            "into the same oss:tick-review call (#1798)."
        )
    )
    parser.add_argument(
        "--open-prs-json",
        required=True,
        help="path to a JSON file holding a list of PR dicts (number, "
        "branch), '-' to read from stdin, or the literal word unknown when "
        "the open-PR list itself could not be fetched",
    )
    parser.add_argument(
        "--known-json",
        required=True,
        help="path to a JSON file holding a list of ints (this tick's own "
        "known pull-request numbers), '-' to read from stdin, or the "
        "literal word unknown when that set was never established -- an "
        "empty JSON list ([]) is a real, confirmed fact, distinct from "
        "unknown",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of prose"
    )
    args = parser.parse_args(argv)

    open_prs = _read_arg(args.open_prs_json, "--open-prs-json", parser)
    known_numbers = _read_arg(args.known_json, "--known-json", parser)

    if open_prs not in (None, UNKNOWN) and (
        not isinstance(open_prs, list)
        or not all(isinstance(pr, dict) for pr in open_prs)
    ):
        parser.error(
            "--open-prs-json must hold a JSON list of PR objects (dicts), "
            "or the literal word unknown -- got {0!r}".format(open_prs)
        )
    if known_numbers not in (None, UNKNOWN) and (
        not isinstance(known_numbers, list)
        or not all(isinstance(n, int) for n in known_numbers)
    ):
        parser.error(
            "--known-json must hold a JSON list of ints, or the literal "
            "word unknown -- got {0!r}".format(known_numbers)
        )

    result = orphan_numbers(open_prs, known_numbers)

    if args.json:
        print(json.dumps(result))
    else:
        if result["status"] == "could-not-tell":
            print("ORPHANS: could-not-tell")
        elif result["orphans"]:
            print("ORPHANS: {0}".format(",".join(str(n) for n in result["orphans"])))
        else:
            print("ORPHANS: none")
        print("  {0}".format(result["reason"]))

    return EXIT_COULD_NOT_TELL if result["status"] == "could-not-tell" else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
