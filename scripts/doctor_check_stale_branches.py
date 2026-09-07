"""``check_stale_branches`` -- one check, in its own module per the #497/#630
convention.

#1046: a curated trap fragment found 57 of 58 `origin/fix/*` refs on this
repository's own forge were MERGED-only leftovers, months old, and nothing in
`python3 scripts/doctor.py --root .` ever looks at refs on the forge --
`gh-pr-merge:...|cleanup` deletes the remote branch at merge time and does so
correctly for a fresh merge, but the leaks predate that convention, or came
from a merge where cleanup was correctly `refused` (visible at the time, in
that tick's own output, and never looked at again). Nothing re-checks after a
refusal, so this set only grows -- the same shape `check_trap_queue` and
`check_vanished_worktrees` exist to catch for their own queues: a fact that
was reported once and then only lived in a transcript nobody re-reads.

**Read from the tracker, never from ancestry.** `skills/manager/phases/
merge.md` states this explicitly for the analogous worktree-cleanup case,
and for the identical reason: `git branch -r --merged` cannot see a squash
merge, because the squash commit that lands on the default branch is not an
ancestor of the feature branch's own tip. A repository configured for
`"merge_method": "squash"` (this one is) would have every merged branch
render as `not merged` under an ancestry check, which is worse than not
checking at all -- it is a check that always says "not stale" when it never
tells the truth. So this module asks the tracker (`gh pr list --state all`)
whether a branch's own head ref maps to a merged pull request, and never
asks git's own ancestry graph.

**Every branch listing goes through `gh api`, never a local `git` call.**
An earlier version of this check ran `git ls-remote --heads origin`, which
needs a local `origin` remote to exist -- a fact this clone happens to have,
but neither `.oss.json`'s own `repo` key nor a fresh checkout guarantees it
(the doctor test fixtures configure `repo` directly and never add an
`origin` remote at all, which is exactly the gap that a self-review round
turned up: a "fully configured, everything clean" fixture rendered `WARN`
because there was no local remote for `git` to ask). `gh api repos/{slug}/
git/matching-refs/heads/{prefix}` answers the identical question --
every ref on the forge whose path starts with `refs/heads/{prefix}` --
straight from the tracker's own account of the remote, with no local git
state involved at all. That also means this check only needs `gh` on PATH,
never `git`, matching `doctor_check_branch_protection.py`'s own shape.

**Report-only, matching every other `doctor` check.** #1046's own filed
trap leaned this way -- diagnose, never remediate -- and no other check in
this file writes to the forge; `check_branch_protection` states the same
reasoning for declining a runnable remedy command (an administrative
action with no preview, no diff and no revert is not something a
diagnostic should do on your behalf). Deleting a branch is reversible only
via the reflog on whoever's clone still has it, so the same caution
applies twice over. The remedy line names the exact per-branch `gh api`
delete command `|cleanup` itself already runs, for a maintainer to run by
hand.

**No age threshold.** #1046's own second open question asked whether
"stale enough to report" needs an age cutoff. `check_vanished_worktrees`
and `check_trap_queue` -- the two closest siblings, both drift detectors
over a set that only grows if unwatched -- report every instance they find
the moment they find it, with no threshold of their own: a live lane record
whose worktree vanished is reported the first time doctor runs after it
vanishes, and a trap fragment is reported the first time doctor runs after
it is logged. A branch is merged-but-undeleted as soon as its PR merges and
`|cleanup` did not run or was refused; there is no "grace period" during
which that state is expected or benign, so none is added here. A one-day-old
merge and a one-year-old one are reported identically, and that is a choice,
not an oversight.

Every shared name is reached through `doctor` imported as a module, so a
test's `monkeypatch.setattr(doctor, ...)` still reaches this code after a
future move, the same convention every sibling module documents.
"""

import json
import subprocess

import doctor
import gh_which

#: The placeholder `branch_pattern` uses to mark where the issue number goes
#: (`scripts/lane_setup_worktree.py`'s own `ISSUE_PLACEHOLDER`, vendored as a
#: literal rather than imported -- this module has no other reason to import
#: a worktree-lifecycle module, and the placeholder spelling is part of
#: `.oss.json`'s own public contract, not an implementation detail of that
#: module).
ISSUE_PLACEHOLDER = "{issue}"

#: `MERGED` is the only pull-request state this check treats as "should have
#: been deleted". `OPEN` and `CLOSED` (closed without merging) both leave the
#: branch legitimately in play or legitimately somebody else's call to clean
#: up -- this check has no business flagging either.
_STALE_PR_STATE = "MERGED"

_REFS_HEADS_PREFIX = "refs/heads/"


def _branch_prefix(pattern):
    """The literal text before `{issue}` in `branch_pattern`, or ``None`` when
    the pattern cannot be used to derive a glob -- not a string, or missing
    the placeholder entirely. Never invented: a pattern with no placeholder
    would make every branch on the remote match, which is answering a
    different, much louder question than the one this check exists to ask.
    """
    if not isinstance(pattern, str) or ISSUE_PLACEHOLDER not in pattern:
        return None
    return pattern.split(ISSUE_PLACEHOLDER)[0]


def _gh_json(gh_bin, args, run):
    """Run ``gh <args>``, returning ``(returncode, parsed_or_None, raw_err,
    exc)``. ``exc`` is set only when the process itself failed to start.
    Bytes are decoded with ``errors="replace"`` (#1019) -- never
    ``universal_newlines=True`` under the runner's own locale codec, which
    raises `UnicodeDecodeError` on a byte that codec cannot represent and
    would escape every `except` in this module, aborting a check meant to
    always return a state.
    """
    try:
        done = run(
            [gh_bin] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, "", exc
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


def _list_matching_branches(gh_bin, slug, prefix, run):
    """``(names, None)`` or ``(None, reason)`` -- every branch on the forge
    whose name starts with `prefix`, read live from the tracker via
    `git/matching-refs`, never off a local remote-tracking ref.
    """
    rc, stdout, stderr, exc = _gh_json(
        gh_bin,
        ["api", "repos/{}/git/matching-refs/heads/{}".format(slug, prefix)],
        run,
    )
    if exc is not None:
        return None, "gh api .../matching-refs/heads/{} did not run ({})".format(
            prefix, exc
        )
    if rc != 0:
        return None, "gh api .../matching-refs/heads/{} failed: {}".format(
            prefix, (stderr or stdout or "").strip()[:200]
        )
    try:
        rows = json.loads(stdout or "[]")
    except ValueError as exc:
        return None, "matching-refs response did not parse as JSON ({})".format(exc)
    if not isinstance(rows, list):
        return None, "matching-refs response was not a list"
    names = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ref = row.get("ref")
        if isinstance(ref, str) and ref.startswith(_REFS_HEADS_PREFIX):
            names.append(ref[len(_REFS_HEADS_PREFIX) :])
    return names, None


def _list_pull_requests(gh_bin, slug, run):
    """``(rows, None)`` or ``(None, reason)`` -- every pull request this repo's
    tracker has ever recorded, `number`/`headRefName`/`state`, `--state all`
    so a merged one is not filtered out before it is even read.
    """
    rc, stdout, stderr, exc = _gh_json(
        gh_bin,
        [
            "pr",
            "list",
            "-R",
            slug,
            "--state",
            "all",
            "--json",
            "number,headRefName,state",
            "--limit",
            "500",
        ],
        run,
    )
    if exc is not None:
        return None, "gh pr list did not run ({})".format(exc)
    if rc != 0:
        return None, "gh pr list failed: {}".format(
            (stderr or stdout or "").strip()[:200]
        )
    try:
        rows = json.loads(stdout or "[]")
    except ValueError as exc:
        return None, "gh pr list output did not parse as JSON ({})".format(exc)
    if not isinstance(rows, list):
        return None, "gh pr list output was not a list"
    return rows, None


def _pr_state_by_branch(rows):
    """`headRefName` -> its pull request state, `MERGED` winning over any
    other state recorded for the same head. A branch name is only ever
    reused across pull requests when somebody force-pushed a new PR onto an
    old branch name after the first one closed unmerged -- rare, but a
    `MERGED` verdict once earned for that name must not be erased by a later,
    unrelated row for the same string.
    """
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        head = row.get("headRefName")
        state = row.get("state")
        if not isinstance(head, str) or not isinstance(state, str):
            continue
        if result.get(head) == _STALE_PR_STATE:
            continue
        result[head] = state
    return result


def stale_branches_state(project_dir, config=None, run=None):
    """`"ok"` / a finding (`"stale"`) / `"could-not-read"` -- never two states
    standing in for three. `could-not-read` covers every local gating
    failure (`gh` missing, no usable `branch_pattern`, no resolvable repo
    slug) and every live failure of either call (an unauthenticated `gh`, a
    rate limit, an offline machine, an unparseable response) -- none of
    those may ever render as "no stale branches found", because none of
    them looked.

    Returns a dict: `state`, `detail` (a rendered sentence), `slug` (the
    resolved `owner/repo`, or ``None``), and `stale` (the list of branch
    names found merged-but-undeleted, empty unless `state == "stale"`).
    """
    run = subprocess.run if run is None else run
    gh_bin = gh_which.safe_which("gh")
    if gh_bin is None:
        return {
            "state": "could-not-read",
            "detail": "gh is not on PATH",
            "slug": None,
            "stale": [],
        }

    pattern = (config or {}).get("branch_pattern") if config else None
    prefix = _branch_prefix(pattern)
    if prefix is None:
        return {
            "state": "could-not-read",
            "detail": "branch_pattern {!r} has no {} placeholder, so which "
            "remote branches to check is unknown".format(pattern, ISSUE_PLACEHOLDER),
            "slug": None,
            "stale": [],
        }

    slug = (config or {}).get("repo") if config else None
    if slug is not None and not isinstance(slug, str):
        slug = None
    if not slug:
        slug, reason = doctor._origin_slug(project_dir, run=run)
        if slug is None:
            return {
                "state": "could-not-read",
                "detail": reason,
                "slug": None,
                "stale": [],
            }
    if doctor._malformed_repo(slug):
        return {
            "state": "could-not-read",
            "detail": "repo {!r} is not a safe 'owner/name' shape".format(slug),
            "slug": None,
            "stale": [],
        }

    matching, reason = _list_matching_branches(gh_bin, slug, prefix, run)
    if matching is None:
        return {
            "state": "could-not-read",
            "detail": reason,
            "slug": slug,
            "stale": [],
        }
    matching = sorted(matching)
    if not matching:
        return {
            "state": "ok",
            "detail": "no {}* branches on the forge".format(prefix),
            "slug": slug,
            "stale": [],
        }

    rows, reason = _list_pull_requests(gh_bin, slug, run)
    if rows is None:
        return {
            "state": "could-not-read",
            "detail": reason,
            "slug": slug,
            "stale": [],
        }

    pr_state = _pr_state_by_branch(rows)
    stale = [name for name in matching if pr_state.get(name) == _STALE_PR_STATE]
    if not stale:
        return {
            "state": "ok",
            "detail": "{} branch(es) matching {}* checked against the tracker; "
            "none merged-but-undeleted".format(len(matching), prefix),
            "slug": slug,
            "stale": [],
        }
    return {
        "state": "stale",
        "detail": "{} of {} branch(es) matching {}* are merged on the tracker "
        "but still present on the forge".format(len(stale), len(matching), prefix),
        "slug": slug,
        "stale": stale,
    }


def check_stale_branches(project_dir, config=None, run=None):
    """Report only -- see this module's own docstring for why no `--apply`
    exists here, the same reasoning `check_branch_protection` states for
    itself.
    """
    result = stale_branches_state(project_dir, config=config, run=run)
    if result["state"] == "could-not-read":
        doctor.report(
            "WARN",
            "stale merged branches: could not be checked -- {}. UNKNOWN, not "
            "clean: nothing here has been shown to be free of a stale "
            "branch.".format(result["detail"]),
        )
        return
    if result["state"] == "ok":
        doctor.report("OK", "stale merged branches: {}".format(result["detail"]))
        return
    names = result["stale"]
    shown = ", ".join(names[:20])
    if len(names) > 20:
        shown += ", and {} more".format(len(names) - 20)
    slug = result["slug"] or "OWNER/REPO"
    doctor.report(
        "WARN",
        "stale merged branches: {} ({}). Report-only: delete by hand with `gh "
        "api -X DELETE repos/{}/git/refs/heads/<branch>` per branch, the same "
        "call the merge step's own |cleanup already runs for a fresh "
        "merge.".format(result["detail"], shown, slug),
    )
