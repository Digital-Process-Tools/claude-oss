#!/usr/bin/env python3
"""Does the prompt about to be dispatched carry the two per-lane facts? -- #1535.

`agents/developer.md` is the lane's system prompt and is re-sent on every turn.
Everything a brief used to restate -- supertool, the TDD order, the publishing
clause, pushback, untrusted input, the docs duty -- is in that document already.
Only two facts about a dispatch are not:

    the issue numbers   nothing else tells the lane what to work on
    the worktree path   derived at claim time by the dispatcher

So this module checks those two, plus the one check that was always about the
*prompt string* rather than a brief's content: a literal double-brace template
marker (#1022), which is unfixable once `Agent()` has returned.

## What was removed and why (#1535)

Nine elements were checked before this, five of them pure restatement of
`agents/developer.md`. The checks were substring matches over the brief's own
text, so they were satisfied by the words appearing and could not tell a genuine
instruction from one pasted to pass the gate: the validator measured compliance
with itself, and the dispatcher paid ~7,900 B per spawn to satisfy it.

## The checks are verified against the claim, not against themselves

`check_issues` and `check_worktree` take the values the `--claim` call actually
derived. Given them, the check is a real one -- *these* numbers, *this* path.
Given neither (a prompt composed some other way), each falls back to asking
whether any issue number and any path-shaped token appear at all, and **says so
in the row's note**: a weaker reading must never render as the verified one.

## States

  ok               all three elements found
  findings         one row per element missing, named individually
  could-not-read   the file could not be opened or decoded. Never `ok`, and
                   never a findings row either: "this prompt is missing the
                   worktree" and "nobody read this file" are different facts.

## No longer a standalone CLI (#1143)

`lane_setup.py --claim` is the one entry point that reaches `check_text` /
`check_path`, checking the prompt a `--subagent-type` render is about to
dispatch before it renders the `Agent(...)` line.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import re
from pathlib import Path

STATE_OK = "ok"
STATE_FINDINGS = "findings"
STATE_COULD_NOT_READ = "could-not-read"

#: How an element was checked. All three are structural now -- each can fail for
#: the reason the element exists, not merely when a section is missing. The
#: constant stays because `lane_setup.compose_claim_label` reads it to decide
#: whether to refuse the render.
STRUCTURAL = "structural"

#: `worktree_state`, passed by a caller that *attempted* the derivation. The
#: distinction is the whole of #1535's self-review finding: `worktree=None`
#: alone cannot tell "nobody gave me a value to check against" from "this
#: lane's worktree could not be derived", and reading the second as the first
#: sends the unverified fallback below to decide -- where any path-shaped token
#: in an appended recon summary satisfies the row, and the dispatch that most
#: needs the refusal is the one that does not get it.
WORKTREE_COULD_NOT_DERIVE = "could-not-derive"

#: #1022: a sub-manager wrote a brief's supertool paragraph as the literal
#: template placeholder string it was meant to be substituted with -- "{{PASTE
#: THE FULL CONTENTS OF <scratchpad path> HERE}}" -- and only noticed after all
#: three Agent() calls of that tick had already returned, by which point
#: SendMessage was unavailable to correct any of them. There is no templating
#: step between composing a prompt and the Agent() call that sends it: whatever
#: string is typed is what the agent receives verbatim, so this is only
#: catchable before the call, on the composed text.
#:
#: Excludes a match immediately preceded by `$` (self-review finding on #1022):
#: this repo's own workflow files and `scripts/scaffold.py`'s generated YAML use
#: GitHub Actions' `${{ ... }}` expression syntax extensively, and a prompt
#: scoping a CI/workflow lane can legitimately quote a line like
#: `GH_TOKEN: ${{ github.token }}` -- a genuine "double-brace syntax" this repo's
#: own tree does use, unlike a bare `{{...}}`, which nothing here ever writes on
#: purpose.
#:
#: Allows a newline and up to 4000 characters inside the braces (a second
#: self-review finding, oss:auditor on #1022): the recorded phrase itself embeds
#: a full scratchpad path, which grows with repo/branch/session-id length and can
#: plausibly exceed a tight single-line character cap, or wrap across a line in
#: prose. The earlier `[^{}\n]{1,200}` bound silently missed exactly that shape:
#: `check_placeholder` fell through to the same "found, clean" payload whether no
#: marker was present or one was present but did not fit the pattern's
#: assumptions -- this repo's own defect class, a script's own absence read as an
#: absence in the world.
_PLACEHOLDER_RE = re.compile(r"(?<!\$)\{\{[^{}]{1,4000}\}\}")

#: Any run of digits long enough to be an issue number, used only by the
#: unverified fallback below. Deliberately loose: the verified path compares
#: against the numbers the claim holds and never consults this.
_ANY_ISSUE_RE = re.compile(r"\b\d{1,6}\b")

#: A path-shaped token, for the unverified fallback: a separator with a
#: non-separator on each side. Both separators are in the class, so a dispatcher
#: on Windows composing a backslash path is never told its prompt names no
#: worktree -- a platform claim that is reasoned here and observed only on POSIX.
_ANY_PATH_RE = re.compile(r"[^\s/\\][/\\][^\s/\\]")


def _finding(element, why, checked=STRUCTURAL):
    return {"element": element, "state": "missing", "why": why, "checked": checked}


def _found(element, checked=STRUCTURAL, note=None):
    row = {"element": element, "state": "found", "checked": checked}
    if note:
        row["note"] = note
    return row


def check_issues(text, issues=None):
    """Does the prompt name the issues this lane holds?

    With ``issues`` given, every number must appear -- a lane dispatched at two
    issues and told about one works the first and never learns of the second.
    Without it, only that *some* issue number appears, and the row says so.
    """
    if issues:
        missing = [str(n) for n in issues if not re.search(r"\b{0}\b".format(n), text)]
        if missing:
            return _finding(
                "issues",
                "the prompt does not name {0} -- a lane never told an issue "
                "number cannot work it, and nothing else carries it "
                "(#1535)".format(", ".join(missing)),
            )
        return _found(
            "issues",
            note="verified against the {0} issue(s) this claim holds".format(
                len(issues)
            ),
        )
    if not _ANY_ISSUE_RE.search(text):
        return _finding(
            "issues",
            "the prompt names no issue number at all; nothing else tells the "
            "lane what to work on (#1535)",
        )
    return _found(
        "issues",
        note="an issue number appears, but not verified against a claimed set -- "
        "no issues were given to check against",
    )


def check_worktree(text, worktree=None, worktree_state=None):
    """Does the prompt name the worktree this lane was claimed into?

    Three readings, and the third is the one that was missing (#1535
    self-review). `worktree_state=WORKTREE_COULD_NOT_DERIVE` says the caller
    tried and failed: that is a finding whatever the text contains, because the
    fallback below cannot tell a real path from `read/write` in a sentence, and
    a caller that attempted the derivation has already answered the question
    the fallback exists to guess at. A lane not told its worktree cuts its own,
    which is how two lanes end up briefed into the same files.
    """
    if worktree_state == WORKTREE_COULD_NOT_DERIVE:
        return _finding(
            "worktree",
            "the worktree could not be derived for this lane, so there is no "
            "path to name -- refused rather than dispatched to cut its own "
            "(#1535). This is not 'no worktree was given': the caller tried.",
        )
    if worktree:
        if str(worktree) not in text:
            return _finding(
                "worktree",
                "the prompt does not name the worktree this claim derived "
                "({0}) -- a lane not told where to work cuts its own "
                "(#1535)".format(worktree),
            )
        return _found("worktree", note="verified against the path this claim derived")
    if not _ANY_PATH_RE.search(text):
        return _finding(
            "worktree",
            "the prompt names no worktree path at all; the worktree is derived "
            "at claim time and the lane cannot read it anywhere (#1535)",
        )
    return _found(
        "worktree",
        note="a path appears, but not verified against a derived worktree -- "
        "no worktree was given to check against, and no caller said it had "
        "tried. Weak by construction: this only asks whether a separator sits "
        "between two non-separators, which ordinary prose satisfies",
    )


def check_placeholder(text):
    """#1022: a literal double-brace marker is unfixable once dispatched --
    SendMessage is unavailable to correct a lane after Agent() returns, so
    this can only be caught on the composed text before the call."""
    match = _PLACEHOLDER_RE.search(text)
    if match:
        return _finding(
            "placeholder",
            "literal template placeholder marker found ({0!r}) -- there is no "
            "templating step between composing a prompt and the Agent() call "
            "that sends it; whatever string is typed is what the agent "
            "receives verbatim, and it cannot be corrected after dispatch "
            "(#1022)".format(match.group(0)),
        )
    return _found("placeholder")


#: Order matters only for the receipt; every check runs regardless of what the
#: ones before it found. A validator that stopped at the first finding would
#: send an author back for one fix at a time.
CHECKS = (
    ("issues", lambda text, issues, worktree, state: check_issues(text, issues)),
    (
        "worktree",
        lambda text, issues, worktree, state: check_worktree(text, worktree, state),
    ),
    ("placeholder", lambda text, issues, worktree, state: check_placeholder(text)),
)


def check_text(text, issues=None, worktree=None, worktree_state=None):
    rows = [run(text, issues, worktree, worktree_state) for _, run in CHECKS]
    missing = [row for row in rows if row["state"] == "missing"]
    return {
        "state": STATE_FINDINGS if missing else STATE_OK,
        "elements": rows,
        "missing": [row["element"] for row in missing],
    }


def check_path(path, issues=None, worktree=None, worktree_state=None):
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
    payload = check_text(
        text, issues=issues, worktree=worktree, worktree_state=worktree_state
    )
    payload["path"] = str(path)
    return payload


def receipt(payload):
    lines = [
        "prompt-schema: {0}  {1}".format(payload["state"], payload.get("path", ""))
    ]
    if payload["state"] == STATE_COULD_NOT_READ:
        lines.append("  detail: {0}".format(payload["detail"]))
        lines.append(
            "  COULD NOT READ is not a passing prompt and not a failing one -- "
            "nobody looked."
        )
        return "\n".join(lines)
    for row in payload["elements"]:
        mark = "ok " if row["state"] == "found" else "MISS"
        lines.append(
            "  {0}  {1:<12} [{2}]  {3}".format(
                mark,
                row["element"],
                row["checked"],
                row.get("why") or row.get("note") or "",
            ).rstrip()
        )
    lines.append(
        "  The three per-lane facts, checked. Everything else a lane needs is "
        "agents/developer.md, re-sent on every turn (#1535)."
    )
    return "\n".join(lines)
