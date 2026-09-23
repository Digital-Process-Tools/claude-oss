#!/usr/bin/env python3
"""Two threshold routes, read by `next_action.py`'s own `rank()` (#1155):
/oss:triage and /oss:curate, each a standing count crossing a per-repo
threshold.

`bin/oss-workspace` used to call this module directly for its own job-2
routing; #1389/#1390/#1392 removed that call, and job 2 now lives entirely
in `next_action.py`'s `rank()` (see `docs/open-the-workspace.md`'s "Job 2
moved" section). This module's own routes are: open issues missing a
`lane-*` or `priority-*` label, and `trap.d/` fragments waiting for
`/oss:curate`.

This used to be a third route too -- `release`, counting `changelog.d/`
fragments waiting for `/oss:release`. #1652 removed it: `next_action.py`'s
`_release_candidate` never took `routes` as an argument and never read this
route's counted value at all, `release_trigger.py` already owns whether a
release is due with its own richer fired/not-fired/could-not-tell
vocabulary, and does not need the repeat-suppression receipt `curate`/
`triage` both do -- a threshold layered on top would have been redundant,
not complementary.

## The states

Every count is one of three, never a bare number:

  over               the count is strictly greater than this repo's own
                      configured threshold.
  under               the count is at or below it.
  could-not-count    the count could not be taken at all -- `gh` is not on
                      PATH, the network call failed, the directory could
                      not be listed. Never collapses into `under`: a
                      repository this could not look at must not read the
                      same as one that is genuinely fine.

A route with **no configured threshold is not evaluated at all** -- an
absent `.oss.json` key means this repository does not want the route,
the same rule `changelog_untagged` and `user_visible_paths` already use.

## Precedence

More than one route can be `over` at once. Ranked by what blocks the most,
never by which check happened to run first: a triage pass changes what the
next tick can see; curate changes nothing downstream. `ROUTES` below is
that order.

## The receipt

A count stuck `over` threshold is the same shape as a WARN nobody can
clear (#1064's own incident): without a receipt, 11 uncurated traps would
pin every launch to `/oss:curate` forever. `oss_state.workspace_route_
check` arms a route only when its signature (state plus count) has moved
since the last receipt recorded for that route -- every failure to compare
fails OPEN, arming as though no receipt exists, the same direction every
other unknown in this repository's own loop fails.

## What this deliberately does not do

**Not a second scheduler.** This picks the first command of one session;
tick ordering stays in `skills/manager/phases/tick-order.md`.

**Not the three states #1155 explicitly declines to design**: a red or
pending default branch, a green pull request waiting to merge, lanes
already running. None of those is a standing count crossing a threshold,
so the shape here does not fit them.

Python 3.9 compatible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_which  # noqa: E402
import oss_config  # noqa: E402
import oss_state  # noqa: E402
import trap_curate  # noqa: E402


def _flatten(text):
    """#1257: `why` can carry text this loop did not generate itself --
    `gh`'s own stderr, read verbatim in `triage_count` -- collapsed onto
    one line before `main` prints it into a line-structured receipt
    `bin/oss-workspace` parses with `awk '/^ROUTE:/ { line = $0 } END {
    print line }'`. Unflattened, an embedded newline puts forge-supplied
    text at column 0 of the next printed line, where a line shaped like
    `ROUTE: <something>` reads as a second, unrelated `ROUTE:` line --
    the identical mechanism `pr_green._flatten` was written for (#1113).
    #1263 widened the same guard to every other value `main` interpolates
    into a printed line, regardless of provenance -- `result["threshold"]`
    (a repository-supplied `.oss.json` value, not `gh` output) and the
    `.oss.json` load-error `problems` list, neither of which is `gh`
    stderr, but both reach the same `awk`-parsed print."""
    return " ".join(str(text).split())


OVER = "over"
UNDER = "under"
COULD_NOT_COUNT = "could-not-count"

#: Most-blocking first (#1155's own argument -- see the module docstring).
#: Ties (more than one route `over` at once) are broken by this order.
#: #1652 removed the third entry this used to carry, `"release"` -- see the
#: module docstring's own "used to be a third route too" paragraph.
ROUTES = ("triage", "curate")

PROMPT_FOR_ROUTE = {
    "triage": "/oss:triage",
    "curate": "/oss:curate",
}

#: The one per-repo fact each route reads from `.oss.json`. Absent means the
#: repository declares it does not want the route.
THRESHOLD_KEY = {
    "triage": "triage_route_threshold",
    "curate": "curate_route_threshold",
}


def _decode(raw):
    """Decode a subprocess's bytes for display. Never raises. Same shape as
    `cohort_freeze._decode_output` -- an issue label or a `gh` stderr line is
    free text someone else authored, the one place a byte the runner's
    locale cannot decode is ordinary rather than exotic."""
    if raw is None:
        return ""
    if not isinstance(raw, bytes):
        return raw
    return raw.decode("utf-8", "replace")


def _count_state(count, threshold):
    if count is None:
        return COULD_NOT_COUNT
    return OVER if count > threshold else UNDER


def _current_branch(repo_root, run=subprocess.run, git_bin=None, timeout=10):
    """(branch_name_or_None, why_or_None). `None` on a detached HEAD, on a
    `git` failure, or when `git` cannot be run at all -- never a guessed
    branch name."""
    command = [
        git_bin or "git",
        "-C",
        str(repo_root),
        "rev-parse",
        "--abbrev-ref",
        "HEAD",
    ]
    try:
        done = run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "{0} did not run ({1})".format(" ".join(command), exc)
    if done.returncode != 0:
        message = (_decode(done.stderr) or _decode(done.stdout)).strip()
        return None, "{0} failed: {1}".format(
            " ".join(command), message or "exit {0}".format(done.returncode)
        )
    branch = _decode(done.stdout).strip()
    if not branch or branch == "HEAD":
        return None, "HEAD is detached, so no current branch name is available"
    return branch, None


#: `_fetch_head_age_seconds`'s three states (self-review finding, oss:auditor,
#: #1522). The first version collapsed a genuine "this checkout has never run
#: `git fetch`" into the exact same `None` as "the `git` call that would have
#: told me that itself failed to run" -- rendering both as the identical "no
#: fetch recorded" text, this repository's own named defect class (an absence
#: the tool produced read as an absence in the world). `_current_branch`,
#: right above this in the same file, already avoids the analogous mistake for
#: branch detection; this mirrors that three-way split rather than repeating
#: the two-way one.
_FETCH_KNOWN = "known"
_FETCH_ABSENT = "absent"
_FETCH_COULD_NOT_TELL = "could-not-tell"


def _fetch_head_age_seconds(repo_root, run=subprocess.run, git_bin=None, timeout=15):
    """(state, age_or_None). `git fetch` writes `FETCH_HEAD` on every run,
    whether or not any ref actually moved -- unlike a remote-tracking ref
    itself, which git only rewrites when its value changes -- so this is
    "how long since this checkout last even asked the remote", which is
    the freshness question #1522 names, not "how long since
    origin/<default_branch> last moved".

    `_FETCH_KNOWN` is the only state carrying a real `age_or_None`
    (seconds since `FETCH_HEAD`'s mtime). `_FETCH_ABSENT` means the git
    directory WAS resolved and `FETCH_HEAD` genuinely does not exist
    there -- an honest "never fetched". `_FETCH_COULD_NOT_TELL` covers
    every way this could not even ask the question: `git` missing from
    PATH or failing to spawn, `rev-parse --git-dir` exiting non-zero or
    printing nothing, or `FETCH_HEAD`'s own `stat()` failing for a reason
    other than not existing (a permission error, say)."""
    command = [git_bin or "git", "-C", str(repo_root), "rev-parse", "--git-dir"]
    try:
        done = run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return _FETCH_COULD_NOT_TELL, None
    if done.returncode != 0:
        return _FETCH_COULD_NOT_TELL, None
    raw = _decode(done.stdout).strip()
    if not raw:
        return _FETCH_COULD_NOT_TELL, None
    git_dir = Path(raw)
    if not git_dir.is_absolute():
        git_dir = Path(repo_root) / git_dir
    try:
        mtime = (git_dir / "FETCH_HEAD").stat().st_mtime
    except FileNotFoundError:
        return _FETCH_ABSENT, None
    except OSError:
        return _FETCH_COULD_NOT_TELL, None
    return _FETCH_KNOWN, max(0, int(time.time() - mtime))


def _with_fetch_freshness(why, repo_root, run, git_bin):
    """Append a freshness note to an `origin/<default_branch>` reading's
    own `why` (#1522): the reading is only as fresh as this checkout's
    last `git fetch`, and nothing on this path fetches, so a caller
    comparing two readings taken minutes apart has no way to tell a
    genuinely fresh one from a stale one without this. Three states, not
    two (self-review finding, oss:auditor) -- see `_fetch_head_age_seconds`."""
    state, age = _fetch_head_age_seconds(repo_root, run=run, git_bin=git_bin)
    if state == _FETCH_KNOWN:
        return "{0} (last fetched {1}s ago)".format(why, age)
    if state == _FETCH_ABSENT:
        return (
            "{0} (no fetch recorded in this checkout, so freshness is unknown)".format(
                why
            )
        )
    return "{0} (fetch freshness could not be determined)".format(why)


def curate_count(repo_root, config=None, run=subprocess.run, git_bin=None):
    """(count_or_None, why). `count` is `None` only on `could-not-read`.

    #1723: a lane, the releaser, and `worktree_reap.py`'s own
    `harvest_fragments` all write `trap.d/*.md` fragments straight into the
    clone's working tree as a plain filesystem copy -- no `git add`, no
    commit. Those fragments are untracked on EVERY branch, not just
    whichever one happens to be checked out, and a fresh `/oss:curate`
    worktree (`git worktree add ... origin/<default_branch>`) starts from
    committed history only, so it can never see them either way. The
    #1476 version of this function only counted them when the checkout WAS
    the default branch, which reported a number `/oss:curate` itself could
    never match on any branch other than that one -- the disagreement
    #1723 is about.

    So: when `config` names a `default_branch`, the count is always the
    union of two reads:

    - `origin/<default_branch>`'s own committed tree via `git ls-tree`
      (`trap_curate.waiting_at_ref`, unchanged from #1476);
    - a SECOND read that depends on which branch is actually checked out,
      never guessed (#1476's own original branch check, preserved rather
      than removed -- an #1723 self-review finding, both a spawned
      `Explore` reviewer and `oss:auditor` independently reproduced the
      regression the first version of this fix introduced by dropping it:
      a fragment `git add`ed or even committed on the default branch
      itself, but not yet pushed to `origin`, is neither `origin/
      <default_branch>`'s tree nor untracked -- it would have silently
      stopped counting at all):

      - the checkout IS the default branch -> the clone's own full working
        tree (`trap_curate.waiting`, tracked and untracked both), so a
        just-committed-but-not-yet-pushed fragment stays visible exactly
        as #1476 first established;
      - the checkout is standing on some OTHER, known branch ->
        `trap_curate.untracked_fragments` (#1723) -- untracked-ness is a
        fact about the index, not about HEAD, so a `harvest_fragments`-
        style stray sitting in the clone counts here too, on whichever
        branch happens to be checked out;
      - the current branch could not even be determined -> `could-not-
        count`, never a guessed read of whichever tree happens to be on
        disk (unchanged from #1476: `curate_count`'s own module already
        states the rule this follows -- "a repository this could not look
        at must not read the same as one that is genuinely fine").

    Either read failing is `could-not-count` -- never a guessed read of
    only the half that succeeded. #1522: nothing on the ref-read path
    fetches, so `why` also carries how long ago this checkout's last `git
    fetch` ran (`_with_fetch_freshness`).

    When no `default_branch` is configured at all, this preserves the
    function's original, no-config-passed behaviour -- an unconditional
    working-tree read -- used by every existing caller that does not
    supply one. The working-tree path carries no fetch-freshness note:
    it never reads `origin/*` at all, so there is nothing to date."""
    default_branch = (config or {}).get("default_branch")
    if isinstance(default_branch, str) and default_branch.strip():
        ref_result = trap_curate.waiting_at_ref(
            repo_root,
            "origin/{0}".format(default_branch),
            run=run,
            git_bin=git_bin,
        )
        if ref_result["state"] == "could-not-read":
            return None, ref_result["why"]
        current, branch_why = _current_branch(repo_root, run=run, git_bin=git_bin)
        if current is None:
            return None, (
                "the checked-out branch could not be determined, so whether an "
                "untracked or not-yet-pushed fragment belongs to {0} could not "
                "be told ({1})".format(default_branch, branch_why)
            )
        if current == default_branch:
            extra_result = trap_curate.waiting(repo_root)
            extra_label = "in the clone's own working tree (tracked or untracked)"
        else:
            extra_result = trap_curate.untracked_fragments(
                repo_root, run=run, git_bin=git_bin
            )
            extra_label = "untracked in the clone's own working tree"
        if extra_result["state"] == "could-not-read":
            return None, extra_result["why"]
        combined = {f["name"] for f in ref_result["fragments"]} | {
            f["name"] for f in extra_result["fragments"]
        }
        why = "{0} fragment(s) at origin/{1} plus {2} {3} = {4} total".format(
            len(ref_result["fragments"]),
            default_branch,
            len(extra_result["fragments"]),
            extra_label,
            len(combined),
        )
        return len(combined), _with_fetch_freshness(why, repo_root, run, git_bin)
    result = trap_curate.waiting(repo_root)
    if result["state"] == "could-not-read":
        return None, result["why"]
    return result["count"], result["why"]


def triage_count(repo, gh, run, timeout=25):
    """(count_or_None, why). `repo` is `.oss.json`'s own `owner/name`
    string. The count is the LARGER of "open issues with no `lane-*`
    label" and "open issues with no `priority-*` label" -- either alone
    means the board is lying about at least one issue, and the launcher's
    own route exists to say so, not to average the two away."""
    if not repo or not str(repo).strip():
        return None, "no repo configured, so open issues could not be listed"
    if not gh:
        return None, "gh is not on PATH, so open issues could not be listed"
    command = [
        gh,
        "issue",
        "list",
        "--repo",
        str(repo),
        "--state",
        "open",
        "--limit",
        "500",
        "--json",
        "number,labels",
    ]
    try:
        done = run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "{0} did not run ({1})".format(" ".join(command), exc)
    stdout = _decode(done.stdout)
    stderr = _decode(done.stderr)
    if done.returncode != 0:
        message = (stderr or stdout or "").strip()
        return None, "{0} failed: {1}".format(" ".join(command), message)
    try:
        issues = json.loads(stdout)
    except (ValueError, TypeError):
        return None, "{0} printed text that is not JSON".format(" ".join(command))
    if not isinstance(issues, list):
        return None, "{0} printed JSON that is not a list".format(" ".join(command))
    no_lane = 0
    no_priority = 0
    for issue in issues:
        labels = issue.get("labels") if isinstance(issue, dict) else None
        names = (
            [entry.get("name", "") for entry in labels if isinstance(entry, dict)]
            if isinstance(labels, list)
            else []
        )
        if not any(name.startswith("lane-") for name in names):
            no_lane += 1
        if not any(name.startswith("priority-") for name in names):
            no_priority += 1
    count = max(no_lane, no_priority)
    return count, "{0} of {1} open issue(s) missing lane-* or priority-*".format(
        count, len(issues)
    )


def _valid_threshold(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def decide(repo_root, config, gh=None, run=subprocess.run, git_bin=None):
    """Every route's own state, plus which one (if any) is armed to fire,
    in precedence order. Returns ``(armed_route_or_None, results)``, where
    ``results`` maps each name in `ROUTES` to a dict carrying at least
    ``configured`` (bool), and, when configured, ``state``/``count``/
    ``threshold``/``why``.

    `git_bin` (#1476) is resolved through `gh_which.safe_which` once here,
    the same way `gh` already is below, and threaded into `curate_count` so
    it can tell which branch the checkout is standing on."""
    gh = gh if gh is not None else gh_which.safe_which("gh")
    git_bin = git_bin if git_bin is not None else gh_which.safe_which("git")
    repo = (config or {}).get("repo")
    results = {}

    for name in ROUTES:
        threshold = (config or {}).get(THRESHOLD_KEY[name])
        if threshold is None:
            results[name] = {"configured": False}
            continue
        if not _valid_threshold(threshold):
            results[name] = {
                "configured": True,
                "state": COULD_NOT_COUNT,
                "count": None,
                "threshold": threshold,
                "why": (
                    "{0} is {1!r}, not a usable non-negative integer threshold".format(
                        THRESHOLD_KEY[name], threshold
                    )
                ),
            }
            continue
        if name == "curate":
            count, why = curate_count(
                repo_root, config=config, run=run, git_bin=git_bin
            )
        else:
            count, why = triage_count(repo, gh, run)
        results[name] = {
            "configured": True,
            "state": _count_state(count, threshold),
            "count": count,
            "threshold": threshold,
            "why": why,
        }

    armed_route = None
    for name in ROUTES:
        if results[name].get("state") == OVER:
            armed_route = name
            break
    return armed_route, results


def _now():
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Decide whether /oss:triage, /oss:curate or /oss:release should "
            "be this launch's opening prompt (#1155)."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        help="the repository root to evaluate (its .oss.json and .oss.local.json)",
    )
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    config, problems = oss_config.load(os.path.join(args.root, ".oss.json"))
    if config is None:
        print(
            "COULD-NOT-DECIDE: .oss.json could not be read ({0})".format(
                _flatten("; ".join(problems)) if problems else "unknown reason"
            )
        )
        return 3

    armed_route, results = decide(args.root, config)

    for name in ROUTES:
        result = results[name]
        if not result.get("configured"):
            print("{0}: not-configured".format(name))
            continue
        print(
            "{0}: {1} (count={2}, threshold={3}) -- {4}".format(
                name,
                result["state"],
                result["count"],
                _flatten(result["threshold"]),
                _flatten(result["why"]),
            )
        )

    if armed_route is None:
        print("ROUTE: none")
        return 0

    state_file = config.get("state_file")
    record_path = os.path.join(args.root, state_file) if state_file else None
    result = results[armed_route]
    signature = "{0}:{1}".format(result["state"], result["count"])

    if record_path is None:
        print(
            "ROUTE: {0} (no-receipt -- this repo's state_file is not "
            "configured, so whether this exact state already fired could "
            "not be told)".format(armed_route)
        )
        return 0

    try:
        _entry, prior_signature = oss_state._last_workspace_route(
            record_path, armed_route
        )
        check = oss_state.workspace_route_check(armed_route, signature, prior_signature)
    except Exception as exc:  # noqa: BLE001 -- fail open, name why
        print(
            "ROUTE: {0} (whether this exact state already fired could not "
            "be told: {1}: {2}; routing as though it has not)".format(
                armed_route, type(exc).__name__, _flatten(exc)
            )
        )
        return 0

    if not check["armed"]:
        print(
            "ROUTE: none (unchanged since the receipt already recorded for "
            "{0}'s {1})".format(armed_route, signature)
        )
        return 0

    print("ROUTE: {0} ({1})".format(armed_route, check["state"]))
    try:
        oss_state.append(
            record_path,
            _now(),
            "oss-workspace: recorded a #1155 route receipt",
            detail={
                "workspace_route_name": armed_route,
                "workspace_route_signature": signature,
            },
        )
    except Exception as exc:  # noqa: BLE001 -- announced, never raised
        print(
            "ROUTE-RECEIPT-ERROR: the receipt could not be recorded ({0}: "
            "{1}), so the next launch will not see this one.".format(
                type(exc).__name__, _flatten(exc)
            ),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
