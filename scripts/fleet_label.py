"""The fleet-view label for one dispatched developer lane (#539).

Four developer lanes running concurrently used to render as ``Lane 534  auto-update
path``, ``Lane 535  statusline guard sets``, and so on -- the first issue's number plus
a phrase about that issue. A lane carrying three issues (#534, #537, #495) and a lane
carrying one rendered identically, because the label was composed by habit at the
moment of the spawn and nothing checked it.

``fleet_label`` composes the *description* -- a string handed to the ``Agent`` tool's
own ``description`` parameter, which nothing in this repository can inspect after the
fact (the sibling constraint the issue names explicitly). It does not observe what a
lane actually carries. What it can do is refuse to *compose* a label from an incomplete
answer: the caller must state every issue the lane carries, not just the one that named
the branch, or nothing is rendered at all. A convention followed only by habit is
exactly what #539 was filed about, so the guard lives in the one function that ever
produces the description, not in a sentence next to it.

The count is the load-bearing half (see the issue's own "what would settle it"): a
reader scanning a fleet must see ``x3`` without reading the phrase. A genuine one-issue
lane never carries the multiplier -- if every lane wrote ``x1``, a bundled lane's ``x3``
would read as house style rather than as a fact.

``agent_call`` (#989) is the module's second composition function, built on
``fleet_label``. It renders the *whole* literal ``Agent(...)`` invocation rather than
only the description, and it closes the one half of "nothing can inspect that after the
fact" that a Python-level check *can* reach before the call is ever pasted: whether
``subagent_type`` was given at all, and whether it resolves to one of this loop's known
agent types. What still cannot be inspected after the fact is the call actually run --
``agent_call`` only makes the correct call cheaper to produce than a wrong one typed
from memory.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import sys


class FleetLabelError(ValueError):
    """The label cannot be composed from what was given."""


def fleet_label(primary_issue, issues, phrase):
    """Render ``Lane <primary> [x<N>]  <phrase>`` for one dispatched lane.

    ``primary_issue`` is the issue that named the branch and the worktree.
    ``issues`` is every issue this lane carries, primary included -- never inferred
    from ``primary_issue`` alone, because the whole failure this module exists to
    close is a label that named only the first issue. ``phrase`` is the short
    description of what the lane is doing.
    """
    if not isinstance(issues, (list, tuple)) or not issues:
        raise FleetLabelError(
            "fleet_label needs every issue this lane carries, as a non-empty list -- "
            "an omitted or empty bundle is exactly the label #539 was filed about"
        )

    normalized = []
    for item in issues:
        if isinstance(item, bool):
            raise FleetLabelError(
                "fleet_label: {!r} is not a usable issue number".format(item)
            )
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            raise FleetLabelError(
                "fleet_label: {!r} is not a usable issue number".format(item)
            )

    if len(set(normalized)) != len(normalized):
        raise FleetLabelError(
            "fleet_label: {!r} names the same issue more than once".format(issues)
        )

    if isinstance(primary_issue, bool):
        raise FleetLabelError(
            "fleet_label: {!r} is not a usable primary issue".format(primary_issue)
        )
    try:
        primary = int(primary_issue)
    except (TypeError, ValueError):
        raise FleetLabelError(
            "fleet_label: {!r} is not a usable primary issue".format(primary_issue)
        )

    if primary not in normalized:
        raise FleetLabelError(
            "fleet_label: primary issue {} is not among the lane's own issues {!r} -- "
            "the primary is the branch's issue and must be counted in its own "
            "bundle".format(primary, issues)
        )

    if not phrase or not str(phrase).strip():
        raise FleetLabelError("fleet_label needs a phrase describing the lane's work")
    phrase = str(phrase).strip()

    count = len(normalized)
    if count == 1:
        return "Lane {}  {}".format(primary, phrase)
    return "Lane {} x{}  {}".format(primary, count, phrase)


KNOWN_AGENT_TYPES = ("oss:developer", "oss:triager")
"""The only two agent types this loop's dispatch step ever composes a call for.

Not every agent type this repository defines -- ``oss:sub-manager`` and
``oss:releaser`` are spawned from ``commands/tick.md``, a different call site with
its own literal examples. Widen this tuple only when this module grows a second
call site to compose for.
"""


def _quote_for_call(text):
    """Escape ``text`` so it survives inside a double-quoted field of the
    rendered ``Agent(...)`` call.

    A phrase carrying an unescaped ``"`` closes the ``description`` field
    early, leaving the remainder as bare tokens the human pasting the line
    must hand-repair -- and a phrase crafted with
    ``", subagent_type: "general-purpose`` would silently re-open a new
    keyword and could flip the very ``subagent_type`` this module exists to
    protect (found in self-review of #989, before this function existed).
    Backslash is escaped first so an existing backslash is never mistaken for
    part of the quote escape this function adds.
    """
    return text.replace("\\", "\\\\").replace('"', '\\"')


def agent_call(primary_issue, issues, phrase, subagent_type, model=None,
                run_in_background=False):
    """Render the whole literal ``Agent(...)`` invocation for one dispatched lane (#989).

    A sub-manager tick reported, unprompted, that all three of its ``Agent()`` calls
    omitted ``subagent_type: "oss:developer"`` and ran as ``general-purpose`` instead
    -- caught only because the tick happened to notice. Nothing distinguishes a lane
    run by the wrong agent from one run by the right one: same brief text, it
    commits, it reports. ``fleet_label`` already refuses to compose a *description*
    from an incomplete bundle; this does the same for the *whole call*, so a caller
    pastes the rendered line instead of retyping ``subagent_type`` from memory at
    every call site.

    ``subagent_type`` has no default -- a call built without one is a Python
    ``TypeError`` at the call site, before this function's own body ever runs, which
    is the structural half of the fix. The runtime half is this: a ``subagent_type``
    that *is* given but does not resolve to one of ``KNOWN_AGENT_TYPES`` -- a typo, or
    literally ``"general-purpose"``, the historical failure's own value -- refuses
    the same way an omitted issue bundle already refuses, rather than rendering a
    call that quietly spawns the wrong agent.

    ``prompt`` is never composed here -- the brief is lane-specific text only the
    caller can write -- so the rendered call carries a placeholder the caller fills
    in, the same way ``fleet_label`` never composes the phrase for the caller.
    """
    label = fleet_label(primary_issue, issues, phrase)

    if subagent_type not in KNOWN_AGENT_TYPES:
        raise FleetLabelError(
            "agent_call: {!r} is not one of this loop's known agent types {!r} -- "
            "an omitted or misspelled subagent_type is the #989 failure this "
            "function exists to make structurally harder".format(
                subagent_type, KNOWN_AGENT_TYPES
            )
        )

    parts = ['subagent_type: "{}"'.format(subagent_type)]
    if model:
        parts.append('model: "{}"'.format(_quote_for_call(model)))
    parts.append(
        "run_in_background: {}".format("true" if run_in_background else "false")
    )
    parts.append('description: "{}"'.format(_quote_for_call(label)))
    parts.append('prompt: "<brief>"')

    return "Agent({})".format(", ".join(parts))


def _print(text, stream=None):
    """Print ``text`` without dying on the console's own codepage.

    ``print`` encodes with the stream's encoding, not the source file's, and on
    Windows that is typically cp1252 -- a phrase carrying a character cp1252 cannot
    represent (an arrow, for instance; an em dash is representable and would not
    have caught this) raises ``UnicodeEncodeError`` and kills the process at this
    call, after every validation in ``fleet_label`` already passed. Round-tripped
    through the stream's own encoding first, with ``backslashreplace`` on the way
    out, so an unrepresentable character survives as an escape somebody can read
    instead of ending the process -- the same shape ``oss_state._say`` already uses
    for the same reason.
    """
    stream = sys.stdout if stream is None else stream
    encoding = getattr(stream, "encoding", None)
    if encoding:
        text = text.encode(encoding, "backslashreplace").decode(encoding, "replace")
    print(text, file=stream)


def _main(argv=None):
    """CLI: ``fleet_label.py PRIMARY ISSUE1,ISSUE2,... "phrase" [SUBAGENT_TYPE]``.

    Named in the brief instead of composed by hand -- the whole point is that the
    guard runs even when the caller is a maintainer typing a spawn call, not only a
    test.

    The fourth positional argument is optional and is what turns this from "print
    the description" into "print the whole ``Agent(...)`` call" (#989): give it and
    the CLI prints ``agent_call``'s output instead of ``fleet_label``'s, refusing an
    unresolvable agent type exactly as ``agent_call`` does. Omit it and the CLI
    behaves exactly as before -- the original three-argument form is untouched.
    """
    argv = sys.argv[1:] if argv is None else list(argv)

    model = None
    background = False
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--model":
            i += 1
            if i >= len(argv):
                sys.stderr.write("--model needs a value\n")
                return 2
            model = argv[i]
        elif arg == "--background":
            background = True
        else:
            positional.append(arg)
        i += 1

    if len(positional) == 3:
        primary_text, issues_text, phrase = positional
        subagent_type = None
    elif len(positional) == 4:
        primary_text, issues_text, phrase, subagent_type = positional
    else:
        sys.stderr.write(
            "usage: fleet_label.py PRIMARY_ISSUE ISSUE1,ISSUE2,... PHRASE "
            "[SUBAGENT_TYPE] [--model MODEL] [--background]\n"
        )
        return 2

    issues = [part.strip() for part in issues_text.split(",") if part.strip()]

    try:
        if subagent_type is None:
            output = fleet_label(primary_text, issues, phrase)
        else:
            output = agent_call(
                primary_text, issues, phrase, subagent_type,
                model=model, run_in_background=background,
            )
    except FleetLabelError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1

    _print(output)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
