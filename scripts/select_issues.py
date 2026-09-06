"""Board in, ranked claimable candidates out -- #970.

Selection used to be five scripts and a session doing the joins by hand:
`select_issues_rank.py` for the order, `select_issues_claim_read.py --read` for who already
holds an issue, `select_issues_preflight.py` for whether it is stale, and
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
(`select_issues_rank.rank` could not place it -- an undeclared label axis, or a
non-loop issue whose `author_association` this payload never carried, most
often) / `lane-collision` (its own declared files overlap a lane already
claimed).

## What this deliberately does NOT do

**The lane pattern stays an input, never a GUESS -- from an issue's body.**
#267 settled that an issue's files are not derivable from its body, so this
module never invents `lane_patterns` or a `preflight_pattern` from prose. A
path a human wrote literally, in backticks, is a declaration rather than a
guess (#851's own distinction, extended to the lead by #1135 below) --
what #267 forbids is inventing a file set from a subject line, never
reading one the issue's own author already wrote down. An issue with none
of `lane_patterns`, a body-declared path (#1135) or a mapped `lane-*`
label (#1129) is simply never checked for staleness or collision, which is
the correct answer for an issue nobody has looked at that closely yet, not
a silent `stale: no` or `lane-collision: no`.

**#1129 adds one narrow, declared exception to that rule, never a second
way to guess.** An issue with no `lane_patterns` of its own falls back to
`_derive_lane_patterns_from_labels`: its `lane-*` GitHub label, resolved
through a mapping a human wrote into `.oss.json`'s `labels.lane_patterns` --
never text an issue itself wrote. No lane label, an uncovered one, two
differently-mapped labels on the same issue, or no mapping declared at all
still resolve to `None` -- the identical "not derivable" posture as before,
never an empty file set (which would read as disjoint with every other
lane and falsely bundle an unexamined issue into one of them). A derived
set is coarser than a declared one -- a lane label names a whole
subsystem, not one issue's own files -- so every candidate carries
`lane_patterns_source` (`"declared"` / `"derived-from-body"` /
`"derived-from-label"` / `None`), never folding the sources together.

**#1135 inserts a narrower source ahead of both.** `select()`'s own lead
used to skip straight to the label fallback the moment it had no explicit
`lane_patterns` -- broad by construction, a whole subsystem -- while
`suggest_companions` derived each OTHER open issue's file set from
`select_issues_companions._derive_declared_files`: paths named literally,
in backticks, in that issue's own title and body (#851). Overlap was
therefore computed broad-against-narrow: a lead labelled `lane-dispatch`
claimed all of that lane's files and swallowed anything else in the
subsystem, while the precise overlaps on a live board were exactly the
ones where at least one side had no lane label and its files came from
its body instead. The fix gives the lead the identical body-declared
extraction first, falling back to the label's globs only when the title
and body name no path at all -- there is no argument for trusting a
backtick declaration on one side of an overlap and not the other.
Precedence is now strict and three deep: an issue's own explicit
`lane_patterns`, then paths declared in its own body
(`"derived-from-body"`), then its label's globs (`"derived-from-label"`),
then unknown (`None`) -- never `[]` at any step. See "## Groups" below for
`adjacency`, the group-level signal this adds so a bundle joined by a
measured file and a bundle joined only through a lead's coarse label set
render differently.

**#1130 adds one more per-repo label, never a sixth lane: `labels.lane_other`.**
A `lane-other` GitHub label is the triager's positive statement that an
issue was examined and no real lane owns its files -- never "nobody has
looked yet", which stays plain unlabelled. It carries no file set by
definition, so `_derive_lane_patterns_from_labels` special-cases it to
`None` explicitly, before the mapping is even consulted, rather than
reaching the same `None` through the ordinary "uncovered label" path by
accident. A candidate whose issue carries that label also gets
`is_lane_other: True`, independent of `lane_patterns_source` (which cannot
carry the distinction -- both a `lane-other` issue and one with no lane
label at all resolve `lane_patterns_source` to `None`). See "## Groups"
below for what that flag does to grouping.

**This module never calls `gh` for the board itself.** The same separation
`select_issues_rank.py` and `lane_setup.py --suggest-companions` already use: the
caller (a tick, a sub-manager, a human) reads the board and hands it in as
data, so this module's own reads never depend on network access or forge
credentials beyond the one call it does make itself -- `select_issues_claim_read.check`,
to verify the assignee state of whichever issues survive ranking, staleness
and lane-collision (checking every issue on a large board would be a `gh`
call per issue paid for issues about to be dropped anyway).

## Groups, not only a flat list (#1068)

A `candidates` result also carries `groups`: `{"groups": [...], "ungrouped":
[...]}`. Each group composes `select_issues_companions.suggest_companions` over one
`candidates` entry's own resolved lane files -- board in, ranked
**dispatchable lanes** out, the same way this module already composes
`resolve_lane` and `select_issues_claim_read.check`. A group targets three members
(`_GROUP_TARGET`), never pads to hit that number, and a member's own
disposition plus a group's own three-value state
(`candidates`/`none`/`could-not-tell`) survive per group rather than
flattening to one verdict for the whole call. A group is a suggestion, never
a dispatch -- the caller still decides whether it is worth a lane.
`ungrouped` lists candidates that could not be grouped at all (no declared
files, per #267, or files that could not be resolved), never candidates that
were grouped and stayed alone -- a short group with a stated
`short_reason` is a different, weaker claim than "never entered grouping".

**#1130: a `lane-other` candidate is a third route into `groups`, never
into `ungrouped`.** It is dispatched solo, always -- never given a
companion, never offered as one, never padded toward `_GROUP_TARGET` --
but it still enters grouping and comes out as a deliberate group of one
with a stated `short_reason` naming the rule. That is the same
"entered, and stayed alone" claim a short overlap-based group makes, kept
apart from "never entered grouping at all" so a reader can tell "no lane
owns this, by rule" from "nobody could place this".

**#1135: a group joined by an actual overlap also carries `adjacency`,**
`"measured"` or `"label-derived"` -- which kind of claim joined its
members, never left to be inferred from `lane_patterns_source` alone. A
companion that survives `suggest_companions` at all always got there
through its own body-declared file set (#851) -- never through a label --
so the only side of an overlap that can still be coarse is the lead's own,
and `adjacency` reads directly off it: `"label-derived"` when the lead's
own claim fell back to its `lane-*` label's globs (broad by construction,
per #1135 above), `"measured"` otherwise (`declared` or
`derived-from-body`, narrow by construction). A group the lead entered
without an overlap at all -- a short group with nothing further to say, or
a #1130 `lane-other` singleton -- carries `adjacency: None`: nothing
joined it, so there is no claim to grade.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import select_issues_claim_read  # noqa: E402
import select_issues_companions  # noqa: E402
import select_issues_preflight  # noqa: E402
import select_issues_rank  # noqa: E402
import select_issues_overlap  # noqa: E402

STATE_CANDIDATES = "candidates"
STATE_NONE_AVAILABLE = "none-available"
STATE_COULD_NOT_SELECT = "could-not-select"

#: #1013: `select_issues_rank.rank`'s own contract (see its module docstring)
#: expects an already-translated `"external"`/`"maintainer"` axis, never
#: GitHub's own `author_association` vocabulary -- but this module is the one
#: that reads a raw `gh api` payload, and nothing translated the field
#: between the two, so every real board marked every non-loop issue
#: `unrankable`. Only the two sets `select_issues_rank.py`'s own module docstring
#: names are translated here; a value in neither set -- `FIRST_TIMER`,
#: `FIRST_TIME_CONTRIBUTOR`, `MANNEQUIN`, a typo, a missing field -- is left
#: untranslated (`None`) on purpose, so `rank()`'s own "could not tell"
#: refusal still fires rather than this module guessing which axis an
#: unrecognised value belongs to.
_MAINTAINER_ASSOCIATIONS = frozenset(("OWNER", "MEMBER", "COLLABORATOR"))
_EXTERNAL_ASSOCIATIONS = frozenset(("CONTRIBUTOR", "NONE"))


def _translate_author_association(raw):
    """GitHub's own `author_association` field to `select_issues_rank.rank`'s two-
    value vocabulary (`"maintainer"` / `"external"`), or `None` for "could
    not tell" -- see the module-level comment above for which values map
    where and why an unrecognised one is never guessed.

    A caller that already translated the field (this module's own test
    fixtures, and any caller written before this function existed) passes
    straight through unchanged: the two vocabularies never share a spelling
    (GitHub's is all-caps, `select_issues_rank.ASSOCIATIONS` is not), so accepting
    either introduces no ambiguity, and it means this fix does not silently
    stop ranking a payload that was already correct."""
    if raw in select_issues_rank.ASSOCIATIONS:
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
    """#1068: compose `select_issues_companions.suggest_companions` over `select()`'s own
    ranked, eligible `candidates` -- the fourth join this module used to leave
    to a session, the same way it already composes `resolve_lane` and
    `select_issues_claim_read.check`. `suggest_companions` keeps its own signature and
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
                  for the whole call, per the issue's own requirement. #1130
                  adds a fourth value, `"lane-other"`, for the one case
                  that never calls `suggest_companions` at all: a candidate
                  whose issue carries the repo's configured `lane-other`
                  label is routed straight to a solo group, by rule, before
                  any board sweep runs.
                  `short_reason` is set (never guessed at, never blank) only
                  when the group has not reached `_GROUP_TARGET`: it says
                  which of the two distinct reasons applies -- no overlapping
                  candidate was found, or the board read that fed
                  `suggest_companions` was capped -- so a short group because
                  nothing overlaps and a short group because the read was
                  truncated never render as the same row.
      ungrouped   every candidate that could not join any group at all --
                  declares no files (#267: never guessed into one), the only
                  reason reachable through `select()`'s own call graph today
                  for a candidate that is not `is_lane_other`;
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
        if cand.get("is_lane_other"):
            # #1130: never given a companion, always solo -- the direction
            # of the risk runs opposite to a declared-file group. Bundling
            # is justified by PROVEN disjointness (#267); a `lane-other`
            # issue has no known file set at all, so disjointness against it
            # can only be assumed, and assuming it is the dangerous
            # direction. This still ENTERS grouping and comes out as a
            # deliberate group of one with a stated `short_reason` -- never
            # `ungrouped`, which means "never entered grouping at all".
            groups.append(
                {
                    "members": [dict(cand, role="lead")],
                    "state": "lane-other",
                    "detail": "",
                    "short_reason": (
                        "lane-other: no lane owns this issue's files -- "
                        "dispatched alone by rule, never assumed disjoint "
                        "with another candidate (#1130)"
                    ),
                    # #1135: nothing joined this group -- there is no
                    # overlap to grade for precision.
                    "adjacency": None,
                }
            )
            continue
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
                if other.get("is_lane_other"):
                    # #1130: symmetric with the solo-dispatch branch above --
                    # a `lane-other` candidate is never offered AS a
                    # companion either, regardless of iteration order (this
                    # lead may be ranked ahead of the `lane-other` issue's
                    # own turn in the loop above).
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
        # #1135: which kind of claim joined this group -- `"measured"` when
        # the LEAD's own file set is narrow (an explicit declaration or a
        # path named in its own body), `"label-derived"` when it fell back
        # to its `lane-*` label's whole subsystem. A companion that reached
        # `members` at all always got there through its own body-declared
        # set (#851's guarantee, unchanged) -- never through a label -- so
        # the lead's own `lane_patterns_source` is the only place coarseness
        # can still come from. `None` when nothing actually joined the
        # group (a solo lead, whatever the reason): there is no overlap to
        # grade for precision.
        adjacency = None
        if len(members) > 1:
            adjacency = (
                "label-derived"
                if cand.get("lane_patterns_source") == "derived-from-label"
                else "measured"
            )
        groups.append(
            {
                "members": members,
                "state": result["state"],
                "detail": result["detail"],
                "short_reason": short_reason,
                "adjacency": adjacency,
            }
        )
    return groups, ungrouped


def _derive_lane_patterns_from_labels(labels, lane_pattern_map, lane_other_label=None):
    """#1129: an issue's `lane_patterns` when it declares none of its own,
    derived from whichever of its GitHub labels the repo's declared
    `.oss.json` `labels.lane_patterns` mapping covers -- the fix for
    `select_issues.py` forming zero groups on every real board, because not
    one real issue carries a literal `lane_patterns` and #267 rightly
    forbids inventing one from an issue's body.

    Three states, never two, matching this issue's own governing rule for a
    single lane one level down (`_lane_resolved_to_nothing`): a lane label
    covered by the mapping derives that lane's patterns; no lane label, a
    lane label the mapping does not cover, two DIFFERENTLY-mapped lane
    labels on the same issue (ambiguous -- guessing which one applies is
    exactly the invention #267 forbids), or no mapping declared at all are
    all `None` -- **unknown**, never `[]`. An empty file set would read as
    disjoint with every other lane on the board and falsely bundle an
    unexamined issue into one of them, which is worse than the "not
    checked" this module already renders for an issue with no
    `lane_patterns` at all.

    A lane label is coarser than an issue -- the mapping names a whole
    subsystem's files, not this one issue's -- so a derived set is a weaker
    claim than a declared one. The caller (`select()`) records that as
    `lane_patterns_source`, never folding the two together, so a reader can
    tell a measured disjointness from an inferred one.

    #1130: `lane_other_label` -- the per-repo `labels.lane_other` name --
    is checked FIRST and unconditionally, before the mapping is consulted
    at all. `lane-other` has no file set by definition: it is the label the
    triager applies precisely when no lane owns an issue's files, so it
    must resolve to unknown even if a mapping happens to carry an entry
    keyed by that same label (never produced by `.oss.json`'s own validated
    shape, but a hand edit could do it). Reaching `None` for `lane-other`
    via the ordinary "uncovered label" fallback below would be the right
    answer for the wrong reason -- indistinguishable from a repo that
    simply forgot to map it -- so this is its own explicit branch, not a
    consequence of the loop underneath.
    """
    if lane_other_label and lane_other_label in (labels or []):
        return None
    if not isinstance(lane_pattern_map, dict) or not lane_pattern_map:
        return None
    matched = None
    for label in labels or []:
        patterns = lane_pattern_map.get(label)
        if not patterns:
            continue
        candidate = list(patterns)
        if matched is not None and matched != candidate:
            return None
        matched = candidate
    return matched


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
    `select_issues_claim_read.check`/`select_issues_preflight.search`/
    `select_issues_overlap.resolve_lane`/`select_issues_companions.suggest_companions` --
    injectable so a caller (or a test)
    never needs a live `gh` session or a real tree to drive this function.

    #1078: an optional top-level `lane_label` narrows candidate GENERATION to
    one GitHub label (a LABEL lane, e.g. `lane-dispatch`) before ranking
    runs; see the guard just above `held_files` below for the full contract.
    Never confuse it with a developer LANE, the worktree/branch sense this
    module uses everywhere else.

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
    checker = select_issues_claim_read.check if checker is None else checker
    search = select_issues_preflight.search if search is None else search
    resolve_lane = (
        select_issues_overlap.resolve_lane if resolve_lane is None else resolve_lane
    )
    suggest_companions = (
        select_issues_companions.suggest_companions
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

    # #1078: an optional top-level `lane_label` narrows candidate GENERATION
    # to issues carrying that one GitHub LABEL (e.g. `lane-dispatch`) before
    # ranking ever runs. This is a LABEL lane -- never to be confused with a
    # developer LANE (a worktree on `fix/N`, what `lane_setup.py` and
    # `held_files` above are about); this module never uses the bare word
    # "lane" for the label, only "lane label". Admission is unchanged: the
    # existing declared-file disjointness sweep (`_group_candidates`, below)
    # still decides which of the label-filtered issues actually ride
    # together in one developer lane -- the label only narrows what gets
    # checked, per #1078's own framing ("a heuristic for legibility, not a
    # guarantee"). Absent or empty, nothing is filtered -- the historical,
    # whole-board behaviour every caller before #1078 still gets.
    lane_label = payload.get("lane_label")
    if lane_label:
        issues = [row for row in issues if lane_label in (row.get("labels") or [])]

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

    # #1013 review round: `select_issues_rank.order()` computes its own stable-sort
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
    ranked = select_issues_rank.order(translated_issues, declared)

    dropped = []
    survivors = []  # (issue_row, rank_answer)
    dark_inputs = []
    # #1068: captured here, once, so grouping (below) never re-resolves a lane
    # pattern it has already paid to resolve -- only survives for a candidate
    # whose lane pattern was neither refused nor resolved-to-nothing, which is
    # exactly the set grouping is safe to use.
    resolved_files_by_number = {}
    # #1129: parallel to `resolved_files_by_number` -- which of a
    # candidate's two possible producers actually supplied its
    # `lane_patterns`, so the result can say so rather than let a measured
    # disjointness and an inferred one render identically. `None` covers
    # both "no lane_patterns at all" and every one of #1129's own unknown
    # cases (no lane label, an uncovered one, no declared mapping, or an
    # ambiguous match across two differently-mapped labels on one issue).
    lane_patterns_source_by_number = {}
    # #1130: independent of `lane_patterns`/`lane_patterns_source` above --
    # a `lane-other` issue has no file set by definition (it is always
    # `None`, same as "no lane label at all"), so this is the one signal
    # that tells "triaged, no lane owns this" apart from "nobody has looked
    # yet" once grouping needs to route the two differently. Read directly
    # off the issue's own `lane-*` label and the repo's declared
    # `labels.lane_other` name -- never derived from `lane_patterns_source`,
    # which cannot carry the distinction (both render `None`).
    is_lane_other_by_number = {}
    lane_other_label = declared.get("lane_other")

    for item in ranked:
        number = item.get("number")
        answer = select_issues_rank.rank(
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
        lane_patterns_source = "declared" if lane_patterns else None
        if not lane_patterns:
            # #1135: prefer a path the issue's OWN title/body names in
            # backticks over its label's whole subsystem -- the same
            # extraction `select_issues_companions._derive_declared_files`
            # already trusts for a companion (#851), now given to the LEAD
            # too. There is no argument for trusting a backtick declaration
            # on one side of an overlap and not the other: a human-written
            # path is a declaration, never the guess #267 forbids. `None`
            # (never `[]`) when the title and body name nothing path-shaped.
            derived_body = select_issues_companions._derive_declared_patterns(
                item.get("title"), item.get("body")
            )
            if derived_body:
                lane_patterns = derived_body
                lane_patterns_source = "derived-from-body"
        if not lane_patterns:
            # #1129: falls back to whatever `_derive_lane_patterns_from_
            # labels` can read off its `lane-*` label through the repo's own
            # declared mapping, only once the issue's own title/body have
            # already been asked and named nothing. `derived` is `None` for
            # every one of #1129's own unknown cases, never `[]`;
            # `lane_patterns`/`lane_patterns_source` are simply left as they
            # were (falsy / `None`) when it is, which is the exact "an issue
            # nobody has looked at that closely yet" posture this module's
            # own docstring already promises for an issue with no
            # `lane_patterns` at all.
            derived_label = _derive_lane_patterns_from_labels(
                item.get("labels"), declared.get("lane_patterns"), lane_other_label
            )
            if derived_label:
                lane_patterns = derived_label
                lane_patterns_source = "derived-from-label"
        is_lane_other_by_number[number] = bool(
            lane_other_label and lane_other_label in (item.get("labels") or [])
        )

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
            if select_issues_overlap._lane_resolved_to_nothing(resolved):
                # #1067: every member was well-formed and checked, but the
                # lane still names zero files on disk (`glob-no-match`, not
                # `refused`) -- `select_issues_overlap.lane_overlap` against an empty
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
                overlap = select_issues_overlap.lane_overlap(
                    resolved["files"], held_files
                )
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
            lane_patterns_source_by_number[number] = lane_patterns_source

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
            if row["state"] == select_issues_claim_read.STATE_COULD_NOT_READ:
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
            if row["state"] == select_issues_claim_read.STATE_ASSIGNED:
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
                    # #1129: `"declared"` (the issue's own `lane_patterns`),
                    # `"derived-from-label"` (#1129's own fallback), or `None`
                    # -- no `lane_patterns` at all, declared or derived. A
                    # reader must never have to guess which producer a
                    # candidate's resolved files came from.
                    "lane_patterns_source": lane_patterns_source_by_number.get(number),
                    # #1130: `True` when the issue carries the repo's
                    # configured `labels.lane_other` label -- a positive,
                    # triaged "no lane owns this", never a guess. Read by
                    # `_group_candidates` to route this candidate to a
                    # deliberate solo group instead of `ungrouped`.
                    "is_lane_other": is_lane_other_by_number.get(number, False),
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


def _reconfigure_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass


def _read_stdin_json():
    """`(payload, error_result)`. `error_result` is `None` on success, else
    the `could-not-select`-shaped dict to print and return for a caller that
    reads JSON off stdin -- the same three checks every stdin-JSON entry
    point in this plugin repeats (`select_issues_rank.py`'s former `main`,
    `lane_setup.py --suggest-companions`, and this module's own default
    mode): no stream at all (#846), can't decode as UTF-8, not valid JSON.
    """
    if sys.stdin is None:
        return None, _could_not_select(
            "stdin: no readable stdin -- the process was handed a closed or "
            "unopenable standard input"
        )
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover - not a TextIOWrapper
        pass
    try:
        return json.load(sys.stdin), None
    except UnicodeDecodeError as exc:
        return None, _could_not_select(
            "stdin: could not be decoded as UTF-8 ({0})".format(exc)
        )
    except ValueError as exc:
        return None, _could_not_select("stdin: not valid JSON ({0})".format(exc))


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Board in, ranked claimable candidates out (#970)."
    )
    parser.add_argument(
        "--board",
        action="store_true",
        help="print the whole-board ranking receipt instead of the JSON "
        "candidates result (#1069, folded in from dispatch_rank.py's own "
        "CLI) -- reads the same board shape on stdin.",
    )
    parser.add_argument(
        "--check-lane",
        type=int,
        nargs="*",
        default=None,
        metavar="N",
        help="check a dispatched lane's own size instead of selecting from "
        "a board (#1069, folded in from dispatch_rank.py --lane) -- these "
        "issue numbers, never read from stdin.",
    )
    parser.add_argument(
        "--short-reason", default=None, choices=select_issues_rank.SHORT_REASONS
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=None,
        metavar="N",
        help="file-disjoint candidates still open on the board, for --check-lane",
    )
    parser.add_argument(
        "--adjacent",
        type=int,
        default=None,
        metavar="N",
        help="candidates adjacent to the lane's top issue, for --check-lane",
    )
    parser.add_argument(
        "--preflight",
        default=None,
        metavar="PATTERN",
        help="pre-flight code check instead of selecting from a board "
        "(#1069, folded in from preflight_check.py) -- a regular expression "
        "naming the code path or contract to check.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        dest="paths",
        metavar="FILE_OR_DIR",
        help="for --preflight: a file or directory to search. Repeatable; "
        "defaults to the current directory.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="for --preflight: JSON indent (0 for compact).",
    )
    return parser


def main(argv=None):
    """Read the board (and the rest of `select`'s payload) as JSON on stdin,
    print the result as JSON, and exit 0 (candidates), 1 (none-available) or
    2 (could-not-select) -- the default mode, and the only one this module
    had before #1069.

    #846's own class, guarded here from the start rather than added after
    the fact: `sys.stdin` is `None` when the harness hands this process a
    closed or unopenable standard input, and `json.load(None)` raises
    `AttributeError` uncaught -- past this module's own `could-not-select`,
    which is exactly the state that exists for a read that failed.

    `--board`, `--check-lane` and `--preflight` (#1069) are the whole-board
    ranking receipt, the dispatched-lane-size check and the pre-flight code
    probe folded in from `dispatch_rank.py` and `preflight_check.py`'s own
    former CLIs -- see the module docstring's "No longer a standalone CLI"
    note on each of `select_issues_rank.py`/`select_issues_preflight.py`.
    Each is a separate mode from the default and from each other.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    _reconfigure_streams()

    if args.check_lane is not None:
        answer = select_issues_rank.check_lane(
            args.check_lane,
            args.short_reason,
            candidates=args.candidates,
            adjacent=args.adjacent,
        )
        print(
            "{0}: {1} issue(s){2}".format(
                answer["state"].upper(),
                answer["size"],
                "" if not answer["why"] else " -- " + answer["why"],
            )
        )
        return 0 if answer["state"] == "ok" else 2

    if args.preflight is not None:
        roots = [Path(p) for p in args.paths] if args.paths else [Path(".")]
        result = select_issues_preflight.search(args.preflight, roots)
        indent = args.indent if args.indent > 0 else None
        print(json.dumps(result, indent=indent, sort_keys=True))
        return (
            2
            if result["state"] == select_issues_preflight.STATE_COULD_NOT_SEARCH
            else 0
        )

    if args.board:
        payload, error_result = _read_stdin_json()
        if error_result is not None:
            print(json.dumps(error_result, indent=2, sort_keys=True))
            return 2
        declared = payload.get("declared") or {}
        issues = payload.get("issues") or []
        print(select_issues_rank.render_board_receipt(issues, declared))
        return 0

    # #970 review round: the sibling idiom used by select_issues_rank.py,
    # lane_setup.py, select_issues_claim_read.py and others (#794, #834) -- a
    # candidate's `why` can carry an issue's own label or title text (via
    # `select_issues_rank.rank`'s `repr(unrecognised)`), and a console codepage
    # that cannot encode one of them must not crash this print after the
    # selection was already computed. Already handled above by
    # `_reconfigure_streams()`, called once at the top of this function
    # regardless of which mode runs.
    payload, error_result = _read_stdin_json()
    if error_result is not None:
        print(json.dumps(error_result, indent=2, sort_keys=True))
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
