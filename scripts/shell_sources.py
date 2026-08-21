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
files whose classification actually depended on the read are reported that way -- a `.sh`
that exists and will not read qualified on its name and needs no first line.

A fourth state is **not** an exit code, and that is the decision #384 turned on. `git
ls-files` reports the index while the read happens in the working tree, so an
uncommitted delete -- which is exactly what the changelog fold leaves behind until the
release commit -- hands this script paths that are not on disk. Those are noted on
stderr, by name, and the exit code is decided without them: nothing is there to lint,
and a tree that read completely must not answer `could not read`. Silence would be the
other half of the same defect, so the note is unconditional when the list is non-empty.

Paths are printed one per line, relative to the repository's top level, forward slashes,
UTF-8 through the byte stream rather than the console codepage. On Windows anything
written through `print` is encoded with the console's codepage, typically cp1252, where
a non-ASCII path raises UnicodeEncodeError and kills the process at the write -- after
the work the write was reporting already happened.

Usage:
    python3 scripts/shell_sources.py [--root DIR]

Python 3.9 compatible. No third-party imports: since #303 the shell leg installs nothing
at all -- `shellcheck` ships in the runner image, and fetching it put a package mirror
inside the job's `timeout-minutes`.
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
    """One tracked path, in four states: 'shell', 'other', 'absent', or unknown.

    Returns (verdict, detail). `verdict` is 'shell', 'other', 'absent' or 'unknown'.

    `absent` exists because the enumeration and the read ask two different questions.
    `git ls-files` reports the **index**; the read happens in the **working tree**, and
    between the changelog fold and the release commit those two disagree about every
    fragment the fold deleted. Folding that into `unknown` made the leg refuse -- and
    four tests fail -- on a tree that had been read completely (#384). It is reported
    rather than dropped: a file deleted in a hostile diff is still worth saying out loud.

    The exception in hand decides which it is: `FileNotFoundError` is absence, anything
    else is unreadable. Asking the filesystem a second question -- `exists()` -- to
    explain why the first one failed is a trap this repository has already paid for; it
    swallows some errnos and raises the rest. One consequence is worth writing down:
    Windows folds several Win32 codes onto `ENOENT`, so a path that is unlookable rather
    than missing arrives here as `FileNotFoundError` and reads as `absent`. That is a
    degraded answer, not a silent one -- the path is still named, with its `strerror`.
    """
    path = os.path.join(str(toplevel), *name.split("/"))
    if name.endswith(SHELL_SUFFIXES):
        # The extension is authoritative and needs no first line, so a file that merely
        # will not read still classifies as shell -- the `except OSError: pass` below.
        # Absence is the one answer the extension cannot give: a path that is not there
        # would otherwise be handed to `shellcheck`, which fails on a missing file.
        try:
            os.stat(path)
        except FileNotFoundError as error:
            return "absent", error.strerror or str(error)
        except OSError:
            pass
        return "shell", "extension"
    try:
        with open(path, "rb") as handle:
            head = handle.read(HEAD_BYTES)
    except FileNotFoundError as error:
        return "absent", error.strerror or str(error)
    except OSError as error:
        return "unknown", error.strerror or str(error)
    interpreter = _shebang_interpreter(head)
    if interpreter in SHELL_INTERPRETERS:
        return "shell", "shebang names {}".format(interpreter)
    return "other", ""


def survey(root):
    """(shell sources, unreadable, absent) for the repository containing `root`.

    Three lists rather than one verdict. Collapsing `unreadable` into `found` would make
    `could not read the tree` indistinguishable from `read the tree, no shell in it`;
    collapsing `absent` into `unreadable` makes an ordinary uncommitted delete
    indistinguishable from a tree this cannot read (#384). Each entry in the second and
    third lists is a `(path, reason)` pair.
    """
    toplevel = _toplevel(root)
    found = []
    unknown = []
    absent = []
    for name in _tracked_paths(toplevel):
        verdict, detail = classify(toplevel, name)
        if verdict == "shell":
            found.append(name)
        elif verdict == "unknown":
            unknown.append((name, detail))
        elif verdict == "absent":
            absent.append((name, detail))
    return sorted(found), sorted(unknown), sorted(absent)


def shell_sources(root):
    """The list alone, for callers that have already accepted the refusals.

    Only `unknown` refuses. A path in the index and not on disk has nothing to lint and
    is not evidence that the tree could not be read, so it does not raise -- callers who
    want to see it call `survey`.
    """
    found, unknown, _absent = survey(root)
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
        found, unknown, absent = survey(args.root)
    except CannotEnumerate as error:
        _emit(sys.stderr, "shell-sources: {}\n".format(error))
        return 3

    if absent:
        # A note, not a refusal, and not silence either. This is the ordinary shape of a
        # working tree between the changelog fold and the release commit; saying nothing
        # would hide a file deleted on purpose in a diff nobody meant to make (#384).
        _emit(
            sys.stderr,
            "shell-sources: {} tracked file(s) are in the index and not on disk, so "
            "they are not linted and are not a tree that could not be read. This is "
            "what an uncommitted delete looks like:\n".format(len(absent)),
        )
        for name, detail in absent:
            _emit(sys.stderr, "  {}: {}\n".format(name, detail))

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
