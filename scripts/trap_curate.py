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
    """
    command = [
        git_bin or "git",
        "-C",
        str(root),
        "ls-tree",
        "-r",
        "--name-only",
        ref,
        "--",
        DIRNAME,
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
    root = argv[1] if len(argv) > 1 else "."
    result = waiting(root)
    print(render(result))
    # Exit 0 in every state. A queue length is a report, never a gate: the gate that refuses to tag
    # over a non-empty trap.d/ lives in the release phase, where the person reading the failure is
    # the person who skipped the pass.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
