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
  record     recorded (this call passed --claim and the write succeeded), unknown
             (no worktree_root to write to -- expected inside a worktree this loop
             cuts), could-not-write (worktree_root known, the write itself failed),
             or not-claimed (#705: this call did not pass --claim, so it asked
             without writing -- the ordinary shape for a disjointness probe that
             may never be dispatched).

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

    #766: a `|`-joined value (`--lane 'a|b'`) used to fall straight through to
    the literal branch below -- `_is_lane_glob` only tests for `*?[`, so an
    awk/ERE-style alternation is neither a glob (no `Path.glob` semantics for
    `|`) nor a real filename, and the flag's own repeatable form is what
    actually spells "these two files". It resolved as one literal path that
    matched nothing on disk, the receipt printed it `(literal)`, and the
    overlap check then reported `none` for a pattern that was never read at
    all -- a disjointness gate rendering "could not be checked" as "checked,
    clear". Measured against this repository's own `--lane`, by the
    maintainer, three hours before this fix was written; the issue's own
    reproduction is against a sibling repo. `|` is refused unconditionally
    here rather than inferred as a mistake sometimes: it is not a legal glob
    metacharacter this module gives any meaning to, so there is no reading of
    it that is not the repeatable-flag form spelled wrong.

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
    if "|" in pattern:
        return (
            "lane pattern {0!r} contains '|' -- this flag takes one file or glob "
            "per invocation and does not read '|' as alternation; repeat --lane "
            "(or --against) once per file instead (#766)".format(pattern)
        )
    normalized = pattern.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", pattern):
        return "lane pattern {0!r} is not relative".format(pattern)
    if ".." in normalized.split("/"):
        return "lane pattern {0!r} is a traversal".format(pattern)
    return None


def _raise_walk_error(exc):
    """The `onerror` callback `_expand_directory` gives `os.walk` -- its own
    docstring default is `onerror=None`, meaning "ignore errors and continue
    the walk", which is `Path.rglob`'s own swallow (CLAUDE.md's trap) reached
    through a different stdlib entry point rather than avoided by using
    `os.walk` at all. Measured directly (`chmod 0` on a subdirectory, no
    exception observed from a bare `os.walk` over it): the swallow is real
    and the previous version of this function's own docstring claimed the
    opposite without checking. Passing this re-raises instead, which is what
    turns an unreadable subtree into the caller's `except OSError` -- a
    `refused` entry -- rather than a directory that silently reports fewer
    files than are really there.
    """
    raise exc


def _expand_directory(repo, rel):
    """Every regular file under repo-relative directory `rel`, recursively --
    sorted, repo-relative, POSIX paths. Caller has already confirmed `rel` is
    a directory; this only enumerates what is under it.

    `os.walk`, not `Path.rglob` -- CLAUDE.md's own trap: `rglob` swallows a
    `PermissionError` raised mid-walk and simply yields nothing for the
    unreadable subtree, so a directory this process cannot fully read would
    render identically to one that is genuinely empty. `os.walk` swallows the
    identical error by default (`onerror=None`), so `_raise_walk_error` is
    passed explicitly to re-raise -- the caller's `except OSError` around
    this call is what turns that into a `refused` entry instead of a silent
    `[]`.
    """
    matches = []
    for dirpath, _dirnames, filenames in os.walk(repo / rel, onerror=_raise_walk_error):
        for name in filenames:
            p = Path(dirpath) / name
            if _match_is_regular_file(p):
                matches.append(p.relative_to(repo).as_posix())
    return sorted(matches)


def _is_existing_directory(p):
    """`p.is_dir()`, but through `stat()` directly -- the same reason
    `_match_is_regular_file` does not use `Path.is_file()`: the convenience
    wrapper swallows a version-dependent set of `OSError`s and simply
    answers False, which here would silently fall a directory this process
    cannot `stat()` through to the ordinary literal-path branch instead of
    surfacing the failure.
    """
    try:
        st = p.stat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(st.st_mode)


def _raw_comma_pattern_names_one_existing_path(repo, raw):
    """Whether an unsplit `--lane` value `raw` -- known to contain a comma
    -- should be kept as a single member instead of being split on `,`
    (#836). A glob is never eligible: `_is_lane_glob` characters and a
    literal comma inside a path do not interact, so a glob is always split
    as before. Otherwise this is true only when `raw`, taken whole and
    unsplit, is refused by nothing `_lane_pattern_problem` checks and names
    a regular file or a directory that actually exists -- the one case a
    positive answer can be trusted rather than guessed, since a comma-
    joined value naming something that does not exist yet is exactly as
    likely to be two not-yet-existing patterns as one not-yet-existing
    path with a comma in its name, and `resolve_lane`'s `literal` state is
    documented to permit exactly that ambiguity for a single pattern with
    no comma at all.
    """
    if _is_lane_glob(raw) or _lane_pattern_problem(raw) is not None:
        return False
    normalized = raw.replace("\\", "/")
    rel = os.path.normpath(normalized).replace(os.sep, "/")
    try:
        target = repo / rel
        return _match_is_regular_file(target) or _is_existing_directory(target)
    except OSError:
        return False


def resolve_lane(repo, patterns):
    """Render a maintainer-asserted lane -- a mix of literal paths, bare
    directories and glob patterns, exactly what a brief's `lane:` line
    carries today -- in the one canonical form the issue asks for: a sorted,
    deduplicated list of repo-relative POSIX paths, so a second brief's lane
    can be compared to it by `lane_overlap` instead of by eye.

    `patterns` is the raw list of `--lane`/`--against` values, one per flag
    occurrence -- but a single value may itself be a comma-separated list of
    members (#809: `--lane 'a.md,b.md,c.py'`, the multi-pattern shape a
    brief's `lane:` line also uses). Each value is split on `,` into members
    *before* anything else runs, and every member is resolved independently
    through the identical per-pattern pipeline below -- there used to be no
    split at all, so a comma-joined string was compared as one literal path
    containing a literal comma, which matched nothing on disk regardless of
    what its members named, and a lane naming a held file inside a
    comma-list read `overlap: none`. Splitting first also fixes the
    collapse #809's third instance measured: one member matching nothing
    used to zero out every other member's real matches, because the whole
    joined string shared one `glob-no-match` entry; each member now keeps
    its own state and its own files, so a non-matching member no longer
    erases a matching one beside it. A member with no comma in the original
    value is unaffected -- `"x".split(",")` is `["x"]`.

    #267, instance two: `fix/247-244`'s lane was a literal path
    (`skills/manager/SKILL.md`) and `fix/262-248`'s was a glob
    (`commands/*.md`); the second agent's fix correctly touched
    `commands/tick.md`, and nothing caught the collision because a glob and a
    path cannot be intersected by eye. Both forms resolve through here to the
    same shape.

    Four states per member, not three: `literal` (asserted, not checked
    against the tree -- the file may not exist yet, such as a changelog
    fragment about to be created), `dir-expanded` (#809: the member names an
    existing directory, expanded to the regular files under it, recursively
    -- the natural thing to type for "everything under this directory", and
    until this fix compared as a literal path string against a held set of
    *file* paths, so it could never intersect even when a file inside it was
    genuinely held, while the equivalent glob correctly reported the
    collision), `glob-resolved` (expanded against files that exist), and
    `glob-no-match` (the pattern -- or the directory -- was well-formed and
    matched nothing, reported rather than silently folded into an empty
    result, the same distinction `derive_branch`'s `unknown` state draws
    elsewhere in this file). A fifth, `refused`, covers a member
    `_lane_pattern_problem` will not resolve at all.

    A lane whose members are *all* well-formed and checked but whose union
    still names zero files (every member `glob-no-match`, or a lane with no
    members at all having already returned early elsewhere) is not, on its
    own, a fact this function states -- callers needing to distinguish "this
    lane resolved to nothing" from "this lane is genuinely disjoint" read
    `resolved["files"]` being empty alongside `resolved["patterns"]` being
    non-empty; `lane_report`'s `_lane_resolved_to_nothing` is where that
    reading turns into its own availability state.
    """
    repo = Path(repo)
    entries = []
    files = set()
    members = []
    for raw in patterns:
        if "," in raw and _raw_comma_pattern_names_one_existing_path(repo, raw):
            # #836: a comma is legal in a filename on every platform this
            # loop's CI runs, and splitting a real path like
            # `docs/comma,name.md` apart on `,` breaks it into two members
            # that name nothing on disk -- the whole raw string already
            # names something real, so it is kept as one member rather than
            # guessed apart. Checked only when the *unsplit* raw string
            # resolves to an existing file or directory, which is the one
            # case a positive answer can be trusted instead of guessed: a
            # comma-joined value naming a not-yet-existing path (a
            # changelog fragment about to be created, joined with a second,
            # real pattern) still falls through to the split branch below,
            # unaffected -- `resolve_lane`'s documented `literal` contract
            # for not-yet-existing paths is preserved.
            members.append(raw)
        else:
            # #835: a member is stripped of surrounding whitespace before
            # it reaches `_lane_pattern_problem` -- a comma-joined value
            # typed with a space after the comma (`'a.md, b.md'`, the shape
            # a human types) used to carry that space into the literal
            # path itself, so it matched nothing on disk and a lane sharing
            # the real file printed `overlap: none` for a collision that
            # was never actually checked.
            members.extend(member.strip() for member in raw.split(","))
    for pattern in members:
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
            try:
                is_dir = _is_existing_directory(repo / rel)
            except OSError as exc:
                entries.append(
                    {
                        "pattern": pattern,
                        "state": "refused",
                        "files": [],
                        "detail": "{0}: {1}".format(type(exc).__name__, exc),
                    }
                )
                continue
            if is_dir:
                try:
                    matches = _expand_directory(repo, rel)
                except OSError as exc:
                    entries.append(
                        {
                            "pattern": pattern,
                            "state": "refused",
                            "files": [],
                            "detail": "{0}: {1}".format(type(exc).__name__, exc),
                        }
                    )
                    continue
                state = "dir-expanded" if matches else "glob-no-match"
                entries.append({"pattern": pattern, "state": state, "files": matches, "detail": ""})
                files.update(matches)
            else:
                entries.append({"pattern": pattern, "state": "literal", "files": [rel], "detail": ""})
                files.add(rel)
    return {"patterns": entries, "files": sorted(files)}


def _lane_resolved_to_nothing(resolved):
    """True when `resolved` (a `resolve_lane` result) named at least one
    member and every one of them was well-formed and checked, but the whole
    lane still names zero files on disk (#809: every member `glob-no-match`,
    e.g. `formatters/**/*.py` -- `**` is not the recursion this matcher
    implements -- or a directory with nothing under it).

    A lane in this state is not "genuinely disjoint" -- disjointness is a
    claim about two sets of real files that happen not to intersect, and
    there is no set here to have compared. It is "nobody managed to name a
    file", the issue's own wording, and must not share a verdict with either
    `available` or `blocked`.

    Returns False for `None` (nothing was asked for) and for a lane whose
    only members were `refused` -- that already has its own, more specific,
    `could-not-check` state in `lane_report`, and takes priority: a refused
    pattern was never read as a pattern at all, which is a different claim
    from "read, and named nothing".
    """
    if resolved is None or not resolved["patterns"]:
        return False
    if resolved["files"]:
        return False
    return any(entry["state"] != "refused" for entry in resolved["patterns"])


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


def _refused_patterns(resolved):
    """Every pattern in a `resolve_lane` result (`resolved["patterns"]`) that was
    refused outright, rather than checked against the tree at all -- #774. A
    `glob-no-match` pattern is a well-formed, verified fact (the pattern really
    does match nothing on disk) and correctly contributes an empty `files` list;
    a `refused` pattern was never read as a pattern in the first place, so the
    comparison `lane_overlap` performs never happened for it at all. Conflating
    the two -- both leave the pattern's own files out of `files` -- is exactly
    how a disjointness check that never ran for one side ends up printing the
    identical `overlap : none` a real, checked, disjoint result would also print
    (the issue's own measurement). `None` in, `[]` out: nothing to ask about a
    side that was never given.
    """
    if resolved is None:
        return []
    return [entry["pattern"] for entry in resolved["patterns"] if entry["state"] == "refused"]


def _unresolved_overlap_detail(a, a_refused, b, b_refused):
    """One line naming which side(s) carried a refused pattern and how many --
    #774's own suggested shape, `1 of 1 lane pattern(s) refused`, so the reason
    a comparison could not run is said in as many words rather than standing in
    silently for the bare word `none`.
    """
    parts = []
    if a_refused:
        parts.append(
            "{0} of {1} lane pattern(s) refused: {2}".format(
                len(a_refused), len(a["patterns"]), ", ".join(a_refused)
            )
        )
    if b_refused:
        parts.append(
            "{0} of {1} against pattern(s) refused: {2}".format(
                len(b_refused), len(b["patterns"]), ", ".join(b_refused)
            )
        )
    return "; ".join(parts)


def lane_report(repo, lane_patterns, against_patterns, derived_held=None):
    """The `lane` section of a lane-setup payload, or None when nothing at all
    was asked for. Two lanes given: also the overlap between them, so a
    developer brief's setup call can carry the collision check the maintainer
    would otherwise have to run by eye.

    `guards` (#432) is computed only from the `lane` side's resolved files --
    the files a developer brief is actually about to touch -- never from
    `against`, which names a sibling lane's off-limits files. Reporting a
    guard triggered by the sibling's files would tell a developer to run a
    test for a change it must not make.

    `derived_held` (#558) is `derive_held_set`'s own return value, or None. When
    given, it replaces `against_patterns` as the source of the "against" side --
    combining `--against` with it is refused earlier, in `main`, because a hand-typed
    exclusion beside a derived one is exactly the ambiguity #558 exists to close (was
    this file excluded because the derivation found it, or because someone typed it?).
    Its `held` files become literal patterns through the same `resolve_lane` every
    other side of this call already goes through, so the rendering and the overlap
    check are the one mechanism, not two. When `derived_held["state"]` is
    `could-not-derive`, no "against" side is resolved at all and `availability`
    carries `could-not-derive-the-held-set` -- #558's own words, never `available`
    and never `blocked`.

    `availability` (#558) is a *per-candidate* verdict -- available / blocked /
    could-not-check / could-not-derive-the-held-set -- computed only when
    `derived_held` was given, and only for the `lane` side against the derived
    set: a mechanical question this function can answer on its own. The
    tick-level *fill* verdict (filled / under-filled / could-not-tell) that #558
    also names is deliberately NOT computed here: it needs the full list of
    candidate issues under consideration this tick, which is a judgement about
    which issues are even being weighed, not a fact this script can derive from
    one `--lane` argument. That verdict stays prose in the tick, per the issue's
    own framing of the two halves as separable.

    `overlap_state` (#774) is a third answer sitting beside `overlap` itself --
    `resolved` (both sides were actually compared), `could-not-check` (at least
    one side carried a pattern `_lane_pattern_problem` refused, so the
    comparison never ran for it), or `n/a` (fewer than both sides were given at
    all, the pre-existing case). `overlap` alone cannot carry this on its own:
    `[]` is the correct, meaningful answer for two sides that were both
    genuinely resolved and share nothing, and #774's own measurement is that a
    refused pattern produces the identical `[]` -- one word, `none`, for two
    different claims, and in `--against` mode there is no sibling `verdict:`
    line to disambiguate it. `overlap` itself is left `None` whenever
    `overlap_state` is `could-not-check`, the same "nothing to report as a file
    list" shape the pre-existing `n/a` case already uses, so a caller reading
    `overlap` alone (the pre-#774 contract) never mistakes an unresolved
    comparison for a computed empty one; `overlap_detail` carries the reason.
    A refused pattern on the derived-held `lane` side also stops `availability`
    from reading `available` -- the dangerous direction, since a real collision
    hiding behind an unchecked pattern would otherwise render as clear to
    dispatch on.
    """
    if not lane_patterns and not against_patterns and derived_held is None:
        return None
    a = resolve_lane(repo, lane_patterns) if lane_patterns else None
    a_refused = _refused_patterns(a)
    availability = None
    overlap_state = "n/a"
    overlap_detail = ""
    if derived_held is not None:
        if derived_held["state"] != "resolved":
            b = None
            overlap = None
            if a is not None:
                availability = {
                    "state": "could-not-derive-the-held-set",
                    "files": [],
                    "holders": [],
                    "detail": derived_held["detail"],
                }
        else:
            held_files = sorted(derived_held["held"])
            b = resolve_lane(repo, held_files) if held_files else {"patterns": [], "files": []}
            # #774, audit round: a held FILE can trip `_lane_pattern_problem`
            # exactly the way a hand-typed pattern can -- a real git-tracked path
            # containing '|' is legal on the filesystems this loop runs on, and
            # `resolve_lane` gives it the identical `refused` state either way.
            # Checking only `a_refused` left a refused held file silently
            # dropping out of `b["files"]`, so a lane whose own pattern resolved
            # cleanly could still read `available` while one of the files it was
            # meant to be checked against was never actually compared -- the
            # same dangerous direction the `a_refused` branch below exists to
            # close, just on the other side of the comparison.
            b_refused = _refused_patterns(b)
            if a is None:
                overlap = None
            elif a_refused or b_refused:
                # #774: a refused pattern on either side means this comparison
                # never ran for it -- rendering `available` here would be the
                # dangerous direction (a real collision hiding behind an
                # unchecked pattern reads as clear to dispatch on), so this is
                # its own state rather than folding into either `available` or
                # `blocked`.
                overlap = None
                overlap_state = "could-not-check"
                overlap_detail = _unresolved_overlap_detail(a, a_refused, b, b_refused)
                availability = {
                    "state": "could-not-check",
                    "files": [],
                    "holders": [],
                    "detail": overlap_detail,
                }
            else:
                overlap = lane_overlap(a["files"], b["files"])
                overlap_state = "resolved"
                if overlap:
                    holders = []
                    for f in overlap:
                        for h in derived_held["held"].get(f, []):
                            if h not in holders:
                                holders.append(h)
                    availability = {
                        "state": "blocked",
                        "files": overlap,
                        "holders": holders,
                        "detail": "",
                    }
                elif _lane_resolved_to_nothing(a):
                    # #809: every member of the lane side was well-formed and
                    # checked, and the union still names zero files (an empty
                    # glob, an empty directory, or a mix of the two). `overlap`
                    # is `[]` here for the same reason it would be for a real,
                    # disjoint, non-empty lane -- an empty set intersects
                    # nothing -- so `overlap` alone cannot tell the two apart.
                    # This must not read `available`: a lane nobody managed to
                    # name is not a lane confirmed free.
                    overlap_state = "resolved-to-nothing"
                    availability = {
                        "state": "resolved-to-nothing",
                        "files": [],
                        "holders": [],
                        "detail": "this lane names no file on disk, so nothing "
                        "was compared against the held set (#809)",
                    }
                else:
                    availability = {"state": "available", "files": [], "holders": [], "detail": ""}
    else:
        b = resolve_lane(repo, against_patterns) if against_patterns else None
        b_refused = _refused_patterns(b)
        if a is None or b is None:
            overlap = None
        elif a_refused or b_refused:
            # #774: the wider half of #766 -- a refused pattern on either side
            # means the comparison never ran, and must never render as the
            # same `none` a real, checked, disjoint pair also prints.
            overlap = None
            overlap_state = "could-not-check"
            overlap_detail = _unresolved_overlap_detail(a, a_refused, b, b_refused)
        else:
            overlap = lane_overlap(a["files"], b["files"])
            overlap_state = "resolved"
            if _lane_resolved_to_nothing(a) or _lane_resolved_to_nothing(b):
                # #809: same reading as the `--derive-held` branch above -- an
                # empty `overlap` from a side that named no file on disk is not
                # the same claim as an empty `overlap` from two real, checked,
                # disjoint sets, so the receipt's `overlap :` line must not
                # print `none` for both. Checked on *both* sides here, unlike
                # the `--derive-held` branch: `--against PATTERN` is itself a
                # maintainer-typed pattern (dispatch.md's own documented
                # fallback), not a derived held set, so it can resolve to
                # nothing exactly the way `--lane` can -- an empty `overlap`
                # from a typo'd or `**`-broken `--against` glob must not read
                # as "checked, disjoint" either. Plain `--against` mode has no
                # `availability` verdict to correct (that field only exists
                # under `--derive-held`), so this is the only render this
                # branch can carry the distinction on.
                overlap_state = "resolved-to-nothing"
    # #566: `repo` is threaded through so each guard's `status` is answered against
    # the repository the lane is actually dispatched into, never against claude-oss's
    # own tree by default -- the whole defect this issue is about.
    guards = guards_for_files(a["files"], repo) if a else []
    result = {
        "lane": a,
        "against": b,
        "overlap": overlap,
        "overlap_state": overlap_state,
        "overlap_detail": overlap_detail,
        "guards": guards,
    }
    if derived_held is not None:
        # #734, review round: `derived_held["lanes"]["stale_pruned"]` names every
        # registry record this call's own `derive_held_set` deleted as a side
        # effect (a branch it corroborated as locally gone) -- surfaced here so a
        # caller can see what was pruned rather than the deletion happening with
        # no trace anywhere in this payload. Absent on the two shapes that carry
        # no `lanes` sub-dict at all (no config loaded; a hand-built `derived_held`
        # in an older test fixture), which is exactly "nothing pruned", not a
        # different claim. `prune_failed` (#792) is the sibling of that same
        # side effect gone wrong -- a record the deletion attempt could not
        # actually remove -- and is surfaced the same way, never folded into
        # `stale_pruned`.
        result["held_source"] = {
            "state": derived_held["state"],
            "detail": derived_held["detail"],
            "stale_pruned": derived_held.get("lanes", {}).get("stale_pruned", []),
            "prune_failed": derived_held.get("lanes", {}).get("prune_failed", []),
        }
        result["availability"] = availability
    return result


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
                gh, "pr", "list", "--repo", str(repo_slug), "--state", "open",
                "--json", "number,files", "--limit", str(_PR_LIST_LIMIT),
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
            "detail": _one_line(
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
        return {"state": "could-not-derive", "held": {}, "detail": "gh pr list did not return a list"}
    if len(prs) >= _PR_LIST_LIMIT:
        return {
            "state": "could-not-derive",
            "held": {},
            "detail": "gh pr list returned {0} open PR(s), at or past the {1}-PR page "
            "limit -- the held set cannot be trusted complete.".format(len(prs), _PR_LIST_LIMIT),
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
    code, _, _ = _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch)
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
        return {"state": "unknown", "held": {}, "stale_pruned": [], "prune_failed": [], "detail": "worktree_root is not known."}
    try:
        found = os.stat(root)
    except (FileNotFoundError, NotADirectoryError):
        if _absence_confirmed(root) is not True:
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
            "state": "unknown", "held": {}, "stale_pruned": [], "prune_failed": [],
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
            "state": "unknown", "held": {}, "stale_pruned": [], "prune_failed": [],
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
                "detail": "lane record {0} under {1} could not be read.".format(name, root),
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
                        prune_failed.append({
                            "issue": issue,
                            "branch": branch,
                            "detail": "{0}: {1}".format(type(exc).__name__, exc),
                        })
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
            "detail": "no live lane records under {0} besides the excluded issue.".format(root),
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


def compute(
    repo,
    issue,
    remote="origin",
    lane_patterns=None,
    against_patterns=None,
    derive_held=False,
    claim=False,
):
    """Everything a lane brief needs, in one payload. `config.state` gates the exit.

    `lane_patterns` / `against_patterns` are optional (#267): when neither is
    given and `derive_held` is False, `payload["lane"]` is None -- an absent ask
    must not read as a checked, empty lane. When either is given, both sides are
    rendered through `resolve_lane` and, when both sides are present, compared
    with `lane_overlap` -- the disjointness check the manager skill currently runs
    by eye.

    `derive_held` (#558) is opt-in, not the default: the local, offline path this
    module has always offered (`--lane`/`--against`, both hand-typed) keeps working
    unchanged when it is False, which is the ordinary case for the "writing each
    brief" call SKILL.md's own table names -- that call has no reason to pay for a
    `gh pr list` round trip. When True, the "against" side is derived instead of
    accepted (`derive_held_set`, from open pull requests and live lane records) --
    a forge call that fails must never render as an empty, confident held set, so
    a failed derivation flows into `lane_report` as `could-not-derive`, not as
    `against=None` (which would silently read as "nothing to check against").

    `claim` (#705) is the only thing that makes this call write *this lane's own*
    record. Default False: `--lane`/`--against`/`--derive-held` never write a
    record for the issue this call is about, and nothing here writes a lane
    record on that issue's behalf without `--claim`. Pass `claim=True` only at
    the moment this lane is actually being dispatched, never while probing
    candidates.

    **That is narrower than "nothing is written to the registry", and it always
    has been.** `lanes_snapshot` -> `lane_count` prunes a TTL-expired record as a
    side effect of the read it performs regardless of `claim` (its own docstring
    says so); `--derive-held` (#734, review round) can now do the same for a
    *different* issue's record, whenever `held_from_live_lanes` corroborates a
    live record's declared branch as locally confirmed gone -- a probe that never
    intends to dispatch can still delete another lane's stale record. Both are
    deletions of records this loop has independent evidence are dead (aged out,
    or the branch a merge already removed), never of a record still legitimately
    held, and both are reported: `lane_report`'s `held_source.stale_pruned` and
    the receipt's first `held :` line name what a `--derive-held` call actually
    removed, so this is a write with a trace, not a silent one. #792: the removal
    itself can fail -- `held_source.prune_failed` and the receipt's second
    `held :` line name a record this call tried and failed to remove, which is
    demonstrably still on disk and never counted in the first line's total.
    """
    repo = Path(repo)
    config_path = repo / CONFIG_NAME
    config, problems = oss_config.load(config_path)

    if config is None:
        derived_held = (
            {
                "state": "could-not-derive",
                "held": {},
                "detail": "config could not be loaded, so neither repo nor "
                "worktree_root is known to derive a held set from.",
            }
            if derive_held
            else None
        )
        return {
            "issue": issue,
            "repo": str(repo),
            "config": {"state": "could-not-run", "problems": problems},
            "base": None,
            "branch": None,
            "worktree": None,
            "board": None,
            "lanes": None,
            "lane": lane_report(repo, lane_patterns, against_patterns, derived_held),
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

    derived_held = (
        derive_held_set(
            config.get("repo"), config.get("worktree_root"), exclude_issue=issue, repo=repo,
        )
        if derive_held
        else None
    )
    lane = lane_report(repo, lane_patterns, against_patterns, derived_held)

    # #558: this lane's own resolved files are recorded so a *later* candidate's
    # `derive_held_set` call can read them back -- computed here, after `lane_report`,
    # rather than calling `resolve_lane` a second time for the same patterns.
    lane_files = lane["lane"]["files"] if lane and lane.get("lane") is not None else None
    lanes = lanes_snapshot(
        config.get("worktree_root"), issue, branch.get("name"), worktree.get("path"),
        files=lane_files, claim=claim,
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
        "lane": lane,
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
        held_source = lane.get("held_source")
        if held_source is None:
            for side_label, side in (("lane", lane["lane"]), ("against", lane["against"])):
                if side is None:
                    continue
                for entry in side["patterns"]:
                    lines.append(
                        "  [{0}] {1} ({2}): {3}".format(
                            side_label, entry["pattern"], entry["state"],
                            ", ".join(entry["files"]) or "-",
                        )
                    )
        else:
            # #558: the "against" side was derived (open PRs + live lanes), not
            # hand-typed -- printing every held file as an individual pattern line,
            # the way the hand-typed side does, would run to hundreds of lines on a
            # busy tracker. The files themselves still appear, in `overlap` and
            # `verdict` below; this line only says where "against" came from.
            for entry in lane["lane"]["patterns"] if lane["lane"] else []:
                lines.append(
                    "  [lane] {0} ({1}): {2}".format(
                        entry["pattern"], entry["state"], ", ".join(entry["files"]) or "-"
                    )
                )
            if held_source["state"] == "resolved":
                held_count = len(lane["against"]["files"]) if lane["against"] else 0
                lines.append("  against : derived held set, {0} file(s)".format(held_count))
            else:
                lines.append(
                    "  against : COULD NOT DERIVE THE HELD SET -- {0}".format(held_source["detail"])
                )
            # #734, review round: a stale-branch prune is a real write this call
            # performs even when --claim was never passed -- named here so it is
            # never a silent action with no trace anywhere in this receipt.
            stale_pruned = held_source.get("stale_pruned") or []
            if stale_pruned:
                lines.append(
                    "  held    : {0} stale record(s) released (branch confirmed gone): {1}".format(
                        len(stale_pruned),
                        ", ".join(
                            "lane #{0} ({1})".format(item["issue"], item["branch"])
                            for item in stale_pruned
                        ),
                    )
                )
            # #792: a prune this call attempted and failed is a fact just as
            # load-bearing as one that succeeded -- the record named here is
            # demonstrably still on disk, never folded into the line above.
            prune_failed = held_source.get("prune_failed") or []
            if prune_failed:
                lines.append(
                    "  held    : {0} stale record(s) could NOT be released (still on disk): {1}".format(
                        len(prune_failed),
                        ", ".join(
                            "lane #{0} ({1}): {2}".format(
                                item["issue"], item["branch"], item["detail"]
                            )
                            for item in prune_failed
                        ),
                    )
                )
        # #774: `overlap_state` is checked first -- `.get` rather than `[]` so a
        # payload built before this field existed (an older test fixture, or a
        # hand-built dict) still renders the pre-#774 lines below rather than
        # raising.
        if lane.get("overlap_state") == "could-not-check":
            lines.append("  overlap : COULD NOT CHECK -- {0}".format(lane.get("overlap_detail", "")))
        elif lane.get("overlap_state") == "resolved-to-nothing":
            # #809: the lane side named no file on disk -- an empty `overlap`
            # here is not the same claim an empty `overlap` from two real,
            # checked, disjoint sets makes, so it gets its own line rather
            # than folding into `none`.
            lines.append(
                "  overlap : n/a -- lane resolved to zero files on disk, nothing to compare (#809)"
            )
        elif lane["overlap"] is None:
            # #558 review round: the pre-#558 "only one side given" wording is
            # wrong when `held_source` is present and no --lane was given -- that
            # is "no candidate to check", not "only the against side is missing",
            # and printing the old sentence there would misdescribe a derived-held
            # call that never named a lane at all.
            if held_source is not None and lane["lane"] is None:
                lines.append("  overlap : n/a -- no --lane given to compare against the held set")
            else:
                lines.append("  overlap : n/a -- only one side given")
        elif lane["overlap"]:
            lines.append("  overlap : " + ", ".join(lane["overlap"]))
        else:
            lines.append("  overlap : none")
        availability = lane.get("availability")
        if availability is not None:
            # #558: the per-candidate verdict the issue asks for -- available /
            # blocked / could-not-check / could-not-derive-the-held-set -- never
            # rendered as `available` or `blocked` when the held set itself
            # could not be derived, or when the lane side itself could not be
            # checked (#774: a refused pattern must never render as clear).
            if availability["state"] == "available":
                lines.append("  verdict : available")
            elif availability["state"] == "blocked":
                lines.append(
                    "  verdict : BLOCKED -- {0} (held by {1})".format(
                        ", ".join(availability["files"]), ", ".join(availability["holders"])
                    )
                )
            elif availability["state"] == "could-not-check":
                lines.append(
                    "  verdict : COULD NOT CHECK -- {0}".format(availability["detail"])
                )
            elif availability["state"] == "resolved-to-nothing":
                # #809: third state, same shape as everywhere else in this
                # loop -- `available`, `BLOCKED`, and "this lane names no
                # file on disk, so nothing was compared". Never folded into
                # `available`, the dangerous direction: a lane that resolved
                # to nothing is not confirmed free, it is unnamed.
                lines.append(
                    "  verdict : RESOLVED TO NOTHING -- {0}".format(availability["detail"])
                )
            else:
                lines.append(
                    "  verdict : COULD NOT DERIVE THE HELD SET -- {0}".format(
                        availability["detail"]
                    )
                )
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
    parser.add_argument(
        "--derive-held",
        action="store_true",
        help="derive the against side instead of accepting it -- from every open "
        "pull request's file list and every live lane record's own files (#558); "
        "refused together with --against, since a derived exclusion and a "
        "hand-typed one beside it is exactly the ambiguity this exists to close",
    )
    parser.add_argument(
        "--claim",
        action="store_true",
        help="write this lane's own record to the registry (#705); every other "
        "call -- including one carrying --lane or --derive-held -- is a read and "
        "writes nothing, so probing candidate lanes never leaves a phantom "
        "record behind. Pass this only at the moment this lane is actually "
        "dispatched.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="release this issue's own lane record (#734), instead of computing "
        "setup facts -- call this once the merge step has independently "
        "verified the pull request merged (state/mergedAt/mergeCommit read "
        "back off the remote), so a follow-up dispatched minutes later never "
        "reads this lane as still held. Exits 0 whether or not a record "
        "existed to release; every other flag is ignored when this is given.",
    )
    args = parser.parse_args(argv)

    if args.derive_held and args.against:
        parser.error("--derive-held and --against are mutually exclusive (#558)")

    if args.claim and not args.lane and not args.release:
        # #788: the documented dispatch-time call used to be `--claim` with no
        # `--lane` at all, which writes a fileless lane record -- indistinguishable
        # at write time from a well-formed one, and indistinguishable from every
        # OTHER live lane's record once written. `derive_held_set` then has to
        # treat the held set as untrustworthy while that record is live (its own
        # `held_from_live_lanes` detail names the cause: "recorded without
        # --lane"), which poisons every later --derive-held call this tick, not
        # just this one's own probe -- the fallback #558 exists to retire. Refuse
        # the write instead of the state it produces, the same shape
        # `fleet_label.py` already refuses an incomplete label bundle rather than
        # composing one from a missing piece.
        parser.error(
            "--claim requires --lane (#788) -- a claim with no files writes a "
            "fileless lane record, which poisons every later --derive-held call "
            "this tick; pass --lane once per file this lane touches, the same "
            "patterns already used to probe this candidate"
        )

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    if args.release:
        config, problems = oss_config.load(Path(args.repo) / CONFIG_NAME)
        # #791 fixed the case where `config` is None -- the project half could
        # not be read at all, absent or malformed. #803: that is not the only
        # way a real read failure hides in `problems`. `worktree_root` only
        # ever lives in `.oss.local.json` (`LOCAL_KEYS`), so when the *local*
        # half is present but unparseable, `oss_config.load` returns a
        # non-None `config` -- with no `worktree_root` key, since the
        # unreadable local half was never merged in -- and the parse error
        # sitting in `problems` right beside advisory findings that fire on
        # every config missing `worktree_root`, read failure or not (a
        # "missing required key: worktree_root" entry, chiefly). Gating on
        # `config is None` alone dropped the local parse error and rendered
        # it identically to the genuinely benign "no worktree_root configured
        # here" case `release_lane` reports below.
        #
        # A first version of this fix scanned `problems` for the substring
        # "could not", reasoning that `_read_json_object`'s own read-failure
        # messages ("could not read/decode/parse") were the only ones that
        # used it. That reasoning was never checked against the rest of
        # `oss_config.py` and was wrong: `test_command_problem`'s own
        # advisory ("...or null when the probe could not tell; got ...")
        # contains the same substring, so a config with a perfectly readable,
        # perfectly known `worktree_root` and an unrelated malformed
        # `test_command` field was blocked from releasing at all (found in
        # this diff's own review round). Ask the one question this arm
        # actually needs answered instead of inferring it from prose
        # elsewhere in the list: did *the local file itself* fail to parse?
        # Re-read it with the exact primitive `load()` uses internally for
        # both halves, so this stays one read failure, one fact, rather than
        # a second implementation of JSON/encoding error handling that could
        # drift from `oss_config`'s own.
        local_read_problem = None
        if config is not None:
            _, local_read_problem = oss_config._read_json_object(
                oss_config.local_config_path(Path(args.repo) / CONFIG_NAME)
            )
        if config is None or local_read_problem is not None:
            result = {
                "state": "could-not-release",
                "path": None,
                "detail": "worktree_root is not known -- the config could not "
                "be read: {0}".format(
                    "; ".join(problems) if problems else "no detail available."
                ),
            }
        else:
            worktree_root = config.get("worktree_root")
            result = release_lane(worktree_root, args.issue)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("RELEASE #{0}: {1}{2}".format(
                args.issue, result["state"],
                " -- " + result["detail"] if result["detail"] else "",
            ))
        return EXIT_COULD_NOT_RUN if result["state"] == "could-not-release" else EXIT_OK

    payload = compute(
        args.repo, args.issue, args.remote, args.lane, args.against,
        derive_held=args.derive_held, claim=args.claim,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return EXIT_COULD_NOT_RUN if blocked(payload) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
