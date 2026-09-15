#!/usr/bin/env python3
"""Read `outbound/` and report what public acts are waiting, drafted but not sent (#1395).

`trap.d/` pointed at public acts: the loop writes one file per intended act -- a
refusal with its reason, a reply to a comment, a review on an outside pull
request -- and something else sends them. Writing a file is not a public act,
so drafting one needs no permission and costs nothing; posting it does, and
posting happens in the maintainer's name on a public tracker. This module is
the read half of that split, mirroring `scripts/trap_curate.py`'s own shape
for the identical reason: two lanes must never collide on a path, and this
never looks inside a fragment.

**The queue waits. The loop does not.** A draft sitting here must never be a
reason a tick pauses, blocks or arms a wakeup -- this module only counts and
reports; nothing here sends anything, and nothing here is called from a gate.

## The four states, in the filename

`<issue>.<state>.<slug>.md`, mirroring `changelog.d/`'s own
`<issue>.<section>[.<slug>].md` convention one directory over:

* ``pending`` -- written, not sent.
* ``sent`` -- posted, carrying the comment or review id as its receipt (in the
  body, not the name), so a re-run cannot double-post.
* ``dropped`` -- read and declined. The same reason `/oss:curate` leaves the
  trace of a declined fragment in the rule layer's `00-README.md`: recorded,
  so the same finding re-drafted next tick is recognised as already declined.
* ``stale`` -- the thing it was written against has moved. Not pending and not
  dropped: it needs rewriting, not sending.

Moving a draft between states -- and everything that reads a draft's own body
for what it was written against -- is the drain pass this module deliberately
does not implement (#1395's own requirement 3: "a pass, not a gate", run when
asked or on the threshold). What ships here is the read half only: the
directory, its ownership, the threshold key and the count this queue needs to
become visible before anything drains it. #1395 tracks the drain and the
send-policy graduation as follow-on work.

Three states for the read itself, never a bare count -- the same reasoning
`trap_curate.waiting`'s own docstring gives:

    waiting          drafts are here, listed and counted per state
    none             the directory is readable and empty, or absent
    could-not-read   the directory could not be listed at all
"""

import os
import re
import sys

#: `<issue>.<state>.<slug>.md`. Both the issue and the slug are required, the
#: same reason `trap_curate.FRAGMENT_RE` requires both: a name with either
#: missing is a path two lanes on one issue -- or two acts on one issue --
#: would collide on.
STATES = ("pending", "sent", "dropped", "stale")

FRAGMENT_RE = re.compile(
    r"\A(?P<issue>[0-9]+)\.(?P<state>" + "|".join(STATES) + r")"
    r"\.(?P<slug>[A-Za-z0-9][A-Za-z0-9._-]*)\.md\Z"
)

DIRNAME = "outbound"

#: `scaffold.py` owns exactly one file inside `outbound/` -- the README, on
#: the `trap.d/README.md` precedent (#1348) -- and replaces it on every run.
#: It documents the directory; it is never a draft.
OWNED_README = "README.md"


def _classify(name):
    m = FRAGMENT_RE.match(name)
    if m is None:
        return {
            "name": name,
            "parses": False,
            "issue": None,
            "state": None,
            "slug": None,
        }
    return {
        "name": name,
        "parses": True,
        "issue": int(m.group("issue")),
        "state": m.group("state"),
        "slug": m.group("slug"),
    }


def waiting(root):
    """What is in `<root>/outbound`, in three states -- see the module docstring."""
    path = os.path.join(str(root), DIRNAME)
    try:
        names = os.listdir(path)
    except FileNotFoundError:
        return {
            "state": "none",
            "count": 0,
            "by_state": {s: 0 for s in STATES},
            "drafts": [],
            "why": "no {}/ here, so nothing has been drafted".format(DIRNAME),
        }
    except OSError as exc:
        return {
            "state": "could-not-read",
            "count": None,
            "by_state": None,
            "drafts": [],
            "why": "{}/ could not be listed: {}: {}".format(
                DIRNAME, type(exc).__name__, exc.strerror or exc
            ),
        }

    drafts = [
        _classify(n)
        for n in sorted(names)
        if n.endswith(".md") and not n.startswith(".") and n != OWNED_README
    ]
    if not drafts:
        return {
            "state": "none",
            "count": 0,
            "by_state": {s: 0 for s in STATES},
            "drafts": [],
            "why": "{}/ is readable and holds no drafts".format(DIRNAME),
        }
    by_state = {s: 0 for s in STATES}
    for d in drafts:
        if d["parses"]:
            by_state[d["state"]] += 1
    return {
        "state": "waiting",
        "count": len(drafts),
        "by_state": by_state,
        "drafts": drafts,
        "why": "{} draft(s) in {}/".format(len(drafts), DIRNAME),
    }


def pending_count(root):
    """The one number that matters to a status line or a threshold route: how
    many drafts are sitting `pending` -- written, not yet sent, not yet
    declined. `None` only on `could-not-read`, never on a readable-but-empty
    or absent directory, which are both a real, measured `0` (#1395's own
    "the third state is load-bearing").
    """
    result = waiting(root)
    if result["state"] == "could-not-read":
        return None
    if result["state"] == "none":
        return 0
    return result["by_state"]["pending"]


def render(result):
    """One line for a status surface, then the draft names when there are any."""
    state = result["state"]
    if state == "could-not-read":
        return "outbound: ? could-not-read -- {}".format(result["why"])
    if state == "none":
        return "outbound: none waiting -- {}".format(result["why"])
    lines = [
        "outbound: {} pending, {} sent, {} dropped, {} stale".format(
            result["by_state"]["pending"],
            result["by_state"]["sent"],
            result["by_state"]["dropped"],
            result["by_state"]["stale"],
        )
    ]
    for d in result["drafts"]:
        mark = (
            ""
            if d["parses"]
            else "  [name does not parse as <issue>.<state>.<slug>.md]"
        )
        lines.append("  {}{}".format(d["name"], mark))
    return "\n".join(lines)


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    result = waiting(root)
    print(render(result))
    # Exit 0 in every state, on the same reasoning trap_curate.main gives: a
    # queue length is a report, never a gate.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
