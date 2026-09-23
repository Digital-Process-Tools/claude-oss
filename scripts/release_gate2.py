#!/usr/bin/env python3
"""Gate 2's own disposition -- computed, not re-argued from the same facts -- #1681.

`skills/manager/phases/release.md` and `commands/release.md` both state gate 2 as
one unelaborated sentence: "Nothing in flight is mid-review." Two `oss:releaser`
runs on `claude-supertool`, four hours apart, read the identical open pull
request (green, mergeable, `Review decision: none`, declined by `oss:tick-merge`
for feature scope, sitting untouched since 05:56) as opposite verdicts: the
first cleared gate 2 and refused later at gate 3; the second refused at gate 2
itself, on the grounds that this is "the ordinary awaiting-merge state gate 2
exists to catch." Nothing about the pull request changed between the two reads
-- only its age, and the agent's own narrative each time. That is this
repository's own defect class from a different angle: a judgement call
re-derived from prose renders a different answer on the same input depending
on how the prose happens to be read that run, which is indistinguishable from
an answer with no rule behind it at all.

This module does not decide what counts as "an active review round" --  that
stays a fact about GitHub (`review_decision`), about this loop's own worktrees
(`git-worktrees`), and about review-comment timestamps (`latest_review_comment_
age_minutes`). What it closes is the one step after those three facts are
read: given them, is a pull request in flight or backlog. That step was pure
narrative judgement at the point it disagreed with itself, and this makes it a
function with tests instead, the same move `gate3_disposition.py` (#1043)
already made for gate 3.

## The rule, per pull request

  review_decision        lane_active   comment age (min)         status
  ----------------------  -----------  -------------------------  -----------
  CHANGES_REQUESTED       n/a          n/a                        in-flight
  REVIEW_REQUIRED         n/a          n/a                        in-flight
  APPROVED                n/a          n/a                        clear
  NONE (or absent)        True         n/a                        in-flight
  NONE (or absent)        False        < threshold                in-flight
  NONE (or absent)        False        >= threshold, or explicit null  clear
  NONE (or absent)        unknown      n/a                        could-not-tell
  NONE (or absent)        False        unknown, or key absent     could-not-tell
  anything unrecognised   --           --                         could-not-tell

`(or absent)` beside `review_decision`/`lane_active` and `key absent` in the comment-age row
name the same fact for a different field: the caller's payload never sent the key at all. This
is deliberately distinct from an explicit `null` -- a caller who checked and confirmed no
review comment exists sends `latest_review_comment_age_minutes: null` and that still clears;
one whose payload omits the key entirely never established the fact and gets `could-not-tell`,
the same as an absent `lane_active`.

`review_decision: NONE` is the exact ambiguity the incident turned on -- no
reviewer has weighed in either way, which is true of both an ordinary
untouched backlog PR and a PR mid-round with the reviewer's comment not yet
turned into a formal decision. This module resolves it from the other two
signals rather than from how the run happens to narrate it: an agent still
alive in the PR's own worktree, or a review comment recent enough to still be
part of an active back-and-forth, both mean a round is open regardless of
`review_decision`. Neither means the pull request is not "mid-review"; the
absence of a formal decision is not the same fact as the absence of a review.

A PR that `oss:tick-merge` has already declined for feature scope is deliberately
NOT treated as a separate case here. It waits on the maintainer the same way
every other unreviewed backlog PR does, and clears by the same rule: no
formal decision, no active lane, no recent comment. Nothing needs to know
*why* it is backlog for this gate to read it correctly.

Three states for the whole decision, not two, the same shape `gate3_
disposition.py` gives gate 3: any PR read as `in-flight` blocks the whole
gate (`blocked-by:N`, naming the first one found); with none in flight, any PR
whose signals could not be read is `could-not-tell` -- never folded into
`clear`, since an absence produced by a failed read is not an absence in the
world; only when every open PR resolved cleanly one way or the other is the
gate `clear`. An empty open-PR list is `clear` by construction: nothing open
cannot be mid-review. `None`, or the caller's own way of saying "the fetch
itself never came back", is not the same input as an empty list and must not
collapse into the same answer -- a failed `gh pr list` is `could-not-tell`,
never `clear`.

Exit codes, because a shell reads those and never reads prose:

  0   clear
  1   blocked-by:N
  2   could-not-tell, or an argparse usage error
"""

import argparse
import json
import sys
from pathlib import Path

DISPOSITION_CLEAR = "clear"
DISPOSITION_BLOCKED_PREFIX = "blocked-by"
DISPOSITION_COULD_NOT_TELL = "could-not-tell"

DEFAULT_THRESHOLD_MINUTES = 30

_KNOWN_REVIEW_DECISIONS = ("NONE", "APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED")

# The third state for `lane_active` and `latest_review_comment_age_minutes`
# (mirrors `gate3_disposition.BLOCKING_UNKNOWN`): a caller who never checked
# must say so, and this module refuses to guess a value on its behalf.
UNKNOWN = "unknown"

EXIT_CLEAR = 0
EXIT_BLOCKED = 1
EXIT_COULD_NOT_TELL = 2

# Loop-authored branch prefixes: single-spawn, commit-and-die procedures with
# no ongoing multi-turn lane -- a doctor repair or a curate pass, never a
# developer lane's own `fix/{issue}` branch. See derive_lane_active() (#1725).
LOOP_AUTHORED_BRANCH_PREFIXES = ("doctor/", "curate/")


def is_loop_authored_branch(branch):
    """True when ``branch`` is one of this loop's own single-spawn branches
    (`doctor/*`, `curate/*`) -- never a developer lane's `fix/{issue}`
    branch. ``None`` and the empty string are False, not an error: a caller
    that never established the branch name gets the same answer a caller
    that established it is not one of these two prefixes gets, which is the
    conservative direction here (does not suppress a real lane_active
    reading).
    """
    return bool(branch) and branch.startswith(LOOP_AUTHORED_BRANCH_PREFIXES)


def derive_lane_active(branch, occupied):
    """Gate 2's own ``lane_active`` input, computed from git-worktrees'
    ``occupied`` reading rather than passed through unchanged (#1725).

    Observed on claude-supertool: the releaser refused at gate 2 with
    ``blocked-by:N``, reading "a lane process is alive" for a PR whose
    worktree held no lane at all -- it was a `doctor/*` branch the scheduler's
    own repair had just committed and pushed. `git-worktrees`' own
    ``occupied`` verdict ORs together an index-lock, an in-progress
    rebase/merge/cherry-pick, a `git worktree lock`, a write newer than its
    own activity window, and a process cwd'd inside the tree, and reports
    only the composite bit -- never which probe tripped. For a `doctor/*` or
    `curate/*` branch that composite is systematically wrong: both are
    single-spawn, commit-and-die passes, so the write their own commit makes
    is the only thing that will ever trip "occupied" for them, and it is
    indistinguishable in the composite from a lane still producing work.

    For those two prefixes, ``occupied`` is therefore never read as
    ``lane_active`` on its own -- this returns ``False`` for them regardless
    of what ``occupied`` says. Every other branch reads ``occupied``
    unchanged: an ordinary developer lane's worktree genuinely can be
    actively worked in during the window right after a commit, and there is
    no equivalent reason to distrust the signal there.

    ``occupied`` is passed through unchanged for ``None`` or the literal
    string ``"unknown"`` -- a reading that was never established must not be
    overwritten either way by the branch-name rule.
    """
    if occupied is None or occupied == UNKNOWN:
        return occupied
    if is_loop_authored_branch(branch):
        return False
    return occupied


def _decide_one(pr, threshold_minutes):
    """Return the per-PR read: {"number", "status", "reason"}.

    ``status`` is one of ``"in-flight"``, ``"clear"``, ``"could-not-tell"``.
    """
    number = pr.get("number")
    review_decision = pr.get("review_decision") or "NONE"

    if review_decision not in _KNOWN_REVIEW_DECISIONS:
        return {
            "number": number,
            "status": DISPOSITION_COULD_NOT_TELL,
            "reason": "review_decision {0!r} is not one of {1} -- an "
            "unrecognised value is not safely read as either "
            "state".format(review_decision, _KNOWN_REVIEW_DECISIONS),
        }

    if review_decision in ("CHANGES_REQUESTED", "REVIEW_REQUIRED"):
        return {
            "number": number,
            "status": "in-flight",
            "reason": "review_decision is {0}: an active review round is open".format(
                review_decision
            ),
        }

    if review_decision == "APPROVED":
        return {
            "number": number,
            "status": "clear",
            "reason": "review_decision is APPROVED: reviewing is done, this "
            "is the ordinary awaiting-merge state, not mid-review",
        }

    # review_decision == "NONE" -- the exact ambiguity the incident turned
    # on. Resolve it from the other two signals, never from narrative.
    lane_active = pr.get("lane_active")
    if lane_active == UNKNOWN or lane_active is None:
        return {
            "number": number,
            "status": DISPOSITION_COULD_NOT_TELL,
            "reason": "review_decision is NONE and lane_active was never "
            "established -- whether an agent is still iterating on this "
            "PR's own worktree must not be assumed either way",
        }
    if lane_active:
        return {
            "number": number,
            "status": "in-flight",
            "reason": "review_decision is NONE but a lane process is alive "
            "in this PR's own worktree -- work is still being produced "
            "against it",
        }

    if "latest_review_comment_age_minutes" not in pr:
        return {
            "number": number,
            "status": DISPOSITION_COULD_NOT_TELL,
            "reason": "review_decision is NONE, no active lane, but "
            "latest_review_comment_age_minutes is entirely absent from the "
            "caller's own payload -- a key never sent must not render the "
            "same as a confirmed 'no comment exists' (an explicit null)",
        }
    age = pr.get("latest_review_comment_age_minutes")
    if age == UNKNOWN:
        return {
            "number": number,
            "status": DISPOSITION_COULD_NOT_TELL,
            "reason": "review_decision is NONE, no active lane, but whether "
            "a review comment exists inside the staleness window could not "
            "be read",
        }
    if age is not None and age < threshold_minutes:
        return {
            "number": number,
            "status": "in-flight",
            "reason": "a review comment landed {0} minutes ago, inside the "
            "{1}-minute staleness window -- a round is still active even "
            "without a formal review decision".format(age, threshold_minutes),
        }

    return {
        "number": number,
        "status": "clear",
        "reason": "review_decision is NONE, no active lane, and no review "
        "comment inside the {0}-minute window -- ordinary backlog, not "
        "mid-review, whether or not tick-merge declined it for "
        "scope".format(threshold_minutes),
    }


def decide(open_prs, threshold_minutes=DEFAULT_THRESHOLD_MINUTES):
    """Return gate 2's own disposition over every open pull request.

    ``open_prs`` is a list of dicts shaped like ``_decide_one`` reads above:
    ``number``, ``review_decision``, ``lane_active``, and
    ``latest_review_comment_age_minutes``. An *empty list* is ``clear`` --
    the open-PR list was fetched and confirmed to hold nothing, so nothing
    can be mid-review. ``None`` or the string ``"unknown"`` is a **different**
    fact: the fetch itself was never established, and must not collapse into
    the same ``clear`` a confirmed-empty list gets -- a failed `gh pr list`
    and zero real open PRs are not the same input, and only one of them may
    safely clear the gate.
    """
    if open_prs is None or open_prs == UNKNOWN:
        return {
            "disposition": DISPOSITION_COULD_NOT_TELL,
            "reason": "the open pull-request list itself was never "
            "established -- an unperformed fetch must not render as a "
            "confirmed-empty one",
            "per_pr": [],
        }
    if not open_prs:
        return {
            "disposition": DISPOSITION_CLEAR,
            "reason": "no open pull requests -- nothing can be mid-review",
            "per_pr": [],
        }

    per_pr = [_decide_one(pr, threshold_minutes) for pr in open_prs]

    in_flight = [row for row in per_pr if row["status"] == "in-flight"]
    if in_flight:
        first = in_flight[0]
        return {
            "disposition": "{0}:{1!r}".format(
                DISPOSITION_BLOCKED_PREFIX, first["number"]
            ),
            "reason": first["reason"],
            "per_pr": per_pr,
        }

    unresolved = [row for row in per_pr if row["status"] == DISPOSITION_COULD_NOT_TELL]
    if unresolved:
        first = unresolved[0]
        return {
            "disposition": DISPOSITION_COULD_NOT_TELL,
            "reason": "PR #{0!r}: {1}".format(first["number"], first["reason"]),
            "per_pr": per_pr,
        }

    return {
        "disposition": DISPOSITION_CLEAR,
        "reason": "every open pull request is either approved, or "
        "unreviewed backlog with no active lane and no recent review "
        "activity",
        "per_pr": per_pr,
    }


def _exit_code(disposition):
    if disposition == DISPOSITION_CLEAR:
        return EXIT_CLEAR
    if disposition == DISPOSITION_COULD_NOT_TELL:
        return EXIT_COULD_NOT_TELL
    return EXIT_BLOCKED  # blocked-by:N


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compute gate 2's disposition over the open pull requests, so "
            "the same facts cannot read as backlog in one release run and "
            "mid-review in the next (#1681)."
        )
    )
    parser.add_argument(
        "--prs-json",
        required=True,
        help="path to a JSON file holding a list of PR dicts (see decide()'s "
        "own docstring for the shape), '-' to read the list from stdin, or "
        'the literal word unknown (or JSON \\"unknown\\") when the open-PR '
        "list itself could not be fetched -- never an empty list for that "
        "case",
    )
    parser.add_argument(
        "--threshold-minutes", type=int, default=DEFAULT_THRESHOLD_MINUTES
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of prose"
    )
    args = parser.parse_args(argv)

    try:
        raw = (
            sys.stdin.read()
            if args.prs_json == "-"
            else Path(args.prs_json).read_text()
        )
    except (OSError, UnicodeDecodeError) as exc:
        parser.error("--prs-json could not be read: {0}".format(exc))
        return EXIT_COULD_NOT_TELL  # pragma: no cover -- parser.error exits

    stripped = raw.strip()
    if stripped.lower() in ('"unknown"', "unknown"):
        open_prs = UNKNOWN
    else:
        try:
            open_prs = json.loads(raw)
        except json.JSONDecodeError as exc:
            parser.error("--prs-json did not parse as JSON: {0}".format(exc))
            return EXIT_COULD_NOT_TELL  # pragma: no cover -- parser.error exits
        if not isinstance(open_prs, list) or not all(
            isinstance(pr, dict) for pr in open_prs
        ):
            parser.error(
                "--prs-json must hold a JSON list of PR objects (dicts), or "
                "the literal word unknown -- got {0!r}".format(open_prs)
            )
            return EXIT_COULD_NOT_TELL  # pragma: no cover -- parser.error exits

    result = decide(open_prs, threshold_minutes=args.threshold_minutes)

    if args.json:
        print(json.dumps(result))
    else:
        print("DISPOSITION: {0}".format(result["disposition"]))
        print("  {0}".format(result["reason"]))

    return _exit_code(result["disposition"])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
