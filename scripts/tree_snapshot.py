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
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_which  # noqa: E402 -- #1175: `gh_which.safe_which`, not a bare
# `subprocess.run(["git", ...])` with no resolution gate at all -- see
# `gh_which`'s own docstring for the Windows curdir-execution mechanism
# this closes.


def _run_git(args, root):
    """Return ``(output, error)`` -- exactly one of the two is None.

    The same rule this repository applies everywhere else: the exception
    already in hand answers what went wrong, rather than asking the
    filesystem a second question that can itself fail differently across
    platforms and interpreter versions.
    """
    git_bin = gh_which.safe_which("git")
    if git_bin is None:
        return None, "git could not be run: git is not on PATH"
    try:
        result = subprocess.run(
            [git_bin, *args],
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
    """Return ``(root_string, resolved)`` -- `resolved` is `False` whenever
    `root_string` is not actually usable as an absolute, cwd-independent
    path, so a caller can tell the two apart rather than trusting an
    unresolved string as if it had resolved (#971 self-review).

    `root` defaults to `"."`, meaningful only relative to whatever the
    calling process's cwd happened to be at the instant this ran. A
    snapshot taken now and compared later -- possibly by a different
    process, possibly after the caller's cwd has moved, which is exactly
    what happens between two Bash tool calls -- needs a `root` that still
    means the same directory once that cwd is gone.

    `Path.resolve()` can fail: `OSError` on a handful of platforms for a
    cyclic symlink or an unreadable parent, and `ValueError` for a path
    string pathlib cannot even attempt to stat -- an embedded NUL byte,
    reachable in practice because `compare --before -` reads arbitrary
    JSON off stdin and a JSON string can legally encode a NUL character.
    Falling back to the literal string on any of these keeps `snapshot`
    itself never crashing, but the caller must not then treat that literal
    string as though it were resolved -- `resolved=False` is what lets it
    refuse to.
    """
    try:
        return str(Path(root).resolve()), True
    except (OSError, RuntimeError, ValueError):
        return str(root), False


def snapshot(root="."):
    """Capture what is needed to detect a mutation of the working tree.

    Two facts, each cheap and each a fact `git` itself already keeps: the
    commit HEAD names, and the porcelain status of everything that differs
    from it -- staged, unstaged, and untracked alike (``--untracked-files=all``
    so a new file inside an existing untracked directory is still named,
    rather than folded into the directory's own line).

    The `root` recorded in the result is the *resolved, absolute* path,
    never the literal string this was called with (#971), whenever it
    could be resolved at all -- `root_resolved` says which happened, so
    `compare`'s CLI can reuse `root` as the default root for the
    after-snapshot (a caller whose cwd moved between the two calls still
    re-snapshots the directory the before-snapshot actually looked at)
    without also reusing an unresolved fallback string as though it were
    cwd-independent, which it is not.

    A third fact, `branch` (#1096), is corroborating rather than load-
    bearing: three separate incidents (#1024, #1078, #1096) reported this
    call landing on a *sibling* worktree's directory instead of its own,
    even from a single `cd <worktree> && python3 ... snapshot` shell call --
    and none of them found a resolvable code-level cause here (`root`
    always reads the invoking process's own cwd; there is no cross-worktree
    guess anywhere in this module). `branch` cannot detect that on its own
    -- if the whole process really stood in the wrong directory, `branch`
    would consistently read the WRONG worktree's branch too, the same way
    `head`/`status` would. What it buys is cheap, active verification for
    the human or agent holding the before-snapshot: a lane already knows
    its OWN branch name (its brief states it), so reading `branch` back
    immediately -- rather than trusting `root`'s bare path, which is easy
    to misread at a glance -- is a much lower-effort check than comparing
    two directory strings character by character. Best-effort: a failure
    to read the branch name does not fail the whole snapshot (`error`
    stays keyed to `head`/`status` alone), because HEAD/status are what
    `compare` actually needs and a detached-HEAD checkout must not lose
    those over a corroborating field it cannot supply.
    """
    resolved_root, root_resolved = _resolved_root(root)
    head, head_error = _run_git(["rev-parse", "HEAD"], root)
    if head_error is not None:
        return {
            "root": resolved_root,
            "root_resolved": root_resolved,
            "head": None,
            "status": None,
            "branch": None,
            "error": head_error,
        }
    status, status_error = _run_git(
        ["status", "--porcelain=v2", "--untracked-files=all"], root
    )
    if status_error is not None:
        return {
            "root": resolved_root,
            "root_resolved": root_resolved,
            "head": None,
            "status": None,
            "branch": None,
            "error": status_error,
        }
    branch, branch_error = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    return {
        "root": resolved_root,
        "root_resolved": root_resolved,
        "head": head.strip(),
        "status": status,
        "branch": branch.strip() if branch_error is None else None,
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


# `compare`'s own before-snapshot naming convention (#1330): a lane following
# `.claude/jit-context/tools/01-oss/tree-snapshot-compare.md`'s advice to
# write the before-snapshot JSON *inside* the worktree (rather than a shared
# scratchpad, which can vanish mid-run) leaves an untracked file that did not
# exist when the before-snapshot was taken -- so by construction it always
# shows up as an "added" status line at compare time (observed once in
# practice, per PR #1291's own self-review round; see #1330's provenance).
# This matches any basename ending in `-before-snapshot.json` or exactly
# `before-snapshot.json` (a bare name, or one prefixed with an issue number or
# any other label), never a single hardcoded literal filename -- a caller
# free to name its own snapshot file must still be recognised, not just
# today's one instance. This is a pattern match on the *name* only, not on
# the file's content or its author: it is meant to absorb this module's own
# accidental bookkeeping artifact, not to authenticate one, so it is no
# stronger a guarantee than that.
SNAPSHOT_ARTIFACT_RE = re.compile(r"(?:^|/)(?:[^/]*-)?before-snapshot\.json$")


def _normalize_snapshot_path(path):
    """Forward slashes, no leading ``./`` -- the shape both a porcelain
    status line and a caller-supplied ``--before`` argument converge on,
    close enough to compare directly regardless of which relative form
    either one happened to be spelled in."""
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _platform_path_key(text):
    """`text`, case-folded when this module believes it is running on
    Windows, unchanged everywhere else (#1480).

    `sys.platform` is read fresh on every call rather than cached at
    import time, purely so a test can monkeypatch it and exercise the
    Windows branch on any host -- confirming the mechanism does not
    require an actual Windows machine, only the reasoning that a real one
    can hand this module two differently-cased spellings of the same
    root (a drive letter's case, or a short-name spelling) at all, which
    stays reasoned rather than observed here.

    Case-folding is scoped to that one platform on purpose: a POSIX
    filesystem is not guaranteed case-insensitive (ext4 and most Linux
    setups are case-sensitive), so folding case unconditionally would
    make two genuinely different paths compare equal there."""
    if sys.platform.startswith("win"):
        return text.casefold()
    return text


def _root_relative_path(path_str, root):
    """String-only: strip `root` as a literal prefix off `path_str`, when
    `path_str` is absolute and actually sits under `root`, returning the
    remainder in root-relative, forward-slash form -- the same convention
    a git-status line already uses. Never touches the filesystem (no
    existence check, no `Path.resolve()`, no cwd assumption): `root` and
    `path_str` are simply strings this module already trusts (`root` is
    `snapshot()`'s own resolution; `path_str` is what the caller named).

    Returns ``None`` when `root` is falsy, or `path_str` is not absolute,
    or does not sit under `root` -- "cannot resolve", never "does not
    match": the caller falls back to comparing the raw, unresolved form.

    The prefix compare itself goes through `_platform_path_key` (#1480):
    on Windows, `--before`'s recorded root and the live root can differ
    only in case (a drive letter, a short-name spelling) and still name
    the same directory, so a bare, case-sensitive `str.startswith` there
    can refuse to resolve a path that genuinely sits under `root` and
    fall back to comparing the raw, unresolved form instead -- which can
    then mis-render as a false `mutated` verdict on an unmutated
    snapshot. The slice below still indexes into the *original*, un-
    folded `norm_path` and uses `len(prefix)` from the original,
    un-folded `prefix`, so the returned remainder is exactly the text
    that was actually there, never the folded key used only to decide
    whether the prefix matched."""
    if not root:
        return None
    norm_path = _normalize_snapshot_path(path_str)
    norm_root = _normalize_snapshot_path(str(root)).rstrip("/")
    prefix = norm_root + "/"
    if not _platform_path_key(norm_path).startswith(_platform_path_key(prefix)):
        return None
    return norm_path[len(prefix) :]


def _resolve_own_snapshot_path(own_snapshot_path, root):
    """The form `_is_own_snapshot_artifact` compares a status line against:
    `own_snapshot_path` reduced to root-relative form when it resolves
    that way (an absolute `--before` argument, the common CLI shape), or
    left as its own normalized self otherwise (a caller-relative path,
    already root-relative by convention, or one this module cannot place).
    """
    resolved = _root_relative_path(own_snapshot_path, root)
    return (
        resolved
        if resolved is not None
        else _normalize_snapshot_path(own_snapshot_path)
    )


def _is_own_snapshot_artifact(status_line, own_snapshot_relpath=None):
    """True when a porcelain v2 untracked (``? <path>``) line names this
    module's own before-snapshot artifact.

    Only untracked lines are ever eligible: the artifact this module writes
    is a brand-new file, never a modification of something already tracked,
    so a ``1``/``2``-prefixed (ordinary change / rename) line is never
    excluded here regardless of its path.

    #1430: when the caller told us which file it actually used as the
    before-snapshot (``own_snapshot_relpath``, computed by `compare` via
    `_resolve_own_snapshot_path` -- the ordinary CLI shape is ``compare
    --before <path>``), the exclusion is ANCHORED to that exact file via
    EXACT equality on the root-relative form, rather than to the generic
    naming convention -- a real, unrelated file that happens to also match
    `SNAPSHOT_ARTIFACT_RE` (e.g. a lane's own fixture named
    ``src/anything-before-snapshot.json``) must still be reported as a
    mutation, not silently swallowed by the pattern.

    Self-review finding (#1430, both spawned reviewers independently): an
    earlier version of this anchoring matched on a shared basename alone
    (`a.endswith("/" + b)`), which silently re-admitted the exact
    ambiguity the fix exists to remove whenever `own_snapshot_relpath` was
    a bare filename with no directory component -- the ordinary case, per
    #1330's own convention of writing the before-snapshot inside the
    worktree it snapshots. Exact equality on a properly root-resolved path
    removes that heuristic rather than narrowing it.

    With no such path known (`compare` invoked directly by a caller that
    built its own before/after dicts, as every test in
    `tests/test_tree_snapshot_own_artifact_1330.py` still does, or the
    before-snapshot was read from stdin), there is nothing to anchor to,
    so the old, unanchored pattern match is the fallback -- unchanged.
    """
    if not status_line.startswith("? "):
        return False
    path = status_line[2:]
    if own_snapshot_relpath is not None:
        return _normalize_snapshot_path(path) == own_snapshot_relpath
    return bool(SNAPSHOT_ARTIFACT_RE.search(path))


def _verdict(state, reason, **extra):
    out = {
        "state": state,
        "reason": reason,
        "added": [],
        "removed": [],
        "head_moved": False,
    }
    out.update(extra)
    return out


def compare(before, after, own_snapshot_path=None):
    """Sort a before/after pair of `snapshot()` dicts into the three states.

    `own_snapshot_path` (#1430) is the caller-supplied path to the actual
    before-snapshot file, when known -- CLI callers pass `args.before`
    through `main()`. Anchors the own-artifact exclusion to that specific
    file rather than the generic naming convention; see
    `_is_own_snapshot_artifact`'s own docstring for what changes and what
    stays the same when this is left unset.
    """
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
    own_snapshot_relpath = None
    if own_snapshot_path:
        # Trust `before`'s own recorded root only when it says it actually
        # resolved -- same caveat `main()` already applies to `root_for_after`
        # a few lines below in the CLI path, kept consistent here.
        root = before.get("root") if before.get("root_resolved") is True else None
        own_snapshot_relpath = _resolve_own_snapshot_path(own_snapshot_path, root)
    added = sorted(
        line
        for line in (after_lines - before_lines)
        if not _is_own_snapshot_artifact(line, own_snapshot_relpath)
    )
    removed = sorted(
        line
        for line in (before_lines - after_lines)
        if not _is_own_snapshot_artifact(line, own_snapshot_relpath)
    )
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
            return None, "unreadable: {0}".format(
                exc.strerror or exc.__class__.__name__
            )
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
    snap_parser.add_argument(
        "--root",
        default=".",
        help=(
            "the worktree to snapshot (default: the calling process's own cwd "
            "at this call, never a guess across sibling worktrees -- there is no "
            "such heuristic here). The resolved, absolute root is recorded in the "
            "output and reused by a later `compare` call by default, so a `compare` "
            "invoked from a different cwd -- e.g. after the Bash tool resets cwd "
            "between calls -- still re-snapshots this same root rather than "
            "wherever it happens to be standing (#971). Passing --root again at "
            "compare time still overrides that on purpose, unchanged. No such "
            "cross-worktree resolution bug was found or fixed here (#1024)."
        ),
    )

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
            # Trust the recorded root only when the before-snapshot itself
            # says it resolved (#971 self-review): a `root_resolved: False`
            # or absent (pre-#971, or built by hand) before-snapshot has no
            # cwd-independent root to reuse, and defaulting to it anyway
            # would silently reopen the exact bug this default exists to
            # close -- an unresolved fallback string resolved a second
            # time, now against whatever cwd `compare` happens to run in.
            root_for_after = (
                recorded_root
                if isinstance(recorded_root, str)
                and recorded_root
                and before.get("root_resolved") is True
                else "."
            )
        # #1430: anchor the own-artifact exclusion to the file the caller
        # actually named as the before-snapshot, not the generic naming
        # convention -- "-" (stdin) names no such file, so it falls through
        # to the old unanchored behaviour, unchanged.
        own_snapshot_path = args.before if args.before != "-" else None
        verdict = compare(before, snapshot(root_for_after), own_snapshot_path)

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
