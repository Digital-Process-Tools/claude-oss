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
(CLAUDE.md, skills/manager/phases/release.md).

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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oss_config  # noqa: E402  (path insert above must run first)

CONFIG_NAME = ".oss.json"
ISSUE_PLACEHOLDER = "{issue}"

EXIT_OK = 0
EXIT_COULD_NOT_RUN = 3

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


def _match_is_regular_file(p):
    """`p.is_file()`, but through `stat()` directly rather than the
    convenience wrapper.

    `Path.is_file()` wraps its own `stat()` call in a version-dependent
    swallow (CLAUDE.md's own `Path.exists()`/`Path.is_dir()` trap; also
    `doctor._dir_state`'s docstring, which measured the swallow directly on
    a local 3.14 install and found `path.stat()` itself does not swallow
    there -- only the convenience method does). A glob match this process
    cannot `stat()` -- an entry-level failure independent of the
    directory-traversal permission `glob()` already needed to find it --
    used to disappear from `resolve_lane`'s `matches` silently instead of
    reaching the `except (OSError, ValueError)` that already wraps the
    comprehension calling this and turns an unresolvable pattern into a
    `"refused"` state with a detail (#383): the census's second finding,
    that `glob-no-match` is itself a printed verdict `lane_overlap`
    consumes for #267's disjointness check, not a filter with nowhere for
    a swallowed entry to do harm.

    `FileNotFoundError` is not re-raised: `glob()` found the entry and it
    is gone by the time this runs is a race, not a permission problem, and
    is excluded the same as any other non-match rather than refusing the
    whole pattern over it.
    """
    try:
        st = p.stat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(st.st_mode)


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
    disagreeing with each other -- True and False -- so a check that delegates
    to whichever `os.path` the host aliases refuses a POSIX-rooted pattern on
    Linux/macOS and lets the identical string through, unrefused, on Windows.

    #435 sharpened this: it is not only a platform fact, it is an *interpreter*
    fact on top of a platform one. `ntpath.isabs("/etc/passwd")` answers True on
    CPython 3.9-3.12 (observed on this repo's own CI, a 3.9.25 run) and False on
    3.13 (observed locally) -- the same string, the same module, two different
    answers depending on which interpreter loaded it. This repo's CI runs three
    platforms *and* four Python versions, so `os.path.isabs` was never a stable
    foundation on any one of the six combinations it actually gates, only on
    whichever combination happened to be sitting on the machine that wrote the
    check. The string test below needs neither the platform's nor the
    interpreter's answer to agree with any other: a leading `/` (which also
    catches a leading `//` UNC root) or a drive-letter prefix.
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
                    if _match_is_regular_file(p)
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


# #432: a lane's local test command narrows to the files a brief names, and CI then
# reddens on a guard test whose own filename has no visible relationship to the
# diff -- measured on PR #431, where a diff that started calling the changelog
# scaffolding gate's producer function (in `scripts/oss_config.py`) was invisible
# to a narrowed run naming three doctor-shaped test files, and CI failed on
# `tests/test_gate_state_consumers_328.py` instead. Five guard tests answer to
# *what a diff does* rather than to a module it renames -- enumerated here by
# reading each one's own docstring for its trigger, not by trusting the issue's
# own list, which is #335's own sentence about how this seam got here in the
# first place. A guard list is a fact about the repository, so it lives beside
# `resolve_lane` rather than being re-typed into every brief.
#
# Each entry is (path prefix a resolved lane file must start with or equal, the
# guard test file, one-line why). A file can trip more than one guard for
# different reasons -- `scripts/oss_config.py` is both an ordinary script under
# `scripts/` (test_unwired_scripts_253) and the one file that can register a new
# consumer of that gate's state (test_gate_state_consumers_328).
#
# Deliberately not naming the gate producer's function identifier by its exact
# spelling anywhere in this module: `tests/test_gate_state_consumers_328.py`
# scans every file under `scripts/` for a bare occurrence of that name and
# demands it be a *registered* consumer, and this file names it only to describe
# the guard, never to call it -- the same bug this issue is about, one level up,
# caught by writing the fix and running the guard it documents.
CROSS_CUTTING_GUARDS = (
    ("skills/", "tests/test_content_invariants.py",
     "hardcoded repo facts in skill/agent/command prose"),
    ("agents/", "tests/test_content_invariants.py",
     "hardcoded repo facts in skill/agent/command prose"),
    ("commands/", "tests/test_content_invariants.py",
     "hardcoded repo facts in skill/agent/command prose"),
    ("scripts/", "tests/test_unwired_scripts_253.py",
     "a script added, removed, or dropped from its last live reference"),
    ("bin/", "tests/test_unwired_scripts_253.py",
     "a script added, removed, or dropped from its last live reference"),
    # test_gate_state_consumers_328.py scans *every* tracked file under commands/ and
    # scripts/ for a bare occurrence of the gate producer's identifier, not only the
    # files that already call it -- an auditor caught the first version of this
    # mapping naming only the four current consumers, which reported nothing for a
    # brand-new file that started calling it, exactly the PR #431 shape this issue is
    # about. So the trigger here is the same two directories the real guard scans,
    # not an enumeration of who currently calls it.
    ("scripts/", "tests/test_gate_state_consumers_328.py",
     "may add or lose a consumer of the changelog scaffolding gate's state"),
    ("commands/", "tests/test_gate_state_consumers_328.py",
     "may add or lose a consumer of the changelog scaffolding gate's state"),
    ("CLAUDE.md", "tests/test_claude_md_currency.py",
     "the 'What is not proven yet' release marker paragraph"),
    ("changelog.d/", "tests/test_claude_md_currency.py",
     "fragment presence gates whether the release marker must be current"),
    ("pyproject.toml", "tests/test_python_floor_410.py",
     "the declared Python floor and its four derived sites"),
    ("README.md", "tests/test_python_floor_410.py",
     "the Python floor's README support badge"),
    ("scripts/doctor.sh", "tests/test_python_floor_410.py",
     "the Python floor's oldest python3.N candidate in the interpreter walk"),
    (".github/workflows/tests.yml", "tests/test_python_floor_410.py",
     "the Python floor's CI matrix lowest entry"),
)


def _guard_test_existence(repo, test_path):
    """Whether `test_path` (one of `CROSS_CUTTING_GUARDS`'s own entries) exists as a
    regular file under `repo`. Three states, not two -- #566:

      exists          the guard test is present in this repository. Run it.
      absent          confirmed not present -- this class of guard does not exist
                       here, and a lane must be told that rather than handed a
                       path that collects nothing.
      could-not-tell  the repository could not be examined at this path -- an
                       ancestor this process cannot traverse, an unreadable
                       parent. Never folded into `absent`: an unlookable name
                       and a genuine miss render identically as
                       `FileNotFoundError` on a platform that folds Win32 codes
                       onto `ENOENT` (CLAUDE.md), so `_absence_confirmed` --
                       already used by `worktree_occupancy` and `lane_count` for
                       the identical swallow -- decides which of the two this is
                       rather than trusting the exception type alone.

    `CROSS_CUTTING_GUARDS` is a fact about *this* repository (claude-oss) living
    in shared code that runs against every managed repository (#566) -- a
    managed repo carries none of these test files by construction. This
    function is what turns "the table names a guard" into "the guard applies
    here", the same way `resolve_lane`'s `glob-no-match` turns "the pattern is
    well-formed" into "the pattern matched something": a fact asserted and a
    fact confirmed are not the same claim, and only a check can tell them apart.
    """
    p = Path(repo) / test_path
    try:
        st = p.stat()
    except (FileNotFoundError, NotADirectoryError):
        return "absent" if _absence_confirmed(p) is True else "could-not-tell"
    except (OSError, ValueError):
        return "could-not-tell"
    return "exists" if stat.S_ISREG(st.st_mode) else "absent"


def known_guards(repo=None):
    """The full enumeration, grouped by guard test with every trigger reason that
    maps to it. Answers #432's own sizing question -- how many of these exist --
    as a derived count rather than a pasted one, so a sixth guard added later
    changes this return value instead of needing a second list updated by hand.

    `repo` is optional and, when given, adds each entry's `status`
    (`_guard_test_existence`) against that repository -- #566/#567: the sizing
    answer this exists to give is about the repository a lane is dispatched
    into, not about claude-oss's own tree, so a caller counting "how many
    guards apply" in a managed repo must count entries whose `status` is
    `exists`, not the declared length of `CROSS_CUTTING_GUARDS`. Omitted
    (`repo=None`) keeps the declared enumeration only -- the shape this
    function has always had, and what `claude-oss`'s own sizing test still
    checks against its own tree.
    """
    grouped = {}
    for prefix, test_path, why in CROSS_CUTTING_GUARDS:
        grouped.setdefault(test_path, []).append({"prefix": prefix, "why": why})
    result = []
    for test_path in sorted(grouped):
        entry = {"test": test_path, "triggers": grouped[test_path]}
        if repo is not None:
            entry["status"] = _guard_test_existence(repo, test_path)
        result.append(entry)
    return result


def guards_for_files(files, repo=None):
    """Which guard tests a lane's resolved files (`resolve_lane`'s `files` list --
    repo-relative POSIX paths, never a module-name guess) trip, deduplicated to one
    entry per guard even when several files or several reasons point at it.

    Matches by prefix on the canonical path form the rest of this module already
    produces, not by trusting a caller's own idea of which area a change belongs
    to -- the seam #432 exists to close was exactly a human's idea of "these three
    files are about doctor" being wrong about a fourth, unrelated-by-name file.

    `repo` is optional and, when given, adds each entry's `status`
    (`_guard_test_existence`) against that repository -- #566: `CROSS_CUTTING_GUARDS`
    is a fact about claude-oss, and a lane dispatched into a managed repository
    that does not carry a named guard test must be told so rather than handed a
    path that collects nothing when it runs the guard. The entry is never
    dropped for `absent` or `could-not-tell` -- the class still applies to the
    files touched, and dropping it would silently undo the trigger this
    function exists to report; only the disposition changes, from "run this"
    to "this class applies and cannot be run here".
    """
    hits = {}
    for f in files or []:
        for prefix, test_path, why in CROSS_CUTTING_GUARDS:
            if f == prefix or f.startswith(prefix):
                reasons = hits.setdefault(test_path, [])
                if why not in reasons:
                    reasons.append(why)
    result = []
    for test_path in sorted(hits):
        entry = {"test": test_path, "why": hits[test_path]}
        if repo is not None:
            entry["status"] = _guard_test_existence(repo, test_path)
        result.append(entry)
    return result


def lane_report(repo, lane_patterns, against_patterns):
    """The `lane` section of a lane-setup payload, or None when neither side
    was asked for. Two lanes given: also the overlap between them, so a
    developer brief's setup call can carry the collision check the maintainer
    would otherwise have to run by eye.

    `guards` (#432) is computed only from the `lane` side's resolved files --
    the files a developer brief is actually about to touch -- never from
    `against`, which names a sibling lane's off-limits files. Reporting a
    guard triggered by the sibling's files would tell a developer to run a
    test for a change it must not make.
    """
    if not lane_patterns and not against_patterns:
        return None
    a = resolve_lane(repo, lane_patterns) if lane_patterns else None
    b = resolve_lane(repo, against_patterns) if against_patterns else None
    overlap = lane_overlap(a["files"], b["files"]) if a and b else None
    # #566: `repo` is threaded through so each guard's `status` is answered against
    # the repository the lane is actually dispatched into, never against claude-oss's
    # own tree by default -- the whole defect this issue is about.
    guards = guards_for_files(a["files"], repo) if a else []
    return {"lane": a, "against": b, "overlap": overlap, "guards": guards}


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


def record_lane(worktree_root, issue, branch, path):
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
    payload = {
        "issue": issue,
        "branch": branch,
        "path": str(path) if path else None,
        "recorded_at": time.time(),
        "pid": os.getpid(),
    }
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
        return {"state": "unknown", "count": None, "detail": "worktree_root is not known."}
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
        if _absence_confirmed(root) is not True:
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


def lanes_snapshot(worktree_root, issue, branch, path):
    """Record this lane's own presence, then report the live picture -- including
    itself. Called from `compute` at the one moment #385 says the count is useful:
    setup time, before a lane sizes itself against the machine and before `doctor`
    typically runs.
    """
    record = record_lane(worktree_root, issue, branch, path)
    count = lane_count(worktree_root)
    return {"record": record, "count": count}


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
            "lanes": None,
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

    lanes = lanes_snapshot(
        config.get("worktree_root"), issue, branch.get("name"), worktree.get("path")
    )

    return {
        "issue": issue,
        "repo": str(repo),
        "config": {"state": "ok", "problems": problems},
        "base": base,
        "branch": branch,
        "worktree": worktree,
        "board": board,
        "lanes": lanes,
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

    lanes = payload.get("lanes")
    if lanes is not None:
        count = lanes["count"]
        if count["state"] == "resolved":
            lines.append(_row("lanes", "{0} live (recorded, TTL {1}m)".format(
                count["count"], LANE_RECORD_TTL_SECONDS // 60
            )))
        else:
            lines.append(_row("lanes", "{0} -- {1}".format(count["state"].upper(), count["detail"])))
        record = lanes["record"]
        if record["state"] != "recorded":
            lines.append("  this lane not recorded: {0} -- {1}".format(
                record["state"], record["detail"]
            ))

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
        # #432: guards the lane side's own files trip -- a narrowed local test
        # command that omits these will look green and CI will not.
        if lane["lane"] is None:
            pass
        elif lane["guards"]:
            # #566: a guard entry always carries a `status` now that `lane_report`
            # threads `repo` through -- `exists` reads exactly as it always has,
            # `absent` and `could-not-tell` are said in as many words rather than
            # handing a lane a path that would collect nothing.
            for entry in lane["guards"]:
                status = entry.get("status")
                why = "; ".join(entry["why"])
                if status == "absent":
                    lines.append(
                        "  guard   : {0} -- NOT IN THIS REPO, treat as uncovered "
                        "({1})".format(entry["test"], why)
                    )
                elif status == "could-not-tell":
                    lines.append(
                        "  guard   : {0} -- COULD NOT TELL whether this repo has it "
                        "({1})".format(entry["test"], why)
                    )
                else:
                    lines.append("  guard   : {0} ({1})".format(entry["test"], why))
        else:
            lines.append("  guard   : none of the lane's files match a known cross-cutting guard")

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
