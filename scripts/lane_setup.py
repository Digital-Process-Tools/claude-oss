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
  record     recorded (this call passed --claim and the write succeeded), unknown
             (no worktree_root to write to -- expected inside a worktree this loop
             cuts), could-not-write (worktree_root known, the write itself failed),
             or not-claimed (#705: this call did not pass --claim, so it asked
             without writing -- the ordinary shape for a disjointness probe that
             may never be dispatched).

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
lookup, and the disjointness report a lane brief reads), `lane_setup_claim.py`
(the lane registry, held-set derivation, and the claim/release logic below)
or `lane_setup_label.py` (a lane's own fleet-view label, `--label`, folded in
from `fleet_label.py`). Every name is imported here and re-exported at module
level, so `lane_setup.<name>` keeps working for every existing caller.
`resolve_lane`/`lane_overlap` and `suggest_companions` moved to
`select_issues_overlap.py`/`select_issues_companions.py` instead --
`select_issues.py`'s own submodules, not this file's, per that module's
docstring.

## Claim in both senses, in one call (#1069)

Claiming used to be two scripts and two calls: `issue_claim.py --claim`
wrote the GitHub assignee, and this file's own `--claim --lane` registered
the lane, with nothing rolling the first back when the second failed and
nothing releasing the assignee when a lane ended. `--claim` now writes the
assignee for the positional issue (and every `--claim-also` issue) AND
registers the lane in one call, via `lane_setup_claim.claim_and_register` --
rolling every freshly-written assignee back if the registration fails, and
naming the outcome as its own state rather than a silent partial claim.
`--release` is the mirror: it releases the local lane record AND the GitHub
assignee together, via `lane_setup_claim.release_lane_and_assignee`.

Python 3.9 compatible: no match statements, no `X | Y` annotations.
"""

import argparse
import json
import os  # noqa: F401 (re-exported as lane_setup.os for existing monkeypatch-based tests -- see the module docstring)
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lane_setup_claim  # noqa: E402  (path insert above must run first)
import lane_setup_label  # noqa: E402
import lane_setup_patterns  # noqa: E402
import lane_setup_worktree  # noqa: E402
import oss_config  # noqa: E402
import select_issues_companions  # noqa: E402
import select_issues_overlap  # noqa: E402

# Re-exported at module level so `lane_setup.<name>` keeps working for every
# existing caller and test -- only the *definition* moved (#1069). See the
# module docstring's "Two entry points, split into submodules" section.
from lane_setup_claim import (  # noqa: E402,F401
    CLAIM_STATE_ALREADY_CLAIMED,
    CLAIM_STATE_ALREADY_MINE,
    CLAIM_STATE_ASSIGNEE_ROLLED_BACK,
    CLAIM_STATE_CLAIMED,
    CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE,
    CLAIM_STATE_COULD_NOT_REGISTER,
    CLAIM_STATE_ROLLBACK_FAILED,
    LANE_RECORD_TTL_SECONDS,
    LANE_REGISTRY_DIRNAME,
    _PR_LIST_LIMIT,
    _branch_confirmed_gone,
    _branch_confirmed_present,
    _mark_branch_confirmed_created,
    _show_ref_code,
    claim_and_register,
    derive_held_set,
    detect_vanished_worktrees,
    held_from_live_lanes,
    held_from_open_prs,
    lane_count,
    lane_registry_dir,
    lanes_snapshot,
    record_lane,
    release_lane,
    release_lane_and_assignee,
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
    """The live worktree board, condensed. `could-not-run` is a state, not a crash."""
    supertool = shutil.which("supertool")
    if supertool is None:
        return {
            "state": "could-not-run",
            "lines": [],
            "detail": "supertool is not on PATH",
        }
    try:
        done = subprocess.run(
            [supertool, "git-worktrees"],
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
    against_patterns=None,
    derive_held=False,
    claim=False,
    stack_on=None,
    also_claim=None,
    claim_checker=None,
):
    """Everything a lane brief needs, in one payload. `config.state` gates the exit.

    `stack_on` (#1006): when given, `base` is resolved from that branch's own
    tip (`resolve_stacked_base`) instead of from `default_branch` -- the third
    candidate fix in #1006, taken because it needs no change to the
    `git-worktrees` op itself and so needs no upstream filing to land. A
    stacked branch never touches the worktree `stack_on` might be checked out
    in, sidestepping the `cannot tell` collision `git-worktrees` reports for a
    tree whose index was written recently, rather than trying to resolve it.

    `lane_patterns` / `against_patterns` are optional (#267): when neither is
    given and `derive_held` is False, `payload["lane"]` is None -- an absent ask
    must not read as a checked, empty lane. When either is given, both sides are
    rendered through `resolve_lane` and, when both sides are present, compared
    with `lane_overlap` -- the disjointness check the manager skill currently runs
    by eye.

    `derive_held` (#558) is opt-in, not the default: the local, offline path this
    module has always offered (`--lane`/`--against`, both hand-typed) keeps working
    unchanged when it is False, which is the ordinary case for the "writing each
    brief" call SKILL.md's own table names -- that call has no reason to pay for a
    `gh pr list` round trip. When True, the "against" side is derived instead of
    accepted (`derive_held_set`, from open pull requests and live lane records) --
    a forge call that fails must never render as an empty, confident held set, so
    a failed derivation flows into `lane_report` as `could-not-derive`, not as
    `against=None` (which would silently read as "nothing to check against").

    `claim` (#705) is the only thing that makes this call write *this lane's own*
    record. Default False: `--lane`/`--against`/`--derive-held` never write a
    record for the issue this call is about, and nothing here writes a lane
    record on that issue's behalf without `--claim`. Pass `claim=True` only at
    the moment this lane is actually being dispatched, never while probing
    candidates.

    **That is narrower than "nothing is written to the registry", and it always
    has been.** `lanes_snapshot` -> `lane_count` prunes a TTL-expired record as a
    side effect of the read it performs regardless of `claim` (its own docstring
    says so); `--derive-held` (#734, review round) can now do the same for a
    *different* issue's record, whenever `held_from_live_lanes` corroborates a
    live record's declared branch as locally confirmed gone -- a probe that never
    intends to dispatch can still delete another lane's stale record. Both are
    deletions of records this loop has independent evidence are dead (aged out,
    or the branch a merge already removed), never of a record still legitimately
    held, and both are reported: `lane_report`'s `held_source.stale_pruned` and
    the receipt's first `held :` line name what a `--derive-held` call actually
    removed, so this is a write with a trace, not a silent one. #792: the removal
    itself can fail -- `held_source.prune_failed` and the receipt's second
    `held :` line name a record this call tried and failed to remove, which is
    demonstrably still on disk and never counted in the first line's total.

    `also_claim`/`claim_checker` (#1069): when `claim` is True, the assignee
    is written for `issue` AND every issue in `also_claim` (a lane's
    companion issues) via `lane_setup_claim.claim_and_register`, which rolls
    every freshly-written assignee back if the lane registration itself
    fails -- see that function's own docstring for the full state list.
    `claim_checker` is injectable the same way `select_issues.py`'s own
    `select()` injects `checker`, so a test never needs a live `gh` session.
    Ignored when `claim` is False, the ordinary probing case.
    """
    repo = Path(repo)
    config_path = repo / CONFIG_NAME
    config, problems = oss_config.load(config_path)

    if config is None:
        derived_held = (
            {
                "state": "could-not-derive",
                "held": {},
                "detail": "config could not be loaded, so neither repo nor "
                "worktree_root is known to derive a held set from.",
            }
            if derive_held
            else None
        )
        return {
            "issue": issue,
            "repo": str(repo),
            "config": {"state": "could-not-run", "problems": problems},
            "base": None,
            "branch": None,
            "worktree": None,
            "board": None,
            "lanes": None,
            "lane": lane_setup_patterns.lane_report(
                repo, lane_patterns, against_patterns, derived_held
            ),
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

    board = read_board(repo)

    derived_held = (
        lane_setup_claim.derive_held_set(
            config.get("repo"),
            config.get("worktree_root"),
            exclude_issue=issue,
            repo=repo,
        )
        if derive_held
        else None
    )
    lane = lane_setup_patterns.lane_report(
        repo, lane_patterns, against_patterns, derived_held
    )

    # #558: this lane's own resolved files are recorded so a *later* candidate's
    # `derive_held_set` call can read them back -- computed here, after `lane_report`,
    # rather than calling `resolve_lane` a second time for the same patterns.
    lane_files = (
        lane["lane"]["files"] if lane and lane.get("lane") is not None else None
    )

    # #865: a claim standing inside a linked worktree derives `worktree_root`
    # from THAT worktree's own path (#608), not the clone's -- a value, not
    # an absence, and a wrong one: the registry it would write into is a
    # sibling of the one worktree that asked, invisible to every other lane.
    # Checked only when a claim was actually requested -- every probe form
    # above is read-only and this must never refuse one of those.
    #
    # Review round: `linked_worktree_state`'s own docstring says its
    # `could-not-tell` state must never render as `main` -- comparing only
    # against `WORKTREE_LINKED` here let a `could-not-tell` reading (git
    # itself failed to answer one of the two rev-parse calls) fall through
    # to a claim proceeding exactly as if it had been verified safe. Refusing
    # on anything other than a confirmed `WORKTREE_MAIN` closes that: the
    # only way to write is a positive, checked answer, never an unchecked one.
    standing_in = (
        lane_setup_worktree.linked_worktree_state(repo)
        if claim
        else (lane_setup_worktree.WORKTREE_MAIN, "")
    )
    claim_worktree_state = standing_in[0] if claim else None
    claim_refused = claim and claim_worktree_state != lane_setup_worktree.WORKTREE_MAIN
    # Nothing is written when the claim cannot be trusted -- refusing loudly
    # and still writing into the wrong registry would be strictly worse than
    # refusing and writing nothing at all.
    effective_claim = claim and not claim_refused

    # #1069: claiming now writes the GitHub assignee for `issue` (and every
    # issue in `also_claim`) AND registers the lane, rolling the assignee
    # write(s) back if registration fails -- `claim_and_register`'s own
    # docstring names every state. The lane count is read via
    # `lanes_snapshot(..., claim=False)` -- a pure read, never a second
    # write -- and read AFTER registering, so this lane's own just-written
    # record is included in its own count, the same ordering the single
    # `lanes_snapshot(..., claim=effective_claim)` call used to guarantee by
    # writing first and counting second.
    claim_result = None
    if effective_claim:
        claim_result = lane_setup_claim.claim_and_register(
            config.get("worktree_root"),
            issue,
            branch.get("name"),
            worktree.get("path"),
            files=lane_files,
            also_claim=also_claim,
            repo=config.get("repo"),
            checker=claim_checker,
        )
    lanes = lane_setup_claim.lanes_snapshot(
        config.get("worktree_root"),
        issue,
        branch.get("name"),
        worktree.get("path"),
        files=lane_files,
        claim=False,
    )
    if claim_result is not None:
        lanes = dict(lanes)
        lanes["record"] = (
            claim_result["record"]
            if claim_result["record"] is not None
            else {
                "state": "not-claimed",
                "path": None,
                "detail": "the assignee claim was refused or failed before the "
                "lane could be registered ({0}) -- see "
                "claim_result".format(claim_result["state"]),
            }
        )

    return {
        "issue": issue,
        "repo": str(repo),
        "config": {"state": "ok", "problems": problems},
        "base": base,
        "branch": branch,
        "worktree": worktree,
        "board": board,
        "lanes": lanes,
        "lane": lane,
        "claim": claim,
        # #865: None when no claim was requested (nothing to refuse); the
        # worktree state that caused the refusal ('linked' or
        # 'could-not-tell') when one was and the claim could not be trusted;
        # 'main' when a claim was requested and genuinely went through.
        "claim_worktree_state": claim_worktree_state,
        "claim_refused": claim_refused,
        # #1069: None when no claim was requested, or a claim was requested
        # but refused before it ever reached `claim_and_register` (the
        # `claim_refused` case above -- standing inside a linked worktree).
        # Otherwise `claim_and_register`'s own result -- see its docstring.
        "claim_result": claim_result,
    }


def blocked(payload):
    """True when there is not enough here to cut a lane from.

    #865: a `--claim` that could not record is folded in here too, not only
    "not enough to cut a lane from" -- a claim standing inside a linked
    worktree writes into a registry no other lane reads, which is worse than
    writing nothing, and letting it exit 0 identically to a real claim is
    exactly the defect this repository is named after: an absence produced
    by the tool, read as an absence in the world. `claim_refused` covers
    both ways the worktree check can fail to vouch for the claim -- a
    confirmed linked worktree AND a plain could-not-tell -- because only a
    confirmed `WORKTREE_MAIN` reading is grounds to trust it (review round:
    an earlier version compared only against `WORKTREE_LINKED`, so a
    could-not-tell reading silently proceeded as if verified safe).
    """
    if payload["config"]["state"] != "ok":
        return True
    if payload["base"]["state"] == "could-not-resolve":
        return True
    if payload.get("claim_refused"):
        return True
    # #1069: a claim that was attempted and did NOT reach
    # `lane_setup_claim.CLAIM_STATE_CLAIMED` -- already claimed by somebody
    # else, the assignee write itself failed, or the registration failed and
    # the assignee write was rolled back (or the rollback itself failed) --
    # is not a lane a caller may proceed to dispatch from, exactly the same
    # discipline `claim_refused` already applies one case over.
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

    board = payload["board"]
    lines.append("board     :")
    if board["state"] != "ok":
        lines.append("  COULD NOT RUN -- " + board["detail"])
    else:
        for line in board["lines"]:
            lines.append("  " + line)

    lanes = payload.get("lanes")
    if lanes is not None:
        count = lanes["count"]
        if count["state"] == "resolved":
            lines.append(
                _row(
                    "lanes",
                    "{0} live (recorded, TTL {1}m)".format(
                        count["count"], lane_setup_claim.LANE_RECORD_TTL_SECONDS // 60
                    ),
                )
            )
        else:
            lines.append(
                _row(
                    "lanes",
                    "{0} -- {1}".format(count["state"].upper(), count["detail"]),
                )
            )
        record = lanes["record"]
        if payload.get("claim_refused"):
            # #865: --claim was requested and could not be trusted -- either a
            # confirmed linked worktree, or git itself could not answer the
            # check (could-not-tell, never read as safe). Nothing was written
            # (`effective_claim` was forced False in `compute`), so the
            # underlying record always reads `not-claimed` here -- but THAT
            # state's own generic detail ("this call did not pass --claim")
            # is written for #705's genuine probing case and is false for
            # this one: the call plainly did pass --claim. Review round: an
            # earlier version printed the generic line unedited beside the
            # #865 line below, contradicting it. Replaced with the real
            # cause instead of reusing a sentence built for a different one.
            if (
                payload.get("claim_worktree_state")
                == lane_setup_worktree.WORKTREE_LINKED
            ):
                lines.append(
                    "  CLAIM REFUSED: standing inside a linked worktree, not the "
                    "clone -- run --claim from the clone instead (#865)"
                )
            else:
                lines.append(
                    "  CLAIM REFUSED: could not tell whether this is a linked "
                    "worktree or the clone -- git did not answer, so the claim "
                    "was not trusted (#865)"
                )
        elif record["state"] != "recorded":
            lines.append(
                "  this lane not recorded: {0} -- {1}".format(
                    record["state"], record["detail"]
                )
            )
        # #1069: `claim_and_register`'s own outcome, one line naming the
        # assignee side of the claim -- the record line above already names
        # the registry side, and a reader must never have to infer the other
        # half from silence.
        claim_result = payload.get("claim_result")
        if claim_result is not None:
            if claim_result["state"] == lane_setup_claim.CLAIM_STATE_CLAIMED:
                lines.append("  assignee: claimed")
            elif claim_result["state"] == lane_setup_claim.CLAIM_STATE_ALREADY_CLAIMED:
                holders = sorted(
                    {
                        holder
                        for row in claim_result["assignee"]["rows"]
                        for holder in (row.get("holders") or [])
                    }
                )
                lines.append(
                    "  assignee: ALREADY CLAIMED by {0} -- nothing written".format(
                        ", ".join(holders) if holders else "somebody else"
                    )
                )
            elif (
                claim_result["state"]
                == lane_setup_claim.CLAIM_STATE_COULD_NOT_CLAIM_ASSIGNEE
            ):
                lines.append(
                    "  assignee: COULD NOT CLAIM -- the assignee read/write itself "
                    "did not complete for at least one issue"
                )
            elif (
                claim_result["state"]
                == lane_setup_claim.CLAIM_STATE_ASSIGNEE_ROLLED_BACK
            ):
                lines.append(
                    "  assignee: ROLLED BACK -- the lane could not be registered, "
                    "so the assignee write was undone"
                )
            elif claim_result["state"] == lane_setup_claim.CLAIM_STATE_ROLLBACK_FAILED:
                lines.append(
                    "  assignee: ROLLBACK FAILED -- {0} still assigned even though "
                    "the lane was never registered; release by hand".format(
                        ", ".join(
                            "#{0}".format(n)
                            for n in claim_result["assignee"]["rollback_failed"]
                        )
                    )
                )

    lane = payload.get("lane")
    if lane is not None:
        lines.append("lane      :")
        held_source = lane.get("held_source")
        if held_source is None:
            for side_label, side in (
                ("lane", lane["lane"]),
                ("against", lane["against"]),
            ):
                if side is None:
                    continue
                for entry in side["patterns"]:
                    lines.append(
                        "  [{0}] {1} ({2}): {3}".format(
                            side_label,
                            entry["pattern"],
                            entry["state"],
                            ", ".join(entry["files"]) or "-",
                        )
                    )
        else:
            # #558: the "against" side was derived (open PRs + live lanes), not
            # hand-typed -- printing every held file as an individual pattern line,
            # the way the hand-typed side does, would run to hundreds of lines on a
            # busy tracker. The files themselves still appear, in `overlap` and
            # `verdict` below; this line only says where "against" came from.
            for entry in lane["lane"]["patterns"] if lane["lane"] else []:
                lines.append(
                    "  [lane] {0} ({1}): {2}".format(
                        entry["pattern"],
                        entry["state"],
                        ", ".join(entry["files"]) or "-",
                    )
                )
            if held_source["state"] == "resolved":
                held_count = len(lane["against"]["files"]) if lane["against"] else 0
                lines.append(
                    "  against : derived held set, {0} file(s)".format(held_count)
                )
            else:
                lines.append(
                    "  against : COULD NOT DERIVE THE HELD SET -- {0}".format(
                        held_source["detail"]
                    )
                )
            # #734, review round: a stale-branch prune is a real write this call
            # performs even when --claim was never passed -- named here so it is
            # never a silent action with no trace anywhere in this receipt.
            stale_pruned = held_source.get("stale_pruned") or []
            if stale_pruned:
                lines.append(
                    "  held    : {0} stale record(s) released (branch confirmed gone): {1}".format(
                        len(stale_pruned),
                        ", ".join(
                            "lane #{0} ({1})".format(item["issue"], item["branch"])
                            for item in stale_pruned
                        ),
                    )
                )
            # #792: a prune this call attempted and failed is a fact just as
            # load-bearing as one that succeeded -- the record named here is
            # demonstrably still on disk, never folded into the line above.
            prune_failed = held_source.get("prune_failed") or []
            if prune_failed:
                lines.append(
                    "  held    : {0} stale record(s) could NOT be released (still on disk): {1}".format(
                        len(prune_failed),
                        ", ".join(
                            "lane #{0} ({1}): {2}".format(
                                item["issue"], item["branch"], item["detail"]
                            )
                            for item in prune_failed
                        ),
                    )
                )
        # #774: `overlap_state` is checked first -- `.get` rather than `[]` so a
        # payload built before this field existed (an older test fixture, or a
        # hand-built dict) still renders the pre-#774 lines below rather than
        # raising.
        if lane.get("overlap_state") == "could-not-check":
            lines.append(
                "  overlap : COULD NOT CHECK -- {0}".format(
                    lane.get("overlap_detail", "")
                )
            )
        elif lane.get("overlap_state") == "resolved-to-nothing":
            # #809: the lane side named no file on disk -- an empty `overlap`
            # here is not the same claim an empty `overlap` from two real,
            # checked, disjoint sets makes, so it gets its own line rather
            # than folding into `none`.
            lines.append(
                "  overlap : n/a -- lane resolved to zero files on disk, nothing to compare (#809)"
            )
        elif lane["overlap"] is None:
            # #558 review round: the pre-#558 "only one side given" wording is
            # wrong when `held_source` is present and no --lane was given -- that
            # is "no candidate to check", not "only the against side is missing",
            # and printing the old sentence there would misdescribe a derived-held
            # call that never named a lane at all.
            if held_source is not None and lane["lane"] is None:
                lines.append(
                    "  overlap : n/a -- no --lane given to compare against the held set"
                )
            else:
                lines.append("  overlap : n/a -- only one side given")
        elif lane["overlap"]:
            lines.append("  overlap : " + ", ".join(lane["overlap"]))
        else:
            lines.append("  overlap : none")
        availability = lane.get("availability")
        if availability is not None:
            # #558: the per-candidate verdict the issue asks for -- available,
            # blocked, could-not-check, resolved-to-nothing, or
            # could-not-derive-the-held-set (#843: this comment itself still
            # enumerated only the pre-#809 four) -- never rendered as
            # `available` or `blocked` when the held set itself could not be
            # derived, or when the lane side itself could not be checked
            # (#774: a refused pattern must never render as clear).
            if availability["state"] == "available":
                lines.append("  verdict : available")
            elif availability["state"] == "blocked":
                lines.append(
                    "  verdict : BLOCKED -- {0} (held by {1})".format(
                        ", ".join(availability["files"]),
                        ", ".join(availability["holders"]),
                    )
                )
            elif availability["state"] == "could-not-check":
                lines.append(
                    "  verdict : COULD NOT CHECK -- {0}".format(availability["detail"])
                )
            elif availability["state"] == "resolved-to-nothing":
                # #809: third state, same shape as everywhere else in this
                # loop -- `available`, `BLOCKED`, and "this lane names no
                # file on disk, so nothing was compared". Never folded into
                # `available`, the dangerous direction: a lane that resolved
                # to nothing is not confirmed free, it is unnamed.
                lines.append(
                    "  verdict : RESOLVED TO NOTHING -- {0}".format(
                        availability["detail"]
                    )
                )
            else:
                lines.append(
                    "  verdict : COULD NOT DERIVE THE HELD SET -- {0}".format(
                        availability["detail"]
                    )
                )
        # #432: guards the lane side's own files trip -- a narrowed local test
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
    if result["state"] == "candidates":
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
    if result["state"] == "none":
        return "none -- {0}".format(result["detail"])
    return "COULD NOT TELL -- {0}".format(result["detail"])


def main(argv=None):
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
        "--against",
        action="append",
        default=[],
        metavar="PATTERN",
        help="a file or glob to check --lane against for overlap; repeatable (#267)",
    )
    parser.add_argument(
        "--derive-held",
        action="store_true",
        help="derive the against side instead of accepting it -- from every open "
        "pull request's file list and every live lane record's own files (#558); "
        "refused together with --against, since a derived exclusion and a "
        "hand-typed one beside it is exactly the ambiguity this exists to close",
    )
    parser.add_argument(
        "--claim",
        action="store_true",
        help="write this lane's own record to the registry (#705); every other "
        "call -- including one carrying --lane or --derive-held -- is a read and "
        "writes nothing, so probing candidate lanes never leaves a phantom "
        "record behind. Pass this only at the moment this lane is actually "
        "dispatched.",
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
        "issue is the lane's primary issue. Requires --label-issues and "
        "--label-phrase; every other flag is ignored when this is given.",
    )
    parser.add_argument(
        "--label-issues",
        default=None,
        metavar="N,N,...",
        help="every issue this lane carries, primary included, comma-separated "
        "-- an omitted or partial bundle is exactly the label #539 was filed "
        "about, so this is required together with --label.",
    )
    parser.add_argument(
        "--label-phrase",
        default=None,
        metavar="PHRASE",
        help="the short description of what the lane is doing.",
    )
    parser.add_argument(
        "--label-subagent",
        default=None,
        metavar="TYPE",
        help="given together with --label, render the whole literal "
        "Agent(...) call (#989) instead of only the description string.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="passed straight through to the rendered Agent(...) call; only "
        "meaningful together with --label and --label-subagent.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="passed straight through to the rendered Agent(...) call's "
        "run_in_background field; only meaningful together with --label and "
        "--label-subagent.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="release this issue's own lane record (#734), instead of computing "
        "setup facts -- call this once the merge step has independently "
        "verified the pull request merged (state/mergedAt/mergeCommit read "
        "back off the remote), so a follow-up dispatched minutes later never "
        "reads this lane as still held. Exits 0 whether or not a record "
        "existed to release; every other flag is ignored when this is given.",
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
        "--check-vanished",
        action="store_true",
        help="#845: report every live lane record whose own worktree "
        "directory is confirmed absent -- a loud detector for a worktree "
        "that disappeared mid-run, caused by no command this file issues "
        "(the mechanism was not found in this plugin's own code). Reads "
        "worktree_root from .oss.local.json the same way --release does, "
        "needs no issue number, and refuses every other mode flag "
        "alongside it (--claim, --release, --derive-held, --against, "
        "--suggest-companions).",
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
        "(--claim, --release, --derive-held, --against) alongside it.",
    )
    args = parser.parse_args(argv)

    if args.suggest_companions is not None:
        if args.issue is not None:
            parser.error(
                "--suggest-companions carries its own issue number as its "
                "argument; drop the positional issue argument"
            )
        for flag_name, flag_value in (
            ("--claim", args.claim),
            ("--release", args.release),
            ("--derive-held", args.derive_held),
            ("--against", bool(args.against)),
            ("--check-vanished", args.check_vanished),
        ):
            if flag_value:
                parser.error(
                    "--suggest-companions and {0} are mutually exclusive -- "
                    "the sweep answers a different question than any of "
                    "this file's other modes (#851, #845)".format(flag_name)
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
            # measurement, so it is refused at the boundary the way --claim
            # already refuses a fileless claim (#788).
            parser.error(
                "--suggest-companions requires --lane (#851) -- with no claimed "
                "file set the sweep compares every issue against nothing and "
                "reports a confident `none` about a lane that was never named; "
                "pass --lane once per file this lane holds"
            )
    elif args.check_vanished:
        for flag_name, flag_value in (
            ("--claim", args.claim),
            ("--release", args.release),
            ("--derive-held", args.derive_held),
            ("--against", bool(args.against)),
        ):
            if flag_value:
                parser.error(
                    "--check-vanished and {0} are mutually exclusive -- it "
                    "answers a different question than any of this file's "
                    "other modes (#845)".format(flag_name)
                )
    elif args.issue is None and not args.label:
        parser.error(
            "the issue argument is required unless --suggest-companions, "
            "--check-vanished or --label is given"
        )

    if args.derive_held and args.against:
        parser.error("--derive-held and --against are mutually exclusive (#558)")

    if args.claim and not args.lane and not args.release:
        # #788: the documented dispatch-time call used to be `--claim` with no
        # `--lane` at all, which writes a fileless lane record -- indistinguishable
        # at write time from a well-formed one, and indistinguishable from every
        # OTHER live lane's record once written. `derive_held_set` then has to
        # treat the held set as untrustworthy while that record is live (its own
        # `held_from_live_lanes` detail names the cause: "recorded without
        # --lane"), which poisons every later --derive-held call this tick, not
        # just this one's own probe -- the fallback #558 exists to retire. Refuse
        # the write instead of the state it produces, the same shape
        # `fleet_label.py` already refuses an incomplete label bundle rather than
        # composing one from a missing piece.
        parser.error(
            "--claim requires --lane (#788) -- a claim with no files writes a "
            "fileless lane record, which poisons every later --derive-held call "
            "this tick; pass --lane once per file this lane touches, the same "
            "patterns already used to probe this candidate"
        )

    if args.label:
        for flag_name, flag_value in (
            ("--claim", args.claim),
            ("--release", args.release),
            ("--derive-held", args.derive_held),
            ("--against", bool(args.against)),
            ("--check-vanished", args.check_vanished),
            ("--suggest-companions", args.suggest_companions is not None),
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
                output = lane_setup_label.fleet_label(
                    args.issue, issues, args.label_phrase
                )
            else:
                output = lane_setup_label.agent_call(
                    args.issue,
                    issues,
                    args.label_phrase,
                    args.label_subagent,
                    model=args.model,
                    run_in_background=args.background,
                )
        except lane_setup_label.FleetLabelError as exc:
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
            EXIT_OK if result["state"] in ("candidates", "none") else EXIT_COULD_NOT_RUN
        )

    if args.release:
        config, problems = oss_config.load(Path(args.repo) / CONFIG_NAME)
        # #791 fixed the case where `config` is None -- the project half could
        # not be read at all, absent or malformed. #803: that is not the only
        # way a real read failure hides in `problems`. `worktree_root` only
        # ever lives in `.oss.local.json` (`LOCAL_KEYS`), so when the *local*
        # half is present but unparseable, `oss_config.load` returns a
        # non-None `config` -- with no `worktree_root` key, since the
        # unreadable local half was never merged in -- and the parse error
        # sitting in `problems` right beside advisory findings that fire on
        # every config missing `worktree_root`, read failure or not (a
        # "missing required key: worktree_root" entry, chiefly). Gating on
        # `config is None` alone dropped the local parse error and rendered
        # it identically to the genuinely benign "no worktree_root configured
        # here" case `release_lane` reports below.
        #
        # A first version of this fix scanned `problems` for the substring
        # "could not", reasoning that `_read_json_object`'s own read-failure
        # messages ("could not read/decode/parse") were the only ones that
        # used it. That reasoning was never checked against the rest of
        # `oss_config.py` and was wrong: `test_command_problem`'s own
        # advisory ("...or null when the probe could not tell; got ...")
        # contains the same substring, so a config with a perfectly readable,
        # perfectly known `worktree_root` and an unrelated malformed
        # `test_command` field was blocked from releasing at all (found in
        # this diff's own review round). Ask the one question this arm
        # actually needs answered instead of inferring it from prose
        # elsewhere in the list: did *the local file itself* fail to parse?
        # Re-read it with the exact primitive `load()` uses internally for
        # both halves, so this stays one read failure, one fact, rather than
        # a second implementation of JSON/encoding error handling that could
        # drift from `oss_config`'s own.
        local_read_problem = None
        if config is not None:
            _, local_read_problem = oss_config._read_json_object(
                oss_config.local_config_path(Path(args.repo) / CONFIG_NAME)
            )
        if config is None or local_read_problem is not None:
            result = {
                "state": "could-not-release",
                "path": None,
                "detail": "worktree_root is not known -- the config could not "
                "be read: {0}".format(
                    "; ".join(problems) if problems else "no detail available."
                ),
            }
        else:
            worktree_root = config.get("worktree_root")
            # #1069: the mirror of --claim -- release both the local lane
            # record AND the GitHub assignee in one call, closing the gap
            # `.claude/jit-context/tools/01-oss/pr-create-gate.md` used to
            # patch with a prose reminder to run the assignee release by
            # hand after a merge.
            combined = lane_setup_claim.release_lane_and_assignee(
                worktree_root,
                args.issue,
                also_release=args.release_also,
                repo=config.get("repo"),
            )
            result = combined["record"]
        if args.json:
            if config is not None and local_read_problem is None:
                print(json.dumps(combined, indent=2, sort_keys=True))
            else:
                print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(
                "RELEASE #{0}: {1}{2}".format(
                    args.issue,
                    result["state"],
                    " -- " + result["detail"] if result["detail"] else "",
                )
            )
            if config is not None and local_read_problem is None:
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

    if args.check_vanished:
        config, problems = oss_config.load(Path(args.repo) / CONFIG_NAME)
        local_read_problem = None
        if config is not None:
            _, local_read_problem = oss_config._read_json_object(
                oss_config.local_config_path(Path(args.repo) / CONFIG_NAME)
            )
        if config is None or local_read_problem is not None:
            result = {
                "state": "could-not-run",
                "vanished": [],
                "detail": "worktree_root is not known -- the config could not "
                "be read: {0}".format(
                    "; ".join(problems) if problems else "no detail available."
                ),
            }
        else:
            worktree_root = config.get("worktree_root")
            result = lane_setup_claim.detect_vanished_worktrees(worktree_root)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            if result["state"] == "resolved" and result["vanished"]:
                lines = [
                    "VANISHED WORKTREES: {0} live lane record(s) whose own "
                    "worktree directory is confirmed absent".format(
                        len(result["vanished"])
                    )
                ]
                for entry in result["vanished"]:
                    lines.append(
                        "  lane #{0} branch={1} path={2} recorded_at={3}".format(
                            entry["issue"],
                            entry["branch"],
                            entry["path"],
                            entry["recorded_at"],
                        )
                    )
                print("\n".join(lines))
            else:
                print(
                    "VANISHED WORKTREES: {0}{1}".format(
                        result["state"],
                        " -- " + result["detail"]
                        if result["detail"]
                        else " -- none found",
                    )
                )
        if result["state"] == "could-not-run":
            return EXIT_COULD_NOT_RUN
        return 1 if result.get("vanished") else EXIT_OK

    payload = compute(
        args.repo,
        args.issue,
        args.remote,
        args.lane,
        args.against,
        derive_held=args.derive_held,
        claim=args.claim,
        stack_on=args.stack_on,
        also_claim=args.claim_also,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return EXIT_COULD_NOT_RUN if blocked(payload) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
