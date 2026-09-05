#!/usr/bin/env python3
"""Does a developer brief carry the elements dispatch requires? -- #967, #1022.

A lane's *report* is validated by `scripts/report_schema.py`. Its *brief* --
the artefact dispatch actually produces, and the only thing the developer ever
reads -- was validated by nothing, and `skills/manager/phases/dispatch.md` line
"Every brief carries these:" lists eight mandatory elements checked by a
session re-reading its own draft.

Every one of the eight is there because a brief shipped without it:

  * `paste` is named in the supertool block because a brief that omitted it
    "read as correct" for six deliveries (#250) -- an op named and later
    renamed fails *at the call*, an op omitted does not fail at all and routes
    the agent to a heredoc that succeeds;
  * the cwd paragraph cost two agents a re-sent heredoc, and naming it once
    then cost two more (#266, #685);
  * the worktree list says *not retyped from memory* because retyping is how
    agents stop knowing about each other;
  * the publishing clause is unconditional because "do not push *if* something
    blocks you" is how one agent correctly pushed.

Each was fixed by strengthening the prose, and none of them was checked.

## The risk this script carries, stated first

**A brief that passes is not a good brief.** Only four of the eight can be
checked in a way that catches the failure actually observed; the other four are
presence checks, and presence is not quality. A tool reporting `ok` on a brief
nobody read is worse than no tool, because it moves the missing review out of
sight -- this repository's own defect class, produced by the thing meant to
catch it.

So the receipt separates the two, always, in both directions: every element
says whether it was checked `structurally` (a claim about what the text does)
or by `presence` (a claim only that a section exists). `ok` means "the eight
are there", never "this brief is good", and the receipt's own last line says
so rather than leaving it to be inferred.

## States

  ok               all eight elements found
  findings         one row per element missing or degraded, named individually
  could-not-read   the file could not be opened or decoded. Never `ok`, and
                   never a findings row either: "this brief is missing item 4"
                   and "nobody read this brief" are different facts, and the
                   second must not be reported in the vocabulary of the first.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import argparse
import json
import re
import sys
from pathlib import Path

STATE_OK = "ok"
STATE_FINDINGS = "findings"
STATE_COULD_NOT_READ = "could-not-read"

#: How an element was checked. The distinction is load-bearing and is printed
#: on every row: `structural` means the check can fail for the reason the
#: element exists, `presence` means it can only fail when the section is
#: missing altogether.
STRUCTURAL = "structural"
PRESENCE = "presence"

#: Ops the supertool block must name (#250). `paste` is the one that matters:
#: it is the only route to a file that does not exist yet, and a changelog
#: fragment is always one. A named op that supertool later renames fails at the
#: call; an omitted one routes the agent to a heredoc that succeeds.
REQUIRED_OPS = ("edit", "paste", "git-commit")

#: The TDD order, in order. Checked as a sequence rather than a set: "test,
#: red, fix, green" and "fix, green, test, red" contain the same four words and
#: describe opposite processes.
TDD_ORDER = ("test", "red", "fix", "green")

#: A publishing clause softened into a condition is the recorded failure (#7 in
#: dispatch.md), not a stylistic preference: "do not push *if* something blocks
#: you" is how one agent correctly pushed.
_CONDITIONAL_RE = re.compile(r"\b(if|unless|when|should)\b", re.IGNORECASE)

#: #1022: a sub-manager wrote a brief's supertool paragraph as the literal
#: template placeholder string it was meant to be substituted with --
#: "{{PASTE THE FULL CONTENTS OF <scratchpad path> HERE}}" -- and only noticed
#: after all three Agent() calls of that tick had already returned, by which
#: point SendMessage was unavailable to correct any of them. There is no
#: templating step between composing a brief and the Agent() call that sends
#: it: whatever string is typed is what the agent receives verbatim, so this
#: is only catchable before the call, on the composed text.
#:
#: Excludes a match immediately preceded by `$` (self-review finding on
#: #1022): this repo's own workflow files and `scripts/scaffold.py`'s
#: generated YAML use GitHub Actions' `${{ ... }}` expression syntax
#: extensively, and a brief scoping a CI/workflow lane can legitimately quote
#: a line like `GH_TOKEN: ${{ github.token }}` -- a genuine "double-brace
#: syntax" this repo's own tree does use, unlike a bare `{{...}}`, which
#: nothing here ever writes on purpose.
#:
#: Allows a newline and up to 4000 characters inside the braces (a second
#: self-review finding, oss:auditor on #1022): the recorded phrase itself
#: embeds a full scratchpad path -- "{{PASTE THE FULL CONTENTS OF
#: <scratchpad path> HERE}}" -- which grows with repo/branch/session-id
#: length and can plausibly exceed a tight single-line character cap, or wrap
#: across a line in prose. The earlier `[^{}\n]{1,200}` bound silently missed
#: exactly that shape: `check_placeholder` fell through to the same "found,
#: clean" payload whether no marker was present or one was present but did
#: not fit the pattern's assumptions -- this repo's own defect class, a
#: script's own absence read as an absence in the world.
_PLACEHOLDER_RE = re.compile(r"(?<!\$)\{\{[^{}]{1,4000}\}\}")


def _finding(element, why, checked):
    return {"element": element, "state": "missing", "why": why, "checked": checked}


def _found(element, checked, note=None):
    row = {"element": element, "state": "found", "checked": checked}
    if note:
        row["note"] = note
    return row


def _clause_window(text, anchor, width=400):
    """The text around `anchor`, or `None`. Used by the checks that ask what a
    clause says rather than whether it appears -- a conditional word anywhere
    else in a 4,000-word brief says nothing about the clause."""
    at = text.lower().find(anchor)
    if at < 0:
        return None
    return text[at : at + width]


def _outside_supertool(text):
    """The brief minus the paragraphs that make up the supertool instruction.

    Measured, not anticipated: the two presence checks below were reading a
    word that the supertool block legitimately contains. Its own text names
    "your changelog fragment is always one" and `cd <worktree_root>`, so
    deleting the docs paragraph and the worktree list from a brief left both
    checks passing on the block above them. Scoping them to the rest of the
    document is the narrowest fix -- a mention inside the supertool
    instruction is that instruction, never the brief's own docs requirement or
    its list of live lanes.
    """
    return "\n\n".join(
        para for para in text.split("\n\n") if "supertool" not in para.lower()
    )


def check_supertool(text):
    lowered = text.lower()
    if "supertool" not in lowered:
        return _finding(
            "supertool",
            "the brief never names supertool; an agent with no route uses raw tools",
            STRUCTURAL,
        )
    missing = [op for op in REQUIRED_OPS if op not in lowered]
    if missing:
        return _finding(
            "supertool",
            "names supertool but not {0} -- an omitted op does not fail at the "
            "call, it routes the agent to a heredoc that succeeds (#250)".format(
                ", ".join("`{0}`".format(op) for op in missing)
            ),
            STRUCTURAL,
        )
    note = None
    if "cd " not in lowered or "cwd" not in lowered:
        note = (
            "no cwd instruction found; a shell cwd does not persist between calls "
            "and a later bare supertool writes into the clone (#266, #685)"
        )
    return _found("supertool", STRUCTURAL, note)


def check_judgment_call(text):
    lowered = text.lower()
    for phrase in ("judgment call", "judgement call", "will have to decide", "decide"):
        if phrase in lowered:
            return _found(
                "judgment_call",
                PRESENCE,
                "presence only: whether what it names is the real judgement is not "
                "checkable, and this script does not claim it is",
            )
    return _finding(
        "judgment_call",
        "no judgement call named; if you cannot state what the agent must decide, "
        "the issue has not been read closely enough to delegate",
        PRESENCE,
    )


def check_pushback(text):
    lowered = text.lower()
    for phrase in ("push back", "pushback", "hypothesis", "hypotheses", "disagree"):
        if phrase in lowered:
            return _found("pushback", PRESENCE)
    return _finding(
        "pushback",
        "no invitation to push back; a confident mechanical diagnosis is the most "
        "dangerous input an agent receives",
        PRESENCE,
    )


def check_tdd(text):
    lowered = text.lower()
    at = 0
    for word in TDD_ORDER:
        found = lowered.find(word, at)
        if found < 0:
            return _finding(
                "tdd",
                "the four steps do not appear in order (test, red, fix, green); "
                "{0!r} is missing or out of sequence".format(word),
                STRUCTURAL,
            )
        at = found + len(word)
    if "fail" not in lowered and "red" not in lowered:
        return _finding(
            "tdd",
            "no demand for the failure output before the implementation exists",
            STRUCTURAL,
        )
    return _found("tdd", STRUCTURAL)


def check_docs(text):
    lowered = _outside_supertool(text).lower()
    if "changelog" not in lowered:
        return _finding(
            "docs",
            "the changelog is required on every brief, always, and is not named",
            PRESENCE,
        )
    return _found(
        "docs",
        PRESENCE,
        "presence only: whether docs_targets is right for this change is not "
        "checkable from the brief",
    )


def check_worktrees(text):
    lowered = _outside_supertool(text).lower()
    if "worktree" not in lowered:
        return _finding(
            "worktrees",
            "no live worktrees named; agents that do not know about each other "
            "brief into the same files",
            PRESENCE,
        )
    return _found(
        "worktrees",
        PRESENCE,
        "presence only: whether the list came from lane_setup.py or from memory "
        "is not observable from the brief, and this script does not imply it is",
    )


def check_publishing(text):
    """The one check that can fail on a brief that *has* the clause.

    A conditional next to it is the finding, because that softening is the
    recorded failure rather than a wording preference.
    """
    window = _clause_window(text, "do not push")
    if window is None:
        window = _clause_window(text, "don't push")
    if window is None:
        return _finding(
            "publishing",
            "no publishing clause; the developer stops at a commit and every brief "
            "has to say so",
            STRUCTURAL,
        )
    clause = window.split("\n\n")[0]
    conditional = _CONDITIONAL_RE.search(clause)
    if conditional:
        return _finding(
            "publishing",
            "the publishing clause is conditional ({0!r} appears in it) -- "
            "'do not push if something blocks you' is how one agent correctly "
            "pushed".format(conditional.group(0)),
            STRUCTURAL,
        )
    return _found("publishing", STRUCTURAL)


def check_placeholder(text):
    """#1022: a literal `{{...}}` marker is unfixable once dispatched --
    SendMessage is unavailable to correct a lane after Agent() returns, so
    this can only be caught on the composed text before the call."""
    match = _PLACEHOLDER_RE.search(text)
    if match:
        return _finding(
            "placeholder",
            "literal template placeholder marker found ({0!r}) -- there is no "
            "templating step between composing a brief and the Agent() call "
            "that sends it; whatever string is typed is what the agent "
            "receives verbatim, and it cannot be corrected after dispatch "
            "(#1022)".format(match.group(0)),
            STRUCTURAL,
        )
    return _found("placeholder", STRUCTURAL)


#: Order matters only for the receipt; every check runs regardless of what the
#: ones before it found. A validator that stopped at the first finding would
#: send an author back for one fix at a time.
CHECKS = (
    check_supertool,
    check_judgment_call,
    check_pushback,
    check_tdd,
    check_docs,
    check_worktrees,
    check_publishing,
    check_placeholder,
)


def check_text(text):
    rows = [run(text) for run in CHECKS]
    missing = [row for row in rows if row["state"] == "missing"]
    return {
        "state": STATE_FINDINGS if missing else STATE_OK,
        "elements": rows,
        "missing": [row["element"] for row in missing],
    }


def check_path(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "state": STATE_COULD_NOT_READ,
            "path": str(path),
            "detail": "{0}: {1}".format(path, exc),
            "elements": [],
            "missing": [],
        }
    payload = check_text(text)
    payload["path"] = str(path)
    return payload


def receipt(payload):
    lines = ["brief-schema: {0}  {1}".format(payload["state"], payload.get("path", ""))]
    if payload["state"] == STATE_COULD_NOT_READ:
        lines.append("  detail: {0}".format(payload["detail"]))
        lines.append(
            "  COULD NOT READ is not a passing brief and not a failing one -- "
            "nobody looked."
        )
        return "\n".join(lines)
    for row in payload["elements"]:
        mark = "ok " if row["state"] == "found" else "MISS"
        lines.append(
            "  {0}  {1:<14} [{2}]  {3}".format(
                mark,
                row["element"],
                row["checked"],
                row.get("why") or row.get("note") or "",
            ).rstrip()
        )
    structural = sum(1 for row in payload["elements"] if row["checked"] == STRUCTURAL)
    lines.append(
        "  {0} of {1} elements checked structurally; the rest are presence only. "
        "A brief that passes is not a brief that was reviewed.".format(
            structural, len(payload["elements"])
        )
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate a developer brief against dispatch's eight elements."
    )
    parser.add_argument("briefs", nargs="+", help="brief files")
    parser.add_argument("--json", action="store_true", help="emit payloads as JSON")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    payloads = [check_path(path) for path in args.briefs]
    if args.json:
        sys.stdout.write(json.dumps(payloads, indent=2) + "\n")
    else:
        sys.stdout.write("\n".join(receipt(p) for p in payloads) + "\n")
    return 0 if all(p["state"] == STATE_OK for p in payloads) else 1


if __name__ == "__main__":
    sys.exit(main())
