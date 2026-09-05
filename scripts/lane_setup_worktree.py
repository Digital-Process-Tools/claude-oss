"""The base commit, branch, worktree path and their occupancy checks -- lane_setup.py's own worktree facts (#317, #1006, #608, #373, #865).

Split out of `lane_setup.py` for #1069 -- that file crossed 3,600 lines and
took `doctor.py`'s own medicine: one entry point, several `lane_setup_*.py`
submodules, none of which carries a `__main__`. `lane_setup.py` imports every
name below and re-exports it at module level, so `lane_setup.<name>` keeps
working for every existing caller and test -- only the *definition* moved.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import oss_config  # noqa: E402


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


def remote_problem(value):
    """Why this `remote` cannot be handed to git, or None when it is fine.

    #381. The rule is one line because the harm is one line: `git fetch --quiet
    <remote> <branch>` reads argv position 6 as an option when it starts with a dash,
    and `--upload-pack=<cmd>` in that position **runs** `<cmd>`. Measured, not reasoned
    -- git 2.46.2 on darwin executed an injected script and printed its argv before
    reporting "Could not read from remote repository". A refusal wider than the option
    position would be inventing a shape for a value whose legitimate forms include a
    bare name, an ssh URL and a filesystem path, and this file has no authority for
    that; a refusal narrower than it does not close the hole.

    **This rule lives here rather than in `oss_config` because the value does.**
    `remote` is `--remote` argv only and is never config-sourced, so a verdict in the
    config validator would be a rule for a key no config carries and `doctor` would
    have nothing to print it for. #345's one-value-one-rule constraint points the other
    way for `default_branch`, which *is* config-sourced -- hence `resolve_base` calling
    `oss_config.default_branch_problem` for that one and this for this one. If `remote`
    ever becomes config-sourced, this function moves to `oss_config` and this call site
    consults it there; that is the whole migration.
    """
    if value is None:
        return "remote: expected a remote name, URL or path; got None."
    if not isinstance(value, str):
        return (
            "remote: expected a remote name, URL or path as a string; got {!r}.".format(
                value
            )
        )
    if value.startswith("-"):
        return (
            "remote: it starts with '-', so `git fetch --quiet <remote> <branch>` reads "
            "it as an option rather than as a remote -- and `--upload-pack=<cmd>` in "
            "that position runs <cmd>; got {!r}.".format(value)
        )
    return None


def resolve_base(repo, remote, default_branch):
    """The commit a lane should be cut from -- fetched and rev-parsed, never abbreviated.

    Three states. `resolved-stale` exists because a failed fetch and a repo with no
    prior fetch at all both leave a remote-tracking ref that might answer -- and
    answering from it without saying the fetch failed is exactly the staleness this
    script exists to stop reproducing.

    #368 and #381: **two** values here reach git's argv unprefixed, in adjacent
    positions of one command. `git fetch --quiet <remote> <branch>` reads either as an
    option when it starts with a dash, and `--upload-pack=<cmd>` in either one runs
    `<cmd>` -- measured, git 2.46.2 on darwin. Both are refused *before* any argv is
    built, so nothing runs at all rather than running and then failing.

    An earlier version of this paragraph said `default_branch` was the only such value.
    It was false when it was written and #381 is the cost: a sentence that tells the
    next guard sweep it has already found everything is worth more than the value it
    describes, so the two rules are named here rather than counted.

    They are two rules on purpose, because they are two different kinds of value.
    `default_branch` is config-sourced, so #345 (one value, one rule) requires the
    verdict `oss_config` already produced for it -- `default_branch_problem` -- rather
    than a second copy here that could drift from the sentence `doctor` prints.
    `oss_config.load()` deliberately returns the offending value together with a
    sentence rather than stripping it, and #368's defect was this consumer treating a
    loaded config as a usable one. `remote` is argv only and never config-sourced, so
    `oss_config` has no verdict for it and would have no occasion to print one;
    `remote_problem` above carries that rule and says what has to move if that changes.

    Not `git fetch --quiet -- <remote> <branch>`, which was measured and does work: git
    refuses a dash-prefixed repository itself with `fatal: strange pathname ... blocked`
    while a well-formed remote still fetches. Declined for two reasons. It makes git the
    thing that reports the refusal, in a sentence this script would then have to
    interpret to fill `detail`, where the point of the third state is to say why in this
    script's own words. And beside a value already refused above it could never fire --
    an unfireable guard is the thing this repository keeps finding instead of a fix.

    Two values here reach git and are safe by the shape of the argv rather than by a
    rule, which is why neither is guarded. `branch_occupancy` prefixes `refs/heads/` and
    `refs/remotes/`, so neither the branch name nor the remote can occupy the flag
    position. `--repo` is `-C`'s argument, and git consumes that literally instead of
    re-parsing it as an option -- so a dash-prefixed `--repo` is a bad directory, not an
    injection. Both measured the same way.

    `tests/test_lane_setup_368.py` and `tests/test_lane_setup_381.py` measure all of the
    above rather than trusting this paragraph, and the latter sweeps every argument this
    module hands to `_git` rather than the sites somebody enumerated.
    """
    for problem in (
        remote_problem(remote),
        oss_config.default_branch_problem(default_branch),
    ):
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
            "detail": ""
            if fetched
            else "fetch failed, using the last-known ref: {0}".format(
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


def resolve_stacked_base(repo, remote, stack_on):
    """The commit a lane should be cut from when stacking on another lane's own
    branch tip instead of deriving `base` from `default_branch` (#1006's third
    candidate fix, chosen over the other two named in that issue for blast
    radius: it needs no change to the `git-worktrees` op itself, so nothing
    here needs an upstream filing to land -- see #1006 for the two that would).

    Reads the ref straight out of the shared object database -- `refs/heads/
    <stack_on>` first, `refs/remotes/<remote>/<stack_on>` as a fallback --
    rather than through any worktree's checked-out files. Branches are refs
    shared by every worktree linked to one repository, so resolving one never
    touches the tree a live developer agent (or the manager's own merge)
    might be occupying: it sidesteps the same-branch/same-worktree collision
    `git-worktrees`' `cannot tell` state exists to gate, rather than trying to
    reason about who wrote its index most recently.

    Three states, same shape as `resolve_base` above: `resolved` (found
    locally -- likely the freshest answer, since a sibling worktree cut from
    this same repository has already advanced it without needing a fetch),
    `resolved-remote` (found only as a remote-tracking ref -- flagged, since
    this can be stale if nobody has fetched since `stack_on` last moved; that
    staleness is the caller's to weigh, not this function's to hide), and
    `could-not-resolve` (neither ref exists, or `stack_on` is not a usable
    branch name).

    Both git calls prefix `stack_on` with a fixed `refs/...` string before it
    ever reaches argv, the same technique `branch_occupancy` above already
    uses -- so a dash-prefixed value can never occupy git's flag position, and
    `tests/test_lane_setup_1006.py` pins that directly rather than trusting
    this paragraph.
    """
    if not isinstance(stack_on, str) or not stack_on:
        return {
            "state": "could-not-resolve",
            "remote": remote,
            "ref": None,
            "sha": None,
            "detail": "stack_on: expected a non-empty branch name; got {0!r}.".format(
                stack_on
            ),
        }

    local_ref = "refs/heads/" + stack_on
    code, out, err = _git(repo, "rev-parse", "--verify", local_ref)
    if code == 0 and out:
        return {
            "state": "resolved",
            "remote": remote,
            "ref": local_ref,
            "sha": out,
            "detail": "",
        }

    remote_ref = "refs/remotes/{0}/{1}".format(remote, stack_on)
    remote_code, remote_out, remote_err = _git(
        repo, "rev-parse", "--verify", remote_ref
    )
    if remote_code == 0 and remote_out:
        return {
            "state": "resolved-remote",
            "remote": remote,
            "ref": remote_ref,
            "sha": remote_out,
            # #1006, audit round: `stack_on` has already been proven, at this
            # point, to resolve to a real object -- git's own check-ref-format
            # rules already forbid control characters in any ref component, so
            # nothing here can forge a receipt line today. `_one_line` is
            # applied anyway, for the same reason every other text of external
            # origin in this file goes through it (`resolve_base`'s own
            # `fetch_err`/`err` above): consistency with the rest of the
            # module, and defense-in-depth against a future caller feeding
            # --stack-on from a less-trusted source than this one does.
            "detail": _one_line(
                "found only as a remote-tracking ref -- can be stale if "
                "nobody has fetched since {0} last moved.".format(stack_on),
                300,
            ),
        }

    return {
        "state": "could-not-resolve",
        "remote": remote,
        "ref": None,
        "sha": None,
        "detail": _one_line(
            "neither {0} nor {1} exists ({2}).".format(
                local_ref, remote_ref, err or remote_err or "not found"
            ),
            300,
        ),
    }


ISSUE_PLACEHOLDER = "{issue}"


def derive_branch(pattern, issue):
    """The branch name for `issue`, from `branch_pattern`. Never invented."""
    if not isinstance(pattern, str) or ISSUE_PLACEHOLDER not in pattern:
        return {
            "state": "unknown",
            "pattern": pattern,
            "name": None,
            "detail": "branch_pattern has no {0} placeholder -- every issue would "
            "resolve to the same branch, so nothing is derived.".format(
                ISSUE_PLACEHOLDER
            ),
        }
    return {
        "state": "resolved",
        "pattern": pattern,
        "name": pattern.replace(ISSUE_PLACEHOLDER, str(issue)),
        "detail": "",
    }


def branch_occupancy(repo, remote, name):
    """Whether `name` already exists locally or on `remote`. None means unknown."""
    local_code, _, _ = _git(
        repo, "show-ref", "--verify", "--quiet", "refs/heads/" + name
    )
    exists_local = None if local_code is None else local_code == 0

    remote_code, _, _ = _git(
        repo,
        "show-ref",
        "--verify",
        "--quiet",
        "refs/remotes/{0}/{1}".format(remote, name),
    )
    exists_remote = None if remote_code is None else remote_code == 0
    return exists_local, exists_remote


_LANE_WILDCARD_CHARS = frozenset("*?[")


#: `linked_worktree_state`'s own return values -- a repository's ordinary
#: working tree, a linked worktree `git worktree add` cut, or "git did not
#: answer either call" (never folded into `WORKTREE_MAIN`, which would let
#: #865 back in through the one case this function exists to catch).
WORKTREE_MAIN = "main"
WORKTREE_LINKED = "linked"
WORKTREE_COULD_NOT_TELL = "could-not-tell"


def linked_worktree_state(repo):
    """Is `repo`'s working tree a linked worktree (cut by `git worktree add`)
    rather than the repository's own main tree -- `(state, detail)` (#865).

    `.oss.local.json` is git-excluded, so it is absent from every worktree
    this loop cuts, by construction. `derive_worktree`'s `unknown` branch used
    to be the only documented consequence, but #608's own repository-root
    derivation (`oss_config._derive_local_config`) means `worktree_root`
    rarely reaches that branch any more: standing inside a worktree, it
    derives `<this worktree's own path>-wt` instead -- a value, not an
    absence, and a *wrong* one, sibling to the one worktree that asked rather
    than to the clone every other lane reads. Reproduced directly: a
    `--claim` call from inside a real linked worktree recorded into
    `<worktree>-wt/.oss-lanes`, invisible to `--derive-held` runs from
    anywhere else.

    Detecting "standing inside a linked worktree" needs a fact this module
    cannot derive from a path alone -- `worktree_root`'s own convention names
    nothing that distinguishes a clone from a worktree, and guessing from a
    directory name would be exactly the hardcoded-fact failure `CLAUDE.md`
    forbids. Git already carries the fact: `--git-common-dir` and `--git-dir`
    resolve to the same path for an ordinary working tree and differ for a
    linked one (`--git-dir` points at `<common>/.git/worktrees/<name>` from
    inside it) -- measured directly here (`git version 2.55.0`, darwin),
    reused rather than reasoned about.

    Three states, not two: `could-not-tell` when git did not answer either
    call (not on PATH, the repo unreadable) must never render as `main` --
    that fold is the exact defect this function exists to close, one call
    away from where it bit.
    """
    common_code, common_out, common_err = _git(repo, "rev-parse", "--git-common-dir")
    git_code, git_out, git_err = _git(repo, "rev-parse", "--git-dir")
    if common_code != 0 or git_code != 0 or not common_out or not git_out:
        return WORKTREE_COULD_NOT_TELL, _one_line(
            common_err or git_err or "git did not answer"
        )
    common_path = Path(repo, common_out).resolve()
    git_path = Path(repo, git_out).resolve()
    if common_path == git_path:
        return WORKTREE_MAIN, ""
    return WORKTREE_LINKED, ""


def derive_worktree(config, issue, origin=None):
    """The worktree path for `issue`, from `worktree_root` in `.oss.local.json`.

    Absent by construction inside every worktree this loop cuts -- `.oss.local.json`
    is git-excluded, so a lane-setup call run from inside a worktree (rather than the
    main clone) will always land here. That is a real third state, not a bug in this
    function: `doctor` measured a fresh worktree at 4 failures for exactly this reason
    (CLAUDE.md, "Dogfooding still finds what the suite cannot").

    #608: `worktree_root` used to be simply absent on a fresh clone that has never
    written `.oss.local.json` -- `oss_config.load()` now derives it from the
    repository root instead, so this function's `unknown` branch fires only when
    derivation itself could not run. `origin` -- `oss_config.local_key_states(...)
    ["worktree_root"]`, a `(state, value, reason)` triple -- is optional, and every
    existing caller that does not pass one keeps this function's prior wording. When
    given, the returned dict carries an `origin` field (`configured` /
    `derived, not configured` / None when the caller passed none) so a reader of the
    condensed board can tell a value someone chose from one this script guessed --
    #608's own acceptance condition, reached here from the "no lane can be cut" side.
    """
    root = config.get("worktree_root")
    origin_state = origin[0] if origin is not None else None
    if not root:
        if origin_state == oss_config.LOCAL_STATE_COULD_NOT_DERIVE:
            detail = "worktree_root could not be derived from the repository root ({}).".format(
                origin[2]
            )
        else:
            detail = (
                ".oss.local.json carries no worktree_root in this tree -- expected "
                "if this is running inside a worktree rather than the main clone."
            )
        return {
            "state": "unknown",
            "root": None,
            "path": None,
            "detail": detail,
            "origin": origin_state,
        }
    try:
        path = oss_config.resolve_worktree(root, str(issue))
    except oss_config.ContainmentError as exc:
        return {
            "state": "invalid",
            "root": root,
            "path": None,
            "detail": _one_line(str(exc)),
            "origin": origin_state,
        }
    return {
        "state": "resolved",
        "root": root,
        "path": str(path),
        "detail": "",
        "origin": origin_state,
    }


# How far up the tree `_absence_confirmed` will walk looking for an ancestor this
# platform can look at. A path has a finite number of components and the loop already
# stops at the anchor, so this is a belt on a walk that terminates -- against a
# filesystem whose `dirname` never reaches a fixed point (a synthetic path object, a
# broken mount), not against ordinary input.
_ANCESTOR_LIMIT = 512


def _absence_confirmed(path):
    """Confirm positively that nothing is at `path`, after `stat` already raised one
    of the two absence exceptions. True / False / None -- and the third is the point.

    True  -- confirmed absent: an ancestor this platform *can* look at was listed and
             the next component down was not in it (or that ancestor is not a
             directory at all, so nothing can be under it).
    False -- the name is right there in its parent's listing and `stat` could not
             reach it. That is the unlookable case wearing absence's clothes.
    None  -- nothing here could confirm either way, so the caller must not claim.

    **Why this control and not the one #380 proposed.** The issue asks for a
    plainly-missing path *of the same shape* to be stat'ed as a control and compared
    against the subject. That comparison carries no signal on the platform it was
    written for: a same-shape plainly-missing path is *also* past `MAX_PATH`, so it
    answers exactly what the subject answered, and identical-therefore-absent comes
    back for the genuine miss and the unlookable name alike -- a guard nominally on
    and effectively never firing, which is this repository's own defect class one
    layer up. The control used instead is one the subject cannot fake: the subject's
    own deepest ancestor that this platform can look at, plus that ancestor's
    directory listing. Same shape by construction rather than by approximation -- it
    *is* the subject's path prefix -- and enumeration answers regardless of how long
    the resulting full path would be, which is exactly the property `stat` loses.

    No errno appears here and no length is compared against a constant. `MAX_PATH` is
    conditional on a machine setting, so a constant would be the table this file
    already refused to write (#380), and Windows folds several Win32 codes onto
    `ENOENT`, so a table cannot report the value it needs.

    **The price, and where it is paid.** One `stat` per ancestor actually walked plus
    one `listdir`, and it is paid only on the absence arm -- the seam where a
    confident verdict is about to be printed. A successful `stat` pays nothing, and
    the general `OSError` arm pays nothing because it is already the third state. In
    the ordinary input (`worktree_root/NNN` with the root present) that is exactly one
    extra `stat` and one `listdir` per run.

    Two answers it deliberately does not try to be clever about. A parent that stats
    but will not list (mode 0o111) returns None rather than falling back to the
    exception, because "I could not confirm" is what actually happened. And a name
    found in the listing is reported as unlookable even when the real cause was a
    delete racing the `stat`; a race is honestly a case where nothing looked.
    """
    try:
        current = os.path.abspath(os.fspath(path))
    except (OSError, ValueError, TypeError):
        return None
    for _ in range(_ANCESTOR_LIMIT):
        parent = os.path.dirname(current)
        name = os.path.basename(current)
        if not name or parent == current or not parent:
            return None
        try:
            found = os.stat(parent)
        except (FileNotFoundError, NotADirectoryError):
            current = parent
            continue
        except (OSError, ValueError):
            return None
        if not stat.S_ISDIR(found.st_mode):
            return True
        try:
            entries = os.listdir(parent)
        except (OSError, ValueError):
            return None
        return name not in entries
    return None


def worktree_occupancy(path):
    """Whether something already sits at `path`: True, False, or None for "could not look".

    #373: this used `os.path.exists`, which never raises and therefore never
    distinguishes. An unreadable *parent* came back `False` and the receipt printed
    `[free]` -- a confident absence, in output a maintainer pastes into a developer
    brief. The third state existed in the rendering and was reachable only when `path`
    itself was falsy, so the one case it was written for could not produce it.

    `os.stat` is asked once and the exception decides which arm runs -- never an
    errno table. `FileNotFoundError` and `NotADirectoryError` are the absence arm;
    every other `OSError` is "I could not look". Both are the types Python's own
    interpreter normalises platform errors into, which matters because CLAUDE.md
    records Windows folding several Win32 codes onto `ENOENT`, so a table would
    answer for a value it does not contain.

    **The absence arm is an arm, not a verdict -- #380.** Until #380 this paragraph
    also said the exception in hand answered the question outright and no second call
    was ever made, and that stopped being true in the same change that added the
    paragraph below: reaching the absence arm now costs a confirmation
    (`_absence_confirmed`), which is one `os.stat` per ancestor walked plus one
    `os.listdir`. It is paid only there, never on a successful `stat` and never on the
    general `OSError` arm, which is already the third state.

    **#380 closed the gap that folding left open, and the exception is no longer
    trusted on its own.** CLAUDE.md's own measurement is that an over-long path arrives
    on Windows as `FileNotFoundError, errno 2, winerror None` -- no distinguishing
    signal at all -- so a `worktree_root` deep enough that the derived path passes
    `MAX_PATH` on a runner without `LongPathsEnabled` used to be classified `False`
    here and printed `[free]`: the confident absence #373 exists to close, reaching it
    through the one exception type that fix treats as safe. So the absence arm no
    longer returns absence on the strength of the exception type; it asks
    `_absence_confirmed` for a positive confirmation first, and answers `None` when
    none is available. `doctor._dir_state` took the identical decision in the same
    change -- one decision about two functions, which is what
    `tests/test_lane_setup_373.py` and `tests/test_unlookable_absence_380.py` pin.

    Deliberately `os.stat` rather than `Path.exists()` / `Path.is_dir()`, whose
    OSError-swallowing behaviour changed across 3.10-3.14 (CLAUDE.md, "Path.rglob and
    Path.is_dir each destroy the answer a guard beside them was written to read").

    **`doctor._dir_state` is the sibling of this function and was not imported.** It
    answers `dir` / `absent` / `unreadable` and this answers "is anything there", so
    they are two questions sharing one mechanism rather than one classifier written
    twice; and it lives in `scripts/doctor.py` with four call sites and its own tests,
    so lifting it into a shared module is a refactor with a blast radius past this fix.
    What keeps them from drifting is not this paragraph:
    `tests/test_lane_setup_373.py` runs both on one fixture and fails if either changes
    its mind.
    """
    if not path:
        return None
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        # #380: the exception type alone is not evidence of absence on a platform
        # that folds an unlookable name onto it. Absence is claimed only when
        # something positively confirmed it.
        return False if _absence_confirmed(path) is True else None
    except OSError:
        return None
    except ValueError:
        # #380, adjacent: `os.stat` raises `ValueError`, not `OSError`, for a path
        # carrying an embedded null byte, so neither arm above caught it and it
        # escaped this function as a traceback. `worktree_root` is read from
        # `.oss.local.json` and JSON can spell a null. Nothing looked -- which is
        # what this function's third state is for.
        return None
    return True


# Lines the condensed board keeps: a header, the data-provenance disclaimer, one line
# per worktree (the state word starts at column 0 -- "occupied", "idle", "cannot tell"
# -- so it is never itself indented), and the final tally. Everything indented under an
# entry is the bullet-level detail the full op prints, and it is dropped -- see the
# module docstring for the byte budget this buys.
_DROP_PREFIXES = ("---", "PASS", "FAIL", "[exit")
