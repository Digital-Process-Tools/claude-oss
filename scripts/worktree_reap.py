"""#1628: worktree reaping had a permission check (#787's `doctor_check_
worktree_reap_permission.py`, asking whether `git worktree remove --force` and
`git branch -D` are even allowed) but nothing that finds reapable trees or
reaps them. Measured on this repo's own worktree root: 43 trees, 27 idle/
merged/clean and reapable in principle, 8 more idle/merged/dirty with ONLY
lane scratch output (`notes/`, `reports/`) that #1628 step 1 (`.gitignore`)
now ignores, and 2 holding a real `trap.d/` fragment nothing would ever have
read -- a reaper that removed merged-and-dirty trees without harvesting those
first would have destroyed both.

This module is the missing half. `scripts/doctor_check_worktree_reap.py`
names this script's own `--apply` command as its remedy, per the same
#497/#630 per-check-module convention every other `doctor_check_*.py` follows
-- `doctor.sh`'s own docstring is a model for THIS script's CLI shape (always
print something actionable, resolve the interpreter, never fail silently),
never its home.

**Three states per tree, never two: `reaped` / `kept: <reason>` /
`could-not-tell: <what was tried>`.** This repository's own named defect class
is an absence read as a clean result -- a tree whose occupancy, merge state or
dirt could not be read must never render as a tree with nothing in it, and
never as one safely reaped either.

**Harvest before removing.** Any `trap.d/*.md` fragment inside a tree about to
be reaped is copied into the CLONE's own `trap.d/` first, and a fragment that
fails to copy stops that tree's removal -- the tree is kept, not force-reaped
around the loss.

**The artifact allowlist is deliberately small and explicit**: `notes/`,
`reports/`, `.oss-review-snapshot.json` -- the same three `.gitignore` now
covers (#1628 step 1). Anything else found dirty is a refusal naming the
path, never a force.

**Occupancy is a process-cwd scan, never git state alone** -- git has no
notion of "a shell is sitting in this directory". `lsof -a -d cwd -Fn` is the
probe; where `lsof` is not on PATH (most commonly Windows, and any machine
that simply lacks it), occupancy is UNKNOWN, not "not occupied", and an
unknown occupant keeps the tree -- never reaped on an absent answer.

**Merge state is read from the tracker, never from ancestry** -- this repo's
own `doctor_check_stale_branches.py` states the same reasoning for the
identical trap: `"merge_method": "squash"` (this repo's own `.oss.json`)
leaves a squash-merged branch with no ancestor relationship to the default
branch at all, so an ancestry check would call every squash-merged branch
"not merged" and never reap anything real. `gh pr list --head <branch>
--state all` asks the tracker by name instead, the same call
`doctor_check_stale_branches._pr_state_for_branch` already makes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import gh_which  # noqa: E402 -- #1157: the one place gh/git is resolved

#: The small, explicit allowlist of lane scratch output a reapable tree is
#: still allowed to carry dirty. Matched against the TOP-LEVEL path component
#: `git status --porcelain` names (POSIX-separated, since that is what git
#: itself prints regardless of platform).
ARTIFACT_ALLOWLIST = frozenset({"notes", "reports", ".oss-review-snapshot.json"})

_STALE_PR_STATE = "MERGED"


def _run(run, args, cwd=None, timeout=20):
    """``(returncode, stdout, stderr, exc)`` -- ``exc`` set only when the
    process itself never started. Bytes decoded with ``errors="replace"``
    (#1019's own reasoning): a byte the runner's locale codec cannot
    represent must not raise out of a module that always has to return a
    state.
    """
    try:
        done = run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", "", exc
    stdout = (
        done.stdout.decode("utf-8", "replace")
        if isinstance(done.stdout, bytes)
        else (done.stdout or "")
    )
    stderr = (
        done.stderr.decode("utf-8", "replace")
        if isinstance(done.stderr, bytes)
        else (done.stderr or "")
    )
    return done.returncode, stdout, stderr, None


def list_worktrees(clone_dir, run=None, git_bin=None):
    """``("listed", [entries])`` or ``("could-not-tell", reason)``.

    Each entry: ``{"path": str, "branch": str|None, "detached": bool,
    "locked": bool}``. The FIRST entry ``git worktree list`` prints is always
    the main working tree (the clone itself) -- callers exclude it by
    convention (index 0), never by path comparison, matching how ``git``
    itself orders this output.
    """
    run = subprocess.run if run is None else run
    git_bin = git_bin or gh_which.safe_which("git")
    if git_bin is None:
        return "could-not-tell", "git is not on PATH"
    rc, out, err, exc = _run(
        run, [git_bin, "-C", str(clone_dir), "worktree", "list", "--porcelain"]
    )
    if exc is not None:
        return "could-not-tell", "git worktree list did not run ({})".format(exc)
    if rc != 0:
        return "could-not-tell", "git worktree list failed -- {}".format(
            (err or out).strip()[:200] or "not a git repository"
        )
    entries = []
    current = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current is not None:
                entries.append(current)
            current = {
                "path": line[len("worktree ") :],
                "branch": None,
                "detached": False,
                "locked": False,
            }
        elif current is None:
            continue
        elif line.startswith("branch "):
            ref = line[len("branch ") :]
            current["branch"] = (
                ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
            )
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("locked"):
            current["locked"] = True
    if current is not None:
        entries.append(current)
    return "listed", entries


def _lsof_process_cwds(run=None):
    """``list[(pid, cwd)]`` or ``None`` when the probe could not run at all
    (``lsof`` missing, denied, or failed to start) -- ``None`` is the signal
    every caller treats as "occupancy unknown", never "unoccupied".
    """
    run = subprocess.run if run is None else run
    lsof_bin = shutil.which("lsof")
    if lsof_bin is None:
        return None
    rc, out, _err, exc = _run(run, [lsof_bin, "-a", "-d", "cwd", "-Fn"], timeout=25)
    if exc is not None:
        return None
    pairs = []
    pid = None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid is not None:
            pairs.append((pid, line[1:]))
    return pairs


def worktree_occupant(path, list_processes=None):
    """``True`` / ``False`` / ``None`` (unknown) -- is some process's cwd
    inside ``path``? ``list_processes`` is injectable (tests never shell out
    to the real ``lsof``); its default is `_lsof_process_cwds`.
    """
    if list_processes is None:
        list_processes = _lsof_process_cwds
    procs = list_processes()
    if procs is None:
        return None
    target = os.path.realpath(str(path))
    for _pid, cwd in procs:
        if not cwd:
            continue
        try:
            real_cwd = os.path.realpath(cwd)
        except OSError:
            continue
        if real_cwd == target or real_cwd.startswith(target + os.sep):
            return True
    return False


def _gh_json(gh_bin, args, run):
    rc, out, err, exc = _run(run, [gh_bin] + args, timeout=25)
    if exc is not None:
        return None, None, "gh {} did not run ({})".format(" ".join(args), exc)
    if rc != 0:
        return (
            None,
            None,
            "gh {} failed -- {}".format(" ".join(args), (err or out).strip()[:200]),
        )
    try:
        return rc, json.loads(out or "[]"), None
    except ValueError as exc:
        return (
            None,
            None,
            "gh {} output did not parse as JSON ({})".format(" ".join(args), exc),
        )


_CLOSED_PR_STATE = "CLOSED"


def branch_merge_state(slug, branch, run=None, gh_bin=None):
    """``"merged"`` / ``"closed"`` / ``"not-merged"`` / ``"could-not-tell"`` --
    read from the tracker BY NAME, never from local ancestry (see this
    module's own docstring for why: a squash merge leaves no ancestor
    relationship at all). ``MERGED`` wins over any other state recorded for
    the same head, the same precedent
    `doctor_check_stale_branches._pr_state_for_branch` already sets.

    ``"closed"`` is its own state, distinct from ``"not-merged"`` (#1693): a
    pull request explicitly CLOSED without merging is a final, recorded
    decision not to merge that branch's work -- the same finality a MERGED
    PR carries, just the opposite outcome -- and `plan_reap` below treats it
    the same way. A branch with no pull request on record at all, or one
    still OPEN, stays ``"not-merged"``: neither is a decision yet, so
    neither licenses reaping the tree it lives in.
    """
    run = subprocess.run if run is None else run
    gh_bin = gh_bin or gh_which.safe_which("gh")
    if gh_bin is None:
        return "could-not-tell", "gh is not on PATH"
    _rc, rows, reason = _gh_json(
        gh_bin,
        [
            "pr",
            "list",
            "-R",
            slug,
            "--head",
            branch,
            "--state",
            "all",
            "--json",
            "number,headRefName,state",
        ],
        run,
    )
    if reason is not None:
        return "could-not-tell", reason
    if not isinstance(rows, list):
        return "could-not-tell", "gh pr list --head {} output was not a list".format(
            branch
        )
    state = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("headRefName") != branch:
            continue
        row_state = row.get("state")
        if not isinstance(row_state, str):
            continue
        if state == _STALE_PR_STATE:
            continue
        state = row_state
    if state == _STALE_PR_STATE:
        return "merged", None
    if state is None:
        return "not-merged", "no pull request on record for this branch name"
    if state == _CLOSED_PR_STATE:
        return "closed", "the recorded pull request state is CLOSED"
    return "not-merged", "the recorded pull request state is {}".format(state)


def unpushed_commit_state(tree_path, run=None, git_bin=None):
    """``("clean", 0)`` / ``("ahead", n)`` / ``("no-upstream", None)`` /
    ``("could-not-tell", reason)``.

    #1628 self-review finding: `branch_merge_state` asks whether ANY pull
    request headed at this branch NAME ever reached ``MERGED`` and, once
    true, stays true for that name forever -- and `dirt_state` alone only
    sees UNCOMMITTED changes. Neither catches a commit made in the worktree
    AFTER its own pull request merged: the working tree is clean, the branch
    name is merged, and there is still real, unpushed work that `git branch
    -D` would destroy. This asks the one question that closes the gap: does
    this branch have commits its own remote tracking ref does not?

    ``"no-upstream"`` (no ``@{u}`` configured at all) is deliberately as
    conservative as ``"ahead"`` -- a branch pushed once, whose upstream
    tracking was never re-established, cannot be told apart from one that
    was never pushed at all, and treating the former as safe on the strength
    of the latter never having existed is exactly the absence-read-as-clean
    class this repository is named after. Callers keep the tree on both.
    """
    run = subprocess.run if run is None else run
    git_bin = git_bin or gh_which.safe_which("git")
    if git_bin is None:
        return "could-not-tell", "git is not on PATH"
    rc_u, out_u, _err_u, exc_u = _run(
        run,
        [
            git_bin,
            "-C",
            str(tree_path),
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        ],
    )
    if exc_u is not None:
        return "could-not-tell", "git rev-parse @{{u}} did not run ({})".format(exc_u)
    if rc_u != 0 or not out_u.strip():
        return "no-upstream", None
    upstream = out_u.strip()
    rc, out, err, exc = _run(
        run,
        [
            git_bin,
            "-C",
            str(tree_path),
            "rev-list",
            "--count",
            "{}..HEAD".format(upstream),
        ],
    )
    if exc is not None:
        return "could-not-tell", "git rev-list --count did not run ({})".format(exc)
    if rc != 0:
        return "could-not-tell", "git rev-list --count failed -- {}".format(
            (err or out).strip()[:200]
        )
    count = out.strip()
    if not count.isdigit():
        return "could-not-tell", "git rev-list --count returned {!r}".format(count)
    ahead = int(count)
    if ahead:
        return "ahead", ahead
    return "clean", 0


def dirt_state(tree_path, run=None, git_bin=None):
    """``("clean", [], [])`` / ``("artifacts-only", [], [fragments])`` /
    ``("real-dirt", [offending paths], [fragments])`` /
    ``("could-not-tell", reason, [])``.

    ``git status --porcelain`` names every untracked and modified path;
    each is matched against `ARTIFACT_ALLOWLIST` by its TOP-LEVEL component.
    A `trap.d/*.md` path is collected separately (`fragments`) regardless of
    which bucket it lands in -- a fragment is never itself "outside the
    allowlist", it is harvested, per this module's own docstring.
    """
    run = subprocess.run if run is None else run
    git_bin = git_bin or gh_which.safe_which("git")
    if git_bin is None:
        return "could-not-tell", "git is not on PATH", []
    # --untracked-files=all: without it, git collapses an entirely-untracked
    # directory into a single "?? trap.d/" line rather than naming the files
    # inside it -- which would make a `trap.d/*.md` fragment invisible to the
    # match below whenever it is the only thing making the tree dirty.
    rc, out, err, exc = _run(
        run,
        [
            git_bin,
            "-C",
            str(tree_path),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
    )
    if exc is not None:
        return "could-not-tell", "git status did not run ({})".format(exc), []
    if rc != 0:
        return (
            "could-not-tell",
            "git status failed -- {}".format((err or out).strip()[:200]),
            [],
        )
    offenders = []
    fragments = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].strip()
        if not rel:
            continue
        rel_posix = rel.replace("\\", "/").rstrip("/")
        if rel_posix.startswith("trap.d/") and rel_posix.endswith(".md"):
            fragments.append(rel_posix)
            continue
        top = rel_posix.split("/", 1)[0]
        if top in ARTIFACT_ALLOWLIST or rel_posix in ARTIFACT_ALLOWLIST:
            continue
        offenders.append(rel_posix)
    if offenders:
        return "real-dirt", offenders, fragments
    if fragments or out.strip():
        return "artifacts-only", [], fragments
    return "clean", [], []


def harvest_fragments(tree_path, clone_dir, fragments):
    """Copy each ``trap.d/*.md`` fragment from ``tree_path`` into
    ``clone_dir``'s own ``trap.d/``. Returns ``(harvested, failures)`` --
    ``failures`` is a list of ``(fragment, reason)`` pairs; a non-empty
    ``failures`` is the caller's signal to keep the tree rather than reap it
    around a lost fragment.
    """
    harvested = []
    failures = []
    dest_dir = Path(clone_dir) / "trap.d"
    for fragment in fragments:
        src = Path(tree_path) / fragment
        dest = dest_dir / Path(fragment).name
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                failures.append(
                    (
                        fragment,
                        "a fragment named {} already exists in the clone's own "
                        "trap.d/ -- not overwritten".format(dest.name),
                    )
                )
                continue
            dest.write_bytes(src.read_bytes())
            harvested.append(fragment)
        except OSError as exc:
            failures.append((fragment, str(exc)))
    return harvested, failures


def plan_reap(
    clone_dir, config, run=None, git_bin=None, gh_bin=None, list_processes=None
):
    """One dict per non-main worktree: ``{"path", "branch", "decision":
    "reapable"|"kept"|"could-not-tell", "reason", "fragments"}``. Never
    touches anything -- ``reap()`` below is what acts on this plan.
    """
    state, entries = list_worktrees(clone_dir, run=run, git_bin=git_bin)
    if state == "could-not-tell":
        return "could-not-tell", entries
    plan = []
    slug = (config or {}).get("repo") if config else None
    for entry in entries[1:]:  # index 0 is always the main worktree
        path = entry["path"]
        branch = entry["branch"]
        if entry["detached"]:
            plan.append(
                {
                    "path": path,
                    "branch": None,
                    "decision": "kept",
                    "reason": "HEAD is detached -- no branch name to check against "
                    "the tracker",
                    "fragments": [],
                }
            )
            continue
        if entry["locked"]:
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "kept",
                    "reason": "git worktree lock is held",
                    "fragments": [],
                }
            )
            continue
        occupant = worktree_occupant(path, list_processes=list_processes)
        if occupant is None:
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "could-not-tell",
                    "reason": "occupancy could not be determined (lsof unavailable) "
                    "-- never reaped on an absent answer",
                    "fragments": [],
                }
            )
            continue
        if occupant:
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "kept",
                    "reason": "a process has its cwd inside this tree",
                    "fragments": [],
                }
            )
            continue
        if not slug:
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "could-not-tell",
                    "reason": "no repo slug configured, so merge state cannot be "
                    "read from the tracker",
                    "fragments": [],
                }
            )
            continue
        merge_state, merge_reason = branch_merge_state(
            slug, branch, run=run, gh_bin=gh_bin
        )
        if merge_state == "could-not-tell":
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "could-not-tell",
                    "reason": "merge state could not be read from the tracker -- "
                    "{}".format(merge_reason),
                    "fragments": [],
                }
            )
            continue
        if merge_state == "not-merged":
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "kept",
                    "reason": "not merged on the tracker ({})".format(merge_reason),
                    "fragments": [],
                }
            )
            continue
        # merge_state is now "merged" or "closed" here -- both are final,
        # recorded decisions not to keep the branch's work in flight (#1693)
        # -- and #1628's own finding below applies to either the same way.
        #
        # #1628 self-review finding: a MERGED verdict for this branch NAME is
        # not a guarantee this WORKTREE's own tip has nothing beyond it --
        # see `unpushed_commit_state`'s own docstring for the exact gap.
        unpushed, unpushed_detail = unpushed_commit_state(
            path, run=run, git_bin=git_bin
        )
        if unpushed == "could-not-tell":
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "could-not-tell",
                    "reason": "whether this branch is ahead of its own remote "
                    "could not be read -- {}".format(unpushed_detail),
                    "fragments": [],
                }
            )
            continue
        if unpushed == "no-upstream":
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "kept",
                    "reason": "no remote tracking ref configured, so whether this "
                    "branch's tip was ever pushed cannot be confirmed",
                    "fragments": [],
                }
            )
            continue
        if unpushed == "ahead":
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "kept",
                    "reason": "{} commit(s) ahead of its own remote tracking ref -- "
                    "merged under this branch name does not mean this worktree's "
                    "own tip was ever pushed".format(unpushed_detail),
                    "fragments": [],
                }
            )
            continue
        dirt, offenders, fragments = dirt_state(path, run=run, git_bin=git_bin)
        if dirt == "could-not-tell":
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "could-not-tell",
                    "reason": "dirt could not be read -- {}".format(offenders),
                    "fragments": [],
                }
            )
            continue
        if dirt == "real-dirt":
            plan.append(
                {
                    "path": path,
                    "branch": branch,
                    "decision": "kept",
                    "reason": "holds files outside the artifact allowlist: {}".format(
                        ", ".join(offenders)
                    ),
                    "fragments": fragments,
                }
            )
            continue
        plan.append(
            {
                "path": path,
                "branch": branch,
                "decision": "reapable",
                "reason": "{}, unoccupied, clean or artifacts-only".format(merge_state),
                "fragments": fragments,
            }
        )
    return "planned", plan


def reap(
    clone_dir,
    config,
    apply=False,
    run=None,
    git_bin=None,
    gh_bin=None,
    list_processes=None,
):
    """Run `plan_reap` and, when ``apply`` is true, act on every ``reapable``
    entry: harvest its `trap.d/` fragments first, then `git worktree remove
    --force` and `git branch -D`. Returns ``(state, results)`` where
    ``state`` is ``"planned"`` or ``"could-not-tell"`` and each result is
    ``{"path", "branch", "state": "reaped"|"kept"|"could-not-tell"|
    "reapable", "reason", "harvested"}``.
    """
    run = subprocess.run if run is None else run
    git_bin = git_bin or gh_which.safe_which("git")
    state, plan = plan_reap(
        clone_dir,
        config,
        run=run,
        git_bin=git_bin,
        gh_bin=gh_bin,
        list_processes=list_processes,
    )
    if state == "could-not-tell":
        return "could-not-tell", plan
    results = []
    for item in plan:
        if item["decision"] != "reapable":
            results.append(
                {
                    "path": item["path"],
                    "branch": item["branch"],
                    "state": item["decision"],
                    "reason": item["reason"],
                    "harvested": [],
                }
            )
            continue
        if not apply:
            results.append(
                {
                    "path": item["path"],
                    "branch": item["branch"],
                    "state": "reapable",
                    "reason": "dry run -- pass --apply to reap",
                    "harvested": [],
                }
            )
            continue
        harvested, failures = harvest_fragments(
            item["path"], clone_dir, item["fragments"]
        )
        if failures:
            results.append(
                {
                    "path": item["path"],
                    "branch": item["branch"],
                    "state": "kept",
                    "reason": "a trap.d/ fragment could not be harvested: {}".format(
                        failures
                    ),
                    "harvested": harvested,
                }
            )
            continue
        rc, out, err, exc = _run(
            run,
            [
                git_bin,
                "-C",
                str(clone_dir),
                "worktree",
                "remove",
                "--force",
                item["path"],
            ],
        )
        if exc is not None or rc != 0:
            results.append(
                {
                    "path": item["path"],
                    "branch": item["branch"],
                    "state": "could-not-tell",
                    "reason": "git worktree remove failed -- {}".format(
                        exc or (err or out).strip()[:200]
                    ),
                    "harvested": harvested,
                }
            )
            continue
        branch_note = ""
        if item["branch"]:
            # #1628 self-review finding: the worktree is already gone by this
            # point -- its own removal is the destructive, unrecoverable half
            # of this operation, already confirmed above. A failed branch
            # delete leaves a stray ref, not a lost tree, so it does not
            # invent a fourth top-level state; it is folded into `reason`
            # instead, rather than silently discarded, which would have
            # reported "reaped" with no trace that the branch survived.
            rc_b, out_b, err_b, exc_b = _run(
                run,
                [git_bin, "-C", str(clone_dir), "branch", "-D", item["branch"]],
            )
            if exc_b is not None or rc_b != 0:
                branch_note = " (branch {} was NOT deleted -- {})".format(
                    item["branch"], exc_b or (err_b or out_b).strip()[:200]
                )
        results.append(
            {
                "path": item["path"],
                "branch": item["branch"],
                "state": "reaped",
                "reason": item["reason"] + branch_note,
                "harvested": harvested,
            }
        )
    return "planned", results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clone", required=True, help="path to the main clone")
    parser.add_argument(
        "--apply", action="store_true", help="actually reap; default is dry run"
    )
    args = parser.parse_args(argv)

    config = None
    try:
        oss_json = Path(args.clone) / ".oss.json"
        if oss_json.exists():
            config = json.loads(oss_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = None

    state, results = reap(args.clone, config, apply=args.apply)
    if state == "could-not-tell":
        print("could-not-tell: {}".format(results))
        return 0
    reaped = 0
    for item in results:
        print("{} | {} | {}".format(item["state"], item["path"], item["reason"]))
        if item["state"] == "reaped":
            reaped += 1
    if not args.apply:
        print(
            "dry run -- {} reapable, re-run with --apply to actually reap".format(
                sum(1 for i in results if i["state"] == "reapable")
            )
        )
    else:
        print("{} reaped".format(reaped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
