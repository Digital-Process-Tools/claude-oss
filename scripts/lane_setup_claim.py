"""The lane registry: record, release, count and prune this loop's own
"a developer lane is live here" records, plus who else's open pull
requests/live lanes already hold which files (#385, #558, #705, #734, #771,
#792, #845).

Split out of `lane_setup.py` for #1069. `claim_and_register` /
`release_lane_and_assignee` are new in this same split (#1069's own ruling
B): claiming used to be two scripts and two separate calls -- this loop's own
GitHub assignee write (`issue_claim.py --claim`) and this file's lane
registration (`--claim --lane`) -- with nothing rolling the first back when
the second failed, and nothing releasing the assignee when a lane ended.
Both are now one call each, here.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import json
import os
import shutil
import stat
import subprocess
import time

import lane_setup_worktree
import select_issues_claim_read


#: Sibling of the numbered worktree directories, inside `worktree_root` -- #385.
LANE_REGISTRY_DIRNAME = ".oss-lanes"

#: How long a lane's own record is trusted before the next reader prunes it. This is
#: not a guess at how long a *lane* runs -- a worktree can sit unmerged for days
#: (CLAUDE.md's own board shows one). It is how long a record is trusted to mean "a
#: lane recently started and is likely mid test-run", which is the one moment #385
#: asks this to answer. Nothing calls this script when a lane ends, so a record
#: past this age is the only signal this mechanism has that it was abandoned rather
#: than refreshed, and it is pruned on the next read rather than left to accumulate.
LANE_RECORD_TTL_SECONDS = 4 * 60 * 60


def lane_registry_dir(worktree_root):
    """Where live-lane records live, or None when `worktree_root` itself is not known.

    A sibling of the numbered worktree directories -- inside `worktree_root`, not
    inside any one lane's own tree, so a lane cut from a worktree that carries no
    `.oss.local.json` (every worktree this loop cuts, by construction -- see
    `derive_worktree` above) can still be counted from the main clone, which is
    where `worktree_root` is known.
    """
    if not worktree_root:
        return None
    return os.path.join(str(worktree_root), LANE_REGISTRY_DIRNAME)


def record_lane(worktree_root, issue, branch, path, files=None):
    """Write (or refresh) this lane's own record. Three states, not two:

      recorded         the record is on disk, current as of this call.
      unknown          `worktree_root` is not known -- there is nowhere to write to,
                        which is the ordinary case inside a worktree this loop cut
                        (see `lane_registry_dir`), not a failure.
      could-not-write  `worktree_root` is known but the write itself failed --
                        an unwritable directory, a full disk. Distinct from
                        `unknown` because there IS a place this should have gone.

    Keyed by issue number, one file per lane: a second call for the same issue
    overwrites rather than accumulating, so re-running `lane_setup.py` mid-lane (this
    module's own docstring expects facts to be re-derived, not hand-carried) refreshes
    the TTL instead of leaving a duplicate. Written via a temp file and `os.replace`
    so a reader never observes a partially-written record.

    `files` (#558) is the lane's own resolved file list -- `resolve_lane`'s `files`,
    when `--lane` was given -- so a later `derive_held_set` call, run from a sibling
    lane checking availability, can read what this lane actually holds instead of
    the maintainer retyping it. `None` (no `--lane` on this call) tries not to
    overwrite a file list a previous call already recorded for this same issue: if
    this issue's record already carries a file list, a later call that reaches this
    function with no `--lane` of its own (still gated on `--claim` since #705 --
    this function itself is never reached by an unclaimed call at all) preserves it
    rather than blanking out the one payload #558 depends on. `files=[]` (a
    `--lane` that resolved to zero files) is a real, distinct state and is stored as
    given.

    **The preserve is best-effort, not guaranteed** -- #558 review round: if the
    previous record cannot be *read* (corrupt JSON, a permission blip, a concurrent
    writer mid-write), the preserve silently falls through to `None` rather than
    raising, and this call still succeeds and refreshes the TTL. That is a real,
    if rare, loss of this lane's own file list -- but it degrades in the direction
    this whole module insists on: the *next* reader of this record
    (`held_from_live_lanes`) sees `files=None` and reports `could-not-derive` for
    the held set rather than a wrong, silently narrower `resolved` one. A read
    failure here becomes a loud "cannot be trusted complete" one call later, never
    a quiet one.

    **`branch_confirmed_created` (#771 review round) is carried forward the same
    way, and for the same reason `files` already is.** This function's own
    docstring frames a second `--claim` for the same issue as an ordinary,
    supported refresh ("re-running lane_setup.py mid-lane... refreshes the TTL
    instead of leaving a duplicate"), and until this fix that refresh silently
    dropped the flag `held_from_live_lanes` had written -- a lane whose branch
    was positively observed alive, re-claimed once, and then genuinely merged
    and deleted no longer got route 3's prompt prune; it fell back to the
    240-minute TTL, quietly re-opening the exact #734 gap #771 exists to close.
    Preserved only when the previous record's own `branch` still matches this
    call's `branch` -- an observation about a branch that has since been
    renamed in the record is not an observation about this one -- and, like the
    `files` preserve above, best-effort: a previous record that cannot be read
    simply does not carry the flag forward, which is the safe direction (falls
    back to age-based judgement, never to a false prune).
    """
    root = lane_registry_dir(worktree_root)
    if root is None:
        return {
            "state": "unknown",
            "path": None,
            "detail": "worktree_root is not known, so there is nowhere to record this "
            "lane -- expected if this is running inside a worktree rather than the "
            "main clone.",
        }
    try:
        os.makedirs(root, exist_ok=True)
    except OSError as exc:
        return {
            "state": "could-not-write",
            "path": None,
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    record_path = os.path.join(root, "{0}.json".format(issue))
    try:
        with open(record_path) as fh:
            previous = json.load(fh)
    except (OSError, ValueError, AttributeError):
        previous = None
    # #804: valid JSON that is not an object (a list, most concretely) loads
    # fine above -- `json.load` has nothing to raise on -- and only crashes
    # the moment something calls `.get` on it. #786's review round hoisted
    # this read out of the `try` above without carrying that case with it, so
    # both `.get` calls below are guarded again here rather than widening the
    # `try` back around them: `previous` is only ever untrusted for its
    # *shape*, not for a read failure the `try` above already turned into
    # `None`, so a fresh, narrower guard keeps that distinction visible.
    if not isinstance(previous, dict):
        previous = None
    files_to_store = sorted(files) if files is not None else None
    if files_to_store is None and previous is not None:
        prev_files = previous.get("files")
        if isinstance(prev_files, list):
            files_to_store = prev_files
    payload = {
        "issue": issue,
        "branch": branch,
        "path": str(path) if path else None,
        "recorded_at": time.time(),
        "pid": os.getpid(),
        "files": files_to_store,
    }
    if (
        previous is not None
        and previous.get("branch") == branch
        and previous.get("branch_confirmed_created") is True
    ):
        payload["branch_confirmed_created"] = True
    tmp_path = record_path + ".tmp"
    try:
        with open(tmp_path, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp_path, record_path)
    except OSError as exc:
        return {
            "state": "could-not-write",
            "path": None,
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    return {"state": "recorded", "path": record_path, "detail": ""}


def release_lane(worktree_root, issue):
    """Remove this issue's own record, once the caller has independently
    confirmed the lane is done -- #734, route 1. The one caller this loop
    ships is the merge step, after it has already read `state` / `mergedAt` /
    `mergeCommit` back off the remote (`skills/manager/phases/merge.md`): that
    read-back is the confirmation, this function is just the write.

    Three states, not two -- the same shape as `record_lane`'s own, on the
    opposite side of the same registry:

      released           the record existed and was removed.
      not-found           no record existed for this issue -- releasing a
                           lane that never claimed (`--claim` was never
                           passed at dispatch), or one whose record already
                           expired past the TTL and was pruned by an earlier
                           reader. Not a failure: there was nothing to do.
      could-not-release   `worktree_root` is not known, or a record exists
                           and the removal itself failed (a permission
                           error, a directory where the file should be).

    #734's own three recorded instances are all lanes the loop itself merged
    and read back, 20-90 minutes stale against the 240-minute TTL -- the gap
    this closes is exactly that window, not the TTL itself, which stays as
    the fallback for a lane that never gets released at all (abandoned,
    merged by hand outside this loop, or older than this fix).
    """
    root = lane_registry_dir(worktree_root)
    if root is None:
        return {
            "state": "could-not-release",
            "path": None,
            "detail": "worktree_root is not known, so there is no registry to "
            "release this lane's record from.",
        }
    record_path = os.path.join(root, "{0}.json".format(issue))
    try:
        os.remove(record_path)
    except FileNotFoundError:
        return {
            "state": "not-found",
            "path": record_path,
            "detail": "no live record for this issue -- nothing to release.",
        }
    except OSError as exc:
        return {
            "state": "could-not-release",
            "path": record_path,
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    return {"state": "released", "path": record_path, "detail": ""}


def lane_count(worktree_root):
    """How many lanes are recorded live, right now. Three states, not two -- #385:

      resolved        one or more live records, aged under `LANE_RECORD_TTL_SECONDS`.
                       `count` carries the number.
      unknown          the registry could not be located (`worktree_root` unknown),
                       does not exist yet, or exists and holds zero live records.
                       **A registry nothing has ever written to and a registry
                       confirmed empty render identically on disk** -- neither may
                       report `0`, which is a specific claim of certainty this
                       function cannot make. `count` is None.
      could-not-run    either the registry exists and holds at least one record
                       that could not be read at all (corrupt JSON, a missing
                       field) -- a partial count built by skipping it would
                       silently undercount, so this is reported instead of
                       swallowed -- or the registry's own existence could not be
                       examined at all (#472: an ancestor this process cannot
                       traverse, or a path carrying an embedded null byte). The
                       second case is deliberately not folded into `unknown`,
                       because a registry that could not be examined is not a
                       confirmed absence. `count` is None either way.

    A record older than the TTL is pruned as a side effect of this read and excluded
    from the count -- never counted as live, and never folding the whole answer to
    `unknown` on its own, because its age is a direct filesystem timestamp
    comparison rather than a guess reached by asking whether the process that wrote
    it is still around (which is the thing #385 opens by saying cannot be done).
    Pruning here is deliberate: nothing calls this script when a lane ends, so the
    next reader is the only cleanup this mechanism has.
    """
    root = lane_registry_dir(worktree_root)
    if root is None:
        return {
            "state": "unknown",
            "count": None,
            "detail": "worktree_root is not known.",
        }
    # #472: `os.path.isdir` (`genericpath.isdir`) swallows `(OSError, ValueError)`
    # unconditionally, so a registry that exists under an untraversable parent used to
    # answer `False` here, and the `detail` below then claimed a confirmed absence for a
    # registry that was never examined. `os.stat` is asked directly instead, the same
    # move `worktree_occupancy` already made for the identical swallow (#373, #380): the
    # exception decides which arm runs, and `FileNotFoundError` / `NotADirectoryError`
    # are confirmed via `_absence_confirmed` rather than trusted on their own, because
    # Windows folds an over-`MAX_PATH` name onto the same exception with no
    # distinguishing signal. Every other `OSError` (a `PermissionError` on the parent,
    # the case this issue was filed from) is "could not examine", not "not there".
    try:
        found = os.stat(root)
    except (FileNotFoundError, NotADirectoryError):
        if lane_setup_worktree._absence_confirmed(root) is not True:
            return {
                "state": "could-not-run",
                "count": None,
                "detail": "a lane registry may exist at {0} but could not be examined "
                "-- an ancestor could not be looked at, which is not a confirmed "
                "absence.".format(root),
            }
        found = None
    except OSError as exc:
        return {
            "state": "could-not-run",
            "count": None,
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    except ValueError as exc:
        # `os.stat` raises `ValueError`, not `OSError`, for a path carrying an embedded
        # null byte -- `worktree_root` comes from `.oss.local.json` and JSON can spell
        # one. `worktree_occupancy` already guards this (#380); the review round on
        # this fix found the guard had not been carried over here.
        return {
            "state": "could-not-run",
            "count": None,
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    if found is None or not stat.S_ISDIR(found.st_mode):
        return {
            "state": "unknown",
            "count": None,
            "detail": "no lane registry at {0} -- either nothing has ever recorded "
            "itself here, or nothing is live. A confirmed zero is not distinguishable "
            "from that.".format(root),
        }
    try:
        names = os.listdir(root)
    except OSError as exc:
        return {
            "state": "could-not-run",
            "count": None,
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }

    now = time.time()
    live = 0
    unreadable = 0
    for name in names:
        if not name.endswith(".json"):
            continue
        entry_path = os.path.join(root, name)
        try:
            with open(entry_path) as fh:
                data = json.load(fh)
            recorded_at = float(data["recorded_at"])
        except FileNotFoundError:
            # A sibling `lane_count()` call -- the exact concurrency #385 is about --
            # can prune this same stale record between our `listdir` and our `open`.
            # That is not corruption, it is the cleanup this function itself performs
            # arriving one step ahead of us: the record is gone either way, so it is
            # simply not counted, not folded into `unreadable` and not reported as an
            # unreadable-record `could-not-run` for a record nothing was ever wrong
            # with.
            continue
        except (OSError, ValueError, KeyError, TypeError):
            unreadable += 1
            continue
        age = now - recorded_at
        if age < 0:
            # `recorded_at` in the future: clock skew between the writer and this
            # reader, or a read racing a write within the same second. Far more
            # likely to be "just (re)written" than "abandoned", so it is counted as
            # live rather than pruned -- deleting it here would silently undercount a
            # lane that in fact just recorded itself, which is the confident-absence
            # failure the rest of this function exists to avoid, reached through
            # deletion instead of through a wrong number.
            live += 1
            continue
        if age > LANE_RECORD_TTL_SECONDS:
            try:
                os.remove(entry_path)
            except OSError:
                pass  # another reader may have pruned it first; not this call's problem
            continue
        live += 1

    if unreadable:
        return {
            "state": "could-not-run",
            "count": None,
            "detail": "{0} lane record(s) under {1} could not be read -- a partial "
            "count would undercount.".format(unreadable, root),
        }
    if live == 0:
        return {
            "state": "unknown",
            "count": None,
            "detail": "no live lane records under {0} -- either nothing is running or "
            "nothing has recorded itself; a confirmed zero is not distinguishable from "
            "that.".format(root),
        }
    return {"state": "resolved", "count": live, "detail": ""}


def detect_vanished_worktrees(worktree_root):
    """#845: a live lane record whose own worktree directory is confirmed absent.

    #845 was filed with two independently reported instances of a lane's
    worktree directory disappearing mid-run, caused by no command the lane
    itself ran -- once twice in the same run, once as a sub-manager's own
    `git worktree remove` deleting a *different* lane's tree and branch. The
    investigation for #845 found no `git worktree remove` / `worktree_remove`
    / `rmtree` call anywhere in `scripts/` or `skills/` that touches a git
    worktree directory (two unrelated `rmtree` hits, `oss_rules.py` and
    `scaffold.py`, neither near a worktree path) -- the reap is two hand
    commands `doctor_check_worktree_reap_permission.py` names, typed by a
    human or an agent reading `skills/manager/phases/merge.md`'s prose, never
    issued by this file. Root cause was not found in this plugin's own code,
    so this is the loud detector #845 asks for in that case instead: nothing
    before this function ever noticed a vanished worktree at all, which is
    why the reporting agent found out only by rebuilding from `git reflog`
    by hand, twice.

    Reuses `lane_count`'s exact registry walk (live records only, aged under
    `LANE_RECORD_TTL_SECONDS`, same three states) rather than a second idea of
    what "live" means, and adds one check per live record: does
    `worktree_occupancy` on the record's own `path` field come back `False`
    (confirmed absent)?

      resolved         the registry was read; `vanished` lists every live
                        record (`issue`, `branch`, `path`, `recorded_at`)
                        whose own `path` is confirmed absent, `[]` when none
                        are.
      unknown           no lane registry, or no live records at all -- nothing
                        to check, not a failure.
      could-not-run     the registry itself, or a record inside it, could not
                        be read.

    `worktree_occupancy`'s own `None` ("could not look") is never read as
    vanished -- a path this process could not examine is not evidence it
    disappeared, the same distinction every other absence check in this
    module already makes (`_absence_confirmed`, `worktree_occupancy` itself).
    A record carrying no `path` (a version of this script that predates the
    field) is skipped, not flagged -- there is nothing to check it against.
    """
    root = lane_registry_dir(worktree_root)
    if root is None:
        return {
            "state": "unknown",
            "vanished": [],
            "detail": "worktree_root is not known.",
        }
    try:
        found = os.stat(root)
    except (FileNotFoundError, NotADirectoryError):
        if lane_setup_worktree._absence_confirmed(root) is not True:
            return {
                "state": "could-not-run",
                "vanished": [],
                "detail": "a lane registry may exist at {0} but could not be examined "
                "-- an ancestor could not be looked at, which is not a confirmed "
                "absence.".format(root),
            }
        found = None
    except OSError as exc:
        return {
            "state": "could-not-run",
            "vanished": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    except ValueError as exc:
        return {
            "state": "could-not-run",
            "vanished": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    if found is None or not stat.S_ISDIR(found.st_mode):
        return {
            "state": "unknown",
            "vanished": [],
            "detail": "no lane registry at {0}.".format(root),
        }
    try:
        names = os.listdir(root)
    except OSError as exc:
        return {
            "state": "could-not-run",
            "vanished": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }

    now = time.time()
    vanished = []
    live = 0
    for name in names:
        if not name.endswith(".json"):
            continue
        entry_path = os.path.join(root, name)
        try:
            with open(entry_path) as fh:
                data = json.load(fh)
            recorded_at = float(data["recorded_at"])
            issue = data["issue"]
        except FileNotFoundError:
            # A sibling reader pruned this same stale record between our
            # `listdir` and our `open` -- gone either way, not counted.
            continue
        except (OSError, ValueError, KeyError, TypeError):
            return {
                "state": "could-not-run",
                "vanished": vanished,
                "detail": "lane record {0} under {1} could not be read.".format(
                    name, root
                ),
            }
        age = now - recorded_at
        if age >= 0 and age > LANE_RECORD_TTL_SECONDS:
            continue  # expired; not live, and never checked
        live += 1
        path = data.get("path")
        if not path:
            continue
        if lane_setup_worktree.worktree_occupancy(path) is False:
            vanished.append(
                {
                    "issue": issue,
                    "branch": data.get("branch"),
                    "path": path,
                    "recorded_at": recorded_at,
                }
            )

    if live == 0:
        return {
            "state": "unknown",
            "vanished": [],
            "detail": "no live lane records under {0}.".format(root),
        }
    return {"state": "resolved", "vanished": vanished, "detail": ""}


def lanes_snapshot(worktree_root, issue, branch, path, files=None, claim=False):
    """Report the live picture, and record this lane's own presence only when asked.

    #705: every call used to write a record unconditionally, whether or not the
    caller was actually committing to this lane. A maintainer probing three
    candidate lanes to check disjointness (`--lane`/`--derive-held`, neither of
    which implies a dispatch decision) left two phantom records behind -- each one
    carrying `files=None`, which is exactly the shape `held_from_live_lanes`
    refuses to trust as complete (#558). The record then outlived the probe by up
    to the full TTL, blocking every later `--derive-held` call in the meantime --
    a refusal that was correct about what it was asked and wrong about the world,
    because what it was asked was never a claim to begin with.

    So writing is now gated on `claim`, an explicit "I am dispatching this lane"
    signal from the caller -- never inferred from which other flags happen to be
    present, because `--lane` and `--derive-held` are both legitimately used by a
    probe that decides nothing. When `claim` is False, nothing is written: the
    live count still reports what is *already* on disk (#385's original read),
    and `record` comes back `not-claimed` rather than `recorded` or `unknown`, so
    a reader can tell "asked, not claiming" apart from "there was nowhere to
    write" and from "this call actually registered itself".

    `files` (#558) passes straight through to `record_lane` when `claim` is True:
    when this call's own `--lane` resolved a file list, it is what a later
    `derive_held_set` call reads back for this issue.
    """
    if claim:
        record = record_lane(worktree_root, issue, branch, path, files=files)
    else:
        record = {
            "state": "not-claimed",
            "path": None,
            "detail": "this call did not pass --claim, so nothing was written -- "
            "pass --claim only at the moment this lane is actually being "
            "dispatched, not while probing candidates (#705).",
        }
    count = lane_count(worktree_root)
    return {"record": record, "count": count}


# #558 review round: `gh pr list --json` caps a single page at some server limit,
# and a repository with more open PRs than that would otherwise report `resolved`
# on a silently truncated list -- exactly the "empty, confident held set" #558
# says a forge call must never produce, one step removed (a *partial* one is the
# same failure). Chosen low enough that hitting it is a strong truncation signal
# (a repo actually running 150 simultaneously open PRs is not this loop's
# design case) rather than raised to paper over the same risk at a higher count.
_PR_LIST_LIMIT = 150


# #558 review round: `gh pr list --json` caps a single page at some server limit,
# and a repository with more open PRs than that would otherwise report `resolved`
# on a silently truncated list -- exactly the "empty, confident held set" #558
# says a forge call must never produce, one step removed (a *partial* one is the
# same failure). Chosen low enough that hitting it is a strong truncation signal
# (a repo actually running 150 simultaneously open PRs is not this loop's
# design case) rather than raised to paper over the same risk at a higher count.
_PR_LIST_LIMIT = 150


def held_from_open_prs(repo_slug):
    """Every open pull request's own file list against `repo_slug` (`owner/name`,
    `.oss.json`'s own `repo` key) -- #558, the first of the two held-set sources the
    issue names. Uses `gh` directly (`gh pr list --json number,files`) rather than
    `supertool gh-pr:N:diff`: this needs the *set* of open PRs first, which is a
    second call either way, and `--json files` returns each PR's paths as data,
    never text this module would have to parse a diff header to recover.

    **`--repo`'s value is `repo_slug`, straight from config, unrefused -- measured,
    not reasoned.** `oss_config.repo_problem` places no restriction on a leading
    dash the way `remote_problem` above restricts `remote` (`git fetch`'s own argv
    parsing, #368/#381). `gh` was measured directly rather than assumed safe by
    analogy: `gh pr list --repo '--upload-pack=touch pwned' ...` fails with a GraphQL
    hostname-parse error (`gh` version 2.98.0) rather than running anything --
    `--repo`'s value is consumed as a single token by `gh`'s own flag parser and
    never re-scanned as another flag, unlike git's `--upload-pack=<cmd>` hole this
    file's own `remote_problem` exists to close. No refusal is added here because
    there is nothing measured for it to refuse.

    Two states, not the lane registry's three: there is no "nothing has ever
    recorded here" case for an open-PR list the way there is for a registry that
    may never have been written to -- zero open PRs is a confirmed zero, not an
    absence to be suspicious of.

      resolved          `gh` ran and returned a well-formed list (possibly empty)
                         under `_PR_LIST_LIMIT`.
      could-not-derive  `gh` is not on PATH, the call failed or timed out, its
                         output could not be parsed as the JSON it promises, or the
                         result hit `_PR_LIST_LIMIT` exactly -- indistinguishable
                         from "there happen to be exactly that many open PRs" and
                         "the real count is higher and this is a truncated page",
                         so it is not trusted as complete either way. #558 is
                         explicit that a forge call that fails must never render
                         as an empty, confident held set -- a *silently truncated*
                         one is the same failure at one remove, so it is reported
                         the same way rather than folded into `resolved`.
    """
    if not repo_slug:
        return {"state": "could-not-derive", "held": {}, "detail": "no repo configured"}
    gh = shutil.which("gh")
    if gh is None:
        return {"state": "could-not-derive", "held": {}, "detail": "gh is not on PATH"}
    try:
        done = subprocess.run(
            [
                gh,
                "pr",
                "list",
                "--repo",
                str(repo_slug),
                "--state",
                "open",
                "--json",
                "number,files",
                "--limit",
                str(_PR_LIST_LIMIT),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {
            "state": "could-not-derive",
            "held": {},
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    if done.returncode != 0:
        return {
            "state": "could-not-derive",
            "held": {},
            "detail": lane_setup_worktree._one_line(
                "gh pr list exit {0}: {1}".format(
                    done.returncode, done.stderr or done.stdout or "no output"
                ),
                300,
            ),
        }
    try:
        prs = json.loads(done.stdout)
    except (ValueError, TypeError) as exc:
        return {
            "state": "could-not-derive",
            "held": {},
            "detail": "could not parse gh pr list output: {0}".format(exc),
        }
    if not isinstance(prs, list):
        return {
            "state": "could-not-derive",
            "held": {},
            "detail": "gh pr list did not return a list",
        }
    if len(prs) >= _PR_LIST_LIMIT:
        return {
            "state": "could-not-derive",
            "held": {},
            "detail": "gh pr list returned {0} open PR(s), at or past the {1}-PR page "
            "limit -- the held set cannot be trusted complete.".format(
                len(prs), _PR_LIST_LIMIT
            ),
        }
    held = {}
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        number = pr.get("number")
        for f in pr.get("files") or []:
            path = f.get("path") if isinstance(f, dict) else None
            if not path:
                continue
            holders = held.setdefault(path, [])
            label = "PR #{0}".format(number)
            if label not in holders:
                holders.append(label)
    return {"state": "resolved", "held": held, "detail": ""}


def _show_ref_code(repo, branch):
    """The raw `git show-ref --verify --quiet refs/heads/<branch>` exit code in
    `repo`, or `None` when git itself could not answer (`_git` returning `None`
    -- git not on PATH, or the call could not be launched). Shared by
    `_branch_confirmed_gone` and `_branch_confirmed_present` (#771) so both read
    from the one call rather than the registry paying for `git show-ref` twice
    per record.
    """
    code, _, _ = lane_setup_worktree._git(
        repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch
    )
    return code


def _branch_confirmed_gone(repo, branch):
    """True only when `repo`'s local `refs/heads` positively confirm `branch` no
    longer exists there -- #734, route 3. Every worktree cut from the same
    `worktree_root` shares this namespace (`git worktree add` creates a local
    branch in the one clone's shared `.git`), so this needs no fetch and no
    network call: the loop's own merge cleanup runs `git branch -d` on that
    same shared clone (supertool's `gh-pr-merge` help text), and the deletion
    is visible here the instant it happens.

    Never a table of exit codes: `git show-ref --verify --quiet refs/heads/X`
    answers 0 (exists) or 1 (does not) when it can answer at all, and only a
    clean 1 is trusted as gone. `_git` returning `None` (git not on PATH, or the
    call itself could not be launched) and any other code are both "could not
    confirm" -- this function's whole job is to never let silence read as a
    refusal, the same posture `_absence_confirmed` already takes for a
    filesystem path one module up.

    Deliberately **not** checked against the remote. At the moment a lane is
    first dispatched its branch exists only locally -- nothing has pushed it
    yet -- so a remote-tracking check (`git ls-remote` or a cached
    `refs/remotes/...` ref) would read a brand-new, genuinely live lane as
    already gone. The local ref is never ambiguous that way: it exists exactly
    as long as some worktree could have it checked out.

    **#771: "gone" here also covers "never created yet".** `git show-ref` answers
    the identical "not found" for a branch a merge already deleted and for a
    branch `--claim` has recorded but `git worktree add` has not cut. This
    function alone cannot tell those apart -- see `held_from_live_lanes`, which
    is where the distinction is actually made, never here.
    """
    return _show_ref_code(repo, branch) == 1


def _branch_confirmed_present(repo, branch):
    """True only when `repo`'s local `refs/heads` positively confirm `branch`
    exists there right now -- #771, the positive counterpart of
    `_branch_confirmed_gone`. `git show-ref --verify` answers 0 (exists) or 1
    (does not) when it can answer at all, and only a clean 0 is trusted as
    present -- never inferred from "not confirmed gone", which would also be
    true whenever git could not answer at all.
    """
    return _show_ref_code(repo, branch) == 0


def _mark_branch_confirmed_created(entry_path, data):
    """Persist that `data`'s own declared branch has been positively observed to
    exist in the shared clone's `refs/heads` -- #771. Written once, the first
    time a corroborating read (`held_from_live_lanes`, given `repo`) sees the
    branch present, so a *later* read that finds the identical branch absent
    can trust that absence as "gone by deletion" (route 3's own prune
    condition) rather than "never created" (the claimed-but-not-yet-cut window
    #771 is about) -- the one distinction `_branch_confirmed_gone` alone cannot
    make, because both states are the same absence in `refs/heads`.

    Best-effort, like `record_lane`'s own write: a failure here (a permission
    blip, a concurrent writer) leaves this record exactly as conservative as
    before this function ran -- still not eligible for route 3's prune until
    some other read confirms it -- never raises, and never blocks the read
    already in progress around it.
    """
    payload = dict(data)
    payload["branch_confirmed_created"] = True
    tmp_path = entry_path + ".tmp"
    try:
        with open(tmp_path, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp_path, entry_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def held_from_live_lanes(worktree_root, exclude_issue=None, repo=None):
    """Every live lane record's own file list -- #558, the second held-set source.
    Reads the same registry `lane_count` reads, for the full file lists rather than
    a count, and applies the identical TTL/absence handling rather than a second
    idea of what "live" means.

      resolved          at least one live record (other than `exclude_issue`) was
                         read and every one of them carries a `files` list --
                         `held` maps each file to the `lane #N` label(s) claiming it.
      unknown            the registry could not be located, does not exist yet, or
                         holds no live records besides the excluded one -- nothing
                         to hold, not a failure.
      could-not-derive  the registry's own existence could not be examined, a
                         record could not be read, or a live record carries no
                         `files` at all (recorded without `--lane`, or by a version
                         of this script that predates #558) -- the held set would
                         be incomplete, and #558 is explicit that this must never
                         render as a confident (even if partial) `resolved`.

    `repo` (#734, route 3): when given, every record's own declared `branch` is
    corroborated against `repo`'s local `refs/heads` before the record is trusted
    as held. A record whose branch is positively confirmed gone is pruned from
    disk the same way an expired one already is -- `LANE_RECORD_TTL_SECONDS` is a
    reasonable ceiling for "abandoned", and a very long time to keep blocking a
    follow-up after a merge the loop itself just performed and read back (#734's
    own three instances: 20, 27 and 90 minutes stale). `stale_pruned` names every
    record removed this way, `[]` when none were. Omitting `repo` (the default)
    reproduces the exact pre-#734 behaviour, unconditionally: every existing
    caller that does not pass it sees age as the only signal, same as before this
    parameter existed.

    #792: the removal itself can fail (a permission error, a concurrent writer) --
    a record whose branch is confirmed gone is not automatically a record that
    was actually deleted. `FileNotFoundError` still counts as success (another
    reader already pruned it) and folds into `stale_pruned`; any other `OSError`
    lands in `prune_failed` instead, `[]` when none failed -- carrying the
    issue, branch and exception detail for a record that is demonstrably still
    on disk. The two lists are always disjoint: a record appears in at most one
    of them.

    **#771: absence from `refs/heads` alone is never trusted as "gone by
    deletion".** `_branch_confirmed_gone`'s own docstring says why: the identical
    absence also describes a lane `--claim` has recorded but whose branch
    `git worktree add` has not cut yet -- the loop's own documented dispatch
    order puts those two calls in that order, so the window is real and
    structural, not a race to be narrowed. Reproduced directly: three lanes
    claimed back to back, a sibling's `--derive-held` read in between each
    claim and its own `git worktree add`, and the registry emptied itself --
    every record pruned, none of the three branches ever having existed.

    So a record is only pruned here once **this same record** has been
    positively observed with its branch present at some earlier read
    (`data["branch_confirmed_created"]`, written by `_mark_branch_confirmed_created`
    the first time a corroborating call sees it) -- never on a bare "not found"
    alone. A record never yet observed present that now reads "not found" falls
    through to the age-based judgement below, exactly the pre-#734, no-`repo`
    behaviour -- the same degrade this function already makes when `repo` is
    omitted entirely, and never worse than that. `release_lane` (route 1,
    called by the merge step once it has read a merge back off the remote)
    stays the fast, authoritative release; this corroboration is a backstop for
    when route 1's caller never ran, and #771 narrows what it is allowed to
    infer from silence without removing it.
    """
    root = lane_registry_dir(worktree_root)
    if root is None:
        return {
            "state": "unknown",
            "held": {},
            "stale_pruned": [],
            "prune_failed": [],
            "detail": "worktree_root is not known.",
        }
    try:
        found = os.stat(root)
    except (FileNotFoundError, NotADirectoryError):
        if lane_setup_worktree._absence_confirmed(root) is not True:
            return {
                "state": "could-not-derive",
                "held": {},
                "stale_pruned": [],
                "prune_failed": [],
                "detail": "a lane registry may exist at {0} but could not be examined "
                "-- an ancestor could not be looked at, which is not a confirmed "
                "absence.".format(root),
            }
        return {
            "state": "unknown",
            "held": {},
            "stale_pruned": [],
            "prune_failed": [],
            "detail": "no lane registry at {0}.".format(root),
        }
    except OSError as exc:
        return {
            "state": "could-not-derive",
            "held": {},
            "stale_pruned": [],
            "prune_failed": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    except ValueError as exc:
        return {
            "state": "could-not-derive",
            "held": {},
            "stale_pruned": [],
            "prune_failed": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    if not stat.S_ISDIR(found.st_mode):
        return {
            "state": "unknown",
            "held": {},
            "stale_pruned": [],
            "prune_failed": [],
            "detail": "no lane registry at {0}.".format(root),
        }
    try:
        names = os.listdir(root)
    except OSError as exc:
        return {
            "state": "could-not-derive",
            "held": {},
            "stale_pruned": [],
            "prune_failed": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }

    now = time.time()
    held = {}
    live_count = 0
    stale_pruned = []
    prune_failed = []
    for name in names:
        if not name.endswith(".json"):
            continue
        entry_path = os.path.join(root, name)
        try:
            with open(entry_path) as fh:
                data = json.load(fh)
            recorded_at = float(data["recorded_at"])
            issue = data["issue"]
        except FileNotFoundError:
            # A sibling reader pruned this same stale record between our
            # `listdir` and our `open` -- the record is gone either way (see
            # `lane_count`'s identical race), so it is simply not counted.
            continue
        except (OSError, ValueError, KeyError, TypeError):
            return {
                "state": "could-not-derive",
                "held": {},
                "stale_pruned": stale_pruned,
                "prune_failed": prune_failed,
                "detail": "lane record {0} under {1} could not be read.".format(
                    name, root
                ),
            }
        if exclude_issue is not None and str(issue) == str(exclude_issue):
            continue
        branch = data.get("branch")
        if repo is not None and branch:
            ref_code = _show_ref_code(repo, branch)
            if ref_code == 1:
                if data.get("branch_confirmed_created") is True:
                    # #734, route 3: a positive confirmation, not an inference
                    # from age -- the branch this record names cannot be
                    # checked out anywhere, and was itself previously observed
                    # to exist (below), which is what the loop's own merge
                    # cleanup (`git branch -d`) leaves behind. Pruned
                    # immediately rather than merely skipped, unlike the
                    # age-based `continue` below: age is a guess about
                    # abandonment, this is a fact about the shared clone.
                    # #792: `FileNotFoundError` genuinely is success --
                    # "another reader already pruned it" -- and belongs in
                    # `stale_pruned` exactly like an `os.remove` this call
                    # performed itself. Any other `OSError` is a removal
                    # that actually failed: the record is demonstrably still
                    # on disk, so it goes in `prune_failed` instead, never
                    # in `stale_pruned` alongside a release that worked --
                    # reporting it in both would be worse than either.
                    try:
                        os.remove(entry_path)
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        prune_failed.append(
                            {
                                "issue": issue,
                                "branch": branch,
                                "detail": "{0}: {1}".format(type(exc).__name__, exc),
                            }
                        )
                        continue
                    stale_pruned.append({"issue": issue, "branch": branch})
                    continue
                # #771: never observed created -- "not found" here is exactly
                # as likely to mean "claimed, not yet cut" as "merged and
                # cleaned up", and this function cannot tell those apart from
                # a bare absence. Fall through to the age-based judgement.
            elif ref_code == 0 and data.get("branch_confirmed_created") is not True:
                # #771: branch positively exists right now -- record it so a
                # later read, once the branch is genuinely gone, can trust
                # that absence as deletion.
                _mark_branch_confirmed_created(entry_path, data)
        age = now - recorded_at
        if age >= 0 and age > LANE_RECORD_TTL_SECONDS:
            continue  # expired; `lane_count` is what prunes it from disk
        files = data.get("files")
        if files is None:
            return {
                "state": "could-not-derive",
                "held": {},
                "stale_pruned": stale_pruned,
                "prune_failed": prune_failed,
                "detail": "live lane record for issue {0} carries no files -- recorded "
                "without --lane, or by a version of this script that predates #558 -- "
                "so the held set cannot be trusted complete while that lane is "
                "live.".format(issue),
            }
        live_count += 1
        for f in files:
            holders = held.setdefault(f, [])
            label = "lane #{0}".format(issue)
            if label not in holders:
                holders.append(label)
    if live_count == 0:
        return {
            "state": "unknown",
            "held": {},
            "stale_pruned": stale_pruned,
            "prune_failed": prune_failed,
            "detail": "no live lane records under {0} besides the excluded issue.".format(
                root
            ),
        }
    return {
        "state": "resolved",
        "held": held,
        "stale_pruned": stale_pruned,
        "prune_failed": prune_failed,
        "detail": "",
    }


def derive_held_set(repo_slug, worktree_root, exclude_issue=None, repo=None):
    """The file set a new lane is not free to touch, mechanically -- #558: the
    exclusion a maintainer used to retype from memory (CLAUDE.md's own defect
    class -- a check that never ran and a check that found nothing render
    identically) becomes a measurement instead, from the two sources the issue
    names: open pull requests and live lane records.

    `state` is `resolved` only when **both** sources resolved (an `unknown` source
    -- no open PRs, no live lanes besides the one excluded -- contributes nothing
    and does not block the other). If either source is `could-not-derive`, the
    combined state is `could-not-derive` too, with both problems named in
    `detail` -- #558's own words: this "must never render as `available`, and it
    must not render as `blocked` either."

    `repo` (#734, route 3) passes straight through to `held_from_live_lanes`,
    which is the only one of the two sources it applies to -- an open pull
    request is read from the forge itself, already the true current state, and
    has no local branch ref to corroborate against.
    """
    prs = held_from_open_prs(repo_slug)
    lanes = held_from_live_lanes(worktree_root, exclude_issue=exclude_issue, repo=repo)
    problems = []
    if prs["state"] == "could-not-derive":
        problems.append("open pull requests: " + prs["detail"])
    if lanes["state"] == "could-not-derive":
        problems.append("live lanes: " + lanes["detail"])
    if problems:
        return {
            "state": "could-not-derive",
            "held": {},
            "prs": prs,
            "lanes": lanes,
            "detail": "; ".join(problems),
        }
    held = {}
    for source in (prs["held"], lanes["held"]):
        for f, holders in source.items():
            existing = held.setdefault(f, [])
            for h in holders:
                if h not in existing:
                    existing.append(h)
    return {"state": "resolved", "held": held, "prs": prs, "lanes": lanes, "detail": ""}


# How far up the tree `_absence_confirmed` will walk looking for an ancestor this
# platform can look at. A path has a finite number of components and the loop already
# stops at the anchor, so this is a belt on a walk that terminates -- against a
# filesystem whose `dirname` never reaches a fixed point (a synthetic path object, a
# broken mount), not against ordinary input.
_ANCESTOR_LIMIT = 512


#: `claim_and_register`'s own states, named so a half-claim is legible rather
#: than inferred (#1069, ruling B). GitHub's assignee field and this loop's
#: own lane registry are two different systems -- a forge write and a local
#: file write can never be one transaction -- so this is best-effort, never a
#: lock, and every outcome is named rather than folded into a bare ok/fail.
CLAIM_STATE_CLAIMED = "claimed"
CLAIM_STATE_ALREADY_MINE = "already-mine"
CLAIM_STATE_ALREADY_CLAIMED = "already-claimed"
CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE = "could-not-claim-assignee"
CLAIM_STATE_COULD_NOT_REGISTER = "could-not-register"
CLAIM_STATE_ASSIGNEE_ROLLED_BACK = "assignee-rolled-back"
CLAIM_STATE_ROLLBACK_FAILED = "rollback-failed-assignee-still-set"


def claim_and_register(
    worktree_root,
    issue,
    branch,
    path,
    files=None,
    also_claim=None,
    repo=None,
    checker=None,
):
    """Claim in both senses, in one call (#1069): write the GitHub assignee
    for `issue` (and every issue in `also_claim`, a lane's companion issues)
    and register this lane's own record, rolling the assignee write(s) back
    when the registration fails.

    Two systems, never one transaction. GitHub's assignee field is a forge
    write; the lane registry (`record_lane`) is a local file write. This
    function orders them -- assignee first, registry second -- and gives the
    failure of the second its own named states rather than a silent partial
    claim (the gap `.claude/jit-context/tools/01-oss/pr-create-gate.md` used
    to patch with a prose reminder to run `gh issue edit --remove-assignee
    @me` by hand).

    `checker` defaults to `select_issues_claim_read.check`, injectable for a
    test the same way `select_issues.py`'s own `select()` already injects it.

    Returns a dict: `{"state", "assignee": {...rows...}, "record": {...}}`.

    `state` is one of:

      claimed                    every assignee write succeeded (fresh or
                                  already ours) and the record was written.
      already-claimed             at least one of `issue`/`also_claim` is
                                  already assigned to somebody else -- refused
                                  before anything is written, the same
                                  "never claim over somebody" rule
                                  `select_issues_claim_read.py` already states.
      could-not-claim-assignee    the assignee read/write itself could not be
                                  completed for at least one issue -- nothing
                                  further is attempted.
      assignee-rolled-back        the assignee write(s) succeeded but the
                                  registry write failed, and every issue this
                                  call freshly claimed was successfully
                                  un-assigned again.
      rollback-failed-assignee-still-set
                                  the same failure, but at least one rollback
                                  attempt itself failed -- the issue(s) named
                                  in `assignee["rollback_failed"]` are still
                                  assigned to the caller even though the lane
                                  was never registered. A maintainer must
                                  release those by hand
                                  (`select_issues_claim_read.py`'s own
                                  `release_one`, or `gh issue edit --remove-
                                  assignee @me`) until this call is retried.
    """
    checker = select_issues_claim_read.check if checker is None else checker
    numbers = [issue] + [n for n in (also_claim or []) if n != issue]

    rows = checker(numbers, "claim", repo=repo)
    rows_by_number = {row["issue"]: row for row in rows}

    already_claimed = [
        row
        for row in rows
        if row["state"] == select_issues_claim_read.STATE_ALREADY_CLAIMED
    ]
    if already_claimed:
        return {
            "state": CLAIM_STATE_ALREADY_CLAIMED,
            "assignee": {"rows": rows, "rollback_failed": []},
            "record": None,
        }

    unclaimable = [
        row
        for row in rows
        if row["state"] == select_issues_claim_read.STATE_COULD_NOT_CLAIM
    ]
    if unclaimable:
        return {
            "state": CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE,
            "assignee": {"rows": rows, "rollback_failed": []},
            "record": None,
        }

    # Every row is now `claimed` (this call wrote it) or `already-mine` (it
    # was already ours before this call). Only the freshly-claimed ones are
    # ever rolled back below -- rolling back an `already-mine` row would
    # release a claim this call did not create.
    freshly_claimed = [
        n
        for n, row in rows_by_number.items()
        if row["state"] == select_issues_claim_read.STATE_CLAIMED
    ]

    record = record_lane(worktree_root, issue, branch, path, files=files)
    if record["state"] == "recorded":
        overall = (
            CLAIM_STATE_CLAIMED
            if all(
                row["state"]
                in (
                    select_issues_claim_read.STATE_CLAIMED,
                    select_issues_claim_read.STATE_ALREADY_MINE,
                )
                for row in rows
            )
            else CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE
        )
        return {
            "state": overall,
            "assignee": {"rows": rows, "rollback_failed": []},
            "record": record,
        }

    # The registry write failed (`unknown` or `could-not-write`): roll back
    # every issue this call freshly assigned, best-effort. `unknown` -- no
    # worktree_root to write to at all -- still rolls back: an assignee
    # written for a lane that could never be registered is exactly the
    # half-claim this function exists to make legible, not a reason to skip
    # the rollback.
    rollback_failed = []
    for number in freshly_claimed:
        release_rows = checker([number], "release", repo=repo)
        release_row = release_rows[0] if release_rows else None
        if release_row is None or release_row["state"] not in (
            select_issues_claim_read.STATE_RELEASED,
            select_issues_claim_read.STATE_NOT_ASSIGNED,
        ):
            rollback_failed.append(number)

    state = (
        CLAIM_STATE_ROLLBACK_FAILED
        if rollback_failed
        else CLAIM_STATE_ASSIGNEE_ROLLED_BACK
    )
    return {
        "state": state,
        "assignee": {"rows": rows, "rollback_failed": rollback_failed},
        "record": record,
    }


def release_lane_and_assignee(
    worktree_root, issue, also_release=None, repo=None, checker=None
):
    """The mirror of `claim_and_register` (#1069): release this issue's own
    lane record AND its GitHub assignee, in one call, closing the gap
    `.claude/jit-context/tools/01-oss/pr-create-gate.md` used to patch with a
    prose reminder to run the assignee release by hand after a merge.

    `also_release` releases the assignee of every companion issue this lane
    also claimed via `claim_and_register`'s own `also_claim` -- a companion
    issue never gets its own lane record (only the primary issue does), so
    this is assignee-only for each one; the record half only ever applies to
    `issue` itself.

    Both halves are removals, not additions, so there is nothing to roll
    back between them the way `claim_and_register` has to -- each is
    reported on its own, best-effort, and a caller reads both rather than
    one folded verdict.

    Returns `{"record": {...release_lane's own three states...}, "assignee":
    {...one select_issues_claim_read.check "release" row for `issue`...},
    "also_released": [...one row per also_release entry...]}`.
    """
    checker = select_issues_claim_read.check if checker is None else checker
    record = release_lane(worktree_root, issue)
    rows = checker([issue], "release", repo=repo)
    also_rows = (
        checker(list(also_release), "release", repo=repo) if also_release else []
    )
    return {
        "record": record,
        "assignee": rows[0] if rows else None,
        "also_released": also_rows,
    }
