"""Board in, ranked claimable candidates out -- #970.

Selection used to be five scripts and a session doing the joins by hand:
`dispatch_rank.py` for the order, `issue_claim.py --read` for who already
holds an issue, `preflight_check.py` for whether it is stale, and
`lane_setup.py` for whether it collides with a lane already in flight. A
tick that finds no candidate after running all four and a tick that could
not read one of the four inputs used to end the same way -- the `nothing
left` state, whose own guard ("`gh-issues` and `gh-prs` both answered")
lived in prose with nothing enforcing it.

This module composes the four -- never re-implements them -- and enforces
that guard: refuse to answer `none-available` when any input could not be
read, and name which one went dark instead.

## Three states, and the one that must never render as another

  candidates       at least one issue survived every filter -- ranked, with
                    the reason every other issue on the board was dropped.
  none-available    every input was read cleanly and nothing survived -- a
                    real, established absence.
  could-not-select  at least one input could not be read. **Never**
                    `none-available` -- an absence produced because a read
                    failed is not an absence in the world, and #970 exists
                    to close exactly that gap.

## Per-issue disposition

`eligible` / `assigned` / `assignee-unreadable` / `stale` (a preflight
pattern matched -- the defect is already fixed) / `unrankable`
(`dispatch_rank.rank` could not place it -- an undeclared label axis, or a
non-loop issue whose `author_association` this payload never carried, most
often) / `lane-collision` (its own declared files overlap a lane already
claimed).

## What this deliberately does NOT do

**The lane pattern stays an input, never a guess.** #267 settled that an
issue's files are not derivable from its body, so this module never invents
`lane_patterns` or a `preflight_pattern` for an issue that did not carry
one -- an issue with neither is simply never checked for staleness or
collision, which is the correct answer for an issue nobody has looked at
that closely yet, not a silent `stale: no` or `lane-collision: no`.

**This module never calls `gh` for the board itself.** The same separation
`dispatch_rank.py` and `lane_setup.py --suggest-companions` already use: the
caller (a tick, a sub-manager, a human) reads the board and hands it in as
data, so this module's own reads never depend on network access or forge
credentials beyond the one call it does make itself -- `issue_claim.check`,
to verify the assignee state of whichever issues survive ranking, staleness
and lane-collision (checking every issue on a large board would be a `gh`
call per issue paid for issues about to be dropped anyway).

## Groups, not only a flat list (#1068)

A `candidates` result also carries `groups`: `{"groups": [...], "ungrouped":
[...]}`. Each group composes `lane_setup.suggest_companions` over one
`candidates` entry's own resolved lane files -- board in, ranked
**dispatchable lanes** out, the same way this module already composes
`resolve_lane` and `issue_claim.check`. A group targets three members
(`_GROUP_TARGET`), never pads to hit that number, and a member's own
disposition plus a group's own three-value state
(`candidates`/`none`/`could-not-tell`) survive per group rather than
flattening to one verdict for the whole call. A group is a suggestion, never
a dispatch -- the caller still decides whether it is worth a lane.
`ungrouped` lists candidates that could not be grouped at all (no declared
files, per #267, or files that could not be resolved), never candidates that
were grouped and stayed alone -- a short group with a stated
`short_reason` is a different, weaker claim than "never entered grouping".

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispatch_rank  # noqa: E402
import issue_claim  # noqa: E402
import lane_setup  # noqa: E402
import preflight_check  # noqa: E402

STATE_CANDIDATES = "candidates"
STATE_NONE_AVAILABLE = "none-available"
STATE_COULD_NOT_SELECT = "could-not-select"

#: #1013: `dispatch_rank.rank`'s own contract (see its module docstring)
#: expects an already-translated `"external"`/`"maintainer"` axis, never
#: GitHub's own `author_association` vocabulary -- but this module is the one
#: that reads a raw `gh api` payload, and nothing translated the field
#: between the two, so every real board marked every non-loop issue
#: `unrankable`. Only the two sets `dispatch_rank.py`'s own module docstring
#: names are translated here; a value in neither set -- `FIRST_TIMER`,
#: `FIRST_TIME_CONTRIBUTOR`, `MANNEQUIN`, a typo, a missing field -- is left
#: untranslated (`None`) on purpose, so `rank()`'s own "could not tell"
#: refusal still fires rather than this module guessing which axis an
#: unrecognised value belongs to.
_MAINTAINER_ASSOCIATIONS = frozenset(("OWNER", "MEMBER", "COLLABORATOR"))
_EXTERNAL_ASSOCIATIONS = frozenset(("CONTRIBUTOR", "NONE"))


def _translate_author_association(raw):
    """GitHub's own `author_association` field to `dispatch_rank.rank`'s two-
    value vocabulary (`"maintainer"` / `"external"`), or `None` for "could
    not tell" -- see the module-level comment above for which values map
    where and why an unrecognised one is never guessed.

    A caller that already translated the field (this module's own test
    fixtures, and any caller written before this function existed) passes
    straight through unchanged: the two vocabularies never share a spelling
    (GitHub's is all-caps, `dispatch_rank.ASSOCIATIONS` is not), so accepting
    either introduces no ambiguity, and it means this fix does not silently
    stop ranking a payload that was already correct."""
    if raw in dispatch_rank.ASSOCIATIONS:
        return raw
    if raw in _MAINTAINER_ASSOCIATIONS:
        return "maintainer"
    if raw in _EXTERNAL_ASSOCIATIONS:
        return "external"
    return None


def _could_not_select(why, dropped=None):
    # `dropped` defaults to `[]`, never `None` reused across callers: a caller
    # that could not select still knows which issues it had already sorted a
    # disposition for (#970 review round) -- surfacing that partial record
    # rather than discarding it back to a bare empty list.
    return {
        "state": STATE_COULD_NOT_SELECT,
        "why": why,
        "candidates": [],
        "dropped": [] if dropped is None else dropped,
    }


#: #1068: a group is a target of three, never a quota (the maintainer's own
#: reply on the issue) -- the bound stays declared-file overlap, and padding a
#: group to hit this number would invent a relationship #267 forbids this
#: module from guessing.
_GROUP_TARGET = 3


def _group_candidates(
    candidates,
    issues_by_number,
    resolved_files_by_number,
    suggest_companions,
    board_capped,
    board_cap_detail,
):
    """#1068: compose `lane_setup.suggest_companions` over `select()`'s own
    ranked, eligible `candidates` -- the fourth join this module used to leave
    to a session, the same way it already composes `resolve_lane` and
    `issue_claim.check`. `suggest_companions` keeps its own signature and
    stays independently callable; this only adds a caller.

    **Membership is restricted to issues already in `candidates`.**
    `suggest_companions` sweeps every OTHER open issue on the board, including
    ones this call has already dropped as stale, assigned or colliding --
    only a `candidates` entry has passed every one of those checks, so only
    one is safe to hand a developer as part of the same dispatchable lane. An
    overlap `suggest_companions` finds against a non-candidate issue is real,
    but it is not this function's to add to a group; the maintainer still
    sees it via that issue's own row when it is next ranked.

    Returns `(groups, ungrouped)`:

      groups      one entry per lead (highest-ranked first, never a
                  candidate already claimed by an earlier group), each
                  `{"members": [...], "state", "detail", "short_reason"}`.
                  `members` is `candidates` entries, unmodified apart from an
                  added `role` (`"lead"` / `"member"`) and, for a member, the
                  overlapping files `suggest_companions` found. `state` is
                  `suggest_companions`'s own three-value answer for this
                  lead (`candidates` / `none` / `could-not-tell`) --
                  preserved per group rather than flattened into one verdict
                  for the whole call, per the issue's own requirement.
                  `short_reason` is set (never guessed at, never blank) only
                  when the group has not reached `_GROUP_TARGET`: it says
                  which of the two distinct reasons applies -- no overlapping
                  candidate was found, or the board read that fed
                  `suggest_companions` was capped -- so a short group because
                  nothing overlaps and a short group because the read was
                  truncated never render as the same row.
      ungrouped   every candidate that could not join any group at all --
                  declares no files (#267: never guessed into one), the only
                  reason reachable through `select()`'s own call graph today;
                  a second, named reason ("its own declared files could not
                  be resolved to anything on disk") is kept for a future
                  caller of this function that builds `candidates` /
                  `resolved_files_by_number` some other way, since every
                  `select()` candidate with `lane_patterns` has already
                  passed the refused/resolved-to-nothing dark-input checks by
                  the time grouping runs. Each entry carries its own `why`.
                  Not the same list as a short group's members: this is
                  "never entered grouping", `short_reason` is "entered, and
                  stayed alone".
    """
    board = {
        "capped": bool(board_capped),
        "cap_detail": board_cap_detail or "",
        "issues": [
            {"number": n, "title": row.get("title"), "body": row.get("body")}
            for n, row in issues_by_number.items()
        ],
    }
    candidates_by_number = {c["number"]: c for c in candidates}
    taken = set()
    groups = []
    ungrouped = []
    for cand in candidates:
        number = cand["number"]
        if number in taken:
            continue
        taken.add(number)
        claimed = resolved_files_by_number.get(number)
        if not claimed:
            row = issues_by_number.get(number) or {}
            if row.get("lane_patterns"):
                # Defensive only, reviewed and left in on purpose (#1068 review
                # round): under `select()`'s own control flow this arm cannot
                # actually run today -- any candidate whose `lane_patterns` is
                # truthy has already passed the refused/`_lane_resolved_to_
                # nothing` dark-input checks above (either of which would have
                # forced the whole call to `could-not-select` before grouping
                # ever runs), so `resolved_files_by_number[number]` is always
                # set and non-empty by the time `candidates` is built. Kept as
                # a second, named reason -- rather than folded into the one
                # below -- so a future caller of this internal function with a
                # `candidates`/`resolved_files_by_number` pair built some other
                # way still gets a true answer instead of a misleading one.
                why = "its own declared files could not be resolved to anything on disk"
            else:
                why = (
                    "declares no files -- an issue's files are not derivable "
                    "from its body (#267), so it cannot be grouped"
                )
            ungrouped.append(dict(cand, why=why))
            continue
        result = suggest_companions(Path("."), number, claimed, board)
        members = [dict(cand, role="lead")]
        if result["state"] == "candidates":
            for entry in result["candidates"]:
                cnum = entry["number"]
                if cnum in taken:
                    continue
                other = candidates_by_number.get(cnum)
                if other is None:
                    continue
                members.append(dict(other, role="member", overlap=entry["files"]))
                taken.add(cnum)
                if len(members) >= _GROUP_TARGET:
                    break
        short_reason = None
        if len(members) < _GROUP_TARGET:
            if result["state"] == "could-not-tell":
                short_reason = "board sweep could not tell: {0}".format(
                    result["detail"]
                )
            else:
                short_reason = (
                    "no further overlapping candidate among the ranked issues"
                )
        groups.append(
            {
                "members": members,
                "state": result["state"],
                "detail": result["detail"],
                "short_reason": short_reason,
            }
        )
    return groups, ungrouped


def select(
    payload, checker=None, search=None, resolve_lane=None, suggest_companions=None
):
    """The join. `payload` is `{"declared": {...}, "issues": [...], ...}` --
    see the module docstring's per-issue optional fields (`preflight_pattern`
    / `preflight_roots`, `lane_patterns`) and the top-level optional
    `held_files`, `repo`, `lanes_read_ok` / `lanes_read_why` (#1067) and
    `board_capped` / `board_cap_detail` (#1068, consumed only by grouping --
    see "## Groups" above).

    `checker`/`search`/`resolve_lane`/`suggest_companions` default to
    `issue_claim.check`/`preflight_check.search`/`lane_setup.resolve_lane`/
    `lane_setup.suggest_companions` -- injectable so a caller (or a test)
    never needs a live `gh` session or a real tree to drive this function.

    #1067: `held_files` gets the same could-not-read treatment `board_read_ok`
    already has, via a top-level `lanes_read_ok` / `lanes_read_why` pair --
    `lanes_read_ok is False` forces `could-not-select` before `held_files` is
    even read, the same way `board_read_ok is False` already does for the
    board. Their producer is `lane_setup.derive_held_set(...)`: `held_files`
    is `sorted(derive_held_set(...)["held"])`, `lanes_read_ok` is whether its
    `state` came back `resolved`, and `lanes_read_why` is its `detail` when it
    did not -- documented beside the dispatch directive that runs this script
    in `skills/manager/phases/dispatch.md`. An absent `lanes_read_ok` (a
    caller that never populated it, and every test fixture that predates this
    fix) is read as "not attempted" rather than "failed" -- the same posture
    `board_read_ok`'s own absence already gets -- so this stays additive
    rather than breaking a caller that has no lane inventory to offer at all.
    """
    checker = issue_claim.check if checker is None else checker
    search = preflight_check.search if search is None else search
    resolve_lane = lane_setup.resolve_lane if resolve_lane is None else resolve_lane
    suggest_companions = (
        lane_setup.suggest_companions
        if suggest_companions is None
        else suggest_companions
    )

    declared = payload.get("declared") or {}

    if payload.get("board_read_ok") is False:
        why = (
            payload.get("board_read_why") or "the caller reported the board read failed"
        )
        return _could_not_select("board: {0}".format(why))

    issues = payload.get("issues")
    if not isinstance(issues, list):
        return _could_not_select(
            "board: 'issues' is missing or not a list -- the board could not be read"
        )

    # #1067: `held_files` used to have no unreadable state at all -- "the live
    # lanes could not be enumerated" and "there are no live lanes" arrived as
    # the identical empty set, and the collision check below then silently
    # did nothing. `lanes_read_ok`/`lanes_read_why` give it the same treatment
    # `board_read_ok` already has, above: `is False` (never falsy-but-absent)
    # forces `could-not-select` before `held_files` is read at all, so an
    # absent pair -- a caller that never populated it -- still reads as "not
    # attempted", not as a failure.
    if payload.get("lanes_read_ok") is False:
        why = (
            payload.get("lanes_read_why")
            or "the caller reported the lane inventory read failed"
        )
        return _could_not_select("lanes: {0}".format(why))

    held_files = set(payload.get("held_files") or [])
    repo = payload.get("repo")

    # #1013 review round: `dispatch_rank.order()` computes its own stable-sort
    # key by calling `rank()` internally (see its docstring) with whatever
    # `author_association` the item carries -- translating only inside the
    # loop below fixed each candidate's own rank/author/band fields but left
    # `order()` itself sorting on the raw, untranslated GitHub value, which
    # is unrankable for every real board and so leaves every non-loop issue
    # in input order regardless of true priority. Translating once here, into
    # a shallow-copied issue list, means both `order()`'s key and the loop's
    # own `rank()` call see the same already-translated value.
    translated_issues = [
        dict(
            item,
            author_association=_translate_author_association(
                item.get("author_association")
            ),
        )
        for item in issues
    ]
    ranked = dispatch_rank.order(translated_issues, declared)

    dropped = []
    survivors = []  # (issue_row, rank_answer)
    dark_inputs = []
    # #1068: captured here, once, so grouping (below) never re-resolves a lane
    # pattern it has already paid to resolve -- only survives for a candidate
    # whose lane pattern was neither refused nor resolved-to-nothing, which is
    # exactly the set grouping is safe to use.
    resolved_files_by_number = {}

    for item in ranked:
        number = item.get("number")
        answer = dispatch_rank.rank(
            item.get("labels") or [],
            declared,
            item.get("author_association"),
        )
        if answer["rank"] is None:
            dropped.append(
                {"number": number, "disposition": "unrankable", "why": answer["why"]}
            )
            continue

        pattern = item.get("preflight_pattern")
        if pattern:
            roots = [Path(r) for r in (item.get("preflight_roots") or ["."])]
            result = search(pattern, roots)
            if result["state"] == "matched":
                dropped.append(
                    {
                        "number": number,
                        "disposition": "stale",
                        "why": "preflight pattern matched: {0}".format(pattern),
                    }
                )
                continue
            if result["state"] == "could-not-search":
                dark_inputs.append(
                    "preflight for #{0}: {1}".format(number, result.get("problem"))
                )
                continue

        lane_patterns = item.get("lane_patterns")
        if lane_patterns:
            resolved = resolve_lane(Path("."), lane_patterns)
            refused = [
                entry for entry in resolved["patterns"] if entry["state"] == "refused"
            ]
            if refused:
                # #998/#1067: a refused member contributes `files: []`, and an
                # empty union used to read as "no overlap" -- the same defect
                # class #970 closed for the assignee read, one input over: an
                # unreadable lane pattern is dark, never a clean disjointness
                # result reached by accident. Hoisted out of `and held_files`
                # (#1067): whether a lane pattern could be read at all does
                # not depend on whether anything is currently held -- with
                # `held_files` empty (lane 1 of any tick, and every tick #1067
                # left unaffected before this fix), this guard used to never
                # run at all.
                dark_inputs.append(
                    "lane pattern for #{0}: {1}".format(
                        number, "; ".join(entry["detail"] for entry in refused)
                    )
                )
                continue
            if lane_setup._lane_resolved_to_nothing(resolved):
                # #1067: every member was well-formed and checked, but the
                # lane still names zero files on disk (`glob-no-match`, not
                # `refused`) -- `lane_setup.lane_overlap` against an empty
                # union then passes as disjoint from every live lane, which
                # is not a fact anyone checked. A lane naming nothing on disk
                # is not a lane colliding with nothing, so this is reported
                # dark -- neither a collision nor a disjoint result -- naming
                # the pattern(s) that matched nothing.
                dark_inputs.append(
                    "lane pattern for #{0}: resolved to no files on disk ({1})".format(
                        number,
                        ", ".join(entry["pattern"] for entry in resolved["patterns"]),
                    )
                )
                continue
            if held_files:
                overlap = lane_setup.lane_overlap(resolved["files"], held_files)
                if overlap:
                    dropped.append(
                        {
                            "number": number,
                            "disposition": "lane-collision",
                            "why": "overlaps already-claimed file(s): {0}".format(
                                ", ".join(overlap)
                            ),
                        }
                    )
                    continue
            resolved_files_by_number[number] = resolved["files"]

        survivors.append((item, answer))

    if dark_inputs:
        return _could_not_select("; ".join(dark_inputs), dropped=dropped)

    candidates = []
    if survivors:
        numbers = [item.get("number") for item, _answer in survivors]
        rows = {row["issue"]: row for row in checker(numbers, "read", repo=repo)}
        for item, answer in survivors:
            number = item.get("number")
            row = rows.get(number)
            if row is None:
                dropped.append(
                    {
                        "number": number,
                        "disposition": "assignee-unreadable",
                        "why": "no row returned by the assignee checker",
                    }
                )
                dark_inputs.append(
                    "assignee read for #{0}: no row returned".format(number)
                )
                continue
            if row["state"] == issue_claim.STATE_COULD_NOT_READ:
                # #970 review round: this used to fall straight into
                # `dark_inputs` with no matching `dropped` entry -- and the
                # whole call always returns `could-not-select` with `dropped`
                # hardcoded to `[]` in that case (below), so the disposition
                # named in this module's own docstring could never actually
                # be produced. Recording it here first means a caller that
                # inspects a partial/aborted run (or a future caller that
                # keeps going past the first dark input) sees the real
                # per-issue reason rather than nothing.
                dropped.append(
                    {
                        "number": number,
                        "disposition": "assignee-unreadable",
                        "why": "assignee read failed: {0}".format(row.get("detail")),
                    }
                )
                dark_inputs.append(
                    "assignee read for #{0}: {1}".format(number, row.get("detail"))
                )
                continue
            if row["state"] == issue_claim.STATE_ASSIGNED:
                dropped.append(
                    {
                        "number": number,
                        "disposition": "assigned",
                        "why": "already assigned to {0}".format(
                            ", ".join(row.get("assignees") or [])
                        ),
                    }
                )
                continue
            candidates.append(
                {
                    "number": number,
                    "disposition": "eligible",
                    "rank": answer["rank"],
                    "author": answer["author"],
                    "band": answer["band"],
                    "why": answer["why"],
                }
            )

    if dark_inputs:
        return _could_not_select("; ".join(dark_inputs), dropped=dropped)

    state = STATE_CANDIDATES if candidates else STATE_NONE_AVAILABLE
    if candidates:
        issues_by_number = {item.get("number"): item for item in issues}
        groups, ungrouped = _group_candidates(
            candidates,
            issues_by_number,
            resolved_files_by_number,
            suggest_companions,
            payload.get("board_capped"),
            payload.get("board_cap_detail"),
        )
    else:
        groups, ungrouped = [], []
    return {
        "state": state,
        "why": None,
        "candidates": candidates,
        "dropped": dropped,
        "groups": {"groups": groups, "ungrouped": ungrouped},
    }


def main(argv=None):
    """Read the board (and the rest of `select`'s payload) as JSON on stdin,
    print the result as JSON, and exit 0 (candidates), 1 (none-available) or
    2 (could-not-select).

    #846's own class, guarded here from the start rather than added after
    the fact: `sys.stdin` is `None` when the harness hands this process a
    closed or unopenable standard input, and `json.load(None)` raises
    `AttributeError` uncaught -- past this module's own `could-not-select`,
    which is exactly the state that exists for a read that failed.
    """
    del argv  # this module takes no flags; the payload is the whole input

    # #970 review round: the sibling idiom used by dispatch_rank.py,
    # lane_setup.py, issue_claim.py and others (#794, #834) -- a candidate's
    # `why` can carry an issue's own label or title text (via
    # `dispatch_rank.rank`'s `repr(unrecognised)`), and a console codepage
    # that cannot encode one of them must not crash this print after the
    # selection was already computed.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    if sys.stdin is None:
        result = _could_not_select(
            "stdin: no readable stdin -- the process was handed a closed or "
            "unopenable standard input"
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover - not a TextIOWrapper
        pass

    try:
        payload = json.load(sys.stdin)
    except UnicodeDecodeError as exc:
        # UnicodeDecodeError is a ValueError, not a JSON-syntax error --
        # caught separately so this never renders as "not valid JSON" when
        # stdin was JSON and simply could not be decoded (dispatch_rank.py's
        # own #834 fix, same class).
        result = _could_not_select(
            "stdin: could not be decoded as UTF-8 ({0})".format(exc)
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    except ValueError as exc:
        result = _could_not_select("stdin: not valid JSON ({0})".format(exc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    result = select(payload)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["state"] == STATE_CANDIDATES:
        return 0
    if result["state"] == STATE_NONE_AVAILABLE:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
