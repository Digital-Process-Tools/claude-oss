#!/usr/bin/env python3
"""Classifying what arrived from outside the loop -- #1394.

The loop is complete for work it generates itself and had no path at all for
work that arrives from someone else: an issue nobody filed on our behalf, a
pull request from an outside contributor, a comment on either. `CLAUDE.md`
already makes refusal doctrine -- "a correct, reproducible, well-written
issue is refused when it does not move toward the goal, closed with the
reason stated" -- but nothing computed which set of reasons that statement
was even allowed to draw from, so "declined" had no way to mean anything
more specific than "no".

**This module classifies. It does not act.** Closing an issue, merging an
external pull request and replying to a comment are all public acts taken in
the maintainer's name from an unattended loop -- a different question from
reading what arrived and deciding what it deserves, which #1394 states is
complete on its own. #1395 covers the queue those acts go through. Every
function here may legitimately end in "surface to the maintainer", and that
is not a degraded answer -- the issue says so explicitly.

**No new forge call.** Every input here is data the tick already holds by
the time it reaches this module: `is_inbound_issue` reads the same
`labels`/`declared` pair `select_issues_rank.rank` already reads for its own
author axis; `classify_pr` reads the same `author_association`/CI/mergeable
fields a board read already carries; `comments_needing_answer` reads
whatever comment list an earlier op already fetched (a per-issue
`gh-issue:N:full`, or a pull request's own thread) rather than fetching one
of its own.

## The closed set of refusal reasons

`CLAUDE.md`'s own doctrine is what this set operationalises: "closed with
the reason stated, not left open as a debt nobody intends to pay". A
refusal outside this set is not a stronger claim than one inside it --
it is an unstated one, which is exactly the shape this repository refuses
everywhere else (an absence rendered as a verdict).

  duplicate         -- an open or closed issue already covers this
  out-of-scope      -- does not move toward the goal CLAUDE.md states
  not-reproducible  -- the described behaviour could not be reproduced
  needs-info        -- not enough to act on; asked and not yet answered
  wontfix           -- understood, reproducible, and declined on the merits
  superseded        -- a later issue or a shipped change already covers it

Six reasons, not a taxonomy to grow casually -- a reason not in this list is
a call for `/oss:curate` or a maintainer decision about the list itself,
never a string typed past the check.
"""

import argparse
import sys

#: See the module docstring's own table for what each one means. A frozenset
#: rather than a list: membership is all this module ever asks of it, and a
#: set makes "is this one of the six" a single lookup rather than a scan.
REFUSAL_REASONS = frozenset(
    (
        "duplicate",
        "out-of-scope",
        "not-reproducible",
        "needs-info",
        "wontfix",
        "superseded",
    )
)

#: The three outcomes `classify_pr` can hand back for a pull request it
#: judges to be inbound at all. `not-inbound` is not in this tuple on
#: purpose -- it is what `classify_pr` returns for a PR that is not this
#: module's subject at all (see its own docstring), and folding it into the
#: same tuple as the three real outcomes would let a caller iterate "every
#: state a PR can hold" and silently include a state that means "skip this
#: one".
PR_OUTCOMES = ("green-and-mergeable", "needs-answer", "could-not-tell")

#: GitHub's own `author_association` vocabulary, translated. Not imported
#: from `select_issues.py`: that module is the one place a raw `gh api`
#: payload gets read, and it is reasonable for a caller here to have
#: already translated the field for `select_issues_rank.rank` before this
#: module ever sees it (the same "accept an already-translated value
#: unchanged" shape `select_issues.py`'s own `_translate_author_association`
#: documents for itself). Importing it instead would make this module's
#: behaviour depend on `select_issues.py`'s own import side effects for a
#: two-line, easily-duplicated table -- and CLAUDE.md's rule against a
#: duplicated *fact* does not cover a duplicated, independently-testable
#: *translation table* the two modules each apply to their own input.
_MAINTAINER_ASSOCIATIONS = frozenset(("OWNER", "MEMBER", "COLLABORATOR"))
_EXTERNAL_ASSOCIATIONS = frozenset(("CONTRIBUTOR", "NONE"))
_TRANSLATED = frozenset(("maintainer", "external"))


def _translate_association(raw):
    """`raw` may already be translated (`"maintainer"`/`"external"`) or may
    still be GitHub's own all-caps spelling. Returns `None` -- never a
    guess -- for anything in neither vocabulary: a typo, a value GitHub adds
    later, or a missing field must not be read as either population."""
    if raw in _TRANSLATED:
        return raw
    if raw in _MAINTAINER_ASSOCIATIONS:
        return "maintainer"
    if raw in _EXTERNAL_ASSOCIATIONS:
        return "external"
    return None


def validate_refusal_reason(reason):
    """`True` only for one of the six reasons in `REFUSAL_REASONS`, exactly
    as written -- no case-folding, no synonym table. A caller that types
    `"Duplicate"` or `"dup"` gets `False`, not a guess at which of the six
    was meant; the closed set is only closed if near-misses fail loudly."""
    return reason in REFUSAL_REASONS


def is_inbound_issue(labels, declared):
    """Whether an issue was **not** filed by the loop -- the same predicate
    `select_issues_rank.rank` already applies for its own author axis,
    read here rather than re-derived: an issue carries `declared`'s
    `filed_by_loop` label, or it does not.

    Three states, not two. `True` -- the label is declared and this issue
    does not carry it, so it arrived from outside the loop's own filing.
    `False` -- the label is declared and this issue carries it. `None` --
    `labels.filed_by_loop` is not declared in `.oss.json` at all, so
    whether *any* issue on this board is inbound cannot be told from this
    signal alone; a caller receiving `None` must not read it as `False`,
    the same rule `select_issues_rank.rank` already states for the
    identical undeclared case.
    """
    loop_label = (declared or {}).get("filed_by_loop")
    if not loop_label:
        return None
    return loop_label not in (labels or [])


def classify_pr(pr):
    """`pr` is a dict carrying `author_association` (raw or already
    translated), `ci_state` (`"green"`/`"red"`/`"pending"`/`"unknown"`, the
    same vocabulary `pr_green.py` reports), and `mergeable` (`True`/`False`/
    `None`).

    Returns `"not-inbound"` for a maintainer-authored pull request -- this
    is the loop's own PR, or the maintainer's, and `skills/manager/phases/
    merge.md` already governs it; this module has nothing further to say
    about it. Returns `"could-not-tell"` when the association could not be
    translated at all -- an unrecognised or missing value must never render
    as either `"not-inbound"` or one of the two real outcomes below, the
    same discipline `is_inbound_issue` applies to an undeclared label.

    For an external pull request, one of `PR_OUTCOMES`'s two live members:
    `"green-and-mergeable"` only when CI is green **and** GitHub itself
    reports the pull request mergeable -- both conditions, because a green
    rollup on a branch GitHub cannot merge cleanly is not actually ready.
    Everything else -- red, pending, unknown CI, or `mergeable` anything but
    `True` -- is `"needs-answer"`: a person has to look at it, whether that
    means requesting changes, explaining a decline, or waiting out CI, and
    this module does not compute which.

    **The name is deliberately a measurement, not an instruction (self-review,
    #1394).** An earlier draft called this state `"ready-to-merge"` -- a name
    that reads as a verdict authorising the one act `merge.md` forbids
    absolutely for an external contributor's pull request, never-auto-merge,
    no exception. A caller that sees a string naming the act, on its own,
    without this docstring or `merge.md` beside it, has been handed
    permission it was never given. `"green-and-mergeable"` says only what was
    observed; what happens next -- merge it, or surface it -- is still never
    this function's decision, and now the name cannot be misread as making it
    one.
    """
    association = _translate_association(pr.get("author_association"))
    if association is None:
        return "could-not-tell"
    if association == "maintainer":
        return "not-inbound"
    if pr.get("ci_state") == "green" and pr.get("mergeable") is True:
        return "green-and-mergeable"
    return "needs-answer"


def comments_needing_answer(comments, since_iso, own_login=None):
    """Which of `comments` are new since the last tick and not already
    ours.

    `comments` is a list of dicts each carrying `created_at` (ISO 8601) and
    either `author` (a login) or `author_association`. `since_iso` is the
    timestamp to compare against -- typically the last tick's own recorded
    time. Comparison is a plain string compare, valid because ISO 8601
    timestamps sort lexicographically in the same order they sort
    chronologically **only when every timestamp shares one timezone
    representation** (all `Z`-suffixed UTC, as GitHub's API always returns
    them) -- a caller mixing in a naive or offset-suffixed timestamp from
    elsewhere gets a silently wrong ordering, not an exception.

    Returns `None` -- **not** an empty list -- when `since_iso` is falsy:
    "no watermark to compare against" and "compared, and nothing is new"
    render identically to a caller that only checks truthiness, which is
    the defect class this whole module exists to avoid. Check `is None`
    explicitly, the same way every `could-not-tell` state in this file
    must be checked.

    Both filters apply, not one or the other. A comment authored by
    `own_login`, when given, is excluded -- the loop's own replies (once
    #1395 exists to send them) must not count as inbound work still waiting
    on an answer. Every remaining comment is then also filtered by
    `author_association`: `"maintainer"` is excluded on the same reasoning
    `classify_pr` applies to a maintainer-authored PR -- it is the loop or
    the maintainer, not inbound. **Checking `author` and stopping there was
    the module's own first bug** (self-review, #1394): a maintainer who
    replies under their own human account rather than `own_login` carries
    an `author` that is never equal to `own_login`, so the association
    check must still run for every comment `own_login` alone did not
    already exclude, not only for the ones with no `author` field at all.
    A comment whose author could not be classified at all
    (`author_association` untranslatable, and either no `own_login` was
    given or `author` did not match it) is **included** rather than
    dropped: an unrecognised author is not evidence that it's ours, and
    dropping it silently would produce the same false "nothing waiting"
    this module exists to prevent.

    `comments=None` -- the caller's own fetch never ran, or failed -- also
    returns `None`, never `[]` (self-review, #1394: the audit spawn found
    `comments or []` folding that case into a genuinely empty, successfully
    fetched list, the identical could-not-tell-versus-measured-zero
    collapse the `since_iso` check above already guards against). Pass an
    explicit `[]` only when the fetch actually ran and found nothing.
    """
    if not since_iso:
        return None
    if comments is None:
        return None
    kept = []
    for comment in comments:
        created_at = comment.get("created_at")
        if not created_at or created_at <= since_iso:
            continue
        if own_login is not None and comment.get("author") == own_login:
            continue
        association = _translate_association(comment.get("author_association"))
        if association == "maintainer":
            continue
        kept.append(comment)
    return kept


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Validate a stated refusal reason against the closed set #1394 "
            "defines, so a refusal is never recorded on a ground nobody named."
        )
    )
    parser.add_argument(
        "--check-refusal",
        metavar="REASON",
        required=True,
        help="one of: {0}".format(", ".join(sorted(REFUSAL_REASONS))),
    )
    args = parser.parse_args(argv)

    if validate_refusal_reason(args.check_refusal):
        print("OK: {0!r} is a recognised refusal reason".format(args.check_refusal))
        return 0
    print(
        "FAIL: {0!r} is not one of the closed set: {1}".format(
            args.check_refusal, ", ".join(sorted(REFUSAL_REASONS))
        )
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
