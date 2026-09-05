"""Which OTHER open issues belong in a lane already claimed (#851) -- board in, ranked companion suggestions out.

Split out of `lane_setup.py` for #1069, and owned by `select_issues.py`
now: `suggest_companions` is the fourth join `select()` composes (see that
module's own "## Groups" section) -- board in, ranked dispatchable-lane
suggestions out -- not a lane-setup concern. Needs `resolve_lane`/
`lane_overlap` from `select_issues_overlap.py`, the sibling this same split
produced.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import re

import lane_setup_patterns
import select_issues_overlap


#: sibling, #843) already writes a file path in. `[^`\n]` rather than `.`
#: alone: a code fence's contents can legitimately contain a backtick-adjacent
#: character, but never a literal backtick spanning a newline the way this
#: single-line span is meant to.
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")


def _looks_like_a_declared_path(token):
    """Whether a backtick-quoted `token`, pulled from an issue's title or
    body, is shaped like a file or glob this lane could touch -- rather than
    an inline code identifier, a shell command, or a state word this
    repository's own issues quote constantly (`` `could-not-tell` ``,
    `` `resolved-to-nothing` ``). Cheap and deliberately conservative: a
    false negative here just means one candidate path is missed (the issue
    may still be found through a different backtick span, or not at all,
    which is `_derive_declared_files`'s own "could not be derived" state,
    never silently wrong); a false positive would hand `resolve_lane` a
    string that looks like a path and isn't, reported as `refused` or as a
    `literal` that matches nothing -- reachable, not something this filter
    needs to prevent outright.
    """
    if not token:
        return False
    token = token.strip()
    if not token or any(ch.isspace() for ch in token):
        return False
    if len(token) > 200:
        return False
    # A bare word with neither a path separator nor a dot is virtually never
    # a file this repository tracks (`could-not-tell`, `available`, `main`)
    # -- excluding it is what keeps this option (1) "cheap" rather than
    # "matches every backtick span on the board".
    if "/" not in token and "." not in token:
        return False
    return True


def _derive_declared_files(repo, title, body):
    """Every repo-relative path or glob named literally, in backticks, in one
    issue's `title` and `body` (#851, option 1 of the three the issue itself
    weighs).

    **Why option 1 over the other two, for this repository specifically.**
    The issue's own options were (1) literal paths named in the body -- cheap,
    but "most issues do not name any" on a generic tracker; (2) a grep/
    identifier pass over the title and body mapped to files -- broader, and
    needs its own noise-shaped third state; (3) a declared-files convention on
    the issue itself -- sound, but only for issues filed after the convention
    exists. Option 1's stated weakness does not hold on *this* tracker: #798's
    own measurement is that 98% of this repository's issues are filed by this
    loop, and every filed-by-loop issue this codebase's own CLAUDE.md
    documents (#851's own body among them) already cites the exact files it is
    about in backticks -- because the loop that files them reads the code
    before writing the issue. Option 1 is cheap *and* dense here, which is the
    combination the issue asks for rather than a compromise. Option 2 was
    weighed and declined: broader coverage buys little on a tracker where the
    narrow reading already finds the paths that matter, at the cost of a
    second, noisier "matched nothing" state on top of this one. Option 3 was
    declined for the reason the issue itself gives -- it cannot reach a single
    issue filed before today, which is most of the open board on the day this
    ships.

    Returns `None` when the title and body together named nothing that
    survives `_looks_like_a_declared_path` and `_lane_pattern_problem` --
    the issue's own "could not be derived" case, which a caller must never
    read as an empty, checked lane (the same distinction
    `_lane_resolved_to_nothing` draws one level down, for a lane that WAS
    checked and matched nothing). Otherwise returns `resolve_lane`'s own
    result over the surviving candidates -- the identical pipeline a
    `--lane` value goes through, so a declared path that is a directory or a
    glob expands exactly the same way here as it would on the command line.
    """
    text = "{0}\n{1}".format(title or "", body or "")
    candidates = []
    seen = set()
    for match in _BACKTICK_SPAN_RE.finditer(text):
        token = match.group(1).strip()
        if not _looks_like_a_declared_path(token):
            continue
        if select_issues_overlap._lane_pattern_problem(token) is not None:
            continue
        if token in seen:
            continue
        seen.add(token)
        candidates.append(token)
    if not candidates:
        return None
    return select_issues_overlap.resolve_lane(repo, candidates)


def suggest_companions(repo, own_issue, claimed_files, board):
    """The lane-bundling sweep #851 asks for: given a lane's own issue
    number and the files it already claims (`resolve_lane(...)["files"]` for
    whatever `--lane` patterns it was dispatched with), read an open board
    handed in as `board` and answer, in three states, which OTHER open
    issues land inside the claimed set.

    `board` is `{"capped": bool, "cap_detail": str, "issues": [{"number": N,
    "title": ..., "body": ...}, ...]}` -- the shape `main` reads off stdin as
    JSON, the identical separation of concerns `select_issues_rank.py` already
    uses for the same reason: this script does not call `gh` itself, so a
    probe never depends on network access or forge credentials, and the
    caller (a tick, or a human) controls exactly what population was read.

    Three states, per this repository's own rule that a check which could
    not look must never render as a check that found nothing:

      candidates   at least one other open issue's declared files overlap
                   the claimed set -- returned with the overlapping paths,
                   so a maintainer can see *why* each one lands inside the
                   lane rather than taking the verdict on faith.
      none         the board was read in full (not capped), every other
                   issue's declared files were derived successfully, and
                   none of them overlaps the claimed set. This is the only
                   state that means "swept, confirmed clear".
      could-not-tell   either the board read itself was capped (#593's
                   `per=` ceiling -- more issues may exist outside the
                   population this call ever saw), or at least one other
                   issue's declared files could not be derived. That second
                   case has two distinct causes and `undetermined` names
                   which one applies per issue rather than sharing one
                   sentence: the title and body named nothing path-shaped at
                   all (`_derive_declared_files` returned `None`), or they
                   named something and it could not be READ -- a declared
                   path under an unreadable ancestor, which `resolve_lane`
                   reports as a `refused` pattern with an empty `files` list
                   (`_refused_patterns`, #774). The second one was found by
                   this lane's own auditor and is the sharper of the two: it
                   returns a non-`None` result, so a version of this function
                   checking only for `None` let it fall through
                   `lane_overlap(claimed, [])` and vanish from both lists.
                   Neither is folded into `none`: an issue this sweep could
                   not read a file set for might still belong in the lane,
                   and reporting `none` over an unread population is the
                   exact false negative #851 exists to stop -- the same
                   reasoning `_lane_resolved_to_nothing` already applies to a
                   single lane one level down.

    `undetermined` is a list of `{"number": N, "why": "..."}`, reported in
    the `could-not-tell` detail AND on a `candidates` line, never silently
    dropped -- an absence produced by this tool's own extraction or read
    limits must read as "not read", not as "read and clear". An issue that
    IS a candidate is not also listed there: an overlap found is a positive
    fact about it, and it is going to be looked at anyway.

    `claimed_files` being empty is a caller error this function cannot
    distinguish from a real answer, and it is refused at the CLI boundary
    rather than here: every issue's overlap against the empty set is empty,
    so an empty claimed set produces a confident `none` about a lane nobody
    named -- found by this lane's own reviewer, and the same shape #788
    already refuses for a fileless `--claim`. A library caller passing `[]`
    gets that `none`; `main` will not let a command line produce it.
    """
    own_issue = int(own_issue)
    claimed = sorted(set(claimed_files))
    if board.get("capped"):
        return {
            "state": "could-not-tell",
            "candidates": [],
            "undetermined": [],
            "detail": "the board read was capped ({0}) -- more open issues may "
            "exist outside the population this sweep saw (#593's per= "
            "ceiling)".format(board.get("cap_detail") or "no detail given"),
        }
    issues = board.get("issues") or []
    candidates = []
    undetermined = []
    for item in issues:
        number = item.get("number")
        if number is None or int(number) == own_issue:
            continue
        resolved = _derive_declared_files(repo, item.get("title"), item.get("body"))
        if resolved is None:
            undetermined.append(
                {
                    "number": number,
                    "why": "title and body named no repo-relative path in backticks",
                }
            )
            continue
        overlap = select_issues_overlap.lane_overlap(claimed, resolved["files"])
        if overlap:
            candidates.append({"number": number, "files": overlap})
            continue
        # Found by this lane's own auditor: a candidate token CAN survive the
        # static filter and then fail to resolve against disk -- a
        # `PermissionError` on an unreadable ancestor, which `resolve_lane`
        # reports as a `refused` pattern with an empty `files` list, exactly
        # the state `_refused_patterns` (#774) already exists to separate from
        # a checked `glob-no-match`. `_derive_declared_files` returns non-None
        # for that, so routing only a bare `None` into `undetermined` let this
        # issue fall through `lane_overlap(claimed, []) -> []` and vanish from
        # both lists -- a declaration nothing could read, rendering as a
        # declaration read and found clear. That is the fold this whole
        # function's docstring promises not to make, one layer below where it
        # was being checked.
        refused = lane_setup_patterns._refused_patterns(resolved)
        if refused:
            undetermined.append(
                {
                    "number": number,
                    "why": "declared path(s) could not be read: {0}".format(
                        ", ".join(refused)
                    ),
                }
            )
    if candidates:
        return {
            "state": "candidates",
            "candidates": candidates,
            "undetermined": undetermined,
            "detail": "",
        }
    if undetermined:
        return {
            "state": "could-not-tell",
            "candidates": [],
            "undetermined": undetermined,
            "detail": "{0} of {1} other open issue(s) could not have a file set "
            "derived, so the absence of a candidate among them is not a "
            "swept-clear reading: {2}".format(
                len(undetermined),
                len(issues),
                "; ".join(
                    "#{0} ({1})".format(entry["number"], entry["why"])
                    for entry in undetermined
                ),
            ),
        }
    return {
        "state": "none",
        "candidates": [],
        "undetermined": [],
        "detail": "board read in full ({0} other open issue(s)), every one's "
        "declared files resolved, none lands inside the claimed set".format(
            len(issues)
        ),
    }


# #432: a lane's local test command narrows to the files a brief names, and CI then
# reddens on a guard test whose own filename has no visible relationship to the
# diff -- measured on PR #431, where a diff that started calling the changelog
# scaffolding gate's producer function (in `scripts/oss_config.py`) was invisible
# to a narrowed run naming three doctor-shaped test files, and CI failed on
# `tests/test_gate_state_consumers_328.py` instead. Five guard tests answer to
# *what a diff does* rather than to a module it renames -- enumerated here by
# reading each one's own docstring for its trigger, not by trusting the issue's
# own list, which is #335's own sentence about how this seam got here in the
# first place. A guard list is a fact about the repository, so it lives beside
# `resolve_lane` rather than being re-typed into every brief.
#
# Each entry is (path prefix a resolved lane file must start with or equal, the
# guard test file, one-line why). A file can trip more than one guard for
# different reasons -- `scripts/oss_config.py` is both an ordinary script under
# `scripts/` (test_unwired_scripts_253) and the one file that can register a new
# consumer of that gate's state (test_gate_state_consumers_328).
#
# Deliberately not naming the gate producer's function identifier by its exact
# spelling anywhere in this module: `tests/test_gate_state_consumers_328.py`
# scans every file under `scripts/` for a bare occurrence of that name and
# demands it be a *registered* consumer, and this file names it only to describe
# the guard, never to call it -- the same bug this issue is about, one level up,
# caught by writing the fix and running the guard it documents.
