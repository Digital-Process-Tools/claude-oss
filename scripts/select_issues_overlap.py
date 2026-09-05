"""Lane-pattern resolution and file-set disjointness (#267) -- does one lane's declared files overlap another's.

Split out of `lane_setup.py` for #1069, and owned by `select_issues.py`
now, not `lane_setup.py` -- see that module's own docstring, "## Groups, not
only a flat list", for why lane-pattern resolution and disjointness are a
selection concern rather than a setup one. `lane_setup.py` (via
`lane_setup_patterns.py`) still imports `resolve_lane`/`lane_overlap` from
here for its own registration and disjointness-report path -- the same
cross-import shape `select_issues.py` already used for `lane_setup.py`
before this split, now the other direction for these two names.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import os
import re
import stat
from pathlib import Path


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
    never re-derived. A lane pattern reaching this function from a `--lane` /
    `--against` flag is one step closer to trusted than that -- it is typed by
    a human -- but it is about to be turned into the one canonical form (a
    resolved, repo-relative path) that a second brief's lane can be checked
    against, rather than eyeballed. It is refused the same way
    `oss_config.resolve_worktree` refuses a worktree target: absolute,
    drive-prefixed, home-relative or traversing out of the repo is refused
    before anything touches the filesystem, not caught after.

    #898: that premise does not hold for every caller any more.
    `_derive_declared_files` (#851) pulls backtick-quoted tokens out of an
    issue's own title and body -- text written by a stranger, not typed by
    the human running this command -- and feeds them into this same guard
    unchanged. So the containment here has to hold against untrusted input,
    not only against a human's typo, and every refusal below (including the
    `~` case just added) exists for that caller as much as for `--lane`.

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
    if normalized.startswith("~"):
        return (
            "lane pattern {0!r} starts with '~' -- home-directory expansion "
            "is refused here the same as an absolute path, whether or not "
            "anything downstream calls expanduser() on it today (#898)"
        ).format(pattern)
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


def _split_lane_value(raw):
    """Split one raw `--lane`/`--against` value into its comma-separated
    members (#809: `--lane 'a.md,b.md,c.py'`, the multi-pattern shape a
    brief's `lane:` line also uses), honouring a literal-comma escape
    (#843).

    #836 through #843: a comma is legal in a filename on every platform
    this loop's CI runs, and the first fix for that (#836) was a stat-based
    heuristic -- keep the whole raw string as one member when, unsplit, it
    already named an existing file or directory. #840's own review of that
    lane found three residual gaps in it, all the same shape: the heuristic
    answers by looking at the filesystem, and a filesystem look can be
    wrong or can fail outright --

      (a) a glob combined with a comma in a directory name was excluded
          from the whole-string check outright (`_is_lane_glob(raw)`
          returned early), so `my,dir/*.py` still split into `my` and
          `dir/*.py` even though `my,dir` is a real directory;
      (b) a held file that does not exist *yet* -- a changelog fragment
          about to be created, the ordinary shape of a literal pattern in
          this function's own contract -- could never pass the existence
          check no matter how the comma in its name was meant, so it
          always split;
      (c) a `PermissionError` on an unreadable ancestor made the heuristic
          answer False and fall through to the bogus split, this
          repository's own defect class: a check that could not look,
          rendering as an answer instead of a third state.

    All three share one root cause: whether a comma is a delimiter or part
    of a filename is a *lexical* fact about what was typed, and a stat()
    call cannot supply it -- at best it approximates it for paths that
    happen to exist yet, which is exactly the population `resolve_lane`'s own
    `literal` contract (below) explicitly does not require. So #843 replaces the heuristic
    with a real escaping rule instead of patching a fourth gap into it:
    `\\,` is a literal comma, `\\\\` is a literal backslash, and any other
    `,` is a delimiter. This never touches the filesystem, so a member
    naming something that does not exist yet, a glob, and a `Permission
    Error`-guarded ancestor are no longer three different code paths --
    there is only the one lexical scan below, and it always returns an
    answer. Reverting #827's comma list outright, in favour of repeated
    `--lane` flags only, was weighed and declined: it would still be true
    at the call site, but every caller in this loop's own prose --
    `skills/manager/phases/dispatch.md`'s own `lane:` line included --
    already writes a lane as one comma-joined string, and losing that
    shape moves the cost from one function to every one of those call
    sites instead of removing it.

    This is a breaking change for the narrow case #836 fixed: a comma-named
    file that used to be auto-detected by existence now needs its comma
    escaped (`docs/comma\\,name.md`) to stay one member instead of splitting
    into `docs/comma` and `name.md`. That is the trade: the old heuristic
    guessed right for one population (existing files) and wrong or not-at-
    all for three others: this rule is right for all four, at the cost of
    asking a human who really does have a comma in a filename to say so.

    Whitespace is stripped from each resulting member (#835) after
    escapes are resolved, matching every other member's contract.
    """
    members = []
    current = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\" and i + 1 < n and raw[i + 1] in (",", "\\"):
            current.append(raw[i + 1])
            i += 2
            continue
        if ch == ",":
            members.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    members.append("".join(current))
    return [member.strip() for member in members]


def resolve_lane(repo, patterns):
    """Render a maintainer-asserted lane -- a mix of literal paths, bare
    directories and glob patterns, exactly what a brief's `lane:` line
    carries today -- in the one canonical form the issue asks for: a sorted,
    deduplicated list of repo-relative POSIX paths, so a second brief's lane
    can be compared to it by `lane_overlap` instead of by eye.

    `patterns` is the raw list of `--lane`/`--against` values, one per flag
    occurrence -- but a single value may itself be a comma-separated list of
    members (#809: `--lane 'a.md,b.md,c.py'`, the multi-pattern shape a
    brief's `lane:` line also uses). Each value is run through
    `_split_lane_value` before anything else -- an escape-based lexical
    split (#843: `\\,` for a literal comma, `\\\\` for a literal backslash,
    every other `,` a delimiter), never a filesystem look -- and every
    resulting member is resolved independently through the identical
    per-pattern pipeline below. There used to be no split at all, so a
    comma-joined string was compared as one literal path containing a
    literal comma, which matched nothing on disk regardless of what its
    members named, and a lane naming a held file inside a comma-list read
    `overlap: none`. Splitting first also fixes the collapse #809's third
    instance measured: one member matching nothing used to zero out every
    other member's real matches, because the whole joined string shared one
    `glob-no-match` entry; each member now keeps its own state and its own
    files, so a non-matching member no longer erases a matching one beside
    it. A member with no comma (and no backslash) in the original value is
    unaffected -- see `_split_lane_value`'s own docstring for the escaping
    rule and the heuristic it replaced.

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
        # #843: the split (and the whitespace strip -- #835) is now entirely
        # lexical -- see `_split_lane_value`'s own docstring for the escaping
        # rule and the stat-based heuristic it replaces.
        members.extend(_split_lane_value(raw))
    for pattern in members:
        problem = _lane_pattern_problem(pattern)
        if problem is not None:
            entries.append(
                {"pattern": pattern, "state": "refused", "files": [], "detail": problem}
            )
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
            entries.append(
                {"pattern": pattern, "state": state, "files": matches, "detail": ""}
            )
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
                entries.append(
                    {"pattern": pattern, "state": state, "files": matches, "detail": ""}
                )
                files.update(matches)
            else:
                entries.append(
                    {
                        "pattern": pattern,
                        "state": "literal",
                        "files": [rel],
                        "detail": "",
                    }
                )
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


#: A backtick-quoted span in an issue's title or body -- `` `scripts/foo.py` ``,
#: the shape every issue filed in this repository (including this one's own
#: sibling, #843) already writes a file path in. `[^`\n]` rather than `.`
#: alone: a code fence's contents can legitimately contain a backtick-adjacent
#: character, but never a literal backtick spanning a newline the way this
#: single-line span is meant to.
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")
