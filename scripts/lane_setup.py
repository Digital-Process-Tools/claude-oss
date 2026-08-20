#!/usr/bin/env python3
"""One call for the facts a lane brief hand-carries and that rot before it is read.

#317: every developer brief pastes a base commit and a live-worktree list, both taken
minutes before the brief is written and stale by the time it is read -- `main` has moved
twice within an hour, and a hand-copied worktree list has already flattened `cannot tell`
to `idle` at least once. This script re-derives those facts at the moment they are
needed, mechanically, instead of asking the maintainer to retype a snapshot.

**Not folded in here: the issue itself.** `supertool gh-issue:N:full` already reads it
live at call time, so it does not carry the same staleness defect this script exists to
close, and its size varies from a one-line issue to several thousand characters --
folding it in unconditionally would blow the byte budget below on the same run that
this script was written for (#317's own body ran past 5KB). The granularity call is
made here on purpose, following the issue's own "Not claimed" section: this script owns
the base commit, the branch/worktree derivation, and the worktree board -- the three
facts the issue's own examples are about -- and leaves the issue read as its own call.

Byte budget (#317, measured 2026-08-19): setup-shaped calls among a developer's first
ten average 2 and return a median of 3,904 characters. This script's job is to answer in
*fewer* bytes than the calls it replaces, not merely in fewer calls -- so the worktree
board below is condensed to one line per tree (state, branch, path, merge/dirty bracket)
rather than the full explanatory op output, which runs past 9,000 characters for a
seven-tree board and would be a net loss on its own.

Three states everywhere, never two, because this is the repository that is named after
collapsing them by accident:

  base       resolved (fetched and rev-parsed), resolved-stale (fetched failed, a local
             remote-tracking ref answered anyway -- flagged, never silent), or
             could-not-resolve (neither answered; nothing to brief a lane from).
  branch     resolved (derived from `branch_pattern`) or unknown (no `{issue}`
             placeholder in the pattern -- every issue would get the same branch).
  worktree   resolved, unknown (`.oss.local.json` carries no `worktree_root` --
             expected and absent-by-construction inside every worktree this loop
             cuts, present only in the maintainer's main clone), or invalid (the
             derived path escapes the configured root).
  board      ok (condensed from `supertool git-worktrees`) or could-not-run (supertool
             is not on PATH, or the call itself failed) -- never silently empty.

`git rev-parse` on a full ref, never abbreviated: a short sha returns `[]` from
`gh run list --commit` and exits 0, which has cost this loop a round already
(CLAUDE.md, skills/manager/SKILL.md).

Python 3.9 compatible: no match statements, no `X | Y` annotations.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oss_config  # noqa: E402  (path insert above must run first)

CONFIG_NAME = ".oss.json"
ISSUE_PLACEHOLDER = "{issue}"

EXIT_OK = 0
EXIT_COULD_NOT_RUN = 3


def _one_line(text, limit=200):
    """Text from outside this process, reduced to one printable ASCII line.

    Git's own stderr carries paths and ref names somebody else chose, and the
    condensed board carries branch names contributors chose. A newline in either
    forges a receipt line; a control character can rewrite what a terminal already
    printed. Same shape as `release_delta.py`'s `_one_line`, kept local rather than
    imported: that module is a release gate and this is a setup read, and neither
    should have to change because the other one's contract did.
    """
    flat = " ".join(str(text).split())
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in flat)
    return safe[:limit]


def _git(repo, *args):
    """Run git in `repo`. Returns (returncode, stdout, stderr) and never raises."""
    git = shutil.which("git")
    if git is None:
        return None, "", "git is not on PATH"
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        done = subprocess.run(
            [git, "--no-pager", "-C", str(repo)] + list(args),
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            timeout=120,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return None, "", "{0}: {1}".format(type(exc).__name__, exc)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def resolve_base(repo, remote, default_branch):
    """The commit a lane should be cut from -- fetched and rev-parsed, never abbreviated.

    Three states. `resolved-stale` exists because a failed fetch and a repo with no
    prior fetch at all both leave a remote-tracking ref that might answer -- and
    answering from it without saying the fetch failed is exactly the staleness this
    script exists to stop reproducing.

    #368: `default_branch` is the one value here that reaches git's argv unprefixed --
    `git fetch --quiet <remote> <branch>` reads position 4 as an option when the name
    starts with a dash -- so the verdict `oss_config` already produced for it is
    consulted *before* any argv is built. `oss_config.load()` deliberately returns the
    offending value together with a sentence rather than stripping it, and the defect
    was this consumer treating a loaded config as a usable one. The rule is not
    re-stated here: `default_branch_problem` is called, so one value keeps one rule
    (#345) and a refusal cannot drift from the sentence `doctor` prints for it.

    `branch_occupancy` needs no such guard and that is a property of its argv rather
    than of its input: it prefixes `refs/heads/` and `refs/remotes/`, so a name can
    never occupy the flag position. `tests/test_lane_setup_368.py` measures that
    instead of trusting this sentence.
    """
    problem = oss_config.default_branch_problem(default_branch)
    if problem is not None:
        return {
            "state": "could-not-resolve",
            "remote": remote,
            "ref": None,
            "sha": None,
            "detail": _one_line(problem, 300),
        }

    ref = "{0}/{1}".format(remote, default_branch)
    fetch_code, _, fetch_err = _git(repo, "fetch", "--quiet", remote, default_branch)
    fetched = fetch_code == 0

    code, out, err = _git(repo, "rev-parse", "refs/remotes/" + ref)
    if code == 0 and out:
        return {
            "state": "resolved" if fetched else "resolved-stale",
            "remote": remote,
            "ref": ref,
            "sha": out,
            "detail": "" if fetched else "fetch failed, using the last-known ref: {0}".format(
                _one_line(fetch_err)
            ),
        }
    return {
        "state": "could-not-resolve",
        "remote": remote,
        "ref": ref,
        "sha": None,
        "detail": _one_line(fetch_err if not fetched else err),
    }


def derive_branch(pattern, issue):
    """The branch name for `issue`, from `branch_pattern`. Never invented."""
    if not isinstance(pattern, str) or ISSUE_PLACEHOLDER not in pattern:
        return {
            "state": "unknown",
            "pattern": pattern,
            "name": None,
            "detail": "branch_pattern has no {0} placeholder -- every issue would "
            "resolve to the same branch, so nothing is derived.".format(ISSUE_PLACEHOLDER),
        }
    return {
        "state": "resolved",
        "pattern": pattern,
        "name": pattern.replace(ISSUE_PLACEHOLDER, str(issue)),
        "detail": "",
    }


def branch_occupancy(repo, remote, name):
    """Whether `name` already exists locally or on `remote`. None means unknown."""
    local_code, _, _ = _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + name)
    exists_local = None if local_code is None else local_code == 0

    remote_code, _, _ = _git(
        repo, "show-ref", "--verify", "--quiet", "refs/remotes/{0}/{1}".format(remote, name)
    )
    exists_remote = None if remote_code is None else remote_code == 0
    return exists_local, exists_remote


def derive_worktree(config, issue):
    """The worktree path for `issue`, from `worktree_root` in `.oss.local.json`.

    Absent by construction inside every worktree this loop cuts -- `.oss.local.json`
    is git-excluded, so a lane-setup call run from inside a worktree (rather than the
    main clone) will always land here. That is a real third state, not a bug in this
    function: `doctor` measured a fresh worktree at 4 failures for exactly this reason
    (CLAUDE.md, "Dogfooding still finds what the suite cannot").
    """
    root = config.get("worktree_root")
    if not root:
        return {
            "state": "unknown",
            "root": None,
            "path": None,
            "detail": ".oss.local.json carries no worktree_root in this tree -- expected "
            "if this is running inside a worktree rather than the main clone.",
        }
    try:
        path = oss_config.resolve_worktree(root, str(issue))
    except oss_config.ContainmentError as exc:
        return {"state": "invalid", "root": root, "path": None, "detail": _one_line(str(exc))}
    return {"state": "resolved", "root": root, "path": str(path), "detail": ""}


def worktree_occupancy(path):
    """Whether something already sits at `path`. `os.path.exists` never raises --

    unlike `Path.exists()` / `Path.is_dir()`, whose OSError-swallowing behaviour
    changed across 3.10-3.14 (CLAUDE.md, "Path.rglob and Path.is_dir each destroy the
    answer a guard beside them was written to read"). No second question is asked here.
    """
    if not path:
        return None
    return os.path.exists(path)


# Lines the condensed board keeps: a header, the data-provenance disclaimer, one line
# per worktree (the state word starts at column 0 -- "occupied", "idle", "cannot tell"
# -- so it is never itself indented), and the final tally. Everything indented under an
# entry is the bullet-level detail the full op prints, and it is dropped -- see the
# module docstring for the byte budget this buys.
_DROP_PREFIXES = ("---", "PASS", "FAIL", "[exit")


def _condense_board(raw):
    kept = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith(_DROP_PREFIXES):
            continue
        if line[:1].isspace():
            continue
        kept.append(_one_line(line, 240))
    return kept


def read_board(repo):
    """The live worktree board, condensed. `could-not-run` is a state, not a crash."""
    supertool = shutil.which("supertool")
    if supertool is None:
        return {"state": "could-not-run", "lines": [], "detail": "supertool is not on PATH"}
    try:
        done = subprocess.run(
            [supertool, "git-worktrees"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {
            "state": "could-not-run",
            "lines": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    # A nonzero exit is a real op failure -- an unavailable op, a crash -- and it is
    # not enough to check the header text alone: an error message that names the op
    # (as this plugin's own error text does, "op 'git-worktrees' is unavailable
    # here...") still contains the substring "git-worktrees" and would otherwise read
    # as a successful, well-formed, one-line board. `git-worktrees` with no PATH
    # argument always exits 0 on success (its own text says so), so a nonzero return
    # here is never a tree's occupancy code -- it is the call itself failing.
    if done.returncode != 0 or "git-worktrees" not in done.stdout:
        return {
            "state": "could-not-run",
            "lines": [],
            "detail": _one_line(
                "exit {0}: {1}".format(done.returncode, done.stderr or done.stdout or "empty output"),
                300,
            ),
        }
    return {"state": "ok", "lines": _condense_board(done.stdout), "detail": ""}


def compute(repo, issue, remote="origin"):
    """Everything a lane brief needs, in one payload. `config.state` gates the exit."""
    repo = Path(repo)
    config_path = repo / CONFIG_NAME
    config, problems = oss_config.load(config_path)

    if config is None:
        return {
            "issue": issue,
            "repo": str(repo),
            "config": {"state": "could-not-run", "problems": problems},
            "base": None,
            "branch": None,
            "worktree": None,
            "board": None,
        }

    default_branch = config.get("default_branch")
    base = resolve_base(repo, remote, default_branch) if default_branch else {
        "state": "could-not-resolve",
        "remote": remote,
        "ref": None,
        "sha": None,
        "detail": "no default_branch in config",
    }

    branch = derive_branch(config.get("branch_pattern"), issue)
    if branch["state"] == "resolved":
        exists_local, exists_remote = branch_occupancy(repo, remote, branch["name"])
        branch["exists_local"] = exists_local
        branch["exists_remote"] = exists_remote
    else:
        branch["exists_local"] = None
        branch["exists_remote"] = None

    worktree = derive_worktree(config, issue)
    worktree["exists"] = worktree_occupancy(worktree.get("path"))

    board = read_board(repo)

    return {
        "issue": issue,
        "repo": str(repo),
        "config": {"state": "ok", "problems": problems},
        "base": base,
        "branch": branch,
        "worktree": worktree,
        "board": board,
    }


def blocked(payload):
    """True when there is not enough here to cut a lane from."""
    if payload["config"]["state"] != "ok":
        return True
    return payload["base"]["state"] == "could-not-resolve"


def _row(label, value):
    return "{0:<10}: {1}".format(label, value)


def receipt(payload):
    lines = ["LANE SETUP #{0}".format(payload["issue"]), _row("repo", payload["repo"])]

    if payload["config"]["state"] != "ok":
        lines.append("config    : COULD NOT RUN")
        for problem in payload["config"]["problems"] or []:
            lines.append("  - " + problem)
        return "\n".join(lines)

    for problem in payload["config"]["problems"] or []:
        lines.append("config warn: " + problem)

    base = payload["base"]
    if base["state"] == "could-not-resolve":
        lines.append("base      : COULD NOT RESOLVE -- {0}".format(base["detail"]))
    else:
        flag = "" if base["state"] == "resolved" else "  ** STALE ** {0}".format(base["detail"])
        lines.append(_row("base", "{0} ({1}){2}".format(base["sha"], base["ref"], flag)))

    branch = payload["branch"]
    if branch["state"] != "resolved":
        lines.append("branch    : UNKNOWN -- {0}".format(branch["detail"]))
    else:
        occ = []
        if branch["exists_local"] is True:
            occ.append("already exists locally")
        elif branch["exists_local"] is None:
            occ.append("local existence unknown")
        if branch["exists_remote"] is True:
            occ.append("already exists on " + base["remote"])
        elif branch["exists_remote"] is None:
            occ.append("{0} existence unknown".format(base["remote"]))
        occ_text = " [{0}]".format(", ".join(occ)) if occ else ""
        lines.append(_row("branch", branch["name"] + occ_text))

    worktree = payload["worktree"]
    if worktree["state"] != "resolved":
        lines.append("worktree  : {0} -- {1}".format(worktree["state"].upper(), worktree["detail"]))
    else:
        exists = worktree["exists"]
        exists_text = (
            "already exists" if exists is True else "free" if exists is False else "unknown"
        )
        lines.append(_row("worktree", "{0} [{1}]".format(worktree["path"], exists_text)))

    board = payload["board"]
    lines.append("board     :")
    if board["state"] != "ok":
        lines.append("  COULD NOT RUN -- " + board["detail"])
    else:
        for line in board["lines"]:
            lines.append("  " + line)

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "One call for a developer lane's setup facts: the resolved base, the "
            "derived branch and worktree, and the live worktree board (#317)."
        ),
        epilog="exit 0 = usable; exit 3 = could not run (no usable config, or no base)",
    )
    parser.add_argument("issue", type=int, help="the issue number this lane implements")
    parser.add_argument("--repo", default=".", help="repository to read (default: .)")
    parser.add_argument("--remote", default="origin", help="remote to fetch from (default: origin)")
    parser.add_argument("--json", action="store_true", help="emit the payload instead of the receipt")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    payload = compute(args.repo, args.issue, args.remote)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return EXIT_COULD_NOT_RUN if blocked(payload) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
