#!/usr/bin/env python3
"""Every tracked file the shell leg should lint, derived rather than listed.

The leg used to scope both of its guards with `git ls-files '*.sh'`. That glob returns
exactly one path in this repository, `scripts/doctor.sh`, while `bin/oss-workspace` --
the plugin's user-facing entry point, tracked, POSIX `sh` -- carries no extension and
was therefore never read by `bash -n` or by `shellcheck`, on any leg, on any platform,
in any release. The leg was green throughout, because a lint that ran and found nothing
and a lint that never received the file both exit 0 (#193).

Two decisions are recorded here rather than in the workflow, because both are the kind
that get re-argued later.

**The selection is derived, not listed.** Naming `bin/oss-workspace` beside the glob is
the one-line fix, and it is a fact about this repository living outside `.oss.json` --
which is the same defect one level up, in a repository whose governing rule is that such
a fact is re-derived at the moment it is needed. It also goes stale silently: the second
extensionless script is uncovered and nothing says so. So a file qualifies by extension
OR by shebang. The shebang half costs one 256-byte read per tracked file -- 120 files
here, and linear in a repository of any size -- which buys a selection that cannot go
stale, because a script added without an extension is covered by the commit that adds it.

**Matching nothing is a failure.** `shellcheck` with no arguments exits 0, so a
selection that silently matched nothing would reintroduce exactly the bug this script
repairs, one narrowing later. There are three outcomes and they are three exit codes:

    0  at least one shell source, every tracked file classified -- the list is on stdout
    2  the enumeration completed and matched nothing
    3  the enumeration could not be completed, so what is in the repository is UNKNOWN

Exit 3 is the one worth keeping separate. A tracked file whose first line cannot be read
is not a file without a shebang: answering `not shell` for it would drop a script out of
the leg with the leg still green, which is the absence this plugin is named after. Only
files whose classification actually depended on the read are reported that way -- a
missing `.sh` qualified on its name and needs no first line.

Paths are printed one per line, relative to the repository's top level, forward slashes,
UTF-8 through the byte stream rather than the console codepage. On Windows anything
written through `print` is encoded with the console's codepage, typically cp1252, where
a non-ASCII path raises UnicodeEncodeError and kills the process at the write -- after
the work the write was reporting already happened.

Usage:
    python3 scripts/shell_sources.py [--root DIR]

Python 3.9 compatible. No third-party imports: the shell leg installs nothing but
shellcheck.
"""

import argparse
import os
import subprocess
import sys

#: Extensions that declare a file to be shell without anything having to read it. Kept
#: so a sourced fragment with no shebang -- which the old glob did cover -- is not lost
#: by replacing an extension test with a shebang test.
SHELL_SUFFIXES = (".sh", ".bash", ".dash", ".ksh")

#: Interpreter basenames shellcheck can analyse. `csh` and `fish` are deliberately
#: absent: shellcheck refuses them, so selecting one would fail the leg on a file it
#: cannot read anyway.
SHELL_INTERPRETERS = frozenset({"sh", "bash", "dash", "ksh", "ash", "zsh"})

#: Enough for a shebang line and then some. Read as bytes, so a binary blob in the tree
#: cannot raise a decode error on the way to being classified as `not shell`.
HEAD_BYTES = 256


class CannotEnumerate(Exception):
    """The repository could not be read, so what it contains is unknown, not empty."""


def _emit(stream, text):
    """Write UTF-8 through the byte stream, never the console codepage."""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
        return
    buffer.write(text.encode("utf-8", "replace"))
    buffer.flush()


def _git(root, *args):
    try:
        done = subprocess.run(
            ["git", "-C", str(root)] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise CannotEnumerate("git could not be run: {}".format(error))
    if done.returncode != 0:
        raise CannotEnumerate(
            "git {} failed in {}: {}".format(
                " ".join(args), root, done.stderr.decode("utf-8", "replace").strip()
            )
        )
    return done.stdout


def _toplevel(root):
    """The repository, not the working directory.

    `git ls-files` run from a subdirectory lists only that subtree and says nothing
    about having done so, which would be this same defect wearing a different hat.
    """
    out = _git(root, "rev-parse", "--show-toplevel")
    return out.decode("utf-8", "surrogateescape").strip()


def _tracked_paths(toplevel):
    out = _git(toplevel, "ls-files", "-z")
    text = out.decode("utf-8", "surrogateescape")
    return [name for name in text.split("\0") if name]


def _shebang_interpreter(head):
    """The interpreter basename a first line names, or None if it names none."""
    if not head.startswith(b"#!"):
        return None
    first = head.split(b"\n", 1)[0].decode("utf-8", "replace")
    words = first[2:].replace("\t", " ").strip().split(" ")
    words = [word for word in words if word]
    if not words:
        return None
    # A shebang is written into the file and is a POSIX path even on Windows, so
    # splitting on "/" is the whole of it -- no separator normalisation to get wrong.
    name = words[0].rsplit("/", 1)[-1]
    if name == "env":
        rest = [word for word in words[1:] if not word.startswith("-")]
        if not rest:
            return None
        name = rest[0].rsplit("/", 1)[-1]
    return name


def classify(toplevel, name):
    """One tracked path, in three states: 'shell', 'other', or a reason it is unknown.

    Returns (verdict, detail). `verdict` is 'shell', 'other' or 'unknown'.
    """
    if name.endswith(SHELL_SUFFIXES):
        return "shell", "extension"
    path = os.path.join(str(toplevel), *name.split("/"))
    try:
        with open(path, "rb") as handle:
            head = handle.read(HEAD_BYTES)
    except OSError as error:
        # The exception in hand answers this. Asking the filesystem a second question --
        # `exists()` -- to explain why the first one failed is a trap this repository has
        # already paid for: it swallows some errnos and raises the rest.
        return "unknown", error.strerror or str(error)
    interpreter = _shebang_interpreter(head)
    if interpreter in SHELL_INTERPRETERS:
        return "shell", "shebang names {}".format(interpreter)
    return "other", ""


def survey(root):
    """(shell sources, unreadable) for the repository containing `root`.

    Both halves are returned. Collapsing the second into the first would make `could not
    read the tree` indistinguishable from `read the tree, no shell in it`.
    """
    toplevel = _toplevel(root)
    found = []
    unknown = []
    for name in _tracked_paths(toplevel):
        verdict, detail = classify(toplevel, name)
        if verdict == "shell":
            found.append(name)
        elif verdict == "unknown":
            unknown.append((name, detail))
    return sorted(found), sorted(unknown)


def shell_sources(root):
    """The list alone, for callers that have already accepted the refusals."""
    found, unknown = survey(root)
    if unknown:
        raise CannotEnumerate(
            "{} tracked file(s) could not be read".format(len(unknown))
        )
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List every tracked shell source, by extension or by shebang."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="a path inside the repository to enumerate (default: the working directory)",
    )
    args = parser.parse_args(argv)

    try:
        found, unknown = survey(args.root)
    except CannotEnumerate as error:
        _emit(sys.stderr, "shell-sources: {}\n".format(error))
        return 3

    if unknown:
        _emit(
            sys.stderr,
            "shell-sources: {} tracked file(s) could not be read, so whether they are "
            "shell is unknown rather than no. Nothing is listed, because a partial list "
            "would be linted and reported as complete:\n".format(len(unknown)),
        )
        for name, detail in unknown:
            _emit(sys.stderr, "  {}: {}\n".format(name, detail))
        return 3

    if not found:
        _emit(
            sys.stderr,
            "shell-sources: no tracked shell source matched, by extension {} or by a "
            "shebang naming {}. Reported rather than printing an empty list, because "
            "`shellcheck` with no arguments exits 0 and the leg would be green having "
            "read nothing.\n".format(
                "/".join(SHELL_SUFFIXES), "/".join(sorted(SHELL_INTERPRETERS))
            ),
        )
        return 2

    _emit(sys.stdout, "".join(name + "\n" for name in found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
