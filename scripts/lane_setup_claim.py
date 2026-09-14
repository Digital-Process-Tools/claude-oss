"""A developer lane's own GitHub assignee -- claiming an issue, and releasing
it again (#1069, #1532).

Split out of `lane_setup.py` for #1069, when this file also held the local
lane registry: a hidden directory beside the numbered worktrees, holding one
record per live lane saying "a developer lane is live here", a 240-minute TTL,
and a held set derived from every live record plus every open pull request's
file list (#385, #558, #705, #734, #771, #792, #845).

**#1532 retired all of that.** The held set existed to answer one question --
which files are already spoken for -- and #1528 stopped a collision with it
dropping a candidate while #1530 removed the declared file sets it collided
on. What was left was a record nothing read for a decision: a second, staler
copy of what `git-worktrees` answers from the filesystem, on a TTL long enough
that a phantom record blocked real work for hours.

What is left here is the one claim with a real owner. The assignee is a forge
write, it is the fact two sessions actually contend over, and -- on the code
#1532 removed -- it was already the only thing stopping two lanes taking the
same issue: `claim_and_register` read and wrote it FIRST and returned
`already-claimed` before the registry was reached at all. Retiring the
registry therefore removes no guarantee, which is the question #1532 recorded
as not established and this docstring records as answered.

Because there is now one write rather than two, there is nothing to roll back
between them, and the three rollback states that existed for that
(`could-not-register`, `assignee-rolled-back`,
`rollback-failed-assignee-still-set`) are gone with it.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import select_issues_claim_read


#: Every requested assignee write succeeded -- freshly claimed, or already
#: ours before this call.
CLAIM_STATE_CLAIMED = "claimed"
#: At least one issue is already assigned to somebody else. Refused before
#: anything is written -- the "never claim over somebody" rule
#: `select_issues_claim_read.py` already states.
CLAIM_STATE_ALREADY_CLAIMED = "already-claimed"
#: The assignee read/write itself could not be completed for at least one
#: issue. Not the same as "it is taken", and never folded into it.
CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE = "could-not-claim-assignee"
#: Kept for the caller that reads a single row rather than the fold.
CLAIM_STATE_ALREADY_MINE = "already-mine"


def claim_issues(issue, also_claim=None, repo=None, checker=None):
    """Write the GitHub assignee for `issue` and every issue in `also_claim`.

    `also_claim` is this lane's companion issues -- a lane carries more than
    one issue, and all of them are claimed in the one call rather than in one
    call each.

    `checker` defaults to `select_issues_claim_read.check`, injectable for a
    test the same way `select_issues.py`'s own `select()` already injects it.

    Returns `{"state", "assignee": {"rows": [...]}}`, where `state` is one of
    `CLAIM_STATE_CLAIMED` / `CLAIM_STATE_ALREADY_CLAIMED` /
    `CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE`.

    The three states are the usual three, not two: an issue confirmed taken by
    somebody else and an issue whose assignee could not be read are different
    facts and are reported differently. Folding the second into the first
    would claim a reading nothing performed.
    """
    checker = select_issues_claim_read.check if checker is None else checker
    numbers = [issue] + [n for n in (also_claim or []) if n != issue]

    rows = checker(numbers, "claim", repo=repo)

    already_claimed = [
        row
        for row in rows
        if row["state"] == select_issues_claim_read.STATE_ALREADY_CLAIMED
    ]
    if already_claimed:
        return {
            "state": CLAIM_STATE_ALREADY_CLAIMED,
            "assignee": {"rows": rows},
        }

    unclaimable = [
        row
        for row in rows
        if row["state"] != select_issues_claim_read.STATE_CLAIMED
        and row["state"] != select_issues_claim_read.STATE_ALREADY_MINE
    ]
    if unclaimable:
        return {
            "state": CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE,
            "assignee": {"rows": rows},
        }

    return {
        "state": CLAIM_STATE_CLAIMED,
        "assignee": {"rows": rows},
    }


def release_assignees(issue, also_release=None, repo=None, checker=None):
    """The mirror of `claim_issues`: release this issue's GitHub assignee, and
    every companion issue's, in one call.

    Called once the merge step has independently verified the pull request
    merged, so a follow-up dispatched minutes later never reads this issue as
    still taken.

    Returns `{"assignee": <one row for `issue`>, "also_released": [...]}`.
    Both halves are removals, reported on their own rather than as one folded
    verdict -- a caller that needs to know which companion did not release can
    only learn it from the rows.
    """
    checker = select_issues_claim_read.check if checker is None else checker
    rows = checker([issue], "release", repo=repo)
    also_rows = (
        checker(list(also_release), "release", repo=repo) if also_release else []
    )
    return {
        "assignee": rows[0] if rows else None,
        "also_released": also_rows,
    }
