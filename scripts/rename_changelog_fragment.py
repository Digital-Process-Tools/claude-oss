#!/usr/bin/env python3
"""Rename a changelog fragment to a new issue/PR number, and rewrite its own
self-reference in the same operation (#426).

## Why this exists

A maintainer renames a fragment when opening a pull request --
`git mv changelog.d/N.section.md changelog.d/M.section.md`, keying it to the
pull request's own number, which does not exist until the pull request is
open. Measured on PR #338: the fold consumes the *filename*, so the fragment
body must independently name the number the filename carries
(`assemble_changelog.py`'s `self_reference_finding`). A bare `git mv` moves
the number in the filename and leaves the body naming the old one, and the
`fragment` leg that just passed refuses:

    assemble    : refused     (1 fragment(s) will not assemble)
      changelog.d/338.fixed.md:1: the entry never names #338 -- ...

#335 (the lane-facing half of this same defect) argued the fix should not be
a procedure line for a human to remember, because the rename and the body
rewrite are coupled -- renaming without rewriting produces exactly the
broken fragment above, and rewriting without renaming leaves the filename
wrong. This script performs both together, so there is no window in which
only one half has happened.

## Three states, and the third one is why the rest of this file exists

  0 (OK)        renamed and rewritten, or the fragment already carried the
                target number and nothing needed to move.
  3 (REFUSED)   the source does not parse as a fragment, the destination
                already exists (or could not be examined), `git mv` failed,
                the rewrite itself could not be written (#444: an `OSError`
                from the post-rename write, e.g. disk full), `git add` could
                not stage the rewritten file (#444: it failed to run, or ran
                and refused), or -- the last state, distinct from all of the
                above -- the rewrite left a fragment `--check` would still
                reject. That happens when the old body never named its own
                issue *before* the rename either: there is nothing here to
                move, and inventing text would be a guess this script
                refuses to make. The fragment is still renamed in that case
                (the correct filename is not in question), but the body
                needs a human's `(#N)` before it will pass.
  2              argparse usage error.

A refusal never renames a fragment onto a name that isn't there and never
claims a rewrite that didn't happen -- the receipt says which of the above
fired, not just that something did.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Import the sibling module by location rather than by package, matching how
# every other script in this directory is invoked directly with `python3`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_changelog import (  # noqa: E402
    BadFragment,
    parse_fragment_name,
    self_reference_finding,
)
from lane_setup import _absence_confirmed  # noqa: E402

OK, REFUSED = 0, 3

#: The same shape `assemble_changelog.self_reference_finding` looks for, with
#: the prefix captured so a replacement can keep it and change only the
#: number. Transcribed rather than reinvented, because a rewrite that
#: recognises a narrower set of self-references than the checker accepts
#: would silently leave some of them behind.
_SELF_REF = r"(#|/(?:issues|pull)/){0}(?![0-9])"


def _new_name(fragment, new_issue):
    parts = [str(new_issue), fragment.section]
    if fragment.slug:
        parts.append(fragment.slug)
    return ".".join(parts) + ".md"


def _destination_occupied(path):
    """Whether something already sits at `path`: True, False, or None for "could
    not look".

    `Path.exists()` is not the "never raises" call it looks like -- it swallows
    a version-dependent set of `OSError`s and answers `False` for a path that
    could not be stat'd, not only one that is absent (CLAUDE.md). This is an
    overwrite guard, so a `False` earned that way is the exact failure this
    function exists to close: `rename()`'s caller trusted it and `Path.rename`
    clobbered a destination the guard never actually looked at.

    `os.stat` and the exception in hand classify instead, the same shape
    `oss_config._version_state` (#396/#413) and `lane_setup.worktree_occupancy`
    already use elsewhere in this repo: `FileNotFoundError` /
    `NotADirectoryError` are the absence arm, matching what Python's own
    interpreter normalises platform errors into. Anything else is "could not
    look", and the caller treats that the same as occupied -- refusing an
    overwrite on an unreadable destination is the safe direction, where
    guessing it is free is not.

    #444: the absence arm used to trust the exception type alone, which is
    not actually the same shape `worktree_occupancy` uses -- CLAUDE.md
    records that Windows folds an over-`MAX_PATH` destination onto
    `FileNotFoundError, errno 2, winerror None`, indistinguishable from a
    genuine miss, so on that platform this guard answered "free" for a
    destination nothing had looked at. `_absence_confirmed` (#380) is asked
    for a positive confirmation before absence is claimed, matching
    `lane_setup.worktree_occupancy:557` exactly rather than merely resembling
    it.
    """
    try:
        os.stat(str(path))
    except (FileNotFoundError, NotADirectoryError):
        return False if _absence_confirmed(path) is True else None
    except OSError:
        return None
    except ValueError:
        # `os.stat` raises `ValueError`, not `OSError`, for a path carrying an
        # embedded null byte -- neither arm above catches that, and it would
        # otherwise escape as a traceback. `lane_setup.worktree_occupancy` has
        # the identical arm for the identical reason (#380, adjacent).
        return None
    return True


def rename(fragment_path, new_issue, use_git=True):
    """Rename `fragment_path` to carry `new_issue`, rewriting its own
    self-reference to match. Returns `(state, message, new_path)` --
    `new_path` is `None` only when nothing was written at all.
    """
    old_path = Path(fragment_path)
    if not old_path.is_file():
        return REFUSED, "{0}: no such file".format(old_path), None

    try:
        fragment = parse_fragment_name(old_path.name)
    except BadFragment as exc:
        return REFUSED, str(exc), None

    if fragment.issue == new_issue:
        return (
            OK,
            "{0}: already named for #{1}, nothing to do".format(old_path, new_issue),
            old_path,
        )

    new_path = old_path.with_name(_new_name(fragment, new_issue))
    occupied = _destination_occupied(new_path)
    if occupied is not False:
        detail = (
            "already exists, refusing to overwrite"
            if occupied
            else "could not be examined, refusing to overwrite rather than guess it is free"
        )
        return REFUSED, "{0}: {1}".format(new_path, detail), None

    text = old_path.read_text(encoding="utf-8")
    pattern = re.compile(_SELF_REF.format(fragment.issue))
    rewritten, count = pattern.subn(
        lambda m: "{0}{1}".format(m.group(1), new_issue), text
    )

    if use_git:
        git = shutil.which("git")
        if git is None:
            return REFUSED, "git is not on PATH -- cannot `git mv` {0}".format(old_path), None
        try:
            result = subprocess.run(
                [git, "mv", "--", str(old_path), str(new_path)],
                capture_output=True,
                text=True,
                errors="replace",
            )
        except (OSError, ValueError) as exc:
            return (
                REFUSED,
                "git mv {0} {1} failed to run: {2}: {3}".format(
                    old_path, new_path, type(exc).__name__, exc
                ),
                None,
            )
        if result.returncode != 0:
            return (
                REFUSED,
                "git mv {0} {1} failed: {2}".format(old_path, new_path, result.stderr.strip()),
                None,
            )
    else:
        old_path.rename(new_path)

    # #444: the rewrite runs after the rename and used to be unguarded, with no
    # handler in main() either -- an OSError here left the fragment
    # renamed-but-not-rewritten with a traceback and no receipt, against this
    # module's own docstring claim that the receipt says which state fired.
    try:
        new_path.write_text(rewritten, encoding="utf-8")
    except OSError as exc:
        # `Path.write_text` opens in mode "w", which truncates on open before a
        # single byte of `rewritten` is written -- so a failure at open() really
        # does leave the OLD body in place, but a failure *during* the write
        # (disk full mid-flush) can leave the file empty or partially written
        # instead. The receipt must not assert a specific on-disk state it
        # cannot verify; "cannot be assumed" covers both without guessing.
        return (
            REFUSED,
            "{0}: renamed to {1} but the rewrite failed: {2}: {3} -- the file's "
            "on-disk body cannot be assumed to be either the old or the new text; "
            "verify by hand before committing or amending".format(
                old_path, new_path, type(exc).__name__, exc
            ),
            new_path,
        )

    if use_git and git is not None:
        # `git mv` above staged the pre-rewrite bytes; without this, `git commit
        # --amend` (no `-a`) would commit the old body under the new filename --
        # the exact defect this tool exists to close, one layer later.
        try:
            add_result = subprocess.run(
                [git, "add", "--", str(new_path)],
                capture_output=True,
                text=True,
                errors="replace",
            )
        except (OSError, ValueError) as exc:
            # Same shape as the `git mv` spawn guard above: `git` becoming
            # unspawnable between the two calls (deleted, locked by AV, a
            # fork/exec failure) must not raise past this function.
            return (
                REFUSED,
                "{0} -> {1}: renamed and rewritten, but `git add` failed to run: "
                "{2}: {3} -- an amend without an explicit `git add` would commit "
                "the pre-rewrite body under the new filename".format(
                    old_path, new_path, type(exc).__name__, exc
                ),
                new_path,
            )
        # #444: this exit code used to be discarded, so a failed `git add` was
        # reported identically to a successful one -- reproducing #426's own
        # defect (an amend committing the pre-rewrite body under the new name)
        # while the tool claimed OK. Staging IS this tool's job (that is the
        # reason the `git add` is here at all); the failure needs a state
        # rather than the call being silently unchecked.
        if add_result.returncode != 0:
            return (
                REFUSED,
                "{0} -> {1}: renamed and rewritten, but `git add` failed: {2} -- an "
                "amend without an explicit `git add` would commit the pre-rewrite "
                "body under the new filename".format(
                    old_path, new_path, add_result.stderr.strip()
                ),
                new_path,
            )

    finding = self_reference_finding(new_path.name, rewritten)
    if finding:
        detail = finding
        if count == 0:
            detail += (
                " -- the old body never named #{0} either, so nothing here could be moved "
                "automatically; write (#{1}) into the entry by hand and re-run --check"
                .format(fragment.issue, new_issue)
            )
        return REFUSED, detail, new_path

    return (
        OK,
        "{0} -> {1}, {2} self-reference(s) rewritten to #{3}".format(
            old_path, new_path, count, new_issue
        ),
        new_path,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Rename a changelog fragment to a new issue/PR number and rewrite its "
            "self-reference in the same operation, so the rename and the body it "
            "depends on cannot drift apart (#426)."
        ),
        epilog="exit 0 = renamed (or already correct); exit 3 = refused; exit 2 = usage error.",
    )
    parser.add_argument(
        "fragment", help="path to the existing fragment, e.g. changelog.d/338.fixed.md"
    )
    parser.add_argument(
        "new_issue", type=int, help="the issue or pull request number to key the fragment to"
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="move the file with a plain filesystem rename instead of `git mv`",
    )
    args = parser.parse_args(argv)

    # A Windows console encodes stdout/stderr with its own codepage, not this
    # file's -- an unencodable character here must not kill the process at
    # the print after the rename already happened.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    state, message, _ = rename(args.fragment, args.new_issue, use_git=not args.no_git)
    out = sys.stdout if state == OK else sys.stderr
    print(("OK: " if state == OK else "REFUSED: ") + message, file=out)
    return state


if __name__ == "__main__":
    sys.exit(main())
