#!/usr/bin/env python3
"""One call, several pull requests, states as exit codes -- #1086.

`trap.d/1066.grep-negation-contains-its-own-positive.md`: a hand-written CI
wait loop matched `NOT ALL GREEN` against the substring `ALL GREEN` and
exited green with 12 checks still pending. The reason a text match was forced
at all is that supertool's raw-command guard refuses `gh pr checks --jq`, so
the condition had to be prose matching rather than a field read. This module
calls `gh` directly through `subprocess` (from Python, not through the Bash
tool the guard hooks) and answers with an exit code, never a line a caller
has to grep.

## Shape, per the maintainer's own comments on #1086

These supersede the issue body's original aggregate-precedence design.
**Scan the named pull requests (or --all-open) in order and stop at the
first one that is not pending.** There is no aggregate-precedence table and
no wait-for-all -- a red pull request is news the moment it is red, not when
its slower neighbours finish. The one waiting behaviour this module has:
poll while every named pull request is still pending, and return the instant
any one of them is not.

## The four states

  green            every leg in the check rollup concluded and passed --
                    the exit code, still `green`. A declared,
                    pull_request-triggered workflow that produced no row in
                    the rollup at all does not change the exit code, but is
                    named on the printed line under `missing_workflows`
                    rather than silently absorbed into "every leg passed" --
                    in this repo `changelog` is the workflow most likely to
                    be the one that produced nothing (#1086's own worked
                    example, there about a push commit rather than a pull
                    request, but the same defect class). A caller that reads
                    only the exit code never sees this; one that reads the
                    line does. `missing_workflows` is `None`, not `[]`, when
                    the check itself could not run (an unreadable workflows
                    directory) -- an unreadable directory and a directory
                    that genuinely declares nothing are not the same fact.
  red              at least one leg failed (or completed with a conclusion
                    this module has never seen -- an unrecognised state is a
                    finding, never a silent pass). Reported the instant it
                    is seen, even while a sibling leg is still pending: per
                    the maintainer's third comment, a red leg does not wait
                    for its neighbours. Carries the branch, the sha, each
                    failing leg's name and workflow, and -- best effort --
                    the shortest decisive line out of its own run log, so a
                    developer can be briefed from this one call.
  pending          every leg is either still running or the rollup is empty
                    (no checks reported yet is not a read failure and is
                    never green). Also `pending` -- never `green` -- when an
                    Actions run exists on the commit, is not yet reflected
                    in the rollup at all, and has produced zero jobs so far
                    (#1400): queried directly against
                    `.../actions/runs?head_sha=`, the same fact `gh-branch`
                    already reads to draw this exact line, rather than
                    guessed at from a workflow file's own `on:` declaration,
                    which cannot see a path filter or a conditional job. A
                    workflow that genuinely did not trigger for this event
                    produces no run object at all and is correctly left out
                    of this check -- gate 1's own documented middle state.
                    Named under `unresolved_runs` on the returned entry:
                    `[]` when checked and nothing is unresolved, `None`
                    when it could not be established (owner/repo/sha
                    unavailable, the extra read failed, or too many
                    uncovered runs to check cheaply) -- never blocking
                    `green` forever on a fact this module could not check,
                    the same rule `missing_workflows` already follows, and
                    never folded into the same `[]` that means "checked,
                    clean" either, which is the identical collapse #1400
                    itself reports.
  could-not-read   the read itself failed -- `gh` not on PATH, the process
                    could not start, a non-zero exit, or output this module
                    could not parse. **Never folded into `pending`** (that
                    is a wait loop that spins forever on a PR nobody can
                    read) **and never folded into `green`** (that is a tick
                    that merges blind). Those two collapses are this
                    repository's own defect class.

`EXIT_CODES` is the machine-readable half; the printed line is for the human
reading the sub-manager's transcript.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

import gh_which

STATE_GREEN = "green"
STATE_RED = "red"
STATE_PENDING = "pending"
STATE_COULD_NOT_READ = "could-not-read"

EXIT_CODES = {
    STATE_GREEN: 0,
    STATE_RED: 1,
    STATE_PENDING: 2,
    STATE_COULD_NOT_READ: 3,
}

# Conclusions a completed GitHub Actions check can carry. Anything completed
# but NOT in _PASSING_CONCLUSIONS is treated as failing -- including a
# conclusion this module has never seen, deliberately: an unrecognised state
# must never render as green (test_read_pr_red_on_an_unrecognised_completed_
# conclusion pins this).
_PASSING_CONCLUSIONS = frozenset(("SUCCESS", "NEUTRAL", "SKIPPED"))

# The legacy commit-status ("StatusContext") shape carries `state` rather
# than `status`/`conclusion` -- a different vocabulary for the same three
# outcomes. Anything not in either set below (an unrecognised `state`, same
# rule as `_PASSING_CONCLUSIONS`) is treated as failing.
_PASSING_STATUS_CONTEXT_STATES = frozenset(("SUCCESS",))
_PENDING_STATUS_CONTEXT_STATES = frozenset(("PENDING", "EXPECTED"))

# #1458: a completed conclusion outside _PASSING_CONCLUSIONS is not
# automatically a failure -- GitHub, and supertool's own `gh-pr:N:status`
# (`_checks.github_superseded`, #1792), exclude a leg from the failing tally
# when a *later* run of the exact same check name exists on the same commit.
# `gh-pr:658:status` on claude-remember read a CANCELLED `fragment` leg this
# way while `pr_green.py` read it RED -- the two tools disagreed about the
# same PR at the same instant.
#
# The rule, reproduced here rather than imported (this module has no
# dependency on the supertool package): a leg is superseded only when
# another leg of the *same name* started strictly after this leg completed.
# Deliberately narrower than "collapse to latest per name" -- GitHub's
# default code-scanning setup emits two runs of one workflow per push with
# colliding check-run names, started in the same second (#1640), and neither
# supersedes the other; both still have to pass. A leg whose completion
# timestamp cannot be read is never superseded (declining rather than
# guessing).
_ZERO_TIME_YEAR = 1970


def _parse_ts(value):
    """An ISO-8601 instant as epoch seconds, or ``None`` when not
    establishable -- an unparseable stamp and GitHub's zero-time sentinel
    both mean "no timestamp", never a number. Mirrors supertool's own
    `_checks.parse_ts`."""
    from datetime import datetime, timezone

    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt.year < _ZERO_TIME_YEAR:
        return None
    return dt.timestamp()


def _leg_window(row):
    """``(name, started_epoch, completed_epoch)`` for one rollup row.

    A StatusContext row carries no ``startedAt``/``completedAt`` at all, so
    both stamps collapse to ``None`` and such a row can never supersede or
    be superseded.
    """
    if not isinstance(row, dict):
        return ("", None, None)
    name = str(row.get("name") or row.get("context") or "?")
    return (
        name,
        _parse_ts(row.get("startedAt")),
        _parse_ts(row.get("completedAt")),
    )


def _superseded_flags(rows):
    """Per rollup row: has a later run of the same check name replaced it?

    ``len(result) == len(rows)`` always, so this composes with the
    classification loop below by position.
    """
    windows = [_leg_window(row) for row in rows]
    by_name = {}
    for i, (name, _started, _done) in enumerate(windows):
        by_name.setdefault(name, []).append(i)

    flags = [False] * len(windows)
    for idxs in by_name.values():
        if len(idxs) < 2:
            continue
        for i in idxs:
            done = windows[i][2]
            if done is None:
                continue
            flags[i] = any(
                windows[j][1] is not None and windows[j][1] > done
                for j in idxs
                if j != i
            )
    return flags


_JOB_URL_RE = re.compile(r"/actions/runs/(\d+)/job/(\d+)")

_OWNER_REPO_RE = re.compile(r"^https?://[^/]+/([^/]+)/([^/]+)(?:/|$)")

_PR_VIEW_FIELDS = "number,headRefName,headRefOid,state,statusCheckRollup,url"

# A run that exists on the commit but is not yet reflected in the rollup
# needs one extra `gh api` call per run to ask whether it has a job yet.
# Past this many uncovered runs the answer is "unestablished" rather than a
# slow, correct one -- the same bound `claude-supertool`'s own
# `_declared_legs.MAX_RECONCILED_RUNS` uses for the identical reconciliation.
_MAX_UNRESOLVED_RUN_CHECKS = 4


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _flatten(text):
    """#1113: text this loop did not generate itself -- `gh` stderr, a CI
    leg's own name -- collapsed onto one line before it is stitched into a
    line-structured receipt (`#N | STATE | ...`) a caller parses one row at
    a time. Unflattened, an embedded newline puts forge-supplied text at
    column 0 of the next line, where it can read as a second, unrelated row
    (e.g. a fake `#999 | GREEN | ...`)."""
    return " ".join(str(text).split())


def _gh(gh, args, run, timeout=30):
    """Run ``[gh] + args``, returning ``(stdout, stderr, detail)``.

    ``detail`` is ``None`` on success; otherwise it is a short human-readable
    reason and ``stdout`` is ``None`` -- the same two-outcome shape
    `doctor_check_branch_protection._gh_api` already uses for its own `gh`
    calls, so a caller never has to guess which of ``(None, "")`` means "no
    output" versus "failed to read".
    """
    try:
        done = run(
            [gh] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, str(exc)
    stdout = _decode(done.stdout)
    stderr = _decode(done.stderr)
    if done.returncode != 0:
        return None, None, (stderr.strip() or "gh exit {0}".format(done.returncode))
    return stdout, stderr, None


def _declared_pr_workflow_names(workflows_dir):
    """``(names, ok)`` -- the workflow ``name:`` values under ``workflows_dir``
    that trigger on ``pull_request`` (or ``pull_request_target``), and
    whether the directory itself could be read at all.

    ``ok`` is ``False`` only when ``workflows_dir`` could not be listed
    (missing, a permission denial, not a directory). That is deliberately
    NOT the same fact as "listed cleanly and genuinely declares zero such
    workflows" -- folding the two into one empty set is this repository's
    own named defect class, an absence the tool produced read as an absence
    in the world. A single unreadable *file* inside a readable directory is
    a smaller failure and stays best-effort: it just excludes that one file,
    the same way it always has, since a caller can still trust every file
    that *was* read.
    """
    names = set()
    try:
        entries = os.listdir(str(workflows_dir))
    except OSError:
        return names, False
    for entry in entries:
        if not entry.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(str(workflows_dir), entry)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        if "pull_request" not in text:
            continue
        match = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
        if match:
            names.add(match.group(1).strip().strip('"').strip("'"))
    return names, True


def _owner_repo(url):
    """``(owner, repo)`` parsed out of a GitHub PR URL, ``("", "")`` when
    unparseable -- the same fact `claude-supertool`'s own
    `_declared_legs.owner_repo` derives, re-derived here rather than
    imported since this module has no dependency on that project."""
    text = str(url or "").strip()
    if not text:
        return "", ""
    match = _OWNER_REPO_RE.match(text)
    return (match.group(1), match.group(2)) if match else ("", "")


def _rollup_run_ids(rows):
    """Distinct Actions run ids a rollup already carries, parsed out of each
    row's ``detailsUrl`` -- the same field `_failure_log_line` reads the job
    id from. A run whose id is already in this set is covered by the rollup
    and is never asked about again."""
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        match = _JOB_URL_RE.search(str(row.get("detailsUrl") or ""))
        if match:
            ids.add(match.group(1))
    return ids


# Trigger events that can plausibly feed a pull request's own check rollup.
# A run whose ``event`` is outside this set (a `push` to the same sha on a
# branch, a `schedule` run, a `workflow_dispatch`) was never going to appear
# in the rollup regardless of its job state, so counting it as "uncovered"
# would report a PR pending over a run that has nothing to do with it --
# self-review finding, alongside #1400's own reconciliation.
_PR_RELEVANT_EVENTS = frozenset(("pull_request", "pull_request_target"))


def _runs_on_commit(gh, run, owner, repo, sha):
    """``[(run_id, name, event, status), ...]`` for every Actions run GitHub
    has recorded against ``sha``, or ``None`` when the read failed.

    This is the distinction #1400 asks for: a workflow declared in
    `.github/workflows/` whose trigger genuinely did not fire for this event
    (a `pull_request_target`-only workflow, a path filter that excluded
    every changed file) never produces a run object here at all, and is
    correctly left alone -- gate 1's own documented middle state. A run
    object that *does* exist but carries no job yet is the other case, and
    is resolved by `_run_has_jobs` below rather than being guessed at from
    the workflow file's own trigger declaration, which cannot see a
    path filter or a conditional job. ``event`` rides along so a caller can
    tell a run irrelevant to this PR (a `push` to the same sha) from one
    that actually belongs to its rollup.

    ``status`` (#1480) rides along too: a run whose own ``status`` is
    already ``"completed"`` is settled regardless of what its jobs listing
    says -- confirmed against a real run (a `push`-triggered `tests` run on
    this repository's own history, cancelled while still queued: `status`
    `completed`, `conclusion` `cancelled`, `.../jobs?filter=all` reporting
    `{"jobs": []}` permanently, not merely for the transient window
    `_run_has_jobs`'s own docstring documents for a partial re-run). Only
    the one terminal value, `"completed"`, is checked for -- GitHub's own
    transient vocabulary is not closed (`queued`, `in_progress`, and an
    undocumented `pending` have all been observed for this same field
    elsewhere in this repository's own history, per this file's `--wait`
    loop precedent) and enumerating the open side is a bet that list never
    grows.
    """
    if not owner or not repo or not sha:
        return None
    out, _err, detail = _gh(
        gh,
        [
            "api",
            "repos/{0}/{1}/actions/runs?head_sha={2}&per_page=100".format(
                owner, repo, sha
            ),
        ],
        run,
    )
    if detail is not None or out is None:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    if not isinstance(runs, list):
        return None
    result = []
    for entry in runs:
        if not isinstance(entry, dict):
            continue
        run_id = str(entry.get("id") or "").strip()
        if run_id:
            result.append(
                (
                    run_id,
                    str(entry.get("name") or ""),
                    entry.get("event"),
                    entry.get("status"),
                )
            )
    return result


def _run_has_jobs(gh, run, owner, repo, run_id):
    """``True``/``False``/``None`` (could not tell) -- whether an Actions
    run has produced at least one job yet. ``filter=all`` (not the
    endpoint's own default of ``filter=latest``) for the same reason
    `claude-supertool`'s `_declared_legs.legs_for_run` uses it: a partial
    re-run can otherwise read as zero jobs for ~18s after it starts."""
    if not owner or not repo or not run_id:
        return None
    out, _err, detail = _gh(
        gh,
        [
            "api",
            "repos/{0}/{1}/actions/runs/{2}/jobs?filter=all&per_page=1".format(
                owner, repo, run_id
            ),
        ],
        run,
    )
    if detail is not None or out is None:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return None
    return len(jobs) > 0


def _unresolved_runs(gh, run, owner, repo, sha, rollup_run_ids):
    """Names of the Actions runs on this commit that are not yet covered by
    the rollup and have produced no job -- the shape #1400 reports.

    Three outcomes, deliberately mirroring `missing_workflows`'s own
    `None`/`[]` split rather than only claiming to (self-review finding: an
    earlier version of this function returned `[]` for "unestablished" too,
    which is the exact collapse #1400 itself is about, reproduced one layer
    in):

    * ``None`` -- could not be established: owner/repo/sha could not be
      derived, the commit-runs read itself failed, or more than
      `_MAX_UNRESOLVED_RUN_CHECKS` runs are uncovered (checking all of them
      is not worth the round trips). A caller must not read this as "none
      are unresolved" -- the same rule `missing_workflows` already follows.
    * ``[]`` -- checked, and nothing is unresolved.
    * a non-empty list -- these runs exist on the commit, are not yet in the
      rollup, and have produced no job.

    Only runs whose own ``event`` is plausibly rollup-feeding
    (`_PR_RELEVANT_EVENTS`) are considered at all: a `push`-triggered run
    sharing this sha was never going to reach the PR's rollup regardless of
    its job state, and counting it would both report a false pending and
    spend part of the reconciliation budget on a run that has nothing to do
    with this PR.

    A run already reported ``"completed"`` (#1480) is excluded from
    consideration entirely, regardless of its own job count: a run
    cancelled while still queued reaches `status: completed` and reports
    zero jobs from `.../jobs?filter=all` permanently, not merely for the
    transient window `_run_has_jobs` exists to paper over, and nothing
    distinguishes that state from a genuinely still-in-flight run once only
    the job count is read. `status` missing entirely (a run object shaped
    like #1400's own original reproduction) is treated as "not confirmed
    completed" and still checked the old way, so that reproduction's own
    positive control is unaffected.
    """
    commit_runs = _runs_on_commit(gh, run, owner, repo, sha)
    if commit_runs is None:
        return None
    uncovered = [
        (run_id, name)
        for run_id, name, event, status in commit_runs
        if run_id not in rollup_run_ids
        and (event is None or event in _PR_RELEVANT_EVENTS)
        and status != "completed"
    ]
    if len(uncovered) > _MAX_UNRESOLVED_RUN_CHECKS:
        return None
    unresolved = []
    for run_id, name in uncovered:
        has_jobs = _run_has_jobs(gh, run, owner, repo, run_id)
        if has_jobs is False:
            unresolved.append(name or "run #{0}".format(run_id))
    return unresolved


def _failure_log_line(gh, run, details_url):
    """The shortest decisive line out of a failing job's own log -- never the
    whole log, which is the developer's to pull (#1086's own phrasing).
    Best effort: any failure to fetch or parse returns ``None`` rather than
    raising, since a missing log line must not stop `red` from being
    reported at all.
    """
    if not details_url:
        return None
    match = _JOB_URL_RE.search(details_url)
    if not match:
        return None
    run_id, job_id = match.groups()
    out, _err, detail = _gh(
        gh, ["run", "view", run_id, "--job", job_id, "--log-failed"], run
    )
    if detail is not None or out is None:
        return None
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return None
    return lines[-1]


def read_pr(number, gh, run, workflows_dir=None, declared_workflows=None):
    """Read one pull request's check rollup and classify it.

    ``workflows_dir`` and ``declared_workflows`` are two ways to supply the
    same fact (a directory to derive it from, or the set already derived) --
    passing neither just means `missing_workflows` is always `[]`, which is
    a real, honest answer rather than a guess: this function was not told
    what "every leg" should contain. Passing ``workflows_dir`` for a
    directory that cannot be listed makes it `None` instead -- "could not
    check" is a third answer, never silently folded into "checked and clean".
    """
    out, _err, detail = _gh(
        gh, ["pr", "view", str(number), "--json", _PR_VIEW_FIELDS], run
    )
    if out is None:
        return {"pr": number, "state": STATE_COULD_NOT_READ, "detail": detail}
    try:
        payload = json.loads(out)
    except ValueError as exc:
        return {
            "pr": number,
            "state": STATE_COULD_NOT_READ,
            "detail": "could not parse `gh pr view` output: {0}".format(exc),
        }
    try:
        branch = payload["headRefName"]
        sha = payload.get("headRefOid", "")
        rows = payload.get("statusCheckRollup") or []
    except (KeyError, TypeError) as exc:
        return {
            "pr": number,
            "state": STATE_COULD_NOT_READ,
            "detail": "unexpected `gh pr view` shape: {0}".format(exc),
        }

    if not rows:
        return {
            "pr": number,
            "branch": branch,
            "sha": sha,
            "state": STATE_PENDING,
            "failing": [],
            "pending_legs": [],
            "missing_workflows": [],
            "unresolved_runs": [],
            "superseded": [],
        }

    failing = []
    pending_legs = []
    superseded = []
    seen_workflows = set()
    superseded_flags = _superseded_flags(rows)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        workflow = row.get("workflowName") or row.get("context") or ""
        if workflow:
            seen_workflows.add(workflow)
        name = row.get("name") or row.get("context") or "?"
        details_url = row.get("detailsUrl") or row.get("targetUrl")
        if "status" in row or "conclusion" in row:
            # CheckRun shape (a GitHub Actions job).
            status = row.get("status")
            conclusion = row.get("conclusion")
            if status is not None and status != "COMPLETED":
                pending_legs.append(name)
                continue
            if conclusion in _PASSING_CONCLUSIONS:
                continue
            leg = {
                "name": name,
                "workflow": workflow,
                "conclusion": conclusion or "unknown",
                "detailsUrl": details_url,
            }
            if superseded_flags[i]:
                superseded.append(leg)
                continue
            failing.append(leg)
        else:
            # StatusContext shape (a legacy commit-status check -- Codecov,
            # a preview-deploy bot, anything posted via the Statuses API
            # rather than Actions). No `status`/`conclusion` keys exist on
            # this row at all, only `state`; reading the CheckRun keys above
            # would read both as `None` and misclassify every passing
            # legacy check as a failure (#1086 self-review finding).
            state_value = row.get("state")
            if state_value in _PASSING_STATUS_CONTEXT_STATES:
                continue
            if state_value in _PENDING_STATUS_CONTEXT_STATES:
                pending_legs.append(name)
                continue
            leg = {
                "name": name,
                "workflow": workflow,
                "conclusion": state_value or "unknown",
                "detailsUrl": details_url,
            }
            if superseded_flags[i]:
                superseded.append(leg)
                continue
            failing.append(leg)

    workflows_checked = True
    if declared_workflows is None and workflows_dir is not None:
        declared_workflows, workflows_checked = _declared_pr_workflow_names(
            workflows_dir
        )
    missing_workflows = (
        sorted((declared_workflows or set()) - seen_workflows)
        if workflows_checked
        else None
    )

    if failing:
        state = STATE_RED
        for leg in failing:
            leg["log_line"] = _failure_log_line(gh, run, leg.get("detailsUrl"))
    elif pending_legs:
        state = STATE_PENDING
    else:
        state = STATE_GREEN

    # #1400: a workflow run can exist on this commit with no job reported
    # yet -- the rollup is simply short of rows for it, indistinguishable
    # from those rows having passed once only the exit code is read. Only
    # worth asking when the rollup alone would otherwise read GREEN: a
    # RED or PENDING verdict is already correct and an unresolved run
    # cannot make it more so.
    unresolved_runs = []
    if state == STATE_GREEN:
        owner, repo = _owner_repo(payload.get("url"))
        unresolved_runs = _unresolved_runs(
            gh, run, owner, repo, sha, _rollup_run_ids(rows)
        )
        if unresolved_runs:
            state = STATE_PENDING

    return {
        "pr": number,
        "branch": branch,
        "sha": sha,
        "state": state,
        "failing": failing,
        "pending_legs": pending_legs,
        "missing_workflows": missing_workflows,
        "unresolved_runs": unresolved_runs,
        "superseded": superseded,
    }


def scan(numbers, gh, run, workflows_dir=None, declared_workflows=None):
    """Scan ``numbers`` in order; return the first entry that is not
    pending, or ``None`` if every one of them is. This is the whole
    contract -- no aggregate is ever computed, per the maintainer's own
    comments superseding the issue body's original precedence table.
    """
    for number in numbers:
        entry = read_pr(
            number,
            gh,
            run,
            workflows_dir=workflows_dir,
            declared_workflows=declared_workflows,
        )
        if entry["state"] == STATE_PENDING:
            continue
        return entry
    return None


def wait_for_first_actionable(
    numbers,
    gh,
    run,
    workflows_dir=None,
    declared_workflows=None,
    interval=45,
    timeout=None,
    sleep=time.sleep,
    clock=time.monotonic,
):
    """Poll ``scan`` while every named pull request is still pending; return
    the instant any one of them is not. Returns ``None`` only when
    ``timeout`` expired with every pull request still pending -- the
    caller's cue to hand back `TICK: paused` naming the exact re-invocation.
    """
    start = clock()
    while True:
        entry = scan(
            numbers,
            gh,
            run,
            workflows_dir=workflows_dir,
            declared_workflows=declared_workflows,
        )
        if entry is not None:
            return entry
        if timeout is not None and (clock() - start) >= timeout:
            return None
        sleep(interval)


def list_open_pr_numbers(gh, run, repo=None):
    """``(sorted_numbers, None)`` or ``(None, detail)`` -- #1086's `--all-open`."""
    args = ["pr", "list", "--state", "open", "--json", "number"]
    if repo:
        args = ["-R", repo] + args
    out, _err, detail = _gh(gh, args, run)
    if out is None:
        return None, detail
    try:
        rows = json.loads(out)
    except ValueError as exc:
        return None, "could not parse `gh pr list` output: {0}".format(exc)
    try:
        numbers = sorted(int(row["number"]) for row in rows)
    except (KeyError, TypeError, ValueError) as exc:
        return None, "unexpected `gh pr list` shape: {0}".format(exc)
    return numbers, None


def _superseded_disclosure(entry):
    """One line per superseded leg, appended to any rendered state -- a
    later run of the same check name replaced it, so it is not counted in
    `failing` above, but it is unretractable (no trigger withdraws a
    concluded run) and is named here rather than dropped (#1458, mirroring
    supertool's own `_checks.superseded_disclosure`, #1792)."""
    lines = []
    for leg in entry.get("superseded") or []:
        lines.append(
            "\n  superseded {0} (workflow: {1}, conclusion: {2}) -- a later "
            "run of the same name superseded it".format(
                _flatten(leg["name"]),
                _flatten(leg.get("workflow") or "?"),
                leg["conclusion"],
            )
        )
    return "".join(lines)


def _render(entry):
    if entry["state"] == STATE_COULD_NOT_READ:
        return "#{0} | COULD-NOT-READ | {1}".format(
            entry["pr"], _flatten(entry.get("detail", "unknown"))
        )
    if entry["state"] == STATE_GREEN:
        line = "#{0} | GREEN | branch: {1} | sha: {2}".format(
            entry["pr"], entry["branch"], entry["sha"]
        )
        if entry["missing_workflows"]:
            line += "\n  unknown (produced no run): {0}".format(
                ", ".join(entry["missing_workflows"])
            )
        elif entry["missing_workflows"] is None:
            line += "\n  could not determine whether every declared workflow ran"
        if entry.get("unresolved_runs") is None:
            line += (
                "\n  could not determine whether every run on this commit has started"
            )
        line += _superseded_disclosure(entry)
        return line
    if entry["state"] == STATE_RED:
        lines = [
            "#{0} | RED | branch: {1} | sha: {2}".format(
                entry["pr"], entry["branch"], entry["sha"]
            )
        ]
        for leg in entry["failing"]:
            lines.append(
                "  FAILED {0} (workflow: {1}, conclusion: {2})".format(
                    _flatten(leg["name"]),
                    _flatten(leg.get("workflow") or "?"),
                    leg["conclusion"],
                )
            )
            if leg.get("log_line"):
                lines.append("    {0}".format(leg["log_line"]))
        return "\n".join(lines) + _superseded_disclosure(entry)
    # STATE_PENDING
    # #1113 self-review: `pending_legs` entries come from the identical
    # forge-controlled `name`/`context` source as `leg["name"]` above --
    # flattened for the same reason.
    still_running = [_flatten(leg) for leg in entry.get("pending_legs", [])]
    # #1400: a run that exists on this commit but has produced no job yet is
    # also why this is PENDING rather than GREEN, even when `pending_legs`
    # itself is empty (every rollup row that DID arrive already concluded).
    still_running.extend(
        "{0} (no job yet)".format(_flatten(name))
        for name in entry.get("unresolved_runs", [])
    )
    return "#{0} | PENDING | branch: {1} | sha: {2} | still running: {3}".format(
        entry["pr"],
        entry.get("branch", "?"),
        entry.get("sha", "?"),
        ", ".join(still_running) or "(rollup not yet reported)",
    ) + _superseded_disclosure(entry)


def main(argv=None, run=None):
    run = subprocess.run if run is None else run
    parser = argparse.ArgumentParser(
        description=(
            "One call, several pull requests: scan in order, stop at the first "
            "one that is not pending, exit with that state's code. "
            "green=0 red=1 pending=2 could-not-read=3."
        )
    )
    parser.add_argument(
        "numbers", nargs="*", type=int, help="pull request numbers, in scan order"
    )
    parser.add_argument(
        "--all-open", action="store_true", help="scan every open pull request"
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="poll while every named pull request is pending; return on the first that is not",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=45.0,
        help="seconds between polls (default 45)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="give up after this many seconds and exit pending (default: no timeout)",
    )
    parser.add_argument(
        "--gh", default=None, help="the gh executable (default: the one on PATH)"
    )
    parser.add_argument("--repo", default=None, help="OWNER/NAME, passed to gh as -R")
    parser.add_argument(
        "--project-dir",
        default=".",
        help="repo root, used only to find .github/workflows for the missing-workflow check",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="also emit the winning entry as JSON on stdout",
    )
    args = parser.parse_args(argv)

    if not args.numbers and not args.all_open:
        parser.error("give at least one pull request number, or pass --all-open")

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    # #1157: `gh_which.safe_which`, not `shutil.which` directly -- see that
    # module's docstring for why a `path=` argument does not close the gap.
    gh = args.gh or gh_which.safe_which("gh")
    if not gh:
        sys.stdout.write("COULD-NOT-READ | gh is not on PATH\n")
        return EXIT_CODES[STATE_COULD_NOT_READ]

    numbers = args.numbers
    if args.all_open:
        numbers, detail = list_open_pr_numbers(gh, run, repo=args.repo)
        if numbers is None:
            sys.stdout.write("COULD-NOT-READ | --all-open: {0}\n".format(detail))
            return EXIT_CODES[STATE_COULD_NOT_READ]
        if not numbers:
            sys.stdout.write("GREEN | no open pull requests\n")
            return EXIT_CODES[STATE_GREEN]

    workflows_dir = os.path.join(str(args.project_dir), ".github", "workflows")

    if args.wait:
        entry = wait_for_first_actionable(
            numbers,
            gh,
            run,
            workflows_dir=workflows_dir,
            interval=args.interval,
            timeout=args.timeout,
        )
        if entry is None:
            sys.stdout.write(
                "PENDING | timed out after {0}s with every named pull request still "
                "pending: {1}\n".format(
                    args.timeout, ", ".join(str(n) for n in numbers)
                )
            )
            return EXIT_CODES[STATE_PENDING]
    else:
        entry = scan(numbers, gh, run, workflows_dir=workflows_dir)
        if entry is None:
            sys.stdout.write(
                "PENDING | every named pull request is still pending: {0}\n".format(
                    ", ".join(str(n) for n in numbers)
                )
            )
            return EXIT_CODES[STATE_PENDING]

    sys.stdout.write(_render(entry) + "\n")
    if args.json:
        sys.stdout.write(json.dumps(entry) + "\n")
    return EXIT_CODES[entry["state"]]


if __name__ == "__main__":
    sys.exit(main())
