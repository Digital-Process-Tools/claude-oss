#!/usr/bin/env python3
"""A receipt across a review spawn, so a silent mutation stops being luck (#769).

`agents/developer.md` spawns two review agents against the tree it just
committed, both told explicitly not to mutate it. Both have already done so
in the same run: an `Explore` reviewer built a scratch copy under a symlink
and, in its own words, wrote through the symlink into the real worktree,
reverting a tracked file to its parent-commit content in place; in the same
run, `oss:auditor` wrote and deleted an untracked scratch file inside the
same worktree. **Neither left a ref movement or a reflog entry** -- nothing
in the repository recorded either one. The first was caught only because the
lane happened to run `git diff` before reading the agent's own admission of
it; the second is known only because the agent self-reported it.

Had the first gone unnoticed, the lane's own full-suite run would have
executed against a tree where the fix under review had been silently
reverted, and the resulting green or red would have described neither the
fix nor its absence -- this repository's own defect class, landing inside
the one mechanism built to catch it.

## What this buys, and what it does not

This is a snapshot-and-compare, in the same shape as `review_return.py`'s
answer to #392: it asks nothing of the spawn, grants no capability, and
creates no artifact the spawn can act on. It does not stop a mutation --
nothing here does, short of not handing a review agent the real tree at
all, which #769 itself weighs as the more expensive fix and declines for
now. What it removes is the step where an unnoticed mutation stays
unnoticed: the developer takes a snapshot before spawning, and a second one
after both spawns return, and the comparison is arithmetic rather than a
"did I happen to run `git diff` at the right moment" judgement call.

**It cannot see a write that is created and deleted before the after-snapshot
runs.** That is instance 2's own shape, and no before/after comparison taken
only at the two ends can see a state that returned to identical in between --
there is nothing on disk left to compare. This is a stated limit, not an
oversight: `tests/test_tree_snapshot_769.py` pins it directly, so the gap is
measured rather than assumed.

**It cannot see a persisting write to a path `.gitignore` covers, either --
also stated, and deliberately not closed by adding `--ignored`.** A review
spawn's own permitted work (running the suite, say) leaves artifacts at
exactly the paths most repositories ignore: `.pytest_cache/`, `__pycache__/`,
`.coverage`. Turning `--ignored` on would make an ordinary suite run between
the two snapshots report `mutated` -- measured directly during this module's
own development: `git status --porcelain=v2 --untracked-files=all --ignored`
printed six pre-existing artifacts against an otherwise clean repository.
That false-positive rate would drown the real signal in the one workflow
this tool has to coexist with, which is worse for this tool's actual use
than the false-negative it would close. `tests/test_tree_snapshot_769.py`
pins the current (undetected) behaviour rather than leaving it assumed.

A mutation that persists to the moment the `compare` call runs, at a path
`.gitignore` does not cover -- a reverted file, a scratch file left behind,
HEAD moved -- is exactly what this catches, and that is instance 1's shape and
the harmful one: a lingering change that would otherwise silently sit under
whatever the lane runs next.

## The states

  clean               the tree's status and HEAD are unchanged since the
                       before-snapshot. Not a guarantee nothing happened --
                       see the self-cleaning limit above -- only that nothing
                       PERSISTED.
  mutated             something changed: a tracked file, an untracked file
                       left behind, or HEAD itself moved. The detail names
                       what, so the caller can decide whether to restore.
  could-not-compare   either snapshot could not be taken -- not a git repo,
                       git not on PATH, the root does not exist. Never
                       collapses into `clean`: a check that could not look
                       and a check that looked and found nothing must not
                       render the same way, which is this repository's own
                       rule turned on its own tooling.

Exit codes, because a shell reads those and never reads prose:

  0   clean
  1   mutated
  2   argparse usage error
  3   could-not-compare
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _run_git(args, root):
    """Return ``(output, error)`` -- exactly one of the two is None.

    The same rule this repository applies everywhere else: the exception
    already in hand answers what went wrong, rather than asking the
    filesystem a second question that can itself fail differently across
    platforms and interpreter versions.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return None, "git could not be run: {0}".format(
            getattr(exc, "strerror", None) or exc.__class__.__name__
        )
    if result.returncode != 0:
        return None, "git {0} exited {1}: {2}".format(
            " ".join(args), result.returncode, result.stderr.strip() or "no stderr"
        )
    return result.stdout, None


def _resolved_root(root):
    """Return the absolute path `root` names, or `root` itself unchanged if
    it cannot be resolved (#971).

    `root` defaults to `"."`, meaningful only relative to whatever the
    calling process's cwd happened to be at the instant this ran. A
    snapshot taken now and compared later -- possibly by a different
    process, possibly after the caller's cwd has moved, which is exactly
    what happens between two Bash tool calls -- needs a `root` that still
    means the same directory once that cwd is gone. `Path.resolve()` can
    raise on a handful of platforms for a cyclic symlink or an unreadable
    parent; falling back to the literal string on failure keeps `snapshot`
    itself never crashing over what is, at worst, a return to the
    pre-#971 behaviour for that one path.
    """
    try:
        return str(Path(root).resolve())
    except (OSError, RuntimeError):
        return str(root)


def snapshot(root="."):
    """Capture what is needed to detect a mutation of the working tree.

    Two facts, each cheap and each a fact `git` itself already keeps: the
    commit HEAD names, and the porcelain status of everything that differs
    from it -- staged, unstaged, and untracked alike (``--untracked-files=all``
    so a new file inside an existing untracked directory is still named,
    rather than folded into the directory's own line).

    The `root` recorded in the result is the *resolved, absolute* path,
    never the literal string this was called with (#971) -- `compare`'s
    CLI reuses it as the default root for the after-snapshot precisely so
    a caller whose cwd moved between the two calls still re-snapshots the
    directory the before-snapshot actually looked at.
    """
    resolved_root = _resolved_root(root)
    head, head_error = _run_git(["rev-parse", "HEAD"], root)
    if head_error is not None:
        return {"root": resolved_root, "head": None, "status": None, "error": head_error}
    status, status_error = _run_git(
        ["status", "--porcelain=v2", "--untracked-files=all"], root
    )
    if status_error is not None:
        return {"root": resolved_root, "head": None, "status": None, "error": status_error}
    return {
        "root": resolved_root,
        "head": head.strip(),
        "status": status,
        "error": None,
    }


def _one_line(text, limit=2000):
    """One printed line, folded so a multi-line reason cannot land a second
    line at column 0 of the VERDICT receipt `agents/developer.md:552` reads
    (#806).

    `_run_git`'s error strings embed git's own stderr verbatim, and git's
    stderr is routinely multi-line -- an ambiguous `rev-parse HEAD` on a
    repo with no commits appends a `Use '--' to separate...` hint on its
    own line. Same shape as `lane_setup._one_line` and
    `oss_state._receipt_line`, kept local rather than imported: this is a
    standalone CLI module and neither of those two should have to change
    because this one's contract did.
    """
    return " ".join(str(text).split())[:limit]


def _verdict(state, reason, **extra):
    out = {"state": state, "reason": reason, "added": [], "removed": [], "head_moved": False}
    out.update(extra)
    return out


def compare(before, after):
    """Sort a before/after pair of `snapshot()` dicts into the three states."""
    for label, snap in (("before", before), ("after", after)):
        if not isinstance(snap, dict):
            # Same finding as `_read_before`'s own shape check, caught again
            # here for a caller that built (or mangled) a snapshot dict by
            # hand rather than routing it through `_read_before` -- this
            # function must not assume its callers already validated.
            return _verdict(
                "could-not-compare",
                "the {0}-snapshot is not a JSON object (got {1}): nothing "
                "to compare".format(label, type(snap).__name__),
            )
    if before.get("error"):
        return _verdict(
            "could-not-compare",
            "the before-snapshot could not be taken: {0}".format(before["error"]),
        )
    if after.get("error"):
        return _verdict(
            "could-not-compare",
            "the after-snapshot could not be taken: {0}".format(after["error"]),
        )
    before_lines = {
        line for line in (before.get("status") or "").splitlines() if line.strip()
    }
    after_lines = {
        line for line in (after.get("status") or "").splitlines() if line.strip()
    }
    added = sorted(after_lines - before_lines)
    removed = sorted(before_lines - after_lines)
    head_moved = before.get("head") != after.get("head")

    if not added and not removed and not head_moved:
        return _verdict(
            "clean",
            "the tree's status and HEAD are unchanged since the before-snapshot",
        )

    detail = []
    if head_moved:
        detail.append(
            "HEAD moved from {0} to {1}".format(before.get("head"), after.get("head"))
        )
    if added:
        detail.append("new status line(s): {0}".format("; ".join(added)))
    if removed:
        detail.append(
            "status line(s) present before and gone now (restored, or the "
            "before-snapshot itself was dirty): {0}".format("; ".join(removed))
        )
    return _verdict(
        "mutated",
        "; ".join(detail),
        added=added,
        removed=removed,
        head_moved=head_moved,
    )


EXIT_CODES = {"clean": 0, "mutated": 1, "could-not-compare": 3}


def _read_before(source):
    """Return ``(dict, error)`` -- a malformed or unreadable source is
    ``could-not-compare``, never read as an empty (and therefore clean)
    snapshot."""
    if source == "-":
        stream = getattr(sys.stdin, "buffer", None)
        if stream is None:
            return None, "no readable stdin: closed or unopenable standard input"
        try:
            data = stream.read()
        except (OSError, ValueError) as exc:
            return None, "unreadable stdin: {0}".format(
                getattr(exc, "strerror", None) or exc.__class__.__name__
            )
        text = data.decode("utf-8", errors="replace")
    else:
        try:
            text = Path(source).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            return None, "no such file: {0}".format(exc.strerror or "not found")
        except OSError as exc:
            return None, "unreadable: {0}".format(exc.strerror or exc.__class__.__name__)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, "the before-snapshot is not valid JSON: {0}".format(exc)
    if not isinstance(parsed, dict):
        # A reviewer's own finding (#769): valid JSON that is not an object
        # -- `null`, a bare number, a list -- parsed clean and reached
        # `compare()`'s `before.get("error")`, which is not a method a
        # non-dict has. Checking the *shape* here, not only the syntax,
        # keeps that an AttributeError can never surface as an unhandled
        # crash whose exit code (1) collides with EXIT_CODES["mutated"].
        return None, (
            "the before-snapshot is valid JSON but not a JSON object (got "
            "{0}): nothing to compare".format(type(parsed).__name__)
        )
    return parsed, None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Snapshot a git worktree before spawning a review agent, and "
            "compare after it returns -- so an unnoticed mutation becomes a "
            "reported one instead of a silent one (#769)."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    snap_parser = sub.add_parser("snapshot", help="print a snapshot as JSON")
    snap_parser.add_argument("--root", default=".", help="the worktree to snapshot")

    cmp_parser = sub.add_parser("compare", help="compare a before-snapshot to now")
    cmp_parser.add_argument(
        "--before",
        required=True,
        help="path to a file holding the before-snapshot's JSON, or - for stdin",
    )
    cmp_parser.add_argument(
        "--root",
        default=None,
        help=(
            "the worktree to re-snapshot. Defaults to the before-snapshot's "
            "own recorded root, not the live cwd (#971) -- pass this "
            "explicitly to compare against a different directory on purpose."
        ),
    )

    args = parser.parse_args(argv)

    # The sibling idiom used by lane_setup.py, release_delta.py, scaffold.py,
    # checklist_skew.py, ranking_table.py, release_version.py and
    # rename_changelog_fragment.py (#794): a VERDICT line can carry an
    # arbitrary git status path or a localised git stderr string, and a
    # console codepage that cannot encode one of them must not crash this
    # print -- a UnicodeEncodeError here exits 1, colliding with
    # EXIT_CODES["mutated"] and destroying could-not-compare (exit 3) too.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    if args.command == "snapshot":
        result = snapshot(args.root)
        print(json.dumps(result))
        # A reviewer's own finding (#769): this used to return 0 whether or
        # not `result["error"]` was set, so a failed snapshot and a
        # successful one were indistinguishable by exit code -- exactly the
        # collapse `could-not-compare`'s own docstring entry says this
        # module must never allow. The JSON body already carried `error`
        # either way, so a caller reading the body was never misled; only
        # the exit code was, and `compare` still resolves correctly here
        # because it re-reads that body rather than trusting this exit code.
        return EXIT_CODES["could-not-compare"] if result["error"] else 0

    before, error = _read_before(args.before)
    if error is not None:
        verdict = _verdict(
            "could-not-compare",
            "{0} -- nothing was compared, which is not the same as comparing "
            "and finding no mutation".format(error),
        )
    else:
        # `--root` defaults to `None`, not `"."` -- when the caller did not
        # pass it explicitly, re-snapshot the directory the before-snapshot
        # itself recorded (#971), never a live cwd that may have moved
        # since. An explicit `--root` always wins, unchanged from before
        # this fix. A before-snapshot missing a usable `root` (a hand-built
        # or pre-#971 payload) falls back to `"."`, the old default.
        if args.root is not None:
            root_for_after = args.root
        else:
            recorded_root = before.get("root")
            root_for_after = (
                recorded_root if isinstance(recorded_root, str) and recorded_root else "."
            )
        verdict = compare(before, snapshot(root_for_after))

    print("VERDICT: {0} -- {1}".format(verdict["state"], _one_line(verdict["reason"])))
    if verdict["head_moved"]:
        print("  HEAD moved: yes")
    if verdict["added"]:
        print("  added: {0}".format("; ".join(verdict["added"])))
    if verdict["removed"]:
        print("  removed: {0}".format("; ".join(verdict["removed"])))
    return EXIT_CODES[verdict["state"]]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
