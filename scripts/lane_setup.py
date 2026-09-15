#!/usr/bin/env python3
"""One call for the facts a lane brief hand-carries and that rot before it is read.

#317: every developer brief pastes a base commit and a live-worktree list, both taken
minutes before the brief is written and stale by the time it is read -- `main` has moved
twice within an hour, and a hand-copied worktree list has already flattened `cannot tell`
to `idle` at least once. This script re-derives those facts at the moment they are
needed, mechanically, instead of asking the maintainer to retype a snapshot.

**Not folded in here: the issue itself.** `supertool gh-issue:N:full` already reads it
live at call time, so it does not carry the same staleness defect this script exists to
close, and its size varies from a one-line issue to several thousand characters --
folding it in unconditionally would blow the byte budget below on the same run that
this script was written for (#317's own body ran past 5KB). The granularity call is
made here on purpose, following the issue's own "Not claimed" section: this script owns
the base commit, the branch/worktree derivation, and the worktree board -- the three
facts the issue's own examples are about -- and leaves the issue read as its own call.

Byte budget (#317, measured 2026-08-19): setup-shaped calls among a developer's first
ten average 2 and return a median of 3,904 characters. This script's job is to answer in
*fewer* bytes than the calls it replaces, not merely in fewer calls -- so the worktree
board below is condensed to one line per tree (state, branch, path, merge/dirty bracket)
rather than the full explanatory op output, which runs past 9,000 characters for a
seven-tree board and would be a net loss on its own.

Three states everywhere, never two, because this is the repository that is named after
collapsing them by accident:

  base       resolved (fetched and rev-parsed), resolved-stale (fetched failed, a local
             remote-tracking ref answered anyway -- flagged, never silent),
             resolved-remote (a --stack-on base found only as a remote-tracking
             ref of the branch being stacked on -- #1006, flagged the same way),
             or could-not-resolve (nothing answered; nothing to brief a lane from).
  branch     resolved (derived from `branch_pattern`) or unknown (no `{issue}`
             placeholder in the pattern -- every issue would get the same branch).
  worktree   resolved, unknown (`worktree_root` could not be derived at all --
             #608 made this the rare case: `oss_config.load` now derives
             `worktree_root` from the repository root whenever `.oss.local.json`
             is absent or missing the key, so `unknown` fires only when even
             that derivation fails), or invalid (the derived path escapes the
             configured root). `resolved` carries its own `origin`
             (`configured` -- read from `.oss.local.json` -- or `derived, not
             configured` -- guessed from the repository root) so a value someone
             chose and a value this script guessed never render the same way.
  occupancy  a separate three-state beside the one above, for whether anything
             already sits at the derived path: already exists, free, or unknown
             when the path could not be looked at. #373: it used `os.path.exists`,
             which swallows `OSError`, so an unreadable parent printed `free` and
             the third state was reachable only for an empty path.
  board      ok (condensed from `supertool git-worktrees`) or could-not-run (supertool
             is not on PATH, or the call itself failed) -- never silently empty.
             #1532: this is the single source of truth about which lanes are
             live. The local lane registry that used to sit beside it was a
             second, staler copy of the same fact and is retired.
  assignee   claimed (this call passed --claim and every requested assignee
             write went through), already-claimed (somebody else holds one --
             nothing written), or could-not-claim-assignee (the read/write
             itself did not complete, which is not the same fact and is never
             folded into it).

`git rev-parse` on a full ref, never abbreviated: a short sha returns `[]` from
`gh run list --commit` and exits 0, which has cost this loop a round already
(CLAUDE.md, skills/manager/phases/release.md).

**`--suggest-companions` (#851) is a separate mode from everything else in this
docstring** -- it answers "which other open issues belong in this lane", not
"what are this lane's own setup facts", and it takes the open board on stdin
as JSON rather than deriving anything from git or the local worktree, the
same separation of concerns `select_issues.py` uses for its own `--board`
mode. See `select_issues_companions.suggest_companions`'s own docstring for
its three states (candidates / none / could-not-tell) and
`select_issues_companions._derive_declared_files`'s for which of the issue's
own three options this implements and why.

## Two entry points, split into submodules (#1069)

This file crossed 3,600 lines and took `doctor.py`'s own medicine: it is the
entry point now, and every function it used to define outright lives in one
of `lane_setup_worktree.py` (the base commit, branch, worktree path and
their occupancy checks), `lane_setup_patterns.py` (cross-cutting guard
lookup, and the lane report a brief reads), `lane_setup_claim.py`
(the GitHub assignee -- claiming an issue and releasing it again; #1532
retired the lane registry and held-set derivation that lived there too)
or `lane_setup_brief_schema.py` (whether the composed prompt carries the two
per-lane facts and no leftover template marker, checked before `--claim`
renders an `Agent(...)` line -- #1143, #1535). Every name is imported here and re-exported at module level,
so `lane_setup.<name>` keeps working for every existing caller.
`resolve_lane`/`lane_overlap` and `suggest_companions` moved to
`select_issues_overlap.py`/`select_issues_companions.py` instead --
`select_issues.py`'s own submodules, not this file's, per that module's
docstring.

## The fleet-view label and the Agent(...) call live here now (#1143)

`lane_setup_label.py` (`fleet_label`, `agent_call`) is deleted; both
functions are defined directly below, in this file, rather than in a fourth
submodule. Nothing else in this loop ever calls them except `--claim` and
`--label`, both of which live in this file's own `main`, so a fifth
`import`/re-export pair would have bought no separation the other three
submodules buy (each of those is reused from more than one call site, or
tested against a real filesystem/subprocess fixture large enough to be worth
isolating).

`--claim` now composes the fleet label -- and, given a subagent type, the
whole `Agent(...)` call -- from the issues that call **actually holds**
afterward (`_claimed_issue_numbers`, reading `claim_result`'s own per-issue
rows), never from the issues requested (`issue` plus `--claim-also`). A
companion whose assignee write came back `could-not-claim-assignee` or
`already-claimed` is silently excluded from the count: deriving the
multiplier from the request instead would replace a retype with a confident
wrong number, worse than the retype it replaces. `--label` is unchanged and
stays the path for a lane composed some other way -- it still takes its
issue list as an explicit argument, never derived from a claim.

`compose_claim_label` is the one function both call sites route through.
Given a subagent type it also **composes the prompt** (#1535) -- `lane_prompt`'s
two facts, plus whatever `--brief` names, appended -- and runs
`lane_setup_brief_schema.check_text` over the whole composed string before the
`Agent(...)` line is rendered. All three elements are structural now, so any
finding refuses the render; there is no presence-only tier left to print and
carry on from. A schema pass is still not a review: it says the two facts are
there and no template marker survived, never that dispatching this lane is a
good idea.

## Claiming an issue, in one call (#1069, #1532)

Claiming used to be two scripts and two calls: `issue_claim.py --claim`
wrote the GitHub assignee, and this file's own `--claim --lane` registered
the lane, with nothing rolling the first back when the second failed and
nothing releasing the assignee when a lane ended. #1069 folded them into one
call; #1532 then retired the registry half, because #1528 stopped a held-set
collision dropping a candidate and left a record nothing read for a decision.

So `--claim` writes the GitHub assignee for the positional issue and every
`--claim-also` issue, via `lane_setup_claim.claim_issues`, in three states --
`claimed` / `already-claimed` / `could-not-claim-assignee`. `--release` is
the mirror, via `lane_setup_claim.release_assignees`. There is no second
write to fail, so the rollback states #1069 needed (`could-not-register`,
`assignee-rolled-back`, `rollback-failed-assignee-still-set`) are gone with
it.

## --claim also renders step 5's own token now (#1148)

`docs/pick-the-work.md` step 5 (`oss_state.py --decision ... --lane-fill
PRIMARY:COUNT[:REASON]`) used to be typed by hand -- both `COUNT` and
`REASON` already existed upstream, `COUNT` in this file's own claim result
and `REASON` on whatever named the group short, and a human retyped them
into agreement at the tick's own `--decision` call. `compose_lane_fill` (and
`--claim`'s own `--short-reason`/`--group-state` flags) closes that the same
way #1143 already closed it for the fleet-view label: `COUNT` comes from
`_claimed_issue_numbers`, never from the issue and `--claim-also` values
requested. `REASON` used to require a human to translate the group's own
free-text explanation into the closed vocabulary by hand; `--group-state`
(#1153) does that translation mechanically for three of the four group
`state` values, taking `select_issues.py`'s own `state` field unchanged
rather than a retyped word, and `--short-reason` remains an explicit
override for the fourth state and for a lane composed some other way.
Never invented when neither is given -- a short lane with no derivable and
no explicit reason renders a token with no reason at all, so
`oss_state.py --decision`'s own refusal (#852) still fires on it downstream.

Python 3.9 compatible: no match statements, no `X | Y` annotations.
"""

import argparse
import json
import os  # noqa: F401 (re-exported as lane_setup.os for existing monkeypatch-based tests -- see the module docstring)
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor  # noqa: E402  (path insert above must run first)
import gh_which  # noqa: E402  (path insert above must run first)
import lane_setup_brief_schema  # noqa: E402  (path insert above must run first)
import lane_setup_claim  # noqa: E402
import lane_setup_patterns  # noqa: E402
import lane_setup_worktree  # noqa: E402
import oss_config  # noqa: E402
import select_issues_claim_read  # noqa: E402
import select_issues_companions  # noqa: E402
import select_issues_overlap  # noqa: E402
import select_issues_rank  # noqa: E402

# Re-exported at module level so `lane_setup.<name>` keeps working for every
# existing caller and test -- only the *definition* moved (#1069). See the
# module docstring's "Two entry points, split into submodules" section.
from lane_setup_claim import (  # noqa: E402,F401
    CLAIM_STATE_ALREADY_CLAIMED,
    CLAIM_STATE_ALREADY_MINE,
    CLAIM_STATE_CLAIMED,
    CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE,
    claim_issues,
    release_assignees,
)
from lane_setup_patterns import (  # noqa: E402,F401
    _refused_patterns,
    guards_for_files,
    known_guards,
    lane_report,
)
from lane_setup_worktree import (  # noqa: E402,F401
    WORKTREE_COULD_NOT_TELL,
    WORKTREE_LINKED,
    WORKTREE_MAIN,
    _absence_confirmed,
    _git,
    _one_line,
    branch_occupancy,
    derive_worktree,
    remote_problem,
    resolve_base,
    resolve_stacked_base,
    worktree_last_activity,
    worktree_occupancy,
)
from select_issues_overlap import (  # noqa: E402,F401
    _expand_directory,
    _lane_pattern_problem,
    _split_lane_value,
    lane_overlap,
    resolve_lane,
)
from select_issues_companions import (  # noqa: E402,F401
    _derive_declared_files,
    suggest_companions,
)

# `derive_branch` and `_split_lane_value`/`_expand_directory`/etc. are
# available as `lane_setup_worktree.derive_branch` /
# `select_issues_overlap.<name>` for a caller that wants the module-qualified
# form; the flat names above are only the ones an existing test or caller
# already referenced as `lane_setup.<name>` (see the grep this split was
# built from).


class FleetLabelError(ValueError):
    """The label cannot be composed from what was given."""


def fleet_label(primary_issue, issues, phrase):
    """Render ``Lane <primary> [x<N>]  <phrase>`` for one dispatched lane (#539).

    ``primary_issue`` is the issue that named the branch and the worktree.
    ``issues`` is every issue this lane carries, primary included -- never inferred
    from ``primary_issue`` alone, because the whole failure this function exists to
    close is a label that named only the first issue. ``phrase`` is the short
    description of what the lane is doing.

    Folded in from the now-deleted ``lane_setup_label.py`` (#1143) -- see this
    module's own "The fleet-view label and the Agent(...) call live here now"
    section above for why it is not a fifth submodule.
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


def lane_prompt(issues, worktree):
    """The whole spawn payload for a developer lane: the issue numbers and the
    worktree, and nothing else (#1535).

    Everything else a lane was briefed with -- supertool, the TDD order, the
    publishing clause, pushback, untrusted input -- is in `agents/developer.md`,
    which is that lane's system prompt and is re-sent on every turn. Restating
    it per lane cost ~7,900 B per spawn and told the reader nothing it was not
    already holding.

    An underivable worktree is **named as underivable**, never omitted: a prompt
    that simply does not mention a worktree reads exactly like one for a lane
    that is meant to cut its own, and two lanes cutting their own is how two
    agents end up in the same files.
    """
    numbers = sorted(issues)
    if not numbers:
        raise FleetLabelError(
            "lane_prompt: no issues -- a lane with nothing to work on is not a "
            "lane, and composing a prompt around an empty bundle would dispatch "
            "one. `compose_claim_label` returns `no-claimed-issues` before "
            "reaching here; this is the refusal for any other caller (#1535)"
        )
    if len(numbers) == 1:
        head = "Issue {0}.".format(numbers[0])
    else:
        head = "Issues {0} and {1}.".format(
            ", ".join(str(n) for n in numbers[:-1]), numbers[-1]
        )
    if not worktree:
        return "{0} Your worktree could not be derived -- say so and stop.".format(head)
    return "{0} Your worktree is {1}.".format(head, worktree)


def agent_call(
    primary_issue,
    issues,
    phrase,
    subagent_type,
    model=None,
    run_in_background=False,
    prompt=None,
):
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

    ``prompt``, when given, is rendered into the call verbatim (#1535) -- for a
    developer lane that is `lane_prompt`'s two facts and nothing else. Without
    one the call still carries the ``<brief>`` placeholder, for a caller
    dispatching an agent whose own definition does not carry its instructions.
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
    parts.append(
        'prompt: "{}"'.format(_quote_for_call(prompt))
        if prompt
        else 'prompt: "<brief>"'
    )

    return "Agent({})".format(", ".join(parts))


#: Per-issue assignee states that mean "this issue is genuinely held by us
#: right now", used by `_claimed_issue_numbers` below. Never `STATE_ALREADY_
#: CLAIMED` or `STATE_COULD_NOT_CLAIM` -- those two are exactly the failures
#: #1143 exists to keep out of a rendered label's count.
_HELD_ASSIGNEE_STATES = (
    select_issues_claim_read.STATE_CLAIMED,
    select_issues_claim_read.STATE_ALREADY_MINE,
)


def _claimed_issue_numbers(claim_result):
    """Which issues a ``--claim`` call actually holds afterward, read from the
    checker's own per-issue rows -- never from what was requested (#1143).

    A lane whose third issue came back ``could-not-claim-assignee`` carries
    two, and a label composed from it must say ``x2``, never ``x3``: deriving
    the count from the request instead would replace a retype with a
    confident wrong number, worse than the retype it replaces. Each row in
    ``claim_result["assignee"]["rows"]`` is a real, independent write attempt
    (`select_issues_claim_read.check` writes for every issue named,
    regardless of whether another issue in the same batch failed), so a row
    can genuinely say ``claimed`` even when `claim_issues`' own overall
    ``state`` is a failure -- that dangling write is still real and still
    counts here.

    #1532 removed the one exception to that. A ``claimed`` row used to not
    count when `claim_and_register` had rolled the assignee back because the
    lane's own registry write failed (``assignee-rolled-back`` /
    ``rollback-failed-assignee-still-set``). There is no registry and no
    second write to fail, so there is no rollback and every ``claimed`` row
    is simply held.
    """
    if not claim_result:
        return []
    assignee = claim_result.get("assignee") or {}
    rows = assignee.get("rows") or []

    held = []
    for row in rows:
        state = row.get("state")
        if state not in _HELD_ASSIGNEE_STATES:
            continue
        held.append(row.get("issue"))
    return held


def compose_claim_label(
    payload,
    phrase,
    subagent_type=None,
    model=None,
    run_in_background=False,
    brief_path=None,
    worktree=None,
):
    """Render this ``--claim`` call's own fleet-view label -- or, with
    ``subagent_type``, the whole ``Agent(...)`` call -- from the issues this
    lane actually holds (#1143), never from the issues requested.

    ``payload`` is `compute`'s own return value (or anything carrying its
    ``issue`` and ``claim_result`` keys). Returns a dict always carrying
    ``state``, ``text`` (``None`` unless ``state`` is ``rendered``), ``held``
    (the issue numbers this call derived) and ``brief`` (the raw
    `lane_setup_brief_schema` payload, or ``None`` when ``subagent_type`` was
    never given -- a caller must never have to guess whether the prompt was
    skipped or genuinely clean).

    **The prompt is composed here, not by the caller (#1535).** `lane_prompt`
    renders the two facts a lane cannot read anywhere else -- the issues this
    claim actually holds and ``worktree`` -- and nothing else; everything a
    brief used to restate is in `agents/developer.md`, re-sent on every turn.
    ``brief_path``, when given, is optional extra per-lane context (a recon
    summary, say) appended to that prompt, never a substitute for it.

    States:

      rendered                 ``text`` carries the label or the call.
      no-claimed-issues        nothing in ``claim_result`` came back
                                genuinely held.
      primary-not-held         ``payload["issue"]`` itself is not among the
                                issues actually held -- a label cannot be
                                composed around a lane that does not include
                                its own primary issue.
      fleet-label-error        `fleet_label`/`agent_call` itself refused (a
                                duplicate, a blank phrase, ...); ``detail``
                                carries the message.
      brief-could-not-read     only reachable with ``subagent_type`` and
                                ``brief_path`` given: the extra context file
                                could not be read. Never folded into a
                                findings row -- "this prompt is missing the
                                worktree" and "nobody read that file" are
                                different facts.
      brief-structural-finding only reachable with ``subagent_type`` given:
                                the composed prompt fails at least one of
                                `lane_setup_brief_schema`'s three structural
                                elements -- the ``Agent(...)`` line is
                                refused, never rendered.
    """
    held = _claimed_issue_numbers(payload.get("claim_result"))
    result = {"state": None, "text": None, "held": held, "brief": None}

    if not held:
        result["state"] = "no-claimed-issues"
        return result
    if payload.get("issue") not in held:
        result["state"] = "primary-not-held"
        return result

    prompt = None
    if subagent_type is not None:
        prompt = lane_prompt(held, worktree)
        if brief_path is not None:
            try:
                extra = Path(brief_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                result["brief"] = {
                    "state": lane_setup_brief_schema.STATE_COULD_NOT_READ,
                    "path": str(brief_path),
                    "detail": "{0}: {1}".format(brief_path, exc),
                    "elements": [],
                    "missing": [],
                }
                result["state"] = "brief-could-not-read"
                return result
            prompt = prompt + "\n\n" + extra.strip()
        # A caller reaching here always ATTEMPTED the derivation, so a falsy
        # `worktree` is a failed one, never "not asked" -- the schema needs
        # that told to it or it guesses from the text, and an appended recon
        # summary is full of path-shaped tokens (#1535 self-review).
        brief_payload = lane_setup_brief_schema.check_text(
            prompt,
            issues=held,
            worktree=worktree,
            worktree_state=(
                None if worktree else lane_setup_brief_schema.WORKTREE_COULD_NOT_DERIVE
            ),
        )
        result["brief"] = brief_payload
        structural_missing = any(
            row["state"] == "missing"
            and row["checked"] == lane_setup_brief_schema.STRUCTURAL
            for row in brief_payload["elements"]
        )
        if structural_missing:
            result["state"] = "brief-structural-finding"
            return result

    try:
        if subagent_type is None:
            text = fleet_label(payload["issue"], held, phrase)
        else:
            text = agent_call(
                payload["issue"],
                held,
                phrase,
                subagent_type,
                model=model,
                run_in_background=run_in_background,
                prompt=prompt,
            )
    except FleetLabelError as exc:
        result["state"] = "fleet-label-error"
        result["detail"] = str(exc)
        return result

    result["state"] = "rendered"
    result["text"] = text
    return result


#: #1153: the four values `select_issues.py`'s own per-group `state` field
#: takes -- `"candidates"`/`"none"`/`"could-not-tell"` from
#: `select_issues_companions.suggest_companions`'s own three-value return,
#: and `"lane-other"` set directly by `select_issues.py` for a solo #1130
#: dispatch. #1199 closed the gap #1153 left open: this used to be a
#: second, independently-typed copy of the vocabulary, with no test tying
#: it back to the producer. `select_issues_companions.GROUP_STATES` is now
#: that single source -- imported here rather than retyped, and rather
#: than imported from `select_issues.py` itself, because `select_issues.py`
#: imports THIS file (`lane_setup`), so the reverse import would make the
#: two modules circular. `select_issues_companions` is already imported
#: below regardless, for `suggest_companions`.
_GROUP_STATES = select_issues_companions.GROUP_STATES

#: Three of the four `_GROUP_STATES` translate onto
#: `select_issues_rank.SHORT_REASONS` without guessing -- `"none"` and
#: `"could-not-tell"` are literally what those two reasons already mean
#: (#918: `no-adjacent` is "measured and found nothing adjacent",
#: `could-not-tell` is "attempted and failed"), and `"lane-other"` never
#: calls the board sweep at all (#1130), which is #918's own definition of
#: `did-not-search`: "a computation nobody started". `"candidates"` (some
#: companions found, group still short) is deliberately absent:
#: `board-exhausted` is a claim about the WHOLE board's remaining disjoint
#: candidate count (#871), which a single group's own `state` never
#: establishes, so translating it would invent a reason nobody measured.
_GROUP_STATE_SHORT_REASONS = {
    select_issues_companions.STATE_NONE: "no-adjacent",
    select_issues_companions.STATE_COULD_NOT_TELL: "could-not-tell",
    select_issues_companions.STATE_LANE_OTHER: "did-not-search",
}
assert set(_GROUP_STATE_SHORT_REASONS) <= set(
    _GROUP_STATES
)  # #1153: one vocabulary, checked


def group_short_reason(group_state):
    """Translate a `select_issues.py` group's own ``state`` field into
    ``select_issues_rank.SHORT_REASONS``'s closed vocabulary (#1153), or
    ``None`` when there is no safe translation -- never a guess. See
    ``_GROUP_STATE_SHORT_REASONS`` for which three of the four states
    translate and why the fourth deliberately does not.
    """
    if group_state is None:
        return None
    return _GROUP_STATE_SHORT_REASONS.get(group_state)


def compose_lane_fill(payload, short_reason=None, group_state=None):
    """Render step 5's ready ``--lane-fill PRIMARY:COUNT[:REASON]`` token
    from this ``--claim`` call's own held issues (#1148) -- so nothing is
    retyped by hand at ``oss_state.py --decision`` time the way it is today
    (`docs/pick-the-work.md` step 5 is paste only, and this is what makes
    that true for the fill token the same way #1143 already made it true
    for the fleet-view label).

    ``COUNT`` comes from `_claimed_issue_numbers`, the exact derivation
    `compose_claim_label` already uses for the label's own ``xN`` -- never
    from the issue and ``--claim-also`` values requested: a companion whose
    assignee write failed is silently excluded from the count.

    ``short_reason`` is carried through from whatever named the group short
    -- typed by the caller at this call site as an explicit override. When
    it is omitted, ``group_state`` -- ``select_issues.py``'s own group
    ``state`` field, unchanged -- is translated through `group_short_reason`
    instead (#1153), so the closed-vocabulary word is derived mechanically
    for three of the four states rather than retyped by a human reading the
    group's free-text explanation. An explicit ``short_reason`` always wins
    over ``group_state`` when both are given.

    **Never guessed at when omitted.** A short lane (fewer than
    ``select_issues_rank.MAX_LANE`` issues held) whose caller gave no
    ``short_reason`` renders a token carrying ``PRIMARY:COUNT`` and nothing
    more -- never one with a reason invented to make the call look complete.
    ``oss_state.py --decision``'s own refusal (#852) fires on exactly that
    token once it is pasted into step 5's call: quietly supplying a reason
    nobody established would convert that guard into a rubber stamp, worse
    than the retype this closes.

    A full lane (``select_issues_rank.MAX_LANE`` issues held) never carries a
    reason on its token, whatever ``short_reason`` was given -- a full lane
    makes no short-lane claim for a reason to be about, and ``oss_state.py``'s
    own ``lane_fill()`` refuses an entry that pairs a reason with a full lane
    anyway (a different, unrelated refusal from #852's), so it is dropped
    here rather than passed through to trip that one instead.

    States, the same shape `compose_claim_label` already uses for its own
    early exits:

      rendered           ``text`` carries ``PRIMARY:COUNT[:REASON]``.
      no-claimed-issues  nothing in ``claim_result`` came back genuinely
                          held -- there is no fill to record for a lane that
                          claimed nothing.
      primary-not-held   the primary issue itself is not among the issues
                          held.
    """
    held = _claimed_issue_numbers(payload.get("claim_result"))
    result = {"state": None, "text": None, "held": held}

    if not held:
        result["state"] = "no-claimed-issues"
        return result
    primary = payload.get("issue")
    if primary not in held:
        result["state"] = "primary-not-held"
        return result

    count = len(held)
    reason = (
        short_reason if short_reason is not None else group_short_reason(group_state)
    )
    if count < select_issues_rank.MAX_LANE and reason:
        text = "{0}:{1}:{2}".format(primary, count, reason)
    else:
        text = "{0}:{1}".format(primary, count)

    result["state"] = "rendered"
    result["text"] = text
    return result


CONFIG_NAME = ".oss.json"

EXIT_OK = 0
EXIT_COULD_NOT_RUN = 3


_DROP_PREFIXES = ("---", "PASS", "FAIL", "[exit")


def _condense_board(raw):
    kept = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith(_DROP_PREFIXES):
            continue
        if line[:1].isspace():
            continue
        kept.append(_one_line(line, 240))
    return kept


def read_board(repo):
    """The live worktree board, condensed. `could-not-run` is a state, not a crash.

    #1409: `doctor.supertool_invocation(repo)` is consulted first -- inside a
    worktree of a supertool checkout, the bare `supertool` name on PATH
    resolves to whatever clone the SessionStart hook last linked (ordinarily
    supertool's own live checkout at `master`) and runs master's core against
    *this* worktree's own branch-local presets, refusing a write-class op
    outright (claude-supertool#1942). Everywhere else this is unchanged --
    the bare name, found via `gh_which.safe_which`.
    """
    argv_prefix, _detail = doctor.supertool_invocation(repo)
    if argv_prefix == ["supertool"]:
        # #1157: `gh_which.safe_which`, not `shutil.which` directly -- see that
        # module's docstring for why a `path=` argument does not close the gap.
        supertool = gh_which.safe_which("supertool")
        if supertool is None:
            return {
                "state": "could-not-run",
                "lines": [],
                "detail": "supertool is not on PATH",
            }
        argv = [supertool, "git-worktrees"]
    else:
        argv = argv_prefix + ["git-worktrees"]
    try:
        done = subprocess.run(
            argv,
            cwd=str(repo),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {
            "state": "could-not-run",
            "lines": [],
            "detail": "{0}: {1}".format(type(exc).__name__, exc),
        }
    # A nonzero exit is a real op failure -- an unavailable op, a crash -- and it is
    # not enough to check the header text alone: an error message that names the op
    # (as this plugin's own error text does, "op 'git-worktrees' is unavailable
    # here...") still contains the substring "git-worktrees" and would otherwise read
    # as a successful, well-formed, one-line board. `git-worktrees` with no PATH
    # argument always exits 0 on success (its own text says so), so a nonzero return
    # here is never a tree's occupancy code -- it is the call itself failing.
    if done.returncode != 0 or "git-worktrees" not in done.stdout:
        return {
            "state": "could-not-run",
            "lines": [],
            "detail": _one_line(
                "exit {0}: {1}".format(
                    done.returncode, done.stderr or done.stdout or "empty output"
                ),
                300,
            ),
        }
    return {"state": "ok", "lines": _condense_board(done.stdout), "detail": ""}


def compute(
    repo,
    issue,
    remote="origin",
    lane_patterns=None,
    claim=False,
    stack_on=None,
    also_claim=None,
    claim_checker=None,
    activity=False,
):
    """Everything a lane brief needs, in one payload. `config.state` gates the exit.

    `stack_on` (#1006): when given, `base` is resolved from that branch's own
    tip (`resolve_stacked_base`) instead of from `default_branch` -- the third
    candidate fix in #1006, taken because it needs no change to the
    `git-worktrees` op itself and so needs no upstream filing to land. A
    stacked branch never touches the worktree `stack_on` might be checked out
    in, sidestepping the `cannot tell` collision `git-worktrees` reports for a
    tree whose index was written recently, rather than trying to resolve it.

    `lane_patterns` is optional (#267): when it is not given, `payload["lane"]`
    is None -- an absent ask must not read as a checked, empty lane. When it is
    given, it is rendered through `resolve_lane` so a brief can state what its
    lane touches, and `--suggest-companions` has a claimed set to sweep the
    board against.

    **#1532 retired the against side entirely.** `--against` compared a
    candidate's declared files against a hand-typed set and `--derive-held`
    derived that set from every open pull request plus every live lane record.
    Both existed to answer "which files are already spoken for", and #1528
    stopped that answer dropping a candidate. git reports a real collision at
    merge, like everywhere else; a second answer computed hours earlier does
    not.

    `claim` (#705, #1532) is the only thing that makes this call write
    anything, and what it now writes is the GitHub assignee -- a forge-side
    fact with a real owner -- rather than a local record beside it. Default
    False: a probe writes nothing. Pass `claim=True` only at the moment this
    lane is actually being dispatched.

    `also_claim`/`claim_checker` (#1069): when `claim` is True, the assignee
    is written for `issue` AND every issue in `also_claim` (a lane's
    companion issues) via `lane_setup_claim.claim_issues` -- see that
    function's own docstring for the full state list. `claim_checker` is
    injectable the same way `select_issues.py`'s own `select()` injects
    `checker`, so a test never needs a live `gh` session. Ignored when `claim`
    is False, the ordinary probing case.

    `activity` (#1120) is opt-in and off by default: a plain recursive mtime
    scan (`worktree_last_activity`)
    over a real worktree can be an arbitrarily large walk, and this is the
    unconditional read path every plain `lane_setup.py <issue>` call takes, so
    it is never paid unless asked for. Computed only when the worktree is
    positively confirmed to already exist (`worktree["exists"] is True`) --
    there is nothing to scan for a worktree not yet cut, and scanning a path
    this call could not even confirm exists would answer a question that was
    never asked. `payload["worktree"]["last_activity"]` is always present as a
    key, `None` when not requested or not applicable, never omitted, so a JSON
    consumer never has to guess whether the absence means "not asked" or
    "asked and found nothing".
    """
    repo = Path(repo)
    config_path = repo / CONFIG_NAME
    config, problems = oss_config.load(config_path)

    if config is None:
        return {
            "issue": issue,
            "repo": str(repo),
            "config": {"state": "could-not-run", "problems": problems},
            "base": None,
            "branch": None,
            "worktree": None,
            "board": None,
            "lane": lane_setup_patterns.lane_report(repo, lane_patterns),
        }

    if stack_on:
        base = lane_setup_worktree.resolve_stacked_base(repo, remote, stack_on)
    else:
        default_branch = config.get("default_branch")
        base = (
            lane_setup_worktree.resolve_base(repo, remote, default_branch)
            if default_branch
            else {
                "state": "could-not-resolve",
                "remote": remote,
                "ref": None,
                "sha": None,
                "detail": "no default_branch in config",
            }
        )

    branch = lane_setup_worktree.derive_branch(config.get("branch_pattern"), issue)
    if branch["state"] == "resolved":
        exists_local, exists_remote = lane_setup_worktree.branch_occupancy(
            repo, remote, branch["name"]
        )
        branch["exists_local"] = exists_local
        branch["exists_remote"] = exists_remote
    else:
        branch["exists_local"] = None
        branch["exists_remote"] = None

    # #608: which of configured / derived, not configured / could-not-derive
    # produced `worktree_root` -- computed once here, from the same `config_path`
    # `oss_config.load` above already used, so this call and that one can never
    # disagree about which file each read.
    worktree_origin = oss_config.local_key_states(config_path).get("worktree_root")
    worktree = lane_setup_worktree.derive_worktree(
        config, issue, origin=worktree_origin
    )
    worktree["exists"] = lane_setup_worktree.worktree_occupancy(worktree.get("path"))
    worktree["last_activity"] = (
        lane_setup_worktree.worktree_last_activity(worktree.get("path"))
        if activity and worktree["exists"] is True
        else None
    )

    board = read_board(repo)

    lane = lane_setup_patterns.lane_report(repo, lane_patterns)

    # #1069, #1532: claiming writes the GitHub assignee for `issue` and every
    # issue in `also_claim`. That is now the whole of what a claim does --
    # `claim_issues`' own docstring names every state. There is no local
    # record beside it any more, so there is nothing to roll back and no
    # second, staler answer to the question `git-worktrees` already answers.
    #
    # #865's linked-worktree refusal went with the registry: it existed
    # because a claim standing inside a linked worktree derives
    # `worktree_root` from THAT worktree's own path (#608) and so wrote its
    # record into a sibling registry no other lane could read. An assignee
    # write does not read `worktree_root` at all -- it is a forge call
    # against the issue number -- so it is correct from any directory, and
    # refusing it here would refuse a claim that is in fact sound.
    claim_result = None
    if claim:
        claim_result = lane_setup_claim.claim_issues(
            issue,
            also_claim=also_claim,
            repo=config.get("repo"),
            checker=claim_checker,
        )

    return {
        "issue": issue,
        "repo": str(repo),
        "config": {"state": "ok", "problems": problems},
        "base": base,
        "branch": branch,
        "worktree": worktree,
        "board": board,
        "lane": lane,
        "claim": claim,
        # #1069: None when no claim was requested. Otherwise `claim_issues`'
        # own result -- see its docstring.
        "claim_result": claim_result,
    }


def blocked(payload):
    """True when there is not enough here to cut a lane from.

    A `--claim` that was attempted and did not come back `claimed` is folded
    in here too, not only "not enough to cut a lane from": letting it exit 0
    identically to a real claim is exactly the defect this repository is
    named after -- an absence produced by the tool, read as an absence in the
    world.
    """
    if payload["config"]["state"] != "ok":
        return True
    if payload["base"]["state"] == "could-not-resolve":
        return True
    # #1069: a claim that was attempted and did NOT reach
    # `lane_setup_claim.CLAIM_STATE_CLAIMED` -- already claimed by somebody
    # else, or the assignee write itself failed -- is not a lane a caller may
    # proceed to dispatch from. The two are kept apart by `claim_result`'s own
    # state and folded together only here, where the question is the single
    # yes/no "may this be dispatched".
    claim_result = payload.get("claim_result")
    if (
        claim_result is not None
        and claim_result["state"] != lane_setup_claim.CLAIM_STATE_CLAIMED
    ):
        return True
    return False


def _row(label, value):
    return "{0:<10}: {1}".format(label, value)


#: A receipt line is one line, and nothing interpolated into it may make it two.
#: Generous rather than tight: the longest legitimate line measured here is an
#: `oss_config` problem sentence at roughly 290 characters, and truncating a real
#: sentence to close a forging hole would trade one silent loss for another.
_RECEIPT_LINE_LIMIT = 2000
_TRUNCATION_MARK = " ... [truncated]"


def _receipt_line(text):
    """One assembled receipt line, folded so nothing in it can forge another (#372).

    Applied at the single point where the receipt is joined, rather than to a list of
    fields. Four separate values were measured forging lines: `branch_pattern`, the
    `--repo` argv and `worktree_root`, which the audit reached, and an `oss_config`
    problem sentence built from a hostile JSON **key**, which it did not. That fourth
    one is why this is not a per-field guard: it needs no hostile *value* anywhere, and
    `oss_config` cannot close it at its end without refusing to name the key that is
    wrong. A guard on a list of fields closes the fields somebody enumerated and leaves
    the next field added to this function unguarded.

    Deliberately **not** `_one_line`, which is right for what it does and wrong here.
    Its `" ".join(text.split())` collapses runs of spaces, and every row in this
    receipt is aligned by `_row`'s `{0:<10}` padding -- folding the assembled line
    through it turns `repo      : x` into `repo : x` and destroys the column the whole
    receipt is read by. Only the half that matters for forging is applied: every
    character outside printable ASCII becomes `?`, which covers newline, carriage
    return and the control characters that repaint a line, and leaves spaces alone.
    `_one_line` still runs where it already ran, on `detail` and the board lines, so
    this is additive rather than a replacement.

    Truncation is marked. A cut line that renders as a complete one is this
    repository's own defect class pointed at its own receipt. `_one_line` itself is
    left alone: its callers pin their own limits and its silent truncation is theirs.
    """
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text))
    if len(safe) > _RECEIPT_LINE_LIMIT:
        keep = max(0, _RECEIPT_LINE_LIMIT - len(_TRUNCATION_MARK))
        safe = safe[:keep] + _TRUNCATION_MARK
    return safe


def _render(lines):
    """The one place a receipt becomes text, so the fold cannot be skipped by a caller."""
    return "\n".join(_receipt_line(line) for line in lines)


def receipt(payload):
    lines = ["LANE SETUP #{0}".format(payload["issue"]), _row("repo", payload["repo"])]

    if payload["config"]["state"] != "ok":
        lines.append("config    : COULD NOT RUN")
        for problem in payload["config"]["problems"] or []:
            lines.append("  - " + problem)
        return _render(lines)

    for problem in payload["config"]["problems"] or []:
        lines.append("config warn: " + problem)

    base = payload["base"]
    if base["state"] == "could-not-resolve":
        lines.append("base      : COULD NOT RESOLVE -- {0}".format(base["detail"]))
    else:
        # #1006, review round: the pre-existing `resolved-stale` wording
        # ("STALE" -- the default_branch fetch itself failed) must not
        # silently change for callers who never pass --stack-on. The new
        # `resolved-remote` state (a stacked base found only as a
        # remote-tracking ref -- #1006) gets its own, different word rather
        # than reusing or renaming that one.
        if base["state"] == "resolved":
            flag = ""
        elif base["state"] == "resolved-remote":
            flag = "  ** NOTE ** {0}".format(base["detail"])
        else:
            flag = "  ** STALE ** {0}".format(base["detail"])
        lines.append(
            _row("base", "{0} ({1}){2}".format(base["sha"], base["ref"], flag))
        )

    branch = payload["branch"]
    if branch["state"] != "resolved":
        lines.append("branch    : UNKNOWN -- {0}".format(branch["detail"]))
    else:
        occ = []
        if branch["exists_local"] is True:
            occ.append("already exists locally")
        elif branch["exists_local"] is None:
            occ.append("local existence unknown")
        if branch["exists_remote"] is True:
            occ.append("already exists on " + base["remote"])
        elif branch["exists_remote"] is None:
            occ.append("{0} existence unknown".format(base["remote"]))
        occ_text = " [{0}]".format(", ".join(occ)) if occ else ""
        lines.append(_row("branch", branch["name"] + occ_text))

    worktree = payload["worktree"]
    if worktree["state"] != "resolved":
        lines.append(
            "worktree  : {0} -- {1}".format(
                worktree["state"].upper(), worktree["detail"]
            )
        )
    else:
        exists = worktree["exists"]
        exists_text = (
            "already exists"
            if exists is True
            else "free"
            if exists is False
            else "unknown"
        )
        # #608: a `worktree_root` this call GUESSED from the repository root (no
        # .oss.local.json here, or none carrying the key) must not read the same as
        # one a maintainer configured -- the acceptance condition this issue was
        # filed with.
        origin_note = (
            " (derived, not configured)"
            if worktree.get("origin") == oss_config.LOCAL_STATE_DERIVED
            else ""
        )
        lines.append(
            _row(
                "worktree",
                "{0} [{1}]{2}".format(worktree["path"], exists_text, origin_note),
            )
        )
        activity = worktree.get("last_activity")
        if activity is not None:
            if activity["state"] == "resolved":
                age = max(0, int(time.time() - activity["mtime"]))
                lines.append("  activity: last touched {0}s ago".format(age))
            elif activity["state"] == "empty":
                lines.append("  activity: no files found yet")
            else:
                lines.append("  activity: UNKNOWN -- {0}".format(activity["detail"]))

    board = payload["board"]
    lines.append("board     :")
    if board["state"] != "ok":
        lines.append("  COULD NOT RUN -- " + board["detail"])
    else:
        for line in board["lines"]:
            lines.append("  " + line)

    # #1069, #1532: the assignee is the whole of what a claim writes, so this
    # is the whole of what a claim reports. There used to be a `lanes :` row
    # above it naming the local registry's live count and TTL, and a
    # `this lane not recorded:` line beside it; both are gone with the
    # registry. A reader must never have to infer the outcome of a write from
    # silence, so every state gets its own line here.
    claim_result = payload.get("claim_result")
    if claim_result is not None:
        if claim_result["state"] == lane_setup_claim.CLAIM_STATE_CLAIMED:
            lines.append(_row("assignee", "claimed"))
        elif claim_result["state"] == lane_setup_claim.CLAIM_STATE_ALREADY_CLAIMED:
            holders = sorted(
                {
                    holder
                    for row in claim_result["assignee"]["rows"]
                    for holder in (row.get("holders") or [])
                }
            )
            lines.append(
                _row(
                    "assignee",
                    "ALREADY CLAIMED by {0} -- nothing written".format(
                        ", ".join(holders) if holders else "somebody else"
                    ),
                )
            )
        else:
            # `could-not-claim-assignee`. Kept apart from the line above on
            # purpose: "somebody else holds this" and "nothing could read
            # whether anybody holds this" are different facts, and folding
            # the second into the first claims a reading nothing performed.
            lines.append(
                _row(
                    "assignee",
                    "COULD NOT CLAIM -- the assignee read/write itself did not "
                    "complete for at least one issue",
                )
            )

    lane = payload.get("lane")
    if lane is not None:
        lines.append("lane      :")
        for entry in lane["lane"]["patterns"] if lane["lane"] else []:
            lines.append(
                "  [lane] {0} ({1}): {2}".format(
                    entry["pattern"],
                    entry["state"],
                    ", ".join(entry["files"]) or "-",
                )
            )
        # #432: guards the lane's own files trip -- a narrowed local test
        # command that omits these will look green and CI will not.
        if lane["lane"] is None:
            pass
        elif lane["guards"]:
            # #566: a guard entry always carries a `status` now that `lane_report`
            # threads `repo` through -- `exists` reads exactly as it always has,
            # `absent` and `could-not-tell` are said in as many words rather than
            # handing a lane a path that would collect nothing.
            for entry in lane["guards"]:
                status = entry.get("status")
                why = "; ".join(entry["why"])
                if status == "absent":
                    lines.append(
                        "  guard   : {0} -- NOT IN THIS REPO, treat as uncovered "
                        "({1})".format(entry["test"], why)
                    )
                elif status == "could-not-tell":
                    lines.append(
                        "  guard   : {0} -- COULD NOT TELL whether this repo has it "
                        "({1})".format(entry["test"], why)
                    )
                else:
                    lines.append("  guard   : {0} ({1})".format(entry["test"], why))
        else:
            lines.append(
                "  guard   : none of the lane's files match a known cross-cutting guard"
            )

    return _render(lines)


def _receipt_companions_line(result):
    """One line rendering `suggest_companions`'s own three states -- never
    folding `could-not-tell` into `none`, the exact fold #851 exists to
    close for the sweep the way #809/#837 already closed it for a single
    lane's own availability.

    An issue whose own file set could not be derived is reported by number
    even on a `candidates` line -- #851's own wording, "never silently
    dropped": a real candidate found elsewhere on the board must not read
    as proof the rest of the board was swept clean.
    """
    if result["state"] == select_issues_companions.STATE_CANDIDATES:
        parts = [
            "#{0} ({1})".format(entry["number"], ", ".join(entry["files"]))
            for entry in result["candidates"]
        ]
        line = "candidates: " + "; ".join(parts)
        if result["undetermined"]:
            line += "; also could not derive a file set for {0}".format(
                ", ".join(
                    "#{0}".format(entry["number"]) for entry in result["undetermined"]
                )
            )
        return line
    if result["state"] == select_issues_companions.STATE_NONE:
        return "none -- {0}".format(result["detail"])
    return "COULD NOT TELL -- {0}".format(result["detail"])


def _split_label_positionals(argv):
    """Pull the up-to-three plain positionals that follow ``--label`` out of
    *argv* by hand, before argparse ever sees them.

    argparse cannot reliably parse a *second* run of optional positionals
    (``ISSUES``, ``PHRASE``, ``SUBAGENT_TYPE``) that appears after an
    optional flag (``--label``) -- whether it does depends on the
    interpreter: observed to fail on 3.10 and 3.11 (CPython's own
    intermixed-positional handling changed in 3.12) and pass on 3.12 and
    3.13, which is exactly the kind of silent, version-dependent breakage
    this file's own supported floor (Python 3.9) cannot afford. Since the
    call shape is always ``<issue> --label <ISSUES> <PHRASE>
    [<SUBAGENT_TYPE>] [--model ...] [--background]`` (#1069, #989), consume
    the label's own positionals directly out of the tokens immediately
    following ``--label`` and hand argparse a single, unambiguous
    ``issue`` positional plus whatever flags remain.
    """
    argv = list(argv)
    try:
        label_at = argv.index("--label")
    except ValueError:
        return argv, (None, None, None)
    rest = argv[label_at + 1 :]
    consumed = []
    for token in rest:
        if len(consumed) >= 3:
            break
        if token != "-" and token.startswith("-"):
            break
        consumed.append(token)
    consumed_count = len(consumed)
    consumed += [None] * (3 - consumed_count)
    tail = rest[consumed_count:]
    new_argv = argv[: label_at + 1] + tail
    return new_argv, tuple(consumed)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    argv, (label_issues_value, label_phrase_value, label_subagent_value) = (
        _split_label_positionals(argv)
    )
    parser = argparse.ArgumentParser(
        description=(
            "One call for a developer lane's setup facts: the resolved base, the "
            "derived branch and worktree, and the live worktree board (#317)."
        ),
        epilog="exit 0 = usable; exit 3 = could not run (no usable config, or no base)",
    )
    parser.add_argument(
        "issue",
        type=int,
        nargs="?",
        default=None,
        help="the issue number this lane implements -- omit only together with "
        "--suggest-companions, which carries its own issue number as its argument",
    )
    parser.add_argument("--repo", default=".", help="repository to read (default: .)")
    parser.add_argument(
        "--remote", default="origin", help="remote to fetch from (default: origin)"
    )
    parser.add_argument(
        "--stack-on",
        default=None,
        metavar="BRANCH",
        help="resolve `base` from this branch's own tip instead of "
        "default_branch (#1006) -- reads refs/heads/<BRANCH>, falling back "
        "to refs/remotes/<remote>/<BRANCH>, straight out of the shared "
        "object database, so it never touches whatever worktree BRANCH "
        "might be checked out in. Use this to stack a new lane on another "
        "live lane's branch and sidestep git-worktrees' 'cannot tell' "
        "collision on that worktree entirely, rather than reasoning about it.",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the payload instead of the receipt"
    )
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        metavar="PATTERN",
        help="a file or glob this brief's lane touches; repeatable (#267)",
    )
    parser.add_argument(
        "--claim",
        action="store_true",
        help="write the GitHub assignee for this lane's issue, and for every "
        "--claim-also companion (#705, #1532). Every other call -- including "
        "one carrying --lane -- is a read and writes nothing, so probing "
        "candidates never leaves anything behind. Pass this only at the "
        "moment this lane is actually dispatched. #1532: this no longer "
        "writes a local lane record; the assignee is the one claim with a "
        "real owner, and `git-worktrees` is the authority on which lanes "
        "are live.",
    )
    parser.add_argument(
        "--claim-also",
        action="append",
        default=[],
        type=int,
        metavar="ISSUE",
        help="claim in both senses in one call (#1069): a companion issue in "
        "this same lane whose GitHub assignee should also be written when "
        "--claim runs, alongside the positional issue. Repeatable. Ignored "
        "without --claim.",
    )
    parser.add_argument(
        "--label",
        action="store_true",
        help="compose this lane's own fleet-view label instead of computing "
        "setup facts (#1069, folded in from fleet_label.py) -- the positional "
        "issue is the lane's primary issue, and up to three MORE plain "
        "arguments follow --label itself, positionally, in this fixed order: "
        "ISSUES (every issue this lane carries, primary included, "
        "comma-separated), PHRASE (the short description of what the lane is "
        "doing) and, optionally, SUBAGENT_TYPE (given, renders the whole "
        "literal Agent(...) call (#989) instead of only the description "
        "string) -- the same shape fleet_label.py's own CLI always used. "
        "These three are consumed straight out of argv, by hand, before "
        "argparse ever sees them (#1069's own CI fix), which is why they do "
        "not appear as their own entries under `positional arguments:` above "
        "-- ISSUES and PHRASE are required whenever --label is given; every "
        "other flag is ignored when this is given.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="passed straight through to the rendered Agent(...) call; "
        "meaningful together with --label and --label-subagent, or with "
        "--claim and --subagent-type.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="passed straight through to the rendered Agent(...) call's "
        "run_in_background field; meaningful together with --label and "
        "--label-subagent, or with --claim and --subagent-type.",
    )
    parser.add_argument(
        "--phrase",
        default=None,
        metavar="TEXT",
        help="the short description of what this lane is doing (#1143). "
        "Given together with --claim, composes this lane's own fleet-view "
        "label -- or, with --subagent-type, the whole Agent(...) call -- "
        "from the issues this --claim call actually holds afterward, never "
        "from the issue and --claim-also values requested: a companion "
        "whose assignee write failed is silently excluded from the count. "
        "Ignored without --claim.",
    )
    parser.add_argument(
        "--short-reason",
        default=None,
        choices=select_issues_rank.SHORT_REASONS,
        metavar="REASON",
        help="given together with --claim, carried straight through onto "
        "the ready --lane-fill token this call renders (#1148) -- one of "
        "board-exhausted / no-adjacent / did-not-search / could-not-tell, "
        "the group's own reason for being short. Omit it when the group "
        "established no reason: the rendered token then carries no reason "
        "either, so oss_state.py --decision's own refusal (#852) still "
        "fires downstream on a short lane rather than being satisfied by "
        "one invented here. Always wins over --group-state when both are "
        "given (#1153) -- an explicit correction outranks the mechanical "
        "derivation. Ignored without --claim.",
    )
    parser.add_argument(
        "--group-state",
        default=None,
        choices=_GROUP_STATES,
        metavar="STATE",
        help="given together with --claim: the group's own `state` field, "
        "unchanged, from select_issues.py's own grouping JSON (#1153) -- so "
        "the caller pastes what select_issues.py already printed instead of "
        "translating it into --short-reason's closed vocabulary by hand. "
        "Mechanically derives REASON for three of the four states -- "
        "no-adjacent from 'none' (searched, found nothing adjacent, #918), "
        "could-not-tell from 'could-not-tell' (searched, could not tell, "
        "identical word), did-not-search from 'lane-other' (#1130 never "
        "calls the board sweep at all, which is exactly #918's own "
        "definition of did-not-search: 'a computation nobody started'). "
        "The fourth, 'candidates' (some companions found, still short), has "
        "no safe translation: board-exhausted is a claim about the WHOLE "
        "board's remaining disjoint candidates (#871), which one group's "
        "own state never establishes, so it is never guessed at -- give "
        "--short-reason explicitly for that state instead. Ignored without "
        "--claim.",
    )
    parser.add_argument(
        "--subagent-type",
        default=None,
        metavar="TYPE",
        help="given together with --claim and --phrase, renders the whole "
        "literal Agent(...) call (#989) instead of only the description "
        "string -- prompt included, composed from the issues this claim "
        "holds and the worktree it derived (#1535). Ignored without --claim.",
    )
    parser.add_argument(
        "--brief",
        default=None,
        metavar="PATH",
        help="OPTIONAL extra per-lane context (a recon summary, say) appended "
        "to the composed prompt (#1535) -- never a substitute for it, and "
        "never a place to restate agents/developer.md, which the lane holds "
        "on every turn. The whole composed prompt is checked against "
        "lane_setup_brief_schema's three structural elements before the "
        "Agent(...) line is rendered; any finding refuses the render. "
        "Requires --subagent-type.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="release this issue's GitHub assignee (#734, #1532), instead of "
        "computing setup facts -- call this once the merge step has "
        "independently verified the pull request merged (state/mergedAt/"
        "mergeCommit read back off the remote), so a follow-up dispatched "
        "minutes later never reads this issue as still taken. Exits 0 whether "
        "or not an assignee was set; every other flag is ignored when this is "
        "given.",
    )
    parser.add_argument(
        "--release-also",
        action="append",
        default=[],
        type=int,
        metavar="ISSUE",
        help="release in both senses in one call (#1069, the mirror of "
        "--claim-also): a companion issue this lane also claimed whose "
        "GitHub assignee should also be released. A companion never has its "
        "own lane record, so this is assignee-only. Repeatable. Ignored "
        "without --release.",
    )
    parser.add_argument(
        "--activity",
        action="store_true",
        help="#1120: alongside the default setup-facts read (and --claim), scan "
        "the derived worktree recursively for its most recent modification time "
        "and render it as a `last touched Ns ago` line -- a corroborating "
        "activity signal for a sub-manager doubting a scheduler's own 'dead' "
        "verdict before re-dispatching a second agent into the same tree. Only "
        "computed when the worktree is positively confirmed to already exist; "
        "a plain recursive stat walk, so this is opt-in and never paid by the "
        "unconditional call every plain lane_setup.py <issue> already makes. "
        "Refused together with --release, --suggest-companions and --label, "
        "none of which render a worktree line.",
    )
    parser.add_argument(
        "--suggest-companions",
        type=int,
        default=None,
        metavar="ISSUE",
        help="the lane-bundling sweep (#851): given this lane's OWN issue "
        "number and its claimed --lane set, read an open board handed in as "
        "JSON on stdin (the select_issues_rank.py idiom -- this call never "
        "invokes gh itself) and report every OTHER open issue whose title "
        "or body names a path landing inside the claimed set, in three "
        "states: candidates / none / could-not-tell. Requires at least one "
        "--lane, carries its own issue number (the positional issue argument "
        "is omitted when this is given), and refuses every other mode flag "
        "(--claim, --release) alongside it.",
    )
    # #1069's own CI fix (argparse's inconsistent handling of a second run of
    # optional positionals appearing after --label) moved ISSUES/PHRASE/
    # SUBAGENT_TYPE out of argparse's own positional declarations, which took
    # them out of the auto-generated usage line and `--help` too -- silently,
    # since nothing here checked for it (a maintainer review caught it after
    # the first commit). Splice them back into the usage line derived from
    # the parser's real, still-registered actions, rather than hand-writing
    # the whole usage string: hand-writing it would drift the moment a flag
    # is added or removed anywhere above, exactly the class of fact-in-two-
    # places bug this repository's own CLAUDE.md warns against.
    _label_usage_suffix = " [ISSUES] [PHRASE] [SUBAGENT_TYPE]"
    _default_usage = parser.format_usage()
    if _default_usage.startswith("usage: "):
        _default_usage = _default_usage[len("usage: ") :]
    _default_usage = _default_usage.rstrip("\n")
    if "[issue]" in _default_usage and _label_usage_suffix not in _default_usage:
        parser.usage = _default_usage.replace(
            "[issue]", "[issue]" + _label_usage_suffix, 1
        )

    args = parser.parse_args(argv)
    args.label_issues = label_issues_value
    args.label_phrase = label_phrase_value
    args.label_subagent = label_subagent_value

    if args.suggest_companions is not None:
        if args.issue is not None:
            parser.error(
                "--suggest-companions carries its own issue number as its "
                "argument; drop the positional issue argument"
            )
        for flag_name, flag_value in (
            ("--claim", args.claim),
            ("--release", args.release),
            ("--activity", args.activity),
        ):
            if flag_value:
                parser.error(
                    "--suggest-companions and {0} are mutually exclusive -- "
                    "the sweep answers a different question than any of "
                    "this file's other modes (#851)".format(flag_name)
                )
        if not args.lane:
            # Found by this lane's own reviewer, and it is this repository's
            # own defect class inside the tool written to close it: with no
            # --lane there is no claimed set, every issue's overlap against
            # the empty set is empty, and `suggest_companions` then returns a
            # confident `none` -- "board read in full ... none lands inside
            # the claimed set" -- about a claimed set nobody ever named. The
            # sweep has no third state for "you did not tell me what this
            # lane holds", because that is a usage error rather than a
            # measurement, so it is refused at the boundary.
            parser.error(
                "--suggest-companions requires --lane (#851) -- with no claimed "
                "file set the sweep compares every issue against nothing and "
                "reports a confident `none` about a lane that was never named; "
                "pass --lane once per file this lane holds"
            )
    elif args.issue is None and not args.label:
        parser.error(
            "the issue argument is required unless --suggest-companions or "
            "--label is given"
        )

    if args.release and args.activity:
        parser.error(
            "--release and --activity are mutually exclusive -- --release "
            "does not render a worktree line for --activity to attach to "
            "(#1120)"
        )

    # #788 required `--claim` to carry `--lane`, because a claim with no files
    # wrote a fileless lane record that poisoned every later `--derive-held`
    # call this tick. #1532 removed both the record and `--derive-held`, so
    # the reason is gone and the requirement went with it: `--claim` now
    # writes a GitHub assignee, which does not carry a file set and is not
    # made better or worse by one being declared beside it.

    if args.phrase is not None and not args.claim:
        parser.error("--phrase requires --claim (#1143)")
    if args.subagent_type is not None and not args.claim:
        parser.error("--subagent-type requires --claim (#1143)")
    if args.brief is not None and not args.claim:
        parser.error("--brief requires --claim (#1143)")
    if args.short_reason is not None and not args.claim:
        parser.error("--short-reason requires --claim (#1148)")
    if args.group_state is not None and not args.claim:
        parser.error("--group-state requires --claim (#1153)")
    if args.subagent_type is not None and args.phrase is None:
        parser.error("--subagent-type requires --phrase (#1143)")
    # #1535 retired the reverse direction: --subagent-type no longer requires
    # --brief, because the prompt is composed from the two facts this call
    # already derived. --brief's own direction below stays enforced -- a
    # --brief given alone was silently ignored (#1143).
    if args.brief is not None and args.subagent_type is None:
        # Self-review finding (Explore + oss:auditor, #1143): the reverse of
        # the check above was never enforced, so a --brief given without
        # --subagent-type was silently accepted and never read at all --
        # compose_claim_label only ever calls check_path when subagent_type
        # is given. --brief's own help text already promised this direction;
        # nothing checked it.
        parser.error("--brief requires --subagent-type (#1143)")

    if args.label:
        for flag_name, flag_value in (
            ("--claim", args.claim),
            ("--release", args.release),
            ("--suggest-companions", args.suggest_companions is not None),
            ("--activity", args.activity),
        ):
            if flag_value:
                parser.error(
                    "--label and {0} are mutually exclusive -- composing a "
                    "lane's own label answers a different question than any "
                    "of this file's other modes (#1069)".format(flag_name)
                )
        if not args.label_issues or not args.label_phrase:
            parser.error(
                "--label requires --label-issues and --label-phrase -- an "
                "omitted or partial bundle is exactly the label #539 was "
                "filed about"
            )
    elif args.label_issues or args.label_phrase or args.label_subagent:
        parser.error("--label-issues/--label-phrase/--label-subagent require --label")

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    if args.label:
        issues = [part.strip() for part in args.label_issues.split(",") if part.strip()]
        try:
            if args.label_subagent is None:
                output = fleet_label(args.issue, issues, args.label_phrase)
            else:
                output = agent_call(
                    args.issue,
                    issues,
                    args.label_phrase,
                    args.label_subagent,
                    model=args.model,
                    run_in_background=args.background,
                )
        except FleetLabelError as exc:
            print(str(exc))
            return EXIT_COULD_NOT_RUN
        print(output)
        return EXIT_OK

    if args.suggest_companions is not None:
        # JSON is UTF-8 by spec (RFC 8259) -- the identical reasoning
        # select_issues_rank.py's own former `main` gave for the same reconfigure, kept
        # local rather than imported for the same reason lane_setup.py's own
        # `_one_line` stays local beside release_delta.py's: this is a setup
        # read, not that module, and neither should have to change because
        # the other one's contract did.
        # #984: `sys.stdin` is `None` when the harness hands the process a
        # closed or unopenable standard input, so `.reconfigure` raises
        # `AttributeError` before the `except (AttributeError, ValueError):
        # pass` below can help -- that guard was written for a *stream* that
        # refuses to reconfigure, not for the absence of a stream. Past
        # that, `json.load(None)` would raise `AttributeError` uncaught,
        # exiting 1 with none of this module's own states. Check for `None`
        # first and answer `COULD NOT READ`, the same class #405 and #846
        # already fixed in `review_return.py`, `tree_snapshot.py`,
        # `select_issues_rank.py`, `statusline.py` and `batch_hint.py`.
        if sys.stdin is None:
            print(
                "COULD NOT READ: stdin is not JSON (no readable stdin: "
                "the process was handed a closed or unopenable standard "
                "input)"
            )
            return EXIT_COULD_NOT_RUN
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover - not a TextIOWrapper
            pass
        try:
            board = json.load(sys.stdin)
        except UnicodeDecodeError as err:
            print(
                "COULD NOT READ: stdin could not be decoded as UTF-8 ({0})".format(err)
            )
            return EXIT_COULD_NOT_RUN
        except ValueError as err:
            print("COULD NOT READ: stdin is not JSON ({0})".format(err))
            return EXIT_COULD_NOT_RUN
        claimed = (
            select_issues_overlap.resolve_lane(args.repo, args.lane)["files"]
            if args.lane
            else []
        )
        result = select_issues_companions.suggest_companions(
            args.repo, args.suggest_companions, claimed, board
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(
                "COMPANIONS #{0}: {1}".format(
                    args.suggest_companions,
                    _receipt_companions_line(result),
                )
            )
        return (
            EXIT_OK
            if result["state"]
            in (
                select_issues_companions.STATE_CANDIDATES,
                select_issues_companions.STATE_NONE,
            )
            else EXIT_COULD_NOT_RUN
        )

    if args.release:
        config, problems = oss_config.load(Path(args.repo) / CONFIG_NAME)
        # #791, #803: a release used to need `worktree_root` (to find the lane
        # registry) as well as `repo`, and most of the care here was about
        # telling a genuinely benign "no worktree_root configured" apart from
        # an unparseable `.oss.local.json` that merely LOOKS like one.
        # #1532 retired the registry, so the only thing this arm still needs
        # is the repo slug to aim the assignee call at -- and `config is None`
        # is the one state in which that is unknown.
        if config is None:
            result = {
                "state": "could-not-release",
                "detail": "the repository is not known -- the config could not "
                "be read: {0}".format(
                    "; ".join(problems) if problems else "no detail available."
                ),
            }
            combined = None
        else:
            # #1069, #1532: the mirror of --claim -- release the GitHub
            # assignee for this issue and every --release-also companion,
            # closing the gap `.claude/jit-context/tools/01-oss/
            # pr-create-gate.md` used to patch with a prose reminder to run
            # the assignee release by hand after a merge.
            combined = lane_setup_claim.release_assignees(
                args.issue,
                also_release=args.release_also,
                repo=config.get("repo"),
            )
            # Self-review, both spawns independently (#1532): this read
            # `assignee_row is not None`, which is true in every real call --
            # `select_issues_claim_read.check` returns exactly one row per
            # number it is given, whatever happened. So the top line printed
            # `released` for a release that came back `not-mine`,
            # `could-not-read` or `could-not-release`, with the real answer
            # only on the second line. That is this repository's own defect
            # class inside the receipt reporting it. Read the row's own state
            # against the same ok-set `select_issues_claim_read` already
            # declares for this mode, rather than a second idea of it here.
            assignee_row = combined["assignee"]
            if assignee_row is None:
                result = {
                    "state": "could-not-release",
                    "detail": "the assignee release returned no row at all",
                }
            elif (
                assignee_row["state"] in select_issues_claim_read._OK_STATES["release"]
            ):
                result = {"state": assignee_row["state"], "detail": ""}
            else:
                result = {
                    "state": "could-not-release",
                    "detail": "the assignee for #{0} was not released: {1}{2}".format(
                        args.issue,
                        assignee_row["state"],
                        " -- " + assignee_row["detail"]
                        if assignee_row.get("detail")
                        else "",
                    ),
                }
        if args.json:
            print(
                json.dumps(
                    combined if combined is not None else result,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                "RELEASE #{0}: {1}{2}".format(
                    args.issue,
                    result["state"],
                    " -- " + result["detail"] if result["detail"] else "",
                )
            )
            if combined is not None:
                assignee_row = combined["assignee"]
                if assignee_row is not None:
                    print(
                        "RELEASE #{0} assignee: {1}{2}".format(
                            args.issue,
                            assignee_row["state"],
                            " -- " + assignee_row["detail"]
                            if assignee_row.get("detail")
                            else "",
                        )
                    )
                for row in combined.get("also_released") or []:
                    print(
                        "RELEASE #{0} assignee: {1}{2}".format(
                            row["issue"],
                            row["state"],
                            " -- " + row["detail"] if row.get("detail") else "",
                        )
                    )
        return EXIT_COULD_NOT_RUN if result["state"] == "could-not-release" else EXIT_OK

    payload = compute(
        args.repo,
        args.issue,
        args.remote,
        args.lane,
        claim=args.claim,
        stack_on=args.stack_on,
        also_claim=args.claim_also,
        activity=args.activity,
    )

    # #1143: --claim renders its own fleet-view label (or the whole
    # Agent(...) call) from the issues this call actually holds, so nothing
    # is retyped from the claim it just performed. Only attempted when a
    # phrase was actually given -- an ordinary `--claim` probe with no
    # --phrase behaves exactly as it always has.
    label_result = None
    if args.claim and args.phrase is not None:
        label_result = compose_claim_label(
            payload,
            args.phrase,
            subagent_type=args.subagent_type,
            model=args.model,
            run_in_background=args.background,
            brief_path=args.brief,
            worktree=(payload.get("worktree") or {}).get("path"),
        )
        payload["label"] = label_result

    # #1148: --claim renders step 5's own ready --lane-fill token too,
    # alongside the label/Agent(...) line above -- a separate field, never
    # folded into label_result's own states (`compose_claim_label` and
    # `compose_lane_fill` derive the same held set independently; nothing
    # here assumes one implies the other). Attempted whenever --claim ran at
    # all: unlike the label, this needs no --phrase to be meaningful.
    lane_fill_result = None
    if args.claim:
        lane_fill_result = compose_lane_fill(
            payload, short_reason=args.short_reason, group_state=args.group_state
        )
        payload["lane_fill"] = lane_fill_result

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
        if label_result is not None:
            print()
            if label_result.get("brief") is not None:
                print(lane_setup_brief_schema.receipt(label_result["brief"]))
            state = label_result["state"]
            if state == "rendered":
                print(label_result["text"])
            elif state == "brief-could-not-read":
                print(
                    "AGENT(...) REFUSED -- the brief could not be read; "
                    "nobody has reviewed it (#1143)"
                )
            elif state == "brief-structural-finding":
                print(
                    "AGENT(...) REFUSED -- the composed prompt fails at least one "
                    "structural element above (#1143)"
                )
            elif state == "no-claimed-issues":
                print(
                    "LABEL NOT COMPOSED -- no issue in this --claim call "
                    "came back genuinely held (#1143)"
                )
            elif state == "primary-not-held":
                print(
                    "LABEL NOT COMPOSED -- primary issue #{0} is not among "
                    "the issues actually held (#1143)".format(payload["issue"])
                )
            elif state == "fleet-label-error":
                print("LABEL NOT COMPOSED -- {0}".format(label_result["detail"]))
        if lane_fill_result is not None:
            print()
            fill_state = lane_fill_result["state"]
            if fill_state == "rendered":
                print("--lane-fill " + lane_fill_result["text"])
            elif fill_state == "no-claimed-issues":
                print(
                    "LANE-FILL NOT COMPOSED -- no issue in this --claim call "
                    "came back genuinely held (#1148)"
                )
            elif fill_state == "primary-not-held":
                print(
                    "LANE-FILL NOT COMPOSED -- primary issue #{0} is not "
                    "among the issues actually held (#1148)".format(payload["issue"])
                )

    exit_code = EXIT_COULD_NOT_RUN if blocked(payload) else EXIT_OK
    if label_result is not None and label_result["state"] != "rendered":
        exit_code = EXIT_COULD_NOT_RUN
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
