#!/usr/bin/env python3
"""Pre-flight code check before dispatching an issue (#457).

Pre-flight, as `skills/manager/SKILL.md` already asked for it, reads the
issue body and its comments and re-derives the issue's own claims -- and
neither of those bullets covers the axis that actually fired: the whole
issue, comments included, can go stale against the *code*, when the fix
already landed after the last comment was written. A developer lane was
dispatched for part 3 of #81, already shipped and enforced by tests,
because nobody grepped for it first.

This module is the missing grep, made mechanical rather than left as a
paragraph asking a reader to remember it: given a pattern the issue names
(chosen by whoever writes the brief -- this script has no way to invent one)
and a set of paths to search, it reports whether the pattern is present in
the tree today.

## Three states, never two

  matched           -- the pattern was found at least once.
  not-matched        -- the search ran cleanly and found nothing.
  could-not-search    -- the search itself did not happen: an invalid
                         pattern, a root that does not exist, a directory
                         this process could not walk, or a file it was
                         genuinely denied. Must never render as
                         not-matched -- CLAUDE.md's own defect class, applied
                         here: an absence produced by the tool (a broken
                         search) must never be read as an absence in the
                         world (nothing there).

## A file with no text in it is not a file the search was denied (#717)

A file that fails to decode as UTF-8 was read successfully -- but "cannot
decode as UTF-8" is not the same claim as "has no text to search", and
treating every decode failure as the second, categorically, was tried and
found wrong by review on this same issue: real source in Latin-1, cp1252 or
UTF-16 fails this decode too, and a categorical downgrade would silently
miss a genuine match in it -- trading the loud third state for a quiet
not-matched, the defect this whole repository is named after, one layer
inside the fix meant to remove it.

So the two are told apart by a NUL byte -- the same signal `git diff` and
`grep -I` use to call a file binary, because ordinary text in any encoding
this tool could plausibly be asked to search does not contain one, while a
compiled artifact reliably does. **Present:** the file is treated as binary
and goes to `skipped_files` -- this is the actual #717 target
(`__pycache__/*.pyc`, present in every Python tree the moment a package is
imported or tested even once) -- reported on every result, never suppressed
at zero, and never forcing could-not-search on its own. **Absent:** the
decode failure is genuinely ambiguous -- it could be real text this search
should have been able to read -- so it falls back to `unreadable_files` and
still forces could-not-search, the conservative answer rather than a guess.
A file this process was actually denied (`OSError`) reaches
`unreadable_files` the same way and forces could-not-search for the
original reason, unchanged.

## What a match means is not this script's to decide

Whether "matched" means already-shipped or still-open depends on what the
pattern names -- a contract that should exist (a match means shipped) or a
symptom that should not (a match means still open). Only the reader who read
the issue knows which. `skills/manager/SKILL.md` records the direction
alongside the call, in the same three words this module returns:
still-open / already-shipped / could-not-tell -- could-not-tell is what a
could-not-search state becomes at the dispatch decision, and it must never
render as still-open either, for the same reason.

## The scope has to travel with the answer, or it gets retyped as prose (#727)

A `not-matched` over one file and a `not-matched` over the whole tree render identically
once a human writes the answer into a brief -- `files_searched` was already in the
receipt, but the paths that produced it were not, so a reader still had to remember the
`--path` argument separately to quote the scope honestly, and one did not. `roots` closes
that: the searched paths, verbatim, in the same result the state comes from, on every
return path including `could-not-search`. Quote it whole -- `not-matched over 1 file
(scripts/doctor.py)` -- never a summary of it. This is not a demand to sweep the whole
tree on every pre-flight; a narrow probe is often the right probe, and the defect was a
narrow probe's answer wearing a repository-wide claim's clothes.

## Per-part

A multi-part issue is checked once per part, with each part's own pattern --
this module answers one pattern against one set of roots per call, on
purpose: folding several patterns into one call would blur a per-part
could-not-search into a single verdict for the whole issue, which is exactly
the whole-issue-verdict mistake #457's own body names (#81 had three parts
in three different states).

Python 3.9 compatible -- this project's CI runs 3.9 through 3.12.
"""

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_COULD_NOT_SEARCH = 3

STATE_MATCHED = "matched"
STATE_NOT_MATCHED = "not-matched"
STATE_COULD_NOT_SEARCH = "could-not-search"


def _walk_files(root):
    """Every regular file under `root`, or `root` itself if it is a file.

    `os.walk(onerror=...)` rather than `Path.rglob` -- rglob swallows
    `PermissionError` while walking a subtree and returns nothing for it,
    which would render an unreadable subtree identically to "nothing to
    search here" (see this repo's own CLAUDE.md and
    `transcript_refusals.discover_transcripts`, which this mirrors).
    Returns (files, unreadable_dirs).
    """
    files = []
    unreadable_dirs = []
    try:
        root_mode = os.stat(str(root)).st_mode
    except OSError as exc:
        return None, [{"path": str(root), "reason": str(exc)}]

    if stat.S_ISREG(root_mode):
        return [Path(root)], []
    if not stat.S_ISDIR(root_mode):
        return [], []

    def _onerror(exc, _root=root):
        unreadable_dirs.append({"path": getattr(exc, "filename", None) or str(_root), "reason": str(exc)})

    for dirpath, dirnames, filenames in os.walk(str(root), onerror=_onerror):
        # Never descend into version control metadata -- not a source file,
        # and on a large repo it is most of the tree by file count.
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            files.append(Path(dirpath) / name)

    return files, unreadable_dirs


def search(pattern, roots):
    """Search `pattern` (a regular expression) across every file under each
    of `roots`. Never raises -- every failure mode is a state in the
    returned dict, never an exception the caller has to catch."""
    root_strs = [str(r) for r in roots]
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {
            "state": STATE_COULD_NOT_SEARCH,
            "pattern": pattern,
            "roots": root_strs,
            "problem": "invalid pattern: {0}".format(exc),
        }

    all_files = []
    unreadable_dirs = []
    missing_roots = []
    for root in roots:
        files, bad_dirs = _walk_files(root)
        if files is None:
            missing_roots.append(str(root))
            continue
        all_files.extend(files)
        unreadable_dirs.extend(bad_dirs)

    if missing_roots and not all_files:
        return {
            "state": STATE_COULD_NOT_SEARCH,
            "pattern": pattern,
            "roots": root_strs,
            "problem": "root(s) could not be searched: {0}".format(", ".join(missing_roots)),
        }

    matches = []
    unreadable_files = []
    skipped_files = []
    for path in all_files:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            unreadable_files.append(str(path))
            continue
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            # #717: a file that cannot decode as UTF-8 was not denied to
            # this process -- it was read fine. Most of the time it simply
            # has no text in it (a __pycache__/*.pyc, present the moment a
            # package is imported or tested once), and folding that into
            # unreadable_files made could-not-search fire on every real
            # Python tree and, worse, fire precisely on the negative
            # answer: the unreadable set only downgrades the verdict when
            # there is nothing else to report, so a match elsewhere still
            # returned matched with the identical undecodable file present.
            #
            # But "cannot decode as UTF-8" is not the same claim as "has no
            # text", and review on this same issue found the gap: real
            # source in Latin-1/cp1252/UTF-16 fails this decode too, and a
            # categorical downgrade would silently miss a genuine match in
            # it -- trading the loud third state for a quiet not-matched,
            # this repo's own defect class. A NUL byte is the distinguishing
            # signal -- the same one `git diff` and `grep -I` use to call a
            # file binary -- because ordinary text in any encoding this tool
            # could plausibly be asked to search does not contain one, while
            # a compiled artifact reliably does. Present: skipped_files,
            # reported always, never suppressed at zero, never forcing
            # could-not-search alone. Absent: genuinely ambiguous, so it
            # falls back to unreadable_files and still forces
            # could-not-search -- the conservative answer, not a guess.
            if b"\x00" in raw:
                skipped_files.append(str(path))
            else:
                unreadable_files.append(str(path))
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                matches.append({"path": str(path), "line": lineno, "text": line.strip()})

    # A match found is a match found regardless of what else could not be
    # read -- but an *absence* is only trustworthy when nothing was skipped.
    # missing_roots, unreadable_dirs and unreadable_files are all collected
    # above and were previously left unconsulted here, so a permission-denied
    # file or subdirectory, or one root among several that does not exist,
    # rendered identically to a clean miss (found by review, #457's own
    # defect one layer down: an absence produced by the tool, read as an
    # absence in the world). skipped_files deliberately does not appear in
    # the condition below -- an undecodable file was read, not denied (#717).
    if matches:
        state = STATE_MATCHED
    elif missing_roots or unreadable_dirs or unreadable_files:
        state = STATE_COULD_NOT_SEARCH
    else:
        state = STATE_NOT_MATCHED

    result = {
        "state": state,
        "pattern": pattern,
        "roots": root_strs,
        "matches": matches,
        "files_searched": len(all_files),
        "unreadable_files": unreadable_files,
        "unreadable_dirs": unreadable_dirs,
        "missing_roots": missing_roots,
        "skipped_files": skipped_files,
    }
    if state == STATE_COULD_NOT_SEARCH:
        problems = []
        if missing_roots:
            problems.append("root(s) missing: {0}".format(", ".join(missing_roots)))
        if unreadable_dirs:
            problems.append(
                "director{0} could not be walked: {1}".format(
                    "y" if len(unreadable_dirs) == 1 else "ies",
                    ", ".join(d["path"] for d in unreadable_dirs),
                )
            )
        if unreadable_files:
            problems.append("file(s) could not be read: {0}".format(", ".join(unreadable_files)))
        result["problem"] = "no match found, but not every path was searched -- " + "; ".join(problems)
    return result


def _build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--pattern", required=True, help="Regular expression naming the code path or contract to check.")
    parser.add_argument("--path", action="append", default=[], dest="paths", help="File or directory to search. Repeatable; defaults to the current directory.")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (0 for compact).")
    return parser


def main(argv=None):
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    roots = [Path(p) for p in args.paths] if args.paths else [Path(".")]
    result = search(args.pattern, roots)
    indent = args.indent if args.indent > 0 else None
    print(json.dumps(result, indent=indent, sort_keys=True))
    return EXIT_COULD_NOT_SEARCH if result["state"] == STATE_COULD_NOT_SEARCH else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
