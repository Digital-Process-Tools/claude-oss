"""The tick state file: what was decided, and the one reason for it.

Written every tick, read first every tick. Deliberately thin -- status only, never
diffs. Reasoning that only matters to a pull request belongs in that pull request.

Two decisions worth stating, because both are refusals:

* **A corrupt file raises.** Starting fresh would destroy the history the file exists
  to keep, and the tick that did it would be indistinguishable from a first tick.
* **An over-long decision raises rather than truncating.** A truncation silently
  discards the half that mattered and leaves something that still reads as a record.

Timestamps are arguments, never read from the clock in here. A function that reads the
clock cannot be tested for what it writes, and this file is evidence.

Python 3.9 compatible.
"""

import json
from pathlib import Path

MAX_DECISION = 200


class StateError(Exception):
    """The state file could not be read, or an entry was refused."""


def read(path):
    """Return the entries, oldest first. A missing file is an empty history."""
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateError("{}: could not read ({})".format(path, exc))
    try:
        entries = json.loads(raw)
    except ValueError as exc:
        raise StateError(
            "{}: could not parse ({}). Not resetting it -- the history is the point, "
            "and a silent reset looks exactly like a first tick.".format(path, exc)
        )
    if not isinstance(entries, list):
        raise StateError("{}: expected a JSON list of entries".format(path))
    return entries


def append(path, at, decision, detail=None):
    """Add one entry. Returns the entry as written."""
    if not decision or not decision.strip():
        raise StateError(
            "an entry needs a decision. A tick that records only that it happened "
            "reads as history while carrying none."
        )
    if len(decision) > MAX_DECISION:
        raise StateError(
            "decision is {} characters, over the {} cap. Keep the decision and the one "
            "reason for it; the rest belongs in the pull request.".format(
                len(decision), MAX_DECISION
            )
        )

    entry = {"at": at, "decision": decision}
    if detail is not None:
        entry["detail"] = detail

    entries = read(path)
    entries.append(entry)

    try:
        body = json.dumps(entries, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        # Serialise before touching the file, so a bad detail cannot leave a
        # half-written history behind.
        raise StateError("entry is not serialisable ({})".format(exc))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return entry


def last(path):
    """The most recent entry, or None. An empty history is not an error."""
    entries = read(path)
    return entries[-1] if entries else None


def _main(argv=None):
    """CLI for /oss:tick.

    The timestamp is an argument rather than something read here, for the same reason
    the library takes one: a clock inside this file makes what it writes untestable.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Read and append maintainer tick state.")
    parser.add_argument("path", help="the state file, from .oss.json's state_file")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--read", action="store_true", help="print the whole history")
    group.add_argument("--last", action="store_true", help="print the most recent entry")
    group.add_argument("--decision", help="append an entry with this decision")
    parser.add_argument("--at", help="ISO timestamp for the appended entry (required with --decision)")
    parser.add_argument("--detail", help="optional JSON object attached to the entry")
    args = parser.parse_args(argv)

    try:
        if args.read:
            print(json.dumps(read(args.path), indent=2))
            return 0
        if args.last:
            entry = last(args.path)
            print(json.dumps(entry, indent=2) if entry else "no entries yet")
            return 0

        if not args.at:
            print("FAIL --at is required with --decision; the timestamp is not read from a clock")
            return 1
        detail = json.loads(args.detail) if args.detail else None
        entry = append(args.path, args.at, args.decision, detail=detail)
        print(json.dumps(entry, indent=2))
        return 0
    except StateError as exc:
        print("FAIL {}".format(exc))
        return 1
    except ValueError as exc:
        print("FAIL --detail is not valid JSON ({})".format(exc))
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(_main())
