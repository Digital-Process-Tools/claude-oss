#!/usr/bin/env python3
"""Read `trap.d/` and report what is waiting to be curated. Python 3.9 compatible.

A trap fragment is logged with no judgment: a lane that sees a problem writes what it saw and moves
on. Choosing a jit-context dimension, writing a match pattern and proving it fires is work for
`/oss:curate`, taken later with every fragment visible at once -- which is the only position from
which "these three are one rule" can be seen.

So this module validates exactly one thing, the filename, and validates it because two lanes must
never collide on a path. It does not look inside a fragment. A required heading or a required field
would be friction at the exact moment friction stops the lesson being written.

Three states, never a bare count:

    waiting          N fragments are here, listed
    none             the directory is readable and empty, or absent. `count` is 0, a real finding
    could-not-read   the directory could not be listed. `count` is None, never 0

The third state is the point. A pass that was silently skipped and a cycle with nothing to curate
render identically the moment an unreadable directory is allowed to answer `0`.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

#: `<issue>.<slug>.md`. The issue number is what ties a fragment to the work that found the trap;
#: the slug is what stops two fragments on one issue colliding. Both halves are required, so
#: `904.md` does not parse -- a fragment with no slug is a path two lanes on one issue would share.
FRAGMENT_RE = re.compile(
    r"\A(?P<issue>[0-9]+)\.(?P<slug>[A-Za-z0-9][A-Za-z0-9._-]*)\.md\Z"
)

DIRNAME = "trap.d"

#: `scaffold.py` owns exactly one file inside `trap.d/` -- the README documenting
#: what the directory is for -- and replaces it on every run. It is documentation
#: ABOUT the fragments, never a fragment, so counting it as one reports the
#: directory's own instructions as a malformed trap forever: a finding no manual
#: op and no scaffold run can clear, since scaffold is what writes it (#1348).
#:
#: Excluded by name deliberately, and the name is the whole exclusion: this is
#: NOT the "exclude the class, not the instance" case, because the class here is
#: already `FRAGMENT_RE` and everything outside it is still reported. A second
#: non-fragment file appearing in this directory should be reported as one, which
#: is what happens with no further change.
OWNED_README = "README.md"


def _decode(raw):
    """Decode a subprocess's bytes for display. Never raises -- `git`'s own
    stderr is free text nobody here authored."""
    if raw is None:
        return ""
    if not isinstance(raw, bytes):
        return raw
    return raw.decode("utf-8", "replace")


def _classify(name):
    m = FRAGMENT_RE.match(name)
    if m is None:
        return {"name": name, "parses": False, "issue": None, "slug": None}
    return {
        "name": name,
        "parses": True,
        "issue": int(m.group("issue")),
        "slug": m.group("slug"),
    }


def waiting(root):
    """What is in `<root>/trap.d`, in three states.

    `os.listdir` is asked directly rather than `Path.exists()` first: `exists()` swallows a short
    list of errnos and re-raises the rest, and the list varies by interpreter version, so it takes
    the classification out of our hands. The exception already in hand answers which arm runs --
    `FileNotFoundError` is the absence arm, anything else is unreadable -- and no version's
    `exists()` semantics get a vote.
    """
    path = os.path.join(str(root), DIRNAME)
    try:
        names = os.listdir(path)
    except FileNotFoundError:
        return {
            "state": "none",
            "count": 0,
            "fragments": [],
            "why": "no {}/ here, so nothing has been logged".format(DIRNAME),
        }
    except OSError as exc:
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "{}/ could not be listed: {}: {}".format(
                DIRNAME, type(exc).__name__, exc.strerror or exc
            ),
        }

    fragments = [
        _classify(n)
        for n in sorted(names)
        if n.endswith(".md") and not n.startswith(".") and n != OWNED_README
    ]
    if not fragments:
        return {
            "state": "none",
            "count": 0,
            "fragments": [],
            "why": "{}/ is readable and holds no fragments".format(DIRNAME),
        }
    return {
        "state": "waiting",
        "count": len(fragments),
        "fragments": fragments,
        "why": "{} fragment(s) waiting for /oss:curate".format(len(fragments)),
    }


def waiting_at_ref(root, ref, run=subprocess.run, git_bin=None, timeout=15):
    """Same three states as `waiting()`, but read `ref`'s own committed tree
    via `git ls-tree` rather than the working directory at `root` (#1476).

    `next_action.py`/`workspace_routes.py` call this instead of `waiting()`
    when the checkout is standing on a branch other than the repository's
    own default branch: `waiting()` answers for whatever happens to be
    checked out at `root` right now, which is the wrong question on a
    shared checkout somebody else has switched to a feature branch --
    #1476's own incident had a curate commit already pushed to `main`
    while the checkout under a live session had meanwhile moved to a
    branch cut before that commit, and the stale branch's own `trap.d/`
    was read and reported as `main`'s.

    `git ls-tree` exits 0 with empty output for a pathspec matching
    nothing, so an absent `trap.d/` at `ref` and an empty one both render
    as `none` -- the same collapse `waiting()` makes for the working tree.
    Only a genuine git failure (an unresolvable `ref`, no such repository,
    `git` not on PATH) is `could-not-read`; that failure must never be
    read as `none`, or a checkout with no visibility into `ref` at all
    would silently report a clean trap.d/ that was never actually checked.

    Deliberately NOT `-r` (self-review finding, Explore reviewer, #1476):
    `waiting()` lists `trap.d/`'s immediate entries only via
    `os.listdir`, never descending into a subdirectory. A recursive
    `ls-tree -r` here would count fragments one level deeper than the
    working-tree reader ever would, so the two readers of "the same
    fact" -- a working tree and a ref -- could disagree even when
    nothing about the real backlog changed, purely from which one was
    asked. `trap.d/` is flat by convention (`<issue>.<slug>.md` only),
    so this keeps both readers looking at exactly the same shape.
    """
    command = [
        git_bin or "git",
        "-C",
        str(root),
        "ls-tree",
        "--name-only",
        ref,
        "--",
        # A trailing slash is load-bearing: `ls-tree <ref> -- trap.d` (no
        # slash) names the DIRECTORY ENTRY ITSELF as a pathspec and returns
        # exactly one line, "trap.d", never its contents -- confirmed
        # against a real repo before this landed. `trap.d/` lists that
        # directory's own immediate entries instead, one level deep,
        # matching `os.listdir`'s own non-recursive shape.
        DIRNAME + "/",
    ]
    try:
        done = run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "{0} did not run ({1})".format(" ".join(command), exc),
        }
    if done.returncode != 0:
        message = (_decode(done.stderr) or _decode(done.stdout)).strip()
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "{0} failed: {1}".format(
                " ".join(command), message or "exit {0}".format(done.returncode)
            ),
        }
    names = [line.strip() for line in _decode(done.stdout).splitlines() if line.strip()]
    basenames = [os.path.basename(n) for n in names]
    fragments = [
        _classify(n)
        for n in sorted(basenames)
        if n.endswith(".md") and not n.startswith(".") and n != OWNED_README
    ]
    if not fragments:
        return {
            "state": "none",
            "count": 0,
            "fragments": [],
            "why": "{0}/ at {1} holds no fragments".format(DIRNAME, ref),
        }
    return {
        "state": "waiting",
        "count": len(fragments),
        "fragments": fragments,
        "why": "{0} fragment(s) waiting for /oss:curate (at {1})".format(
            len(fragments), ref
        ),
    }


def untracked_fragments(root, run=subprocess.run, git_bin=None, timeout=15):
    """Same three states as ``waiting()``, but for files physically sitting in
    ``<root>/trap.d/`` that git does not track at all -- never committed on
    ANY branch, so they are invisible to ``waiting_at_ref`` no matter which
    ref it is pointed at (#1723). ``harvest_fragments`` (``worktree_reap.py``)
    and a releaser session both write straight into a clone's own working
    tree this way, as a plain filesystem copy, with no ``git add`` and no
    commit -- exactly the fragments the old working-tree-only branch of
    ``curate_count`` used to count and a fresh ``git worktree add
    origin/<default_branch>`` can never see.

    ``git status --porcelain`` reports untracked entries (``??``) regardless
    of which branch is currently checked out -- untracked-ness is a fact
    about the index, not about HEAD -- so, unlike ``waiting()``, this is safe
    to call no matter what the clone happens to be standing on.
    """
    command = [
        git_bin or "git",
        "-C",
        str(root),
        "status",
        "--porcelain",
        "--ignored=no",
        # Without this, a `trap.d/` that is ENTIRELY untracked (no file in it
        # has ever been part of the index) collapses to one `?? trap.d/`
        # line for the whole directory rather than one line per file --
        # confirmed against a real repo before this landed. `--untracked-
        # files=all` forces the per-file listing this function actually
        # parses, matching `waiting()`'s own per-file, non-recursive shape.
        "--untracked-files=all",
        "--",
        DIRNAME + "/",
    ]
    try:
        done = run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "{0} did not run ({1})".format(" ".join(command), exc),
        }
    if done.returncode != 0:
        message = (_decode(done.stderr) or _decode(done.stdout)).strip()
        return {
            "state": "could-not-read",
            "count": None,
            "fragments": [],
            "why": "{0} failed: {1}".format(
                " ".join(command), message or "exit {0}".format(done.returncode)
            ),
        }
    prefix = DIRNAME + "/"
    names = []
    for line in _decode(done.stdout).splitlines():
        if not line.startswith("??"):
            continue
        rel = line[3:].strip().strip('"')
        rel_posix = rel.replace("\\", "/").rstrip("/")
        if not rel_posix.startswith(prefix):
            continue
        remainder = rel_posix[len(prefix) :]
        if "/" in remainder:
            # `--untracked-files=all` expands a wholly-untracked directory
            # into one line per file, including anything nested a level
            # deeper than `trap.d/` itself -- `waiting()`'s own `os.listdir`
            # never descends, so a fragment logged inside a subdirectory
            # must not be counted here either (mirrors `waiting_at_ref`'s
            # own deliberately-not-recursive note, self-review finding,
            # Explore reviewer, #1476).
            continue
        if remainder:
            names.append(remainder)
    fragments = [
        _classify(n)
        for n in sorted(names)
        if n.endswith(".md") and not n.startswith(".") and n != OWNED_README
    ]
    if not fragments:
        return {
            "state": "none",
            "count": 0,
            "fragments": [],
            "why": "{0}/ holds no untracked fragments".format(DIRNAME),
        }
    return {
        "state": "waiting",
        "count": len(fragments),
        "fragments": fragments,
        "why": "{0} untracked fragment(s) sitting in the clone's own working "
        "tree".format(len(fragments)),
    }


def copy_stray_into(
    clone_dir, worktree_dir, run=subprocess.run, git_bin=None, timeout=15
):
    """Copy every untracked ``trap.d/`` fragment sitting in ``clone_dir``'s
    own working tree into ``worktree_dir``'s ``trap.d/``, so a curate pass
    cut from ``origin/<default_branch>`` evaluates the same set
    ``curate_count`` now counts (#1723) instead of silently missing every
    fragment a filesystem-only write like ``harvest_fragments`` ever
    produced. Read-only against ``clone_dir`` -- never writes there.

    Returns ``(state, copied, skipped, why)``; ``state`` is ``"ok"`` or
    ``"could-not-read"``. ``skipped`` pairs a name with why it was not
    copied -- a name collision with a fragment already in this pass's own
    ``trap.d/`` is never overwritten, the same rule ``harvest_fragments``
    already follows.
    """
    result = untracked_fragments(clone_dir, run=run, git_bin=git_bin, timeout=timeout)
    if result["state"] == "could-not-read":
        return "could-not-read", [], [], result["why"]
    dest_dir = Path(worktree_dir) / DIRNAME
    copied = []
    skipped = []
    for f in result["fragments"]:
        name = f["name"]
        src = Path(clone_dir) / DIRNAME / name
        dest = dest_dir / name
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                skipped.append(
                    (
                        name,
                        "a fragment named {} already exists in this pass's "
                        "own trap.d/ -- not overwritten".format(name),
                    )
                )
                continue
            dest.write_bytes(src.read_bytes())
            copied.append(name)
        except OSError as exc:
            skipped.append((name, str(exc)))
    return "ok", copied, skipped, result["why"]


def sweep_resolved(clone_dir, worktree_dir, copied_names):
    """Once a curate pass has decided every fragment it read, remove from
    ``clone_dir``'s own ``trap.d/`` each name in ``copied_names`` that is no
    longer present in ``worktree_dir``'s ``trap.d/`` -- promote, merge and
    decline all delete the fragment from the pass's own worktree as part of
    the disposition, so its absence there means this pass resolved it and
    the untracked original in the clone is now a stale duplicate that would
    otherwise inflate every later ``curate_count`` forever (#1723). A name
    still present in ``worktree_dir`` was deferred -- left alone in the
    clone too, exactly where ``harvest_fragments`` or the releaser put it,
    so the next pass finds it the same way.

    This is a deliberate, narrow write to the clone -- the one exception to
    "never write to the primary clone" a curate pass otherwise holds to --
    scoped to exactly the fragment names this same pass copied out of it a
    moment earlier and has already safely captured into its own commit.
    """
    result = waiting(worktree_dir)
    if result["state"] == "could-not-read":
        return "could-not-read", [], [], result["why"]
    still_here = {f["name"] for f in result["fragments"]}
    removed = []
    failures = []
    for name in copied_names:
        if not name or name in still_here:
            continue
        path = Path(clone_dir) / DIRNAME / name
        try:
            path.unlink()
            removed.append(name)
        except FileNotFoundError:
            removed.append(name)
        except OSError as exc:
            failures.append((name, str(exc)))
    return "ok", removed, failures, result["why"]


def render(result):
    """One line for a status surface, then the fragment names when there are any."""
    state = result["state"]
    if state == "could-not-read":
        return "trap.d: ? could-not-read -- {}".format(result["why"])
    if state == "none":
        return "trap.d: none waiting -- {}".format(result["why"])
    lines = ["trap.d: {} waiting -- run /oss:curate".format(result["count"])]
    for f in result["fragments"]:
        mark = "" if f["parses"] else "  [name does not parse as <issue>.<slug>.md]"
        lines.append("  {}{}".format(f["name"], mark))
    return "\n".join(lines)


def main(argv):
    args = argv[1:]
    root = args[0] if args else "."
    rest = args[1:]

    if "--copy-stray-from" in rest:
        clone = rest[rest.index("--copy-stray-from") + 1]
        state, copied, skipped, why = copy_stray_into(clone, root)
        if state == "could-not-read":
            print(
                "trap.d: could-not-read -- the stray scan of {0} failed: {1}".format(
                    clone, why
                )
            )
            return 1
        print(
            "trap.d: copied {0} stray fragment(s) from {1}: {2}".format(
                len(copied), clone, ",".join(copied) if copied else "(none)"
            )
        )
        for name, reason in skipped:
            print("  skipped {0}: {1}".format(name, reason))
        print(render(waiting(root)))
        # Exit 0 in every state -- see the note on the plain-read branch below.
        return 0

    if "--sweep-resolved-in" in rest:
        clone = rest[rest.index("--sweep-resolved-in") + 1]
        copied_arg = ""
        if "--copied" in rest:
            copied_arg = rest[rest.index("--copied") + 1]
        copied_names = [n for n in copied_arg.split(",") if n]
        state, removed, failures, why = sweep_resolved(clone, root, copied_names)
        if state == "could-not-read":
            print(
                "trap.d: could-not-read -- this pass's own trap.d/ could not be "
                "read: {0}".format(why)
            )
            return 1
        print(
            "trap.d: removed {0} resolved stray fragment(s) from {1}: {2}".format(
                len(removed), clone, ",".join(removed) if removed else "(none)"
            )
        )
        for name, reason in failures:
            print("  failed to remove {0}: {1}".format(name, reason))
        return 0

    result = waiting(root)
    print(render(result))
    # Exit 0 in every state. A queue length is a report, never a gate: the gate that refuses to tag
    # over a non-empty trap.d/ lives in the release phase, where the person reading the failure is
    # the person who skipped the pass.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
