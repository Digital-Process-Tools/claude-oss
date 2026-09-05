"""The dispatch order (#798, extended by #993) and the lane size bound (#799),
computed rather than felt.

Selection used to be priority-only. On a tracker where the loop files most of
the issues, that means a maintainer's ask waits behind the loop's own backlog:
measured on claude-oss, 476 issues in 20 days, 98% filed by the loop including
those under a human account. #798's fix added an author axis, but "human"
covered two different populations -- the maintainer, and an outside reporter
who hit a real defect -- and they ranked identically. An untriaged external
report is unlabelled by definition (nobody has triaged it yet), so it sank to
the bottom of its band exactly when its evidence was scarcest (#993).

The order now has three author values in strength order, not two:

    rank  author      priority
    ----  ----------  --------
    2     external    high
    3     maintainer  high
    4     loop        high
    5     external    medium
    6     maintainer  medium
    7     loop        medium
    8     external    low, or no priority label
    9     maintainer  low, or no priority label
    10    loop        low, or no priority label

**Rank 1 -- "any author, a blocking-class row in the findings table" -- is
prose, not a computed row**, and `rank()` never returns it. Nothing here can
read a GitHub issue against the eleven-row findings table in
`skills/manager/phases/findings.md`; that classification is a judgment call
made when a finding is written up, not a fact derivable from an issue's
labels. A caller applying this table checks the blocking-class exception
before consulting it, the same way rank 2 of the old six-row table encoded it
implicitly (#993's own text: "whether it stays a row or stays prose is an
implementation call").

**Rank 5's second clause in #993's own proposal -- "or a bug with no priority
label" -- is deferred.** It needs a `labels.defect` (or `labels.type`) key
`.oss.json` does not declare yet, the identical undeclared-axis shape #990
fixes for `labels.filed_by_loop`'s own rot; #993 asks for the two to land
together or in that order rather than reproducing the failure a second time.
Until that key exists, an untriaged external bug ranks by priority alone,
same as any other unprioritised external issue (rank 8).

**"Loop" still means carrying the label `labels.filed_by_loop` names**, exactly
as #798 defined it, and still refuses to rank at all when the repository
declares no such label -- because on a board where every issue is unlabelled,
reading them all as non-loop would rank the loop's whole backlog into every
other row confidently and wrongly. An issue the loop files is filed under the
maintainer's own GitHub account, so GitHub's author association can never
tell "loop" from "maintainer" apart the way this label can -- the label is
checked first, and settles the author axis on its own for a loop-filed issue.

**"External" and "maintainer" are read from GitHub's own author association**
on the issue -- `OWNER`/`MEMBER`/`COLLABORATOR` versus `CONTRIBUTOR`/`NONE` --
never from a declared label: there is no opt-in step here for a label to
forget the way `filed_by_loop` can rot. **This module never reads GitHub's
raw field itself** -- that reasoning, and the exact set of recognised
spellings, lives one call earlier, in `select_issues.py`'s own
`_translate_author_association` (#1013), which is where a repository's real
`gh api` payload actually gets translated before it ever reaches `rank()`.
It still needs a third state: an association that could not be read must not
render as "external" and must not render as "maintainer" either -- the same
"never render as the lowest-cost guess" discipline this module already
applies to an undeclared `filed_by_loop`. `rank()`'s `association` parameter
carries that state explicitly: pass `"external"` or `"maintainer"` for an
already-translated value, or leave it `None` (or anything else) for "could
not tell", which refuses to rank a non-loop issue rather than guessing which
of the two it is.

Nothing in this module can check that a caller actually measured the
association before passing it. What it can do, and does, is refuse to rank a
non-loop issue at all when no recognised value was given -- because guessing
"maintainer" quietly buries an outside reporter's own evidence, and guessing
"external" quietly promotes a stranger's ask above the maintainer's, both
silently, from a caller that simply never wired the read up. That is this
repository's own defect class again: a check that never ran rendering as a
check that found nothing. So the author axis being unavailable is a state,
not a default.

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
#: inverts it rather than restating it, so the two cannot disagree. Numbering
#: starts at 2 on purpose: rank 1 is the prose-only "blocking-class" row the
#: module docstring describes, and this module never computes it.
ROWS = (
    (2, ("external", "high")),
    (3, ("maintainer", "high")),
    (4, ("loop", "high")),
    (5, ("external", "medium")),
    (6, ("maintainer", "medium")),
    (7, ("loop", "medium")),
    (8, ("external", "low")),
    (9, ("maintainer", "low")),
    (10, ("loop", "low")),
)

_BY_PAIR = {pair: number for number, pair in ROWS}

#: `order()`'s sort key for an issue that could not be ranked -- strictly
#: above the *highest real rank*, not `len(ROWS) + 1`. Those used to be the
#: same number when `ROWS` was numbered `1..len(ROWS)`; #993 renumbered it to
#: start at 2 (rank 1 is the prose-only row this module never computes), so
#: `len(ROWS) + 1 == 10` collided with the real `loop`/`low` rank and an
#: unrankable issue silently sorted ahead of it whenever it happened to
#: appear earlier in the caller's input list (found by review, #993). Deriving
#: this from the rows themselves means a future row added or renumbered can
#: never quietly reintroduce the same collision.
_UNRANKABLE_KEY = max(number for number, _ in ROWS) + 1

#: The two GitHub author-association readings `rank()` recognises for a
#: non-loop issue. Anything else -- `None`, an empty string, a typo -- means
#: "could not tell" and refuses to rank rather than guessing between them.
ASSOCIATIONS = ("external", "maintainer")

#: Bands in strength order. A priority list shorter or longer than this is
#: still usable -- the first entry is the strongest -- but only these three
#: names are ever produced, because they are what the table above is written in.
BANDS = ("high", "medium", "low")

#: The four reasons a lane may be short (#799, #918). A closed set on purpose: a
#: free-text reason is unreadable by anything but a person, which is the defect
#: #773 filed against a handback state carrying only prose.
#:
#: `did-not-search` is #918's addition and it is the third state this set was
#: missing. `no-adjacent` asserts the board was measured and found to hold
#: nothing adjacent; `could-not-tell` is an adjacency computation that was
#: attempted and failed. Neither covers a computation nobody started -- and that
#: is what actually happened when one tick dispatched three single-issue lanes
#: with 31 issues open, having run `lane_setup.py --against` only between the
#: three lanes it had already picked. That is the conflict check, not the
#: companion search, and reading `no overlap` from it as `no-adjacent` is a
#: claim about a board nothing looked at.
SHORT_REASONS = (
    "board-exhausted",
    "no-adjacent",
    "did-not-search",
    "could-not-tell",
)

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


def _plausible_priority_typo(label, prefix, priority_spellings):
    """Does `label` look like a typo or rename of a *declared* priority
    spelling, rather than merely starting with the same one or two
    characters as every declared spelling happens to (#838)?

    A short shared prefix over-matches. With spellings `p1`/`p2`/`p3` the
    commonprefix is a single character, `'p'` -- so an unrelated label like
    `python` shares it and `_band` would report it as a mistyped priority.
    There is no fixed floor on prefix length that is right for every repo: a
    floor long enough to exclude `python` would also exclude a genuine
    one-letter-spelling repo's real typos, and a repo's spellings are never
    known in advance -- the whole reason this module reads them from
    `.oss.json` rather than hardcoding `priority-high` (see the module
    docstring).

    What is derived instead is a plausible *suffix length*, from the
    declared spellings themselves -- and it is compared against the
    *nearest* declared spelling's own suffix, not the longest one. An
    earlier version of this function compared against the single longest
    suffix among all declared spellings, which reintroduces #838's own
    over-match the moment the declared spellings vary in length: with
    `p1` (suffix length 1) declared alongside a long spelling (suffix
    length 38), the long spelling's suffix set the floor and let `python`
    (suffix length 5, past `'p'`) back in, exactly the false positive this
    function exists to refuse. Matching against the *nearest* suffix length
    instead means a candidate is only judged against the declared spelling
    it most resembles in length, so one long spelling can no longer vouch
    for an implausible match to a short one.

    The floor of `1` handles the other edge that version missed: a
    repository declaring exactly one priority spelling has a prefix equal
    to that whole spelling, so its own suffix length is `0` -- and a
    zero-length floor can never be exceeded by any real candidate (every
    candidate that reaches this function already has a non-empty suffix,
    by construction), which silently disabled typo detection entirely for
    a single-spelling repository. `max(nearest, 1)` keeps a `'urgentx'`
    close enough to `'urgent'` to be flagged, while a wildly longer
    `'urgentlyneeded'` still is not.

    `'critical'` (8 characters past `'priority-'`) lands nearest `'medium'`
    (6 characters past it) among `high`/`medium`/`low`, and 8 is within
    double of 6 -- a plausible typo. `'ython'` (5 characters past `'p'`)
    lands nearest `'1'`/`'2'`/`'3'` (1 character past it), and 5 is not
    within double of 1 -- not plausible, regardless of what else is
    declared alongside those short spellings. The factor of two is
    generous on purpose: a typo or rename should stay in the same ballpark
    as what it replaces, not merely shorter than infinity.
    """
    candidate_suffix = len(label) - len(prefix)
    suffix_lengths = [len(s) - len(prefix) for s in priority_spellings]
    nearest = min(suffix_lengths, key=lambda n: abs(n - candidate_suffix))
    return candidate_suffix <= 2 * max(nearest, 1)


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
            if label.startswith(prefix)
            and label not in priority_spellings
            and _plausible_priority_typo(label, prefix, priority_spellings)
        )
        if unrecognised:
            return "low", unrecognised[0]
    return "low", None


def rank(labels, declared, association=None):
    """Where one issue sits in the dispatch order.

    `labels` is the issue's label names. `declared` is the repository's own
    `labels` block from `.oss.json` -- read, never assumed, because one repo
    spells it `priority-high` and a sibling spells it `priority:high`.
    `association` is the issue's GitHub author association, read as this
    module's own two-value vocabulary (`"external"` or `"maintainer"`, see
    `ASSOCIATIONS`) or left `None` for "could not tell" -- consulted only
    when the issue does not carry the loop's own label, because a loop-filed
    issue's author axis is already settled by `labels.filed_by_loop` (see the
    module docstring).

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
                "issue as external or maintainer would rank the loop's whole "
                "backlog above the maintainer's own asks"
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
    if loop_label in set(labels):
        author = "loop"
    elif association in ASSOCIATIONS:
        author = association
    else:
        return {
            "state": "could-not-rank",
            "rank": None,
            "author": None,
            "band": None,
            "why": (
                "GitHub's author association could not be read (got {!r}) for "
                "an issue not carrying labels.filed_by_loop's label -- "
                "treating it as external or as maintainer would guess who "
                "filed it, the same discipline this module already applies "
                "to an undeclared axis".format(association)
            ),
        }
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


def reserved(labels, declared):
    """Is this issue reserved by the maintainer (#844) -- a fourth fact
    dispatch selection cannot read off assignees alone.

    A contributor without write access cannot self-assign (GitHub restricts
    assignment to write/triage permission), so an empty assignee field on a
    public repository means only "no maintainer lane holds this" -- not "the
    maintainer is willing to have it taken". A reservation the maintainer
    made off the tracker -- in a session handoff, from memory -- is
    structurally invisible to a sub-manager spawned fresh into the
    repository with nothing (#695): it can only read what is on the tracker.

    `declared` is the repo's own `labels` block; `labels.reserved` is an
    optional label name, the same opt-in shape `labels.filed_by_loop`
    already is (#762) -- derivable from the tracker by anyone, rather than
    recalled from a handoff nothing later can see. A repository that has not
    declared a spelling is read as never reserving anything, not as a third
    state the way author/priority are: there is no ambiguity to report when
    no candidate spelling was ever named, only an opt-in nobody took yet.
    """
    spelling = (declared or {}).get("reserved")
    if not spelling or not isinstance(spelling, str):
        return False
    return spelling in set(labels or [])


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
        answer = rank(
            item.get("labels") or [], declared, item.get("author_association")
        )
        return answer["rank"] if answer["rank"] is not None else _UNRANKABLE_KEY

    return sorted(issues, key=key)


def check_lane(issues, short_reason, candidates=None, adjacent=None):
    """Is this a lane that may be dispatched, and has a short one said why?

    Three issues is the normal case, not the ceiling: the fixed overhead of a
    lane -- a turn-1 baseline, orientation, two self-review spawns, a full suite
    run -- is paid once regardless of how much the lane carries.

    A lane of four or more is refused before the spawn, which is where #799 asks
    for it: past the spawn the cost is already committed. A lane of zero is
    refused too, and deliberately not called short -- naming it short would
    invite a reason for something that should never have been dispatched at all.

    `candidates` (#871) is the number of file-disjoint candidate issues the
    caller found still open on the board -- `lane_setup.py`'s own
    `resolve_lane`/`lane_overlap`, run across every other open, dispatchable
    issue, never something this function derives on its own (an issue's files
    are not derivable from its body, #267, so naming candidate lanes stays the
    caller's job). Every refusal on this path used to check the reason's
    *shape* only -- one of the three declared words -- and never whether it was
    *true*: a lane could write `board-exhausted` with 35 issues open and satisfy
    every gate, because a lane that was correctly short and one that was lazily
    short render identically. When `short_reason` is `'board-exhausted'` and
    `candidates` is given, the claim is checked against it: at or above
    `MAX_LANE` candidates, the board plainly was not exhausted, and the reason
    is refused rather than recorded. `candidates=None` (the default) leaves this
    exactly as it was before #871 -- the caller named no board to check against,
    which is a fact for the caller's own receipt to carry, not something this
    function should guess at. `could-not-tell` stays untouched by both counts: a
    count says nothing about a probe that failed to run.

    `adjacent` (#918) is the same idea aimed at the reason #871 deliberately left
    alone, and it is a *different* count, not the same one reused -- the number of
    open candidates sharing a file or module with this lane's top issue, which is
    what `no-adjacent` is a claim about. Its threshold is stricter than
    `candidates`': `board-exhausted` is refuted by `MAX_LANE` disjoint candidates,
    but `no-adjacent` means *zero*, so a single adjacent candidate refutes it --
    one adjacent candidate is one issue this lane could have carried. Like
    `candidates`, it is the caller's measurement: an issue's files are not
    derivable from its body (#267), so naming candidate lanes stays the caller's
    job and `adjacent=None` means "no board was named", never "the board was
    empty". A caller that never ran the search has no count to offer and should
    declare `did-not-search` rather than borrow a word that asserts it did.
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
    if (
        short_reason == "board-exhausted"
        and candidates is not None
        and candidates >= MAX_LANE
    ):
        return {
            "state": "board-not-exhausted",
            "size": size,
            "short_reason": None,
            "why": (
                "board-exhausted was claimed but {} file-disjoint candidate(s) "
                "remain on the board -- at or above the {}-issue lane size, so "
                "the board was not exhausted (#871)".format(candidates, MAX_LANE)
            ),
        }
    if short_reason == "no-adjacent" and adjacent is not None and adjacent >= 1:
        return {
            "state": "adjacent-candidate-exists",
            "size": size,
            "short_reason": None,
            "why": (
                "no-adjacent was claimed but {} adjacent candidate(s) remain on "
                "the board -- the word means zero, so one refutes it, and one "
                "adjacent candidate is one issue this lane could have carried "
                "(#918)".format(adjacent)
            ),
        }
    return {"state": "ok", "size": size, "short_reason": short_reason, "why": None}


def main(argv=None):
    """Rank a board handed in on stdin as JSON.

    Input is `{"declared": {...}, "issues": [{"number": N, "labels": [...],
    "author_association": "external"|"maintainer"|null}]}`. The
    `author_association` field is optional per issue and is only consulted
    for a non-loop issue; an issue omitting it, or carrying anything outside
    `ASSOCIATIONS`, could not have its author association read. Prints one
    line per issue, best first.
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
    parser.add_argument(
        "--candidates",
        type=int,
        default=None,
        metavar="N",
        help="file-disjoint candidates found still open on the board (#871) -- "
        "checked against a 'board-exhausted' --short-reason; omit when the "
        "board was not measured",
    )
    args = parser.parse_args(argv)

    # The sibling idiom used by lane_setup.py, tree_snapshot.py, ranking_table.py,
    # checklist_skew.py, release_delta.py, release_version.py, scaffold.py and
    # rename_changelog_fragment.py (#794, #834): a receipt line can carry an
    # arbitrary issue label or title, and a console codepage that cannot encode
    # one of them must not crash this print -- a UnicodeEncodeError here used to
    # exit 1 after the ranking was already computed, indistinguishable from a
    # genuine refusal.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    if args.lane is not None:
        answer = check_lane(args.lane, args.short_reason, candidates=args.candidates)
        print(
            "{}: {} issue(s){}".format(
                answer["state"].upper(),
                answer["size"],
                "" if not answer["why"] else " -- " + answer["why"],
            )
        )
        return 0 if answer["state"] == "ok" else 2

    # JSON is UTF-8 by spec (RFC 8259); decoding stdin with whatever the
    # console's codepage happens to be is itself the bug, not a fact to route
    # around -- on a cp1252 console it fails to decode a perfectly valid UTF-8
    # payload the moment a label or title carries a non-ASCII character.
    # Forcing UTF-8 here makes the tool accept what it is documented to
    # accept, on every platform, rather than merely explaining a decode
    # failure caused by reading it wrong in the first place.
    # #846: `sys.stdin` is `None` when the harness hands the process a closed
    # or unopenable standard input, so `.reconfigure` raises `AttributeError`
    # before the `except (AttributeError, ValueError): pass` below can help --
    # that guard was written for a *stream* that refuses to reconfigure, not
    # for the absence of a stream. Past that, `json.load(None)` would raise
    # `AttributeError` uncaught, exiting 1 with none of this module's own
    # states. Check for `None` first and answer `COULD NOT READ`, the state
    # that already exists for exactly this (#405's fix, same class).
    if sys.stdin is None:
        print(
            "COULD NOT READ: stdin is not JSON (no readable stdin: the "
            "process was handed a closed or unopenable standard input)"
        )
        return 2

    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover - not a TextIOWrapper
        pass

    try:
        payload = json.load(sys.stdin)
    except UnicodeDecodeError as err:
        # UnicodeDecodeError is a ValueError, not a JSON-syntax error -- caught
        # separately so this never renders as "stdin is not JSON" when stdin
        # was JSON and simply could not be decoded (#834).
        print("COULD NOT READ: stdin could not be decoded as UTF-8 ({})".format(err))
        return 2
    except ValueError as err:
        print("COULD NOT READ: stdin is not JSON ({})".format(err))
        return 2
    declared = payload.get("declared") or {}
    issues = payload.get("issues") or []
    ranked = order(issues, declared)
    unrankable = 0
    reserved_count = 0
    reserved_spelling = declared.get("reserved")
    reserved_declared = bool(reserved_spelling) and isinstance(reserved_spelling, str)
    for item in ranked:
        answer = rank(
            item.get("labels") or [], declared, item.get("author_association")
        )
        is_reserved = reserved(item.get("labels") or [], declared)
        if is_reserved:
            reserved_count += 1
        # #844: a reservation is a fourth fact selection cannot read off
        # assignees alone -- printed on every row, ranked or not, because an
        # unrankable issue can be reserved too and dropping the marker there
        # would silently let it back onto a candidate list.
        marker = "  [RESERVED]" if is_reserved else ""
        if answer["rank"] is None:
            unrankable += 1
            print(
                "  ?  #{}  could not rank -- {}{}".format(
                    item.get("number"), answer["why"], marker
                )
            )
        else:
            # `why` is non-None on a *ranked* issue only for #826's
            # unrecognised-priority case. Dropping it here would compute the
            # one signal #826 exists to surface and then render it
            # identically to silence -- which is the whole defect, moved one
            # layer out into the receipt a maintainer actually reads.
            print(
                "  {}  #{}  {} / {}{}{}".format(
                    answer["rank"],
                    item.get("number"),
                    answer["author"],
                    answer["band"],
                    "" if not answer["why"] else "  -- " + answer["why"],
                    marker,
                )
            )
    print(
        "{} issue(s), {} unrankable, {}".format(
            len(ranked),
            unrankable,
            "{} reserved".format(reserved_count)
            if reserved_declared
            else "labels.reserved is not declared, so reservation cannot be "
            "read off the board",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
