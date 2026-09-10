#!/usr/bin/env python3
"""What does this repo need now? -- #1389's own addendum, ranked rather than
arbitrated by #1405.

`/oss:run` answers one question -- what does this repo need now -- from state and
config, never from an argument. This module is that answer, as a call rather than
prose a session re-derives every time: the same shape `select_issues.py` already
gave dispatch (#970), composing scripts that already existed rather than
re-implementing any of them.

## Rank, do not arbitrate (#1405)

The first cut of this module (#1389/#1390/#1392, PR #1404) returned one verdict,
picked by a fixed precedence order that stopped at the first fired or unresolved
check. That forces the script to arbitrate between things it has no basis to
compare -- is an unanswered external pull request more urgent than a release
that is due? That is a judgement about this repository at this moment, and a
threshold comparison cannot make it.

So `rank()` composes every source every time and returns them **ordered**,
never stopping early: `select_issues.py` is the precedent this repository
already has for the split -- the script measures, the agent decides, including
taking the second candidate over the first when it can see something this
script cannot.

Three requirements, from #1405's own issue text, and the third is what keeps a
deviation honest:

1. **Every candidate carries its own evidence** -- the threshold, the reading,
   the value compared against -- in its `evidence` field, so skipping the top
   entry is a decision against stated evidence rather than a whim.
2. **A candidate whose reading could not be taken is listed as
   `could-not-tell`, never dropped.** It still occupies a rank slot, ordered
   the same way a `due` one would be -- a short candidate list and one that
   could not be fully built must not render alike.
3. **A skip is recorded.** `record_skip()` below composes the one-line
   decision `oss_state.append` already takes per tick, naming which candidate
   was taken and which higher-ranked one was not, so a loop skipping the top
   candidate six ticks running is distinguishable from one that never had a
   top candidate.

## Four sources, not three (#1405 closes the composition gap)

`inbound` -- external issues still open (unruled) and external pull requests
still open (unreviewed), a fresh reading of `statusline.inbound_reading` --
`release`, `curate` and `triage`, the same three the first cut composed.
Evaluated in that order when more than one is due or unresolved; see
`DEFAULT_ORDER` below. Before #1405, `inbound_triage.py` (#1394) classified
exactly this kind of thing and nothing composed it with the rest -- a
repository with an unanswered external pull request and no release due got
`nothing-due`, while `skills/manager/phases/inbound.md`'s own step, reached
later in the tick, had real work waiting. Ranking closes that without an
arbitration rule: inbound is a candidate alongside the others, and where it
sits relative to them is the agent's call.

## `unsafe` is a refusal, not a candidate

#1390's own gap -- no config and the probe itself could not run, or a
`default_branch` that does not resolve to a real ref -- stays a distinct,
early top-level state, exactly as before. None of the four sources above can
be evaluated at all without a readable config and a resolvable default
branch, so this is a precondition for ranking, not one more thing to rank.
Named with a `remedy`, because "the loop refused to start" must never be a
dead end. `due: setup` (no `.oss.json` at all, but a probe is safe) is the
other early state that stays outside ranking for the identical reason.

## What this deliberately does not do

**No dispatch.** `nothing-due`'s `next: dispatch` is unchanged: this call
never runs `select_issues.py` to ask whether the board has a claimable
candidate. That question has its own three states already and belongs to the
phase that acts on this answer, not to the one naming it.

**No writes except one, narrow receipt**, the same `workspace_route_check`
mechanism the first cut used for curate and triage's own repeat-suppression
(see `_route_already_seen`) -- unchanged by this rewrite. `release_trigger`
and `triage_trigger` still need no such receipt: completing either action
moves the underlying signal itself.

**`unanswered_comments` is not computed.** `statusline.inbound_reading`'s own
docstring states why: a real count needs a per-thread walk this change does
not build. It reports `None` rather than a guessed `0` -- never silently
included in the inbound candidate's own due/not-due decision.

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_which  # noqa: E402
import oss_config  # noqa: E402
import oss_state  # noqa: E402
import release_trigger  # noqa: E402
import release_version  # noqa: E402
import statusline  # noqa: E402
import triage_trigger  # noqa: E402
import workspace_routes  # noqa: E402

# --- top-level states (about the call as a whole) --------------------------
DUE = "due"  # only ever `next: setup`, the pre-ranking case
RANKED = "ranked"
NOTHING_DUE = "nothing-due"
UNSAFE = "unsafe"

# --- per-candidate states (about one source) --------------------------------
CANDIDATE_DUE = "due"
CANDIDATE_COULD_NOT_TELL = "could-not-tell"
CANDIDATE_NOT_DUE = "not-due"

#: The order sources are placed in when more than one is `due` or
#: `could-not-tell` -- a default the ranking itself does not enforce as a
#: rule about urgency, only as a stable, documented tie-break so the same
#: board produces the same order every time. #1405's own worked example
#: ranks inbound first; the composition gap it names (an unanswered outside
#: pull request rendering identically to nothing pending at all) is the
#: reason this module puts it ahead of the other three by default rather
#: than leaving the order to insertion accident.
DEFAULT_ORDER = ("inbound", "release", "curate", "triage")


def _decode(raw):
    """Same shape as `workspace_routes._decode` -- a subprocess's bytes are free
    text nobody here authored, decoded for display rather than assumed."""
    if raw is None:
        return ""
    if not isinstance(raw, bytes):
        return raw
    return raw.decode("utf-8", "replace")


def _git(repo_root, *args, run=subprocess.run, git_bin=None, timeout=10):
    """(ok, output_or_reason). Never raises -- a missing `git`, a repo that is
    not a work tree, and a ref that does not resolve are all ordinary answers
    this call needs to report, not exceptions to propagate.

    `git_bin` is resolved through `gh_which.safe_which` by the caller, never a
    bare "git" argv[0] handed straight to `run` -- the same reasoning
    `workspace_routes.decide` already applies to `gh` (#1157/#1165): a
    same-named git.cmd/git.exe planted at the root of the inspected repo must
    not win over a real PATH entry on Windows."""
    command = [git_bin or "git", "-C", str(repo_root)] + list(args)
    try:
        done = run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "{0} did not run ({1})".format(" ".join(command), exc)
    if done.returncode != 0:
        message = (_decode(done.stderr) or _decode(done.stdout)).strip()
        return False, message or "{0} exited {1}".format(
            " ".join(command), done.returncode
        )
    return True, _decode(done.stdout).strip()


def _due(next_step, reason, evidence=None):
    return {
        "state": DUE,
        "next": next_step,
        "reason": reason,
        "evidence": evidence or {},
    }


def _unsafe(reason, remedy):
    return {"state": UNSAFE, "reason": reason, "remedy": remedy}


def _probe_preconditions(repo_root, run=subprocess.run, git_bin=None):
    """Would `oss_config.py --probe` have a chance of working? Never runs the
    probe itself -- this call has no business writing anything -- only the two
    facts a probe cannot substitute for: a real work tree, and a remote to read
    the repo slug and default branch off of."""
    ok, why = _git(
        repo_root, "rev-parse", "--is-inside-work-tree", run=run, git_bin=git_bin
    )
    if not ok:
        return (
            "{0} is not inside a git work tree ({1})".format(repo_root, why),
            "run this from inside a git checkout of the repository to maintain",
        )
    ok, why = _git(repo_root, "remote", "get-url", "origin", run=run, git_bin=git_bin)
    if not ok:
        return (
            "no `origin` remote is configured ({0})".format(why),
            "add an `origin` remote, or write .oss.json by hand and skip probing",
        )
    return None, None


def _default_branch_unreadable(repo_root, config, run=subprocess.run, git_bin=None):
    """None when `default_branch` resolves to a real ref (local or
    remote-tracking); otherwise the reason it does not."""
    branch = config.get("default_branch")
    if not isinstance(branch, str) or not branch.strip():
        return "default_branch is not set to a usable branch name"
    for ref in (
        "refs/remotes/origin/{0}".format(branch),
        "refs/heads/{0}".format(branch),
    ):
        ok, _why = _git(
            repo_root, "rev-parse", "--verify", ref, run=run, git_bin=git_bin
        )
        if ok:
            return None
    return (
        "default_branch {0!r} does not resolve to refs/remotes/origin/{0} or "
        "refs/heads/{0} in this checkout".format(branch)
    )


def _route_already_seen(repo_root, config, route, signature):
    """Self-review finding (Explore reviewer, #1389): the label-coverage curate
    and triage routes have no completion signal of their own the way
    `triage_trigger`'s tag-vs-last-sweep comparison does -- an interactive
    curate pass that does not fully drain `trap.d/` in one sitting, or a
    triage sweep that does not clear every missing label, leaves the exact
    same `over` reading behind. Without this check, a candidate would report
    `due` on that unchanged reading every single tick, reintroducing the
    permanent-divert defect #1390 exists to close, just one layer in from
    where #1064 originally fixed it for the launcher.

    Same shape as `workspace_routes.main`'s own receipt (#1064/#1155),
    relocated here because `next_action.py`, not the launcher, is what now
    makes this decision. Never raises -- any failure to read or write a
    receipt is announced by returning `False` (never "already seen", the
    same fail-open direction every other unknown in this module takes) and
    named in the returned detail rather than silently swallowed."""
    state_file = config.get("state_file")
    if not isinstance(state_file, str) or not state_file.strip():
        return False, "no state_file configured, so no receipt could be read or written"
    record_path = str(Path(repo_root) / state_file)
    try:
        _entry, prior_signature = oss_state._last_workspace_route(record_path, route)
        check = oss_state.workspace_route_check(route, signature, prior_signature)
    except Exception as exc:  # noqa: BLE001 -- fail open, name why
        return False, "the receipt comparison failed ({0}: {1})".format(
            type(exc).__name__, exc
        )
    if not check["armed"]:
        return True, "unchanged since the receipt already recorded ({0})".format(
            signature
        )
    try:
        oss_state.append(
            record_path,
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "next_action.py: recorded a #1155-shaped route receipt",
            detail={
                "workspace_route_name": route,
                "workspace_route_signature": signature,
            },
        )
    except Exception as exc:  # noqa: BLE001 -- announced, not raised
        return (
            False,
            "armed ({0}), but the receipt could not be recorded ({1}: {2})".format(
                check["state"], type(exc).__name__, exc
            ),
        )
    return False, "armed ({0})".format(check["state"])


def _routes(repo_root, config, gh=None, run=subprocess.run):
    """One `workspace_routes.decide` call, shared by the curate and triage
    checks below -- each reads its own repo-declared threshold-vs-count
    result out of it. Calling `decide` twice would cost a second `gh issue
    list` round trip for a fact the first call already has."""
    _armed, results = workspace_routes.decide(repo_root, config, gh=gh, run=run)
    return results


def _fresh_inbound_reading(repo):
    """The one place `next_action.py` reaches into `statusline.py` for its
    fresh, uncached reading (#1405's design note: one module, two
    consumers). `statusline.refresh()` calls `statusline.inbound_reading`
    for its own cached, throttled copy; this wrapper takes the two totals
    fresh and calls the identical function for a reading the loop can act on
    right now. A single injection point so a test can replace the whole
    reading without needing to fake two subprocess calls into `gh`."""
    issues_total = statusline._gh_count(repo, "issue")
    prs_total = statusline._gh_count(repo, "pr")
    return statusline.inbound_reading(repo, issues_total, prs_total)


def _inbound_candidate(repo_root, config):
    """#1405's fourth source, and the composition gap it names: an
    unanswered outside pull request or an unruled outside issue used to
    render identically to nothing pending at all. `unanswered_comments` is
    never part of this decision -- `statusline.inbound_reading` always
    reports it as `None`, and folding a `None` into `0` here would be
    exactly the false-zero this module is named after avoiding."""
    repo = config.get("repo")
    if not repo:
        return {
            "source": "inbound",
            "state": CANDIDATE_COULD_NOT_TELL,
            "reason": "no repo configured, so outside issues/pull requests cannot be counted",
            "evidence": {},
        }
    reading = _fresh_inbound_reading(repo)
    if reading.get("state") != "measured":
        return {
            "source": "inbound",
            "state": CANDIDATE_COULD_NOT_TELL,
            "reason": "the outside issue/pull-request count could not be taken",
            "evidence": reading,
        }
    unruled = reading.get("unruled_issues") or 0
    unreviewed = reading.get("unreviewed_prs") or 0
    if unruled + unreviewed > 0:
        return {
            "source": "inbound",
            "state": CANDIDATE_DUE,
            "reason": "{0} outside issue(s) unruled, {1} outside pull request(s) unreviewed".format(
                unruled, unreviewed
            ),
            "evidence": reading,
        }
    return {
        "source": "inbound",
        "state": CANDIDATE_NOT_DUE,
        "reason": "no outside issues or pull requests waiting (comments are not checked yet)",
        "evidence": reading,
    }


def _release_candidate(repo_root, config, now=None):
    """Self-review finding from the first cut (#1389): a genuinely
    misconfigured `changelog_dir` (refused, unrecognised, a bare `--dir` on
    a scaffolded gate) must not fall through to `release_trigger.compute`'s
    own default-directory fallback exactly like the ordinary, no-fragment-
    practice repo does -- two different facts must not render as one silent
    substitution. `release_version.NO_DIRECTORY` alone is the ordinary case;
    every other named problem is a `could-not-tell` reading for this source."""
    fragment_dir, fragment_dir_problem = release_version._fragment_dir(
        str(repo_root), None, config
    )
    if fragment_dir is None and fragment_dir_problem != release_version.NO_DIRECTORY:
        return {
            "source": "release",
            "state": CANDIDATE_COULD_NOT_TELL,
            "reason": (
                "changelog_dir could not be resolved ({0}), so whether the "
                "release trigger's user-visible-soak condition holds is "
                "unknown".format(fragment_dir_problem)
            ),
            "evidence": {"fragment_dir_problem": fragment_dir_problem},
        }
    rel = release_trigger.compute(
        str(repo_root),
        config=config,
        findings=None,
        fragment_dir=fragment_dir,
        now=now,
    )
    if rel["state"] == release_trigger.STATE_FIRED:
        return {
            "source": "release",
            "state": CANDIDATE_DUE,
            "reason": "release trigger fired on {0}".format(", ".join(rel["fired"])),
            "evidence": rel,
        }
    if rel["state"] == release_trigger.STATE_COULD_NOT_TELL:
        return {
            "source": "release",
            "state": CANDIDATE_COULD_NOT_TELL,
            "reason": (
                "the release trigger could not be evaluated ({0} unread), so "
                "whether a release is the most urgent action is unknown".format(
                    ", ".join(rel["unevaluated"])
                )
            ),
            "evidence": rel,
        }
    return {
        "source": "release",
        "state": CANDIDATE_NOT_DUE,
        "reason": "release trigger not fired",
        "evidence": rel,
    }


def _curate_candidate(repo_root, config, routes):
    curate = routes.get("curate", {"configured": False})
    if curate.get("configured"):
        if curate.get("state") == workspace_routes.OVER:
            signature = "{0}:{1}".format(curate.get("state"), curate.get("count"))
            seen, seen_detail = _route_already_seen(
                repo_root, config, "curate", signature
            )
            if not seen:
                return {
                    "source": "curate",
                    "state": CANDIDATE_DUE,
                    "reason": (
                        "trap.d/ has {0} fragment(s), over curate_route_threshold "
                        "({1})".format(curate.get("count"), curate.get("threshold"))
                    ),
                    "evidence": dict(curate, receipt=seen_detail),
                }
            return {
                "source": "curate",
                "state": CANDIDATE_NOT_DUE,
                "reason": "unchanged since the last time this reading was routed ({0})".format(
                    seen_detail
                ),
                "evidence": dict(curate, receipt=seen_detail),
            }
        if curate.get("state") == workspace_routes.COULD_NOT_COUNT:
            return {
                "source": "curate",
                "state": CANDIDATE_COULD_NOT_TELL,
                "reason": "the trap.d/ backlog could not be counted ({0})".format(
                    curate.get("why")
                ),
                "evidence": curate,
            }
    return {
        "source": "curate",
        "state": CANDIDATE_NOT_DUE,
        "reason": "trap.d/ is not over curate_route_threshold (or curate is not configured)",
        "evidence": curate,
    }


def _triage_candidate(repo_root, config, routes):
    """Two independent triage signals, not one -- unchanged from the first
    cut. `triage_trigger.py` (#1386) reads "last sweep older than the last
    tag"; `workspace_routes`'s label-coverage route (missing
    `lane-*`/`priority-*`) is checked only once the first cleanly reports
    `not-due`. Neither displaces the other."""
    state_file = config.get("state_file")
    state_path = (
        str(Path(repo_root) / state_file)
        if isinstance(state_file, str) and state_file.strip()
        else None
    )
    tt = triage_trigger.compute(str(repo_root), config=config, state_path=state_path)
    if tt["state"] == triage_trigger.STATE_DUE:
        return {
            "source": "triage",
            "state": CANDIDATE_DUE,
            "reason": tt.get("detail", "triage_trigger: due"),
            "evidence": tt,
        }
    if tt["state"] == triage_trigger.STATE_COULD_NOT_TELL:
        return {
            "source": "triage",
            "state": CANDIDATE_COULD_NOT_TELL,
            "reason": "the post-release triage trigger could not be evaluated ({0})".format(
                tt.get("detail")
            ),
            "evidence": tt,
        }

    triage = routes.get("triage", {"configured": False})
    if triage.get("configured"):
        if triage.get("state") == workspace_routes.OVER:
            signature = "{0}:{1}".format(triage.get("state"), triage.get("count"))
            seen, seen_detail = _route_already_seen(
                repo_root, config, "triage", signature
            )
            if not seen:
                return {
                    "source": "triage",
                    "state": CANDIDATE_DUE,
                    "reason": "{0}".format(triage.get("why")),
                    "evidence": dict(triage, receipt=seen_detail),
                }
            return {
                "source": "triage",
                "state": CANDIDATE_NOT_DUE,
                "reason": "unchanged since the last time this reading was routed ({0})".format(
                    seen_detail
                ),
                "evidence": dict(triage, receipt=seen_detail),
            }
        if triage.get("state") == workspace_routes.COULD_NOT_COUNT:
            return {
                "source": "triage",
                "state": CANDIDATE_COULD_NOT_TELL,
                "reason": "the triage backlog could not be counted ({0})".format(
                    triage.get("why")
                ),
                "evidence": triage,
            }
    return {
        "source": "triage",
        "state": CANDIDATE_NOT_DUE,
        "reason": (
            "post-release triage trigger not due and the label-coverage "
            "triage route is not over its threshold (or not configured)"
        ),
        "evidence": {"triage_trigger": tt, "triage_route": triage},
    }


def rank(repo_root, run=subprocess.run, gh=None, git_bin=None, now=None):
    """The whole answer, in one call. Never raises.

    `git_bin` is resolved through `gh_which.safe_which` once here, the same
    way `gh` already is below -- never a bare "git" argv[0]."""
    repo_root = Path(repo_root)
    git_bin = git_bin if git_bin is not None else gh_which.safe_which("git")
    config_path = repo_root / ".oss.json"
    config, problems = oss_config.load(config_path)

    if config is None:
        reason, remedy = _probe_preconditions(repo_root, run=run, git_bin=git_bin)
        if reason is not None:
            return _unsafe(reason, remedy)
        return _due(
            "setup",
            "no .oss.json at {0}; probing this repository and writing one is safe here".format(
                config_path
            ),
            evidence={"load_problems": problems},
        )

    unreadable = _default_branch_unreadable(repo_root, config, run=run, git_bin=git_bin)
    if unreadable is not None:
        return _unsafe(
            unreadable,
            "fix default_branch in .oss.json, or repair the repository's remote-tracking ref",
        )

    gh = gh if gh is not None else gh_which.safe_which("gh")
    routes = _routes(repo_root, config, gh=gh, run=run)

    by_source = {
        "inbound": _inbound_candidate(repo_root, config),
        "release": _release_candidate(repo_root, config, now=now),
        "curate": _curate_candidate(repo_root, config, routes),
        "triage": _triage_candidate(repo_root, config, routes),
    }

    candidates = []
    not_due = []
    for source in DEFAULT_ORDER:
        entry = by_source[source]
        if entry["state"] in (CANDIDATE_DUE, CANDIDATE_COULD_NOT_TELL):
            candidates.append(entry)
        else:
            not_due.append(entry)

    for index, entry in enumerate(candidates, start=1):
        entry["rank"] = index

    if not candidates:
        return {
            "state": NOTHING_DUE,
            "next": "dispatch",
            "reason": (
                "every source resolved cleanly (inbound, release, curate, "
                "triage) and none of them is due"
            ),
            "not_due": not_due,
        }
    return {
        "state": RANKED,
        "candidates": candidates,
        "not_due": not_due,
    }


def record_skip(state_path, candidates, taken_source, reason, at=None):
    """#1405's third requirement: a skip is recorded, mechanically, so a
    loop skipping the top candidate six ticks running is distinguishable
    from one that never had a top candidate.

    Only for a genuine deviation -- `candidates` is `rank()`'s own ordered
    list, and this raises `ValueError` rather than silently writing a
    no-op entry when `taken_source` already matches `candidates[0]`
    (nothing was skipped) or when `candidates` is empty (there was no top
    candidate to skip past). Composes `oss_state.append`'s one decision
    line rather than leaving callers to hand-write a sentence each time,
    which is exactly the drift #1405's own issue text warns against.
    """
    if not candidates:
        raise ValueError(
            "record_skip needs a non-empty candidate list to skip past -- "
            "there was no top candidate here"
        )
    top = candidates[0]
    if top.get("source") == taken_source:
        raise ValueError(
            "record_skip is for a deviation only -- the top candidate is "
            "already {0!r}, matching taken_source; there is nothing to "
            "record".format(top.get("source"))
        )
    at = at if at is not None else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    decision = "took {0} over {1} ({2})".format(taken_source, top.get("source"), reason)
    return oss_state.append(state_path, at, decision)


def receipt(payload):
    """One block a human reads, thresholds and evidence named rather than
    recalled -- same argument `release_trigger.receipt` makes for its own
    payload."""
    state = payload["state"]
    lines = ["next-action: {0}".format(state)]
    if state == UNSAFE:
        lines.append("  reason: {0}".format(payload["reason"]))
        lines.append("  remedy: {0}".format(payload["remedy"]))
    elif state == DUE:
        lines.append("  next: {0}".format(payload["next"]))
        lines.append("  reason: {0}".format(payload["reason"]))
    elif state == NOTHING_DUE:
        lines.append("  next: dispatch")
        lines.append("  reason: {0}".format(payload["reason"]))
        for entry in payload.get("not_due", []):
            lines.append(
                "  -- not due: {0} ({1})".format(entry["source"], entry["reason"])
            )
    elif state == RANKED:
        for entry in payload["candidates"]:
            marker = (
                entry["rank"] if entry["state"] == CANDIDATE_DUE else "could-not-tell"
            )
            lines.append(
                "  {0}. {1}  -- {2}".format(marker, entry["source"], entry["reason"])
            )
        for entry in payload.get("not_due", []):
            lines.append(
                "  -- not ranked: {0} ({1})".format(entry["source"], entry["reason"])
            )
    return "\n".join(lines)


def _build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit the payload as JSON")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    payload = rank(args.root)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
