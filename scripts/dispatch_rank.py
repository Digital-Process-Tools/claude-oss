"""The dispatch order (#798) and the lane size bound (#799), computed rather
than felt.

Selection used to be priority-only. On a tracker where the loop files most of
the issues, that means a maintainer's ask waits behind the loop's own backlog:
measured on claude-oss, 476 issues in 20 days, 98% filed by the loop including
those under a human account. The order below puts a human ask ahead of loop work
of the same or lower band, without letting an ordinary ask jump a blocking-class
defect.

    rank  author  priority
    ----  ------  --------
    1     human   high
    2     loop    high
    3     human   medium
    4     human   low, or no priority label
    5     loop    medium
    6     loop    low, or no priority label

**"Loop" means carrying the label `labels.filed_by_loop` names. An issue without
it is a human issue** -- and that default is only sound on a board where the
label has actually been applied. The label's own description says "absence is not
proof a human filed it", which is exactly right: absence means *nobody labelled
it* until somebody labels everything. On 2026-09-02 the maintainer closed that by
labelling every open issue and pruning the ones that were theirs, which turns an
absence into a positive act.

Nothing in this module can check that was done. What it can do, and does, is
refuse to rank at all when the repository declares no such label -- because on
that board every issue is unlabelled, and reading them all as human issues would
rank the loop's whole backlog into rows 1, 3 and 4 confidently and wrongly. That
is this repository's own defect class: a check that never ran rendering as a
check that found nothing. So the author axis being unavailable is a state, not a
default.

The same refusal applies one axis over. A repository that declares no priority
spellings has no bands, and inventing `priority-high` for it would be a fact
about one repository living in shared code -- forbidden here for the reason
`CLAUDE.md` gives at length.

Python 3.9 compatible.
"""

import argparse
import json
import os
import sys


#: rank -> (author, band). The single source for the table above; `rank()`
#: inverts it rather than restating it, so the two cannot disagree.
ROWS = (
    (1, ("human", "high")),
    (2, ("loop", "high")),
    (3, ("human", "medium")),
    (4, ("human", "low")),
    (5, ("loop", "medium")),
    (6, ("loop", "low")),
)

_BY_PAIR = {pair: number for number, pair in ROWS}

#: Bands in strength order. A priority list shorter or longer than this is
#: still usable -- the first entry is the strongest -- but only these three
#: names are ever produced, because they are what the table above is written in.
BANDS = ("high", "medium", "low")

#: The three reasons a lane may be short (#799). A closed set on purpose: a
#: free-text reason is unreadable by anything but a person, which is the defect
#: #773 filed against a handback state carrying only prose.
SHORT_REASONS = ("board-exhausted", "no-adjacent", "could-not-tell")

#: Measured across 237 lanes (#499): three issues cost 16% less per issue than
#: one, and four or more is a cliff at 141 median turns and 68% worse per issue.
MAX_LANE = 3


def _priority_prefix(priority_spellings):
    """The longest string every declared priority spelling starts with --
    `priority-high`, `priority-medium`, `priority-low` share `priority-`.

    This is the only signal this module has for "looks like it was meant to
    be a priority label but is not one of the declared ones": there is no
    generic way to tell a priority label from an unrelated one by name alone,
    and inventing one would be the hardcoded-fact failure `rank()` already
    refuses one axis over. Returns `''` when the declared spellings share
    nothing -- `priority-high` and `urgent` share no prefix -- and an empty
    prefix means no label can ever be read as an unrecognised priority, on
    purpose: guessing from no signal is worse than reporting none.
    """
    return os.path.commonprefix(list(priority_spellings))


def _band(labels, priority_spellings):
    """Which band these labels sit in, strongest first, and the unrecognised
    priority-shaped label if one was found -- `(band, unrecognised)`.

    An issue carrying two priority labels takes the stronger. That is a real
    state rather than a hypothetical: a triage sweep and a second writer both
    wrote a priority onto one issue within the same window on 2026-09-02. Taking
    the stronger is the safe direction -- the alternative lets an issue sink
    because somebody added a weaker label beside its real one.

    No priority label at all is `low`, per the table's rows 4 and 6, never a
    band of its own and never `medium` -- and `unrecognised` is `None`, because
    there is nothing to name (#826).

    A label that shares the declared spellings' own prefix but matches none of
    them exactly -- a typo, a rename the repo's `.oss.json` was never updated
    for -- is a different fact from carrying no priority label at all, even
    though both fall into the same `low` band for ordering purposes: the
    issue is still rankable on the author axis, so refusing to rank it would
    be the trap #826 names explicitly. `unrecognised` names the one spelling
    found, so a caller can tell a typo from silence without re-deriving
    anything.
    """
    present = set(labels)
    for index, spelling in enumerate(priority_spellings):
        if spelling in present:
            return (BANDS[index] if index < len(BANDS) else BANDS[-1]), None
    prefix = _priority_prefix(priority_spellings)
    if prefix:
        unrecognised = sorted(
            label
            for label in present
            if label.startswith(prefix) and label not in priority_spellings
        )
        if unrecognised:
            return "low", unrecognised[0]
    return "low", None


def rank(labels, declared):
    """Where one issue sits in the dispatch order.

    `labels` is the issue's label names. `declared` is the repository's own
    `labels` block from `.oss.json` -- read, never assumed, because one repo
    spells it `priority-high` and a sibling spells it `priority:high`.

    Returns `state` `ranked` with `rank`, `author` and `band`, or
    `could-not-rank` with `why` and a `rank` of `None`. The receipt names both
    axes so a dispatch decision can be checked without re-deriving the table.
    """
    loop_label = (declared or {}).get("filed_by_loop")
    priority = (declared or {}).get("priority")
    if not loop_label or not isinstance(loop_label, str):
        return {
            "state": "could-not-rank",
            "rank": None,
            "author": None,
            "band": None,
            "why": (
                "labels.filed_by_loop is not declared, so who filed an issue "
                "cannot be read off the board -- and treating every unlabelled "
                "issue as a human one would rank the loop's whole backlog above "
                "the maintainer's asks"
            ),
        }
    if not priority or not isinstance(priority, (list, tuple)):
        return {
            "state": "could-not-rank",
            "rank": None,
            "author": None,
            "band": None,
            "why": (
                "labels.priority is not declared, so there are no bands to rank "
                "within and this module will not invent spellings for them"
            ),
        }
    author = "loop" if loop_label in set(labels) else "human"
    band, unrecognised = _band(labels, priority)
    why = None
    if unrecognised is not None:
        why = (
            "{!r} looks like a priority label but matches none of the "
            "declared spellings ({}) -- ranked as {} so the issue still "
            "dispatches, but the priority read is unreliable and the label "
            "should be checked for a typo or a rename".format(
                unrecognised, ", ".join(priority), band
            )
        )
    return {
        "state": "ranked",
        "rank": _BY_PAIR[(author, band)],
        "author": author,
        "band": band,
        "why": why,
    }


def order(issues, declared):
    """The issues, best first, stable within a rank.

    Stability is load-bearing rather than incidental: a caller that pre-sorted
    by age or issue number keeps that ordering inside each band, so the rank
    decides between bands and the caller's own sort decides within one.

    An issue that could not be ranked sorts last rather than first. It is not
    evidence of low value -- it is the absence of a reading -- and putting it
    at the front would let a configuration gap silently promote work.
    """
    def key(item):
        answer = rank(item.get("labels") or [], declared)
        return answer["rank"] if answer["rank"] is not None else len(ROWS) + 1

    return sorted(issues, key=key)


def check_lane(issues, short_reason):
    """Is this a lane that may be dispatched, and has a short one said why?

    Three issues is the normal case, not the ceiling: the fixed overhead of a
    lane -- a turn-1 baseline, orientation, two self-review spawns, a full suite
    run -- is paid once regardless of how much the lane carries.

    A lane of four or more is refused before the spawn, which is where #799 asks
    for it: past the spawn the cost is already committed. A lane of zero is
    refused too, and deliberately not called short -- naming it short would
    invite a reason for something that should never have been dispatched at all.
    """
    size = len(issues)
    if size == 0:
        return {
            "state": "refused",
            "size": 0,
            "short_reason": None,
            "why": "a lane with no issues is not a short lane, it is not a lane",
        }
    if size > MAX_LANE:
        return {
            "state": "refused",
            "size": size,
            "short_reason": None,
            "why": (
                "{} issues in one lane, over the cap of {} -- four or more is a "
                "measured cliff at 141 median turns and 68% worse per issue "
                "(#499), not a preference".format(size, MAX_LANE)
            ),
        }
    if size == MAX_LANE:
        return {"state": "ok", "size": size, "short_reason": None, "why": None}
    if short_reason not in SHORT_REASONS:
        return {
            "state": "short-unexplained",
            "size": size,
            "short_reason": None,
            "why": (
                "a lane of {} needs one of {} -- a short lane with no reason is "
                "a defect in the tick, and a free-text reason is unreadable by "
                "anything but a person".format(size, ", ".join(SHORT_REASONS))
            ),
        }
    return {"state": "ok", "size": size, "short_reason": short_reason, "why": None}


def main(argv=None):
    """Rank a board handed in on stdin as JSON.

    Input is `{"declared": {...}, "issues": [{"number": N, "labels": [...]}]}`,
    which is the shape `gh-issues` already produces once the labels are pulled
    out. Prints one line per issue, best first.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--lane",
        metavar="N",
        type=int,
        nargs="*",
        help="check a lane of these issue numbers instead of ranking a board",
    )
    parser.add_argument("--short-reason", default=None, choices=SHORT_REASONS)
    args = parser.parse_args(argv)

    if args.lane is not None:
        answer = check_lane(args.lane, args.short_reason)
        print("{}: {} issue(s){}".format(
            answer["state"].upper(),
            answer["size"],
            "" if not answer["why"] else " -- " + answer["why"],
        ))
        return 0 if answer["state"] == "ok" else 2

    try:
        payload = json.load(sys.stdin)
    except ValueError as err:
        print("COULD NOT READ: stdin is not JSON ({})".format(err))
        return 2
    declared = payload.get("declared") or {}
    issues = payload.get("issues") or []
    ranked = order(issues, declared)
    unrankable = 0
    for item in ranked:
        answer = rank(item.get("labels") or [], declared)
        if answer["rank"] is None:
            unrankable += 1
            print("  ?  #{}  could not rank -- {}".format(
                item.get("number"), answer["why"]))
        else:
            # `why` is non-None on a *ranked* issue only for #826's
            # unrecognised-priority case. Dropping it here would compute the
            # one signal #826 exists to surface and then render it
            # identically to silence -- which is the whole defect, moved one
            # layer out into the receipt a maintainer actually reads.
            print("  {}  #{}  {} / {}{}".format(
                answer["rank"], item.get("number"),
                answer["author"], answer["band"],
                "" if not answer["why"] else "  -- " + answer["why"]))
    print("{} issue(s), {} unrankable".format(len(ranked), unrankable))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
