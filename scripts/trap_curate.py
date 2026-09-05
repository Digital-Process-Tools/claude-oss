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
import sys

#: `<issue>.<slug>.md`. The issue number is what ties a fragment to the work that found the trap;
#: the slug is what stops two fragments on one issue colliding. Both halves are required, so
#: `904.md` does not parse -- a fragment with no slug is a path two lanes on one issue would share.
FRAGMENT_RE = re.compile(
    r"\A(?P<issue>[0-9]+)\.(?P<slug>[A-Za-z0-9][A-Za-z0-9._-]*)\.md\Z"
)

DIRNAME = "trap.d"


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
        if n.endswith(".md") and not n.startswith(".")
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
