#!/usr/bin/env python3
"""Three threshold routes for `bin/oss-workspace`'s job 2 (#1155): /oss:triage,
/oss:curate and /oss:release, each a standing count crossing a per-repo
threshold.

Both of `bin/oss-workspace`'s built routes today decide the next prompt from a
fact about the *tooling* (has the plugin moved, is the setup diagnostic
clean). Neither is a fact about the repository's own work. This module adds
three routes that are: open issues missing a `lane-*` or `priority-*` label,
`trap.d/` fragments waiting for `/oss:curate`, and `changelog.d/` fragments
waiting for `/oss:release`.

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
never by which check happened to run first: a release folds fragments and
moves the tag; a triage pass changes what the next tick can see; curate
changes nothing downstream. `ROUTES` below is that order.

## The receipt

A count stuck `over` threshold is the same shape as a WARN nobody can
clear (#1064's own incident): without a receipt, 11 uncurated traps would
pin every launch to `/oss:curate` forever. `oss_state.workspace_route_
check` arms a route only when its signature (state plus count) has moved
since the last receipt recorded for that route -- every failure to compare
fails OPEN, arming as though no receipt exists, the same direction every
other unknown in `bin/oss-workspace` fails.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_which  # noqa: E402
import oss_config  # noqa: E402
import oss_state  # noqa: E402
import release_version  # noqa: E402
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
ROUTES = ("release", "triage", "curate")

PROMPT_FOR_ROUTE = {
    "release": "/oss:release",
    "triage": "/oss:triage",
    "curate": "/oss:curate",
}

#: The one per-repo fact each route reads from `.oss.json`. Absent means the
#: repository declares it does not want the route.
THRESHOLD_KEY = {
    "release": "release_route_threshold",
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


def curate_count(repo_root, config=None, run=subprocess.run, git_bin=None):
    """(count_or_None, why). `count` is `None` only on `could-not-read`.

    #1476: a shared checkout can be standing on any branch when this runs,
    and `trap.d/` at that branch's own working tree is not the same fact as
    `trap.d/` on the repository's own default branch -- the incident this
    closes had a curate commit already pushed to `main` while the checkout
    itself had meanwhile moved to a feature branch cut before that commit,
    and this reported the stale branch's own leftover fragments as though
    they were `main`'s.

    So: when `config` names a `default_branch`, this decides which tree to
    read by first asking which branch is actually checked out, and never
    guesses:

    - the checkout IS the default branch -> read the working tree
      (`trap_curate.waiting`), so a just-committed, not-yet-pushed curate
      run stays visible before it is pushed;
    - the checkout is standing on some OTHER, known branch -> read
      `origin/<default_branch>`'s own committed tree via `git ls-tree`
      (`trap_curate.waiting_at_ref`) instead of the working directory --
      never the wrong branch's disk state;
    - the current branch could not even be determined (self-review
      finding, Explore reviewer, #1476: an earlier version of this
      function fell back to the working-tree read here too, silently
      reintroducing the exact bug this closes whenever `git rev-parse
      --abbrev-ref HEAD` itself failed to run) -> `could-not-count`,
      never a guessed read of whichever tree happens to be on disk. This
      module's own docstring already states the rule this follows: "a
      repository this could not look at must not read the same as one
      that is genuinely fine."

    When no `default_branch` is configured at all, this preserves the
    function's original, no-config-passed behaviour -- an unconditional
    working-tree read -- used by every existing caller that does not
    supply one."""
    default_branch = (config or {}).get("default_branch")
    if isinstance(default_branch, str) and default_branch.strip():
        current, why = _current_branch(repo_root, run=run, git_bin=git_bin)
        if current is None:
            return None, (
                "the checked-out branch could not be determined, so whether "
                "trap.d/ belongs to {0} could not be told ({1})".format(
                    default_branch, why
                )
            )
        if current != default_branch:
            result = trap_curate.waiting_at_ref(
                repo_root,
                "origin/{0}".format(default_branch),
                run=run,
                git_bin=git_bin,
            )
            if result["state"] == "could-not-read":
                return None, result["why"]
            return result["count"], result["why"]
    result = trap_curate.waiting(repo_root)
    if result["state"] == "could-not-read":
        return None, result["why"]
    return result["count"], result["why"]


def release_count(repo_root, config):
    """(count_or_None, why). Reuses `release_version._fragment_dir` (the
    three ways `changelog_dir` reaches a directory) and `release_version.
    _scan` (every fragment present, regardless of whether it validates) --
    the raw file count is the same one `release_version.compute` reads to
    propose a number, without needing a baseline version to do it."""
    directory, problem = release_version._fragment_dir(repo_root, None, config)
    if directory is None:
        return None, problem
    scan, error = release_version._scan(directory)
    if scan is None:
        return None, error
    return scan["count"], "{0} fragment(s) in {1}".format(scan["count"], directory)


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
        elif name == "release":
            count, why = release_count(repo_root, config)
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
