#!/usr/bin/env python3
"""Claim, read and release the assignee field on one or more issues -- #964.

`skills/manager/SKILL.md` and `skills/manager/phases/dispatch.md` both say
*claim before you spawn* and give the call: `gh issue edit <N> --add-assignee
@me`. `skills/manager/phases/handback.md` gives the release half. All three are
prose, and they are the only dispatch-time judgement in this loop with no
script behind it -- `lane_setup.py` computes disjointness, `select_issues_rank.py`
the order, `select_issues_preflight.py` staleness, and each exists because prose
stating three states does not produce three states.

## The state this exists for

`dispatch.md` already names the three: **assigned** (skip it), **unassigned**
(free to dispatch), and **could not read the assignees**, with the sentence
*this must never render as unassigned* beside it. But the read is "check
`gh-issue:N`, it reports it", so whether a session distinguished the third from
the second is unobservable from anywhere. An unreadable assignee field and an
empty one are the same two lines of output to a reader in a hurry, and picking
an issue whose claim state is unknown is this plugin's own defect class inside
the rule written to prevent a collision.

So `could-not-read` is a state here, it is never folded into `unassigned`, and
it is never a reason to go ahead and claim.

## Several issues per call, deliberately

A lane carries up to three issues and a bundle is claimed together or not at
all, so one call per issue is the wrong unit: it is how half a bundle ends up
claimed while the caller believes it holds all of it. Every issue named gets a
row, and a refusal on one does not stop the others -- a caller that stops at
the first refusal cannot release what it already took.

The exit code summarises; **the rows are the answer**. Same rule as
`checklist_skew.py`: a caller reads the state, never the code.

## What this cannot do, stated so the script is not read as more than it is

GitHub offers no compare-and-set on an assignee field. This is read-then-write,
so two loops racing on the same issue within the same second can both come away
believing they claimed it. That window is much smaller than the failure this
addresses -- a lane running for hours while the issue still reads `Assignees:
none` -- but it is not zero, and a caller must not read `claimed` as a lock.

Nor does it cover a contributor without write access: GitHub restricts
assignment to write or triage permission, so this claims for the maintainer's
own loop only. What an outside contributor uses is #460, and whatever that
lands on has to be read by the same selection step this feeds.

## States

  --read     unassigned / assigned / could-not-read
  --claim    claimed / already-mine / already-claimed / could-not-read /
             could-not-claim
  --release  released / not-assigned / not-mine / could-not-read /
             could-not-release

`already-claimed` names who holds it. When the viewer's own login cannot be
resolved, an assigned issue is `already-claimed` by an unidentified party
rather than a candidate: **never claim over somebody**, and an unknown holder
is somebody.

Exit codes:

  0   every row reached the mode's success state (`claimed`/`already-mine`,
      `released`/`not-assigned`, or a `--read` that read every issue)
  1   at least one row did not -- including every `could-not-*` row
  2   argparse usage error

## No longer a standalone CLI (#1069)

`main()`'s argparse CLI is gone. `select_issues.py` is the one entry point
that reaches `check(..., "read")`, for the same reason `select_issues_rank.py`
and `select_issues_preflight.py` lost theirs. The write half (`--claim`,
`--release`) is now `lane_setup.py`'s own job -- `lane_setup_claim.py` imports
`check`/`claim_one`/`release_one` from here rather than re-implementing the
`gh` calls, so this stays the one place that talks to `gh issue view`/`edit`
for the assignee field. Renamed from `issue_claim.py` to
`select_issues_claim_read.py`, following the `doctor_check_*` precedent.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import json
import subprocess

STATE_UNASSIGNED = "unassigned"
STATE_ASSIGNED = "assigned"
STATE_COULD_NOT_READ = "could-not-read"

STATE_CLAIMED = "claimed"
STATE_ALREADY_MINE = "already-mine"
STATE_ALREADY_CLAIMED = "already-claimed"
STATE_COULD_NOT_CLAIM = "could-not-claim"

STATE_RELEASED = "released"
STATE_NOT_ASSIGNED = "not-assigned"
STATE_NOT_MINE = "not-mine"
STATE_COULD_NOT_RELEASE = "could-not-release"

#: Every entry point takes ``run=None`` and resolves the default *inside* the
#: call rather than as ``run=_run`` in the signature. A default bound at import
#: cannot be replaced later, so a test patching this module's ``_run`` would
#: have patched an attribute nothing reads -- the same shape as patching a
#: module attribute the code under test never looks up, which this repository's
#: own fixture rules warn about. Caught by the exit-code tests, which went
#: through ``main`` and reached the real binary.
#:
#: Rows that mean the caller got what it asked for, per mode. Everything else,
#: `could-not-*` included, is a non-zero exit -- so a shell caller that ignores
#: the rows still cannot proceed as though the claim succeeded.
_OK_STATES = {
    "read": (STATE_UNASSIGNED, STATE_ASSIGNED),
    "claim": (STATE_CLAIMED, STATE_ALREADY_MINE),
    "release": (STATE_RELEASED, STATE_NOT_ASSIGNED),
}

_TIMEOUT = 30


def _run(args, timeout=_TIMEOUT):
    """``(ok, stdout, detail)`` for a `gh` invocation.

    Never raises. A missing `gh` binary, a timeout and a non-zero exit are
    three different reasons and each keeps its own sentence: a caller told only
    "it failed" cannot tell an unauthenticated session from an absent tool, and
    would report the same `could-not-read` for both.
    """
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "", "{0} is not on PATH".format(args[0])
    except OSError as exc:
        return False, "", "{0}: {1}".format(args[0], exc)
    except subprocess.TimeoutExpired:
        return False, "", "{0} timed out after {1}s".format(args[0], timeout)
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        return False, out, err or "exit {0}".format(proc.returncode)
    return True, out, None


def viewer_login(run=None):
    """``(login, detail)``. ``login`` is ``None`` when it could not be resolved.

    `@me` is the only spelling that is correct on a repository this project's
    author does not own, so the login is never written down anywhere -- it is
    resolved from the authenticated session at call time. When that resolution
    fails, the caller must treat every assigned issue as somebody else's; see
    `_classify_assignees`.
    """
    run = _run if run is None else run
    ok, out, detail = run(["gh", "api", "user", "--jq", ".login"])
    if not ok:
        return None, detail
    login = out.strip()
    if not login:
        return None, "gh api user returned an empty login"
    return login, None


def read_assignees(number, run=None, repo=None):
    """``(logins, detail)``. ``logins`` is ``None`` when the field could not be
    read at all -- which is not the same answer as ``[]``, and the caller must
    not collapse the two."""
    run = _run if run is None else run
    args = ["gh", "issue", "view", str(number), "--json", "assignees"]
    if repo:
        args.extend(["--repo", repo])
    ok, out, detail = run(args)
    if not ok:
        return None, detail
    try:
        payload = json.loads(out)
    except ValueError as exc:
        return None, "unparseable JSON from gh issue view: {0}".format(exc)
    assignees = payload.get("assignees")
    if not isinstance(assignees, list):
        # A payload with no `assignees` key is not an issue with no assignees.
        # `gh` shapes this field itself, so its absence means the read did not
        # answer the question, and rendering that as unassigned is exactly the
        # fold this module exists to refuse.
        return None, "gh issue view returned no assignees field"
    logins = []
    for entry in assignees:
        if isinstance(entry, dict) and entry.get("login"):
            logins.append(entry["login"])
        else:
            return None, "unrecognised assignee entry: {0!r}".format(entry)
    return logins, None


def _classify_assignees(logins, login):
    """``(mine, others)`` given the assignee logins and the viewer's own.

    When ``login`` is ``None`` the viewer could not be identified, so nothing
    is `mine`: an assigned issue belongs to somebody unidentified rather than
    to us. Guessing the other way is how a loop claims over a colleague.
    """
    if login is None:
        return False, list(logins)
    mine = login in logins
    return mine, [name for name in logins if name != login]


def _row(number, state, **extra):
    row = {"issue": number, "state": state}
    row.update(extra)
    return row


def read_one(number, login, run=None, repo=None):
    logins, detail = read_assignees(number, run=run, repo=repo)
    if logins is None:
        return _row(number, STATE_COULD_NOT_READ, detail=detail)
    if not logins:
        return _row(number, STATE_UNASSIGNED, assignees=[])
    mine, others = _classify_assignees(logins, login)
    return _row(number, STATE_ASSIGNED, assignees=logins, mine=mine, others=others)


def claim_one(number, login, run=None, repo=None):
    run = _run if run is None else run
    logins, detail = read_assignees(number, run=run, repo=repo)
    if logins is None:
        return _row(number, STATE_COULD_NOT_READ, detail=detail)
    mine, others = _classify_assignees(logins, login)
    if mine and not others:
        return _row(number, STATE_ALREADY_MINE, assignees=logins)
    if logins:
        return _row(
            number,
            STATE_ALREADY_CLAIMED,
            assignees=logins,
            holders=others,
            viewer_known=login is not None,
        )
    args = ["gh", "issue", "edit", str(number), "--add-assignee", "@me"]
    if repo:
        args.extend(["--repo", repo])
    ok, _out, detail = run(args)
    if not ok:
        return _row(number, STATE_COULD_NOT_CLAIM, detail=detail)
    return _row(number, STATE_CLAIMED)


def release_one(number, login, run=None, repo=None):
    run = _run if run is None else run
    logins, detail = read_assignees(number, run=run, repo=repo)
    if logins is None:
        return _row(number, STATE_COULD_NOT_READ, detail=detail)
    if not logins:
        return _row(number, STATE_NOT_ASSIGNED)
    mine, others = _classify_assignees(logins, login)
    if not mine:
        return _row(number, STATE_NOT_MINE, assignees=logins, holders=others)
    args = ["gh", "issue", "edit", str(number), "--remove-assignee", "@me"]
    if repo:
        args.extend(["--repo", repo])
    ok, _out, detail = run(args)
    if not ok:
        return _row(number, STATE_COULD_NOT_RELEASE, detail=detail)
    return _row(number, STATE_RELEASED)


_MODES = {"read": read_one, "claim": claim_one, "release": release_one}


def check(numbers, mode, run=None, repo=None):
    """One row per issue, in the order given. Never raises for a forge failure.

    The viewer login is resolved once rather than per issue: it is the same
    answer for every row, and a per-issue resolution would report one issue as
    `already-claimed` and the next as `already-mine` on a transient failure.
    Its own failure is carried on every row that needed it, so a reader is
    never told an issue is somebody else's without being told why we could not
    check whether it was ours.
    """
    run = _run if run is None else run
    login, login_detail = viewer_login(run=run)
    handler = _MODES[mode]
    rows = []
    for number in numbers:
        row = handler(number, login, run=run, repo=repo)
        if login is None:
            row["viewer"] = None
            row["viewer_detail"] = login_detail
        else:
            row["viewer"] = login
        rows.append(row)
    return rows


def _render(rows, mode):
    lines = []
    for row in rows:
        parts = ["#{0}".format(row["issue"]), row["state"]]
        if row.get("assignees"):
            parts.append("assignees={0}".format(",".join(row["assignees"])))
        if row.get("detail"):
            parts.append(row["detail"])
        if row.get("viewer") is None and row["state"] != STATE_UNASSIGNED:
            parts.append(
                "viewer unresolved ({0}) -- an assigned issue is treated as "
                "somebody else's".format(row.get("viewer_detail"))
            )
        lines.append("  ".join(parts))
    ok = _OK_STATES[mode]
    bad = [row for row in rows if row["state"] not in ok]
    lines.append(
        "{0}: {1} row(s), {2} not {3}".format(mode, len(rows), len(bad), "/".join(ok))
    )
    return "\n".join(lines)
