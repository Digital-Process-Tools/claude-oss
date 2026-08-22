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
  occupancy  a separate three-state beside the one above, for whether anything
             already sits at the derived path: already exists, free, or unknown
             when the path could not be looked at. #373: it used `os.path.exists`,
             which swallows `OSError`, so an unreadable parent printed `free` and
             the third state was reachable only for an empty path.
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
import re
import shutil
import stat
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
            "remote: expected a remote name, URL or path as a string; "
            "got {!r}.".format(value)
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


_LANE_WILDCARD_CHARS = frozenset("*?[")


def _is_lane_glob(pattern):
    return any(ch in pattern for ch in _LANE_WILDCARD_CHARS)


def _lane_pattern_problem(pattern):
    """Why `pattern` cannot be rendered as part of a lane, or None when it can.

    #267: a lane an agent implements gets asserted from a maintainer's memory,
    never re-derived. A lane pattern reaching this function is one step closer
    to trusted than that -- it is still typed by a human, but it is about to be
    turned into the one canonical form (a resolved, repo-relative path) that a
    second brief's lane can be checked against, rather than eyeballed. It is
    refused the same way `oss_config.resolve_worktree` refuses a worktree
    target: absolute, drive-prefixed or traversing out of the repo is refused
    before anything touches the filesystem, not caught after.

    **Deliberately not `os.path.isabs`.** The auditor measured
    `posixpath.isabs("/etc/passwd")` and `ntpath.isabs("/etc/passwd")`
    disagreeing -- True and False -- so a check that delegates to whichever
    `os.path` the host aliases refuses a POSIX-rooted pattern on Linux/macOS
    and lets the identical string through, unrefused, on Windows. This repo's
    own CI runs all three. The check below is a string test against the
    backslash-normalized pattern instead: a leading `/` (which also catches a
    leading `//` UNC root) or a drive-letter prefix, neither of which needs
    the host's own path module to answer the same on every platform.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        return "lane pattern is empty"
    normalized = pattern.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", pattern):
        return "lane pattern {0!r} is not relative".format(pattern)
    if ".." in normalized.split("/"):
        return "lane pattern {0!r} is a traversal".format(pattern)
    return None


def resolve_lane(repo, patterns):
    """Render a maintainer-asserted lane -- a mix of literal paths and glob
    patterns, exactly what a brief's `lane:` line carries today -- in the one
    canonical form the issue asks for: a sorted, deduplicated list of
    repo-relative POSIX paths, so a second brief's lane can be compared to it
    by `lane_overlap` instead of by eye.

    #267, instance two: `fix/247-244`'s lane was a literal path
    (`skills/manager/SKILL.md`) and `fix/262-248`'s was a glob
    (`commands/*.md`); the second agent's fix correctly touched
    `commands/tick.md`, and nothing caught the collision because a glob and a
    path cannot be intersected by eye. Both forms resolve through here to the
    same shape.

    Three states per pattern, not two: `literal` (asserted, not checked
    against the tree -- the file may not exist yet, such as a changelog
    fragment about to be created), `glob-resolved` (expanded against files
    that exist), and `glob-no-match` (the pattern was well-formed and matched
    nothing -- reported rather than silently folded into an empty result, the
    same distinction `derive_branch`'s `unknown` state draws elsewhere in this
    file). A fourth, `refused`, covers a pattern `_lane_pattern_problem` will
    not resolve at all.
    """
    repo = Path(repo)
    entries = []
    files = set()
    for pattern in patterns:
        problem = _lane_pattern_problem(pattern)
        if problem is not None:
            entries.append({"pattern": pattern, "state": "refused", "files": [], "detail": problem})
            continue
        # #267 review: normalized once here, and both branches below use the
        # normalized form -- the literal branch always did (`os.path.normpath`
        # needs it to collapse `.` and repeated separators), and the glob
        # branch used to pass the raw pattern straight to `Path.glob`, which
        # treats a backslash as a literal filename character on POSIX rather
        # than a separator. A pattern typed with Windows-style separators
        # silently matched nothing there -- a laundered false negative in the
        # exact tool #267 exists to stop one.
        normalized = pattern.replace("\\", "/")
        if _is_lane_glob(pattern):
            try:
                matches = sorted(
                    p.relative_to(repo).as_posix()
                    for p in repo.glob(normalized)
                    if p.is_file()
                )
            except (OSError, ValueError) as exc:
                entries.append(
                    {
                        "pattern": pattern,
                        "state": "refused",
                        "files": [],
                        "detail": "{0}: {1}".format(type(exc).__name__, exc),
                    }
                )
                continue
            state = "glob-resolved" if matches else "glob-no-match"
            entries.append({"pattern": pattern, "state": state, "files": matches, "detail": ""})
            files.update(matches)
        else:
            rel = os.path.normpath(normalized).replace(os.sep, "/")
            entries.append({"pattern": pattern, "state": "literal", "files": [rel], "detail": ""})
            files.add(rel)
    return {"patterns": entries, "files": sorted(files)}


def lane_overlap(files_a, files_b):
    """The files two resolved lanes -- `resolve_lane`'s `files` list, from
    either side -- both claim. This is the disjointness check #267 asks for:
    run against two lanes rendered in one form, rather than against a
    maintainer's memory of which glob might touch which path.
    """
    return sorted(set(files_a) & set(files_b))


def lane_report(repo, lane_patterns, against_patterns):
    """The `lane` section of a lane-setup payload, or None when neither side
    was asked for. Two lanes given: also the overlap between them, so a
    developer brief's setup call can carry the collision check the maintainer
    would otherwise have to run by eye.
    """
    if not lane_patterns and not against_patterns:
        return None
    a = resolve_lane(repo, lane_patterns) if lane_patterns else None
    b = resolve_lane(repo, against_patterns) if against_patterns else None
    overlap = lane_overlap(a["files"], b["files"]) if a and b else None
    return {"lane": a, "against": b, "overlap": overlap}


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


def compute(repo, issue, remote="origin", lane_patterns=None, against_patterns=None):
    """Everything a lane brief needs, in one payload. `config.state` gates the exit.

    `lane_patterns` / `against_patterns` are optional (#267): when neither is
    given, `payload["lane"]` is None -- an absent ask must not read as a
    checked, empty lane. When either is given, both sides are rendered
    through `resolve_lane` and, when both sides are present, compared with
    `lane_overlap` -- the disjointness check the manager skill currently runs
    by eye.
    """
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
            "lane": lane_report(repo, lane_patterns, against_patterns),
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
        "lane": lane_report(repo, lane_patterns, against_patterns),
    }


def blocked(payload):
    """True when there is not enough here to cut a lane from."""
    if payload["config"]["state"] != "ok":
        return True
    return payload["base"]["state"] == "could-not-resolve"


def _row(label, value):
    return "{0:<10}: {1}".format(label, value)


#: A receipt line is one line, and nothing interpolated into it may make it two.
#: Generous rather than tight: the longest legitimate line measured here is an
#: `oss_config` problem sentence at roughly 290 characters, and truncating a real
#: sentence to close a forging hole would trade one silent loss for another.
_RECEIPT_LINE_LIMIT = 2000
_TRUNCATION_MARK = " ... [truncated]"


def _receipt_line(text):
    """One assembled receipt line, folded so nothing in it can forge another (#372).

    Applied at the single point where the receipt is joined, rather than to a list of
    fields. Four separate values were measured forging lines: `branch_pattern`, the
    `--repo` argv and `worktree_root`, which the audit reached, and an `oss_config`
    problem sentence built from a hostile JSON **key**, which it did not. That fourth
    one is why this is not a per-field guard: it needs no hostile *value* anywhere, and
    `oss_config` cannot close it at its end without refusing to name the key that is
    wrong. A guard on a list of fields closes the fields somebody enumerated and leaves
    the next field added to this function unguarded.

    Deliberately **not** `_one_line`, which is right for what it does and wrong here.
    Its `" ".join(text.split())` collapses runs of spaces, and every row in this
    receipt is aligned by `_row`'s `{0:<10}` padding -- folding the assembled line
    through it turns `repo      : x` into `repo : x` and destroys the column the whole
    receipt is read by. Only the half that matters for forging is applied: every
    character outside printable ASCII becomes `?`, which covers newline, carriage
    return and the control characters that repaint a line, and leaves spaces alone.
    `_one_line` still runs where it already ran, on `detail` and the board lines, so
    this is additive rather than a replacement.

    Truncation is marked. A cut line that renders as a complete one is this
    repository's own defect class pointed at its own receipt. `_one_line` itself is
    left alone: its callers pin their own limits and its silent truncation is theirs.
    """
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text))
    if len(safe) > _RECEIPT_LINE_LIMIT:
        keep = max(0, _RECEIPT_LINE_LIMIT - len(_TRUNCATION_MARK))
        safe = safe[:keep] + _TRUNCATION_MARK
    return safe


def _render(lines):
    """The one place a receipt becomes text, so the fold cannot be skipped by a caller."""
    return "\n".join(_receipt_line(line) for line in lines)


def receipt(payload):
    lines = ["LANE SETUP #{0}".format(payload["issue"]), _row("repo", payload["repo"])]

    if payload["config"]["state"] != "ok":
        lines.append("config    : COULD NOT RUN")
        for problem in payload["config"]["problems"] or []:
            lines.append("  - " + problem)
        return _render(lines)

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

    lane = payload.get("lane")
    if lane is not None:
        lines.append("lane      :")
        for side_label, side in (("lane", lane["lane"]), ("against", lane["against"])):
            if side is None:
                continue
            for entry in side["patterns"]:
                lines.append(
                    "  [{0}] {1} ({2}): {3}".format(
                        side_label, entry["pattern"], entry["state"], ", ".join(entry["files"]) or "-"
                    )
                )
        if lane["overlap"] is None:
            lines.append("  overlap : n/a -- only one side given")
        elif lane["overlap"]:
            lines.append("  overlap : " + ", ".join(lane["overlap"]))
        else:
            lines.append("  overlap : none")

    return _render(lines)


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
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        metavar="PATTERN",
        help="a file or glob this brief's lane touches; repeatable (#267)",
    )
    parser.add_argument(
        "--against",
        action="append",
        default=[],
        metavar="PATTERN",
        help="a file or glob to check --lane against for overlap; repeatable (#267)",
    )
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    payload = compute(args.repo, args.issue, args.remote, args.lane, args.against)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return EXIT_COULD_NOT_RUN if blocked(payload) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
