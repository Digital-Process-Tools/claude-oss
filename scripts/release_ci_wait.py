#!/usr/bin/env python3
"""Wait for one commit's own CI to conclude before it is tagged -- #1266.

`v0.27.0` was tagged and published at `fb73907` before that commit's own
`tests` run had even started -- it concluded RED four minutes later, on
every non-CodeQL leg, on all three operating systems. Gates 1-6
(`skills/manager/phases/release.md`, `commands/release.md`) verify the
default branch is green *before* the release commit is written -- the right
check for the delta being released. It says nothing about the release
commit's own content: the folded `CHANGELOG.md`, the rewritten version
sites, the rewritten `CLAUDE.md` marker paragraph. This module is that
missing check: wait for the release commit's own run to conclude before a
tag is created and pushed.

Mirrors `pr_green.py`'s shape (#1086) rather than inventing a new one -- a
pull request has a check rollup a caller can wait on; a commit pushed
straight to the default branch has runs `gh run list --commit SHA` lists
instead, one row per workflow *run* (not per workflow name -- #1640's own
lesson, carried over: two runs can share one workflowName). This module
calls `gh` directly through `subprocess`, not through the Bash tool the
raw-command guard hooks, so a caller can actually `--wait` on it from inside
one call -- the same reason `pr_green.py` does.

## The four states

  green            every run on this commit concluded and passed.
  red              at least one run failed, or completed with a conclusion
                    this module has never seen (an unrecognised conclusion
                    is a finding, never a silent pass) -- including
                    `cancelled`, since a concurrency-superseded run is not a
                    green run (#1266's own second named requirement).
                    Reported the instant it is seen, even with a pending
                    sibling still running.
  pending          every run is still queued or running, or nothing has
                    shown up for this commit yet at all. A workflow run is
                    not created the instant a commit is pushed, so an empty
                    list must read as `pending` -- never `red` (nothing to
                    fail yet) and never `green` (nothing passed either).
                    This is `v0.27.0`'s own failure mode, the check
                    inverted: it was tagged while its own rollup was still
                    exactly this shape.
  could-not-read   the read itself failed -- `gh` unreachable, non-zero
                    exit, output this module could not parse. Never folded
                    into `pending` (spins a wait forever on a commit nobody
                    can read) and never into `green` (a tag cut over a run
                    nobody confirmed) -- this repository's own named defect
                    class, applied to one call.

`--wait` polls while the commit is `pending`; on timeout it returns `None`
rather than any of the four states above, so a caller cannot mistake "gave
up waiting" for a real conclusion of any kind -- a tag is not revocable, so
`pending` at timeout must read exactly like "not yet safe", never like
"safe". `main()` reports that as `PENDING` with its own exit code, the same
way `pr_green.py --wait` does on timeout: the caller is expected to treat a
timed-out wait the same as `red` -- do not tag.

**`git rev-parse HEAD` on the full ref, never abbreviated, before calling
this.** A short sha returns `[]` from `gh run list --commit` and exits 0,
which reads as "no runs" when it actually means "no runs *matched this
truncated sha*" -- this has already cost this loop a round
(`scripts/lane_setup.py`'s own note).

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

from __future__ import annotations

import argparse
import json
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

# `gh run list --json status,conclusion` answers in the Actions REST API's
# own lowercase, snake_case vocabulary -- a different casing from `gh pr
# view`'s `statusCheckRollup` (`COMPLETED`/`SUCCESS`), which `pr_green.py`
# reads. Anything completed but not in this set -- including an unrecognised
# value and `cancelled` -- is treated as failing, the same discipline
# `pr_green.py`'s own `_PASSING_CONCLUSIONS` uses for its own vocabulary.
_PASSING_CONCLUSIONS = frozenset(("success", "neutral", "skipped"))

_RUN_LIST_FIELDS = "workflowName,status,conclusion,headSha,url"


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _flatten(text):
    """#1113's own discipline, carried over: text this module did not
    generate itself -- `gh` stderr, a workflow's own name -- collapsed onto
    one line before it is stitched into a line-structured receipt, so an
    embedded newline cannot read as a second, unrelated row."""
    return " ".join(str(text).split())


def _gh(gh, args, run, timeout=30):
    """Run ``[gh] + args``, returning ``(stdout, detail)``. ``detail`` is
    ``None`` on success; otherwise ``stdout`` is ``None`` and ``detail`` is a
    short human-readable reason -- the same two-outcome shape `pr_green.py`'s
    own `_gh` uses."""
    try:
        done = run(
            [gh] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    stdout = _decode(done.stdout)
    stderr = _decode(done.stderr)
    if done.returncode != 0:
        return None, (stderr.strip() or "gh exit {0}".format(done.returncode))
    return stdout, None


def read_commit(sha, gh, run, repo=None):
    """Read one commit's own workflow runs and classify them.

    ``sha`` should be the full 40-character sha -- see the module docstring
    for why an abbreviated one silently returns no runs rather than failing.
    """
    args = ["run", "list", "--commit", sha, "--json", _RUN_LIST_FIELDS]
    if repo:
        args = ["-R", repo] + args
    out, detail = _gh(gh, args, run)
    if out is None:
        return {"sha": sha, "state": STATE_COULD_NOT_READ, "detail": detail}
    try:
        rows = json.loads(out)
    except ValueError as exc:
        return {
            "sha": sha,
            "state": STATE_COULD_NOT_READ,
            "detail": "could not parse `gh run list` output: {0}".format(exc),
        }
    if not isinstance(rows, list):
        return {
            "sha": sha,
            "state": STATE_COULD_NOT_READ,
            "detail": "unexpected `gh run list` shape (not a list)",
        }

    if not rows:
        return {
            "sha": sha,
            "state": STATE_PENDING,
            "failing": [],
            "pending_runs": [],
        }

    failing = []
    pending_runs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("workflowName") or "?"
        status = row.get("status")
        conclusion = row.get("conclusion")
        if status != "completed":
            pending_runs.append(name)
            continue
        if conclusion in _PASSING_CONCLUSIONS:
            continue
        failing.append(
            {
                "workflow": name,
                "conclusion": conclusion or "unknown",
                "url": row.get("url"),
            }
        )

    if failing:
        state = STATE_RED
    elif pending_runs:
        state = STATE_PENDING
    else:
        state = STATE_GREEN

    return {
        "sha": sha,
        "state": state,
        "failing": failing,
        "pending_runs": pending_runs,
    }


def wait_for_conclusion(
    sha,
    gh,
    run,
    repo=None,
    interval=45,
    timeout=None,
    sleep=time.sleep,
    clock=time.monotonic,
):
    """Poll `read_commit` while the commit is `pending`; return the instant
    it is not. Returns ``None`` only when ``timeout`` expired with the
    commit still `pending` -- the caller's cue to stop rather than tag on a
    guess, the same contract `pr_green.py`'s own `wait_for_first_actionable`
    keeps for pull requests.
    """
    start = clock()
    while True:
        entry = read_commit(sha, gh, run, repo=repo)
        if entry["state"] != STATE_PENDING:
            return entry
        if timeout is not None and (clock() - start) >= timeout:
            return None
        sleep(interval)


def _render(entry):
    if entry["state"] == STATE_COULD_NOT_READ:
        return "COULD-NOT-READ | sha: {0} | {1}".format(
            entry["sha"], _flatten(entry.get("detail", "unknown"))
        )
    if entry["state"] == STATE_GREEN:
        return "GREEN | sha: {0}".format(entry["sha"])
    if entry["state"] == STATE_RED:
        lines = ["RED | sha: {0}".format(entry["sha"])]
        for leg in entry["failing"]:
            lines.append(
                "  FAILED {0} (conclusion: {1})".format(
                    _flatten(leg["workflow"]), leg["conclusion"]
                )
            )
        return "\n".join(lines)
    # STATE_PENDING
    return "PENDING | sha: {0} | still running or not yet created: {1}".format(
        entry.get("sha", "?"),
        ", ".join(_flatten(name) for name in entry.get("pending_runs", []))
        or "(no run has appeared for this commit yet)",
    )


def main(argv=None, run=None):
    run = subprocess.run if run is None else run
    parser = argparse.ArgumentParser(
        description=(
            "Wait for one commit's own CI to conclude before it is tagged. "
            "green=0 red=1 pending=2 could-not-read=3."
        )
    )
    parser.add_argument("--commit", required=True, help="the full 40-character sha")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="poll while the commit is pending; return on the first non-pending read",
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
        "--json",
        action="store_true",
        help="also emit the winning entry as JSON on stdout",
    )
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.commit):
        parser.error(
            "--commit must be the full 40-character sha, not an abbreviation "
            "(an abbreviated sha silently returns no runs from `gh run list "
            "--commit` rather than failing)"
        )

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    gh = args.gh or gh_which.safe_which("gh")
    if not gh:
        sys.stdout.write("COULD-NOT-READ | gh is not on PATH\n")
        return EXIT_CODES[STATE_COULD_NOT_READ]

    if args.wait:
        entry = wait_for_conclusion(
            args.commit,
            gh,
            run,
            repo=args.repo,
            interval=args.interval,
            timeout=args.timeout,
        )
        if entry is None:
            sys.stdout.write(
                "PENDING | timed out after {0}s waiting on {1}\n".format(
                    args.timeout, args.commit
                )
            )
            return EXIT_CODES[STATE_PENDING]
    else:
        entry = read_commit(args.commit, gh, run, repo=args.repo)

    sys.stdout.write(_render(entry) + "\n")
    if args.json:
        sys.stdout.write(json.dumps(entry) + "\n")
    return EXIT_CODES[entry["state"]]


if __name__ == "__main__":
    sys.exit(main())
