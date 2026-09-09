#!/usr/bin/env python3
"""What does this repo need now? -- #1389's own addendum.

`/oss:run` answers one question -- what does this repo need now -- from state and
config, never from an argument. This module is that answer, as a call rather than
prose a session re-derives every time: the same shape `select_issues.py` already
gave dispatch (#970), composing scripts that already existed rather than
re-implementing any of them.

## What this composes, and does not re-implement

- **Config presence** -- `oss_config.load`. `None` back means no `.oss.json`, which
  is not a failure to route around; it is the first, most specific answer.
- **The release trigger** -- `release_trigger.compute`, the one this repository's
  own release gate reads (`skills/manager/phases/release.md`): merged PR count,
  soak hours, a blocking finding. This module never passes `findings`, the same
  restraint `release_trigger` itself documents: a tick that ran no audit has
  nothing to say about a blocking finding, and `not-supplied` is not `not-met`.
- **The curate and triage backlog routes** -- `workspace_routes.decide`, built for
  the sibling question `bin/oss-workspace` already asks at launch (#1155). Its own
  `release` sub-route (a changelog-fragment count) is deliberately NOT read here --
  `release_trigger.compute` is the trigger this loop actually gates a release on,
  and reading both would let two different notions of "release is due" disagree
  with each other inside one answer.

## Four states, not three, and the fourth is #1390's own vocabulary

  due               something specific is needed now, named in `next`: `setup`,
                    `release`, `curate` or `triage`.
  nothing-due       every check that could run, ran, resolved cleanly, and none
                    of them fired. `next` is `dispatch` -- the ordinary cadence
                    applies, board work has not been ruled in or out at this
                    layer.
  could-not-decide  a check that outranks the point reached could not be
                    evaluated, so a lower-ranked "nothing fired" cannot be
                    trusted -- the unresolved check might have been the real
                    answer. **Never collapses into `nothing-due`.**
  unsafe            #1390's own gap: no config and the probe itself could not
                    run, or a `default_branch` that does not resolve to a real
                    ref. Named with a `remedy` -- what would clear it -- because
                    "the loop refused to start" must never be a dead end.

## Precedence, and why an unresolved check blocks rather than being skipped

Evaluated strictly in this order, stopping at the first `due` or the first
check this call could not read: release trigger, curate backlog, triage
backlog, then `nothing-due`. A `could-not-tell` release trigger blocks a
verdict on curate or triage even when both of those DID resolve cleanly --
the point of the exercise is naming the single most urgent action, and an
unresolved higher-precedence signal might have been that action. An
unresolved LOWER-precedence signal never reaches this problem, because the
walk stops before it is read.

## What this deliberately does not do

**Two independent triage signals, not one.** `scripts/triage_trigger.py`
(#1386, landed after this module's own first cut) reads exactly the "last
sweep older than the last tag" signal #1389's own issue text describes, and
is checked first; `workspace_routes`'s label-coverage route (missing
`lane-*`/`priority-*`) is checked second, only once the first cleanly reports
`not-due`. Neither displaces the other -- a repo can decline
`triage_after_release` and still be routed to triage on label coverage alone.

**No dispatch.** `next: dispatch` names the residual state; it never runs
`select_issues.py` to ask whether the board actually has a claimable
candidate. That question has its own three states already (`candidates` /
`none-available` / `could-not-select`) and belongs to the phase that acts on
this answer, not to the one naming it.

**No writes except one, narrow receipt.** This call never writes `.oss.json`
and never runs `oss_config.py --probe` -- that stays the caller's job, taken
only once `due: setup` has actually been acted on. It DOES record a
`workspace_route_check`-shaped receipt (#1064/#1155's own mechanism,
relocated here) for the label-coverage curate and triage routes only, the
first time each exact `over` reading is reported due -- self-review found
that without it, `/oss:run`'s own decide-act-decide-again loop would report
the identical unresolved backlog `due` forever, which is exactly the
permanent-divert defect #1390 exists to close, one layer in from where #1064
originally fixed it for the launcher. `release_trigger` and `triage_trigger`
need no such receipt: completing either action moves the underlying signal
itself (a merged-PR delta resets after a real release; a recorded triage
sweep moves `oss_state.last_triage` past the tag), so both are naturally
self-resolving without this module remembering anything.

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
import triage_trigger  # noqa: E402
import workspace_routes  # noqa: E402

DUE = "due"
NOTHING_DUE = "nothing-due"
COULD_NOT_DECIDE = "could-not-decide"
UNSAFE = "unsafe"


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


def _nothing_due(reason, evidence=None):
    return {
        "state": NOTHING_DUE,
        "next": "dispatch",
        "reason": reason,
        "evidence": evidence or {},
    }


def _could_not_decide(reason, blocked_on, evidence=None):
    return {
        "state": COULD_NOT_DECIDE,
        "reason": reason,
        "blocked_on": blocked_on,
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
    """Self-review finding (Explore reviewer): the label-coverage curate and
    triage routes have no completion signal of their own the way
    `triage_trigger`'s tag-vs-last-sweep comparison does -- an interactive
    curate pass that does not fully drain `trap.d/` in one sitting, or a
    triage sweep that does not clear every missing label, leaves the exact
    same `over` reading behind. Without this check, `/oss:run`'s own loop
    (decide -> take the step -> decide again) would report `due` on that
    unchanged reading forever, reintroducing the permanent-divert defect
    #1390 exists to close, just one layer in from where #1064 originally
    fixed it for the launcher.

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
    list` round trip for a fact the first call already has.

    The triage slot is the one #1386 is expected to widen: today this reads
    `workspace_routes`'s label-coverage route (missing `lane-*`/`priority-*`);
    a second signal (staleness against the last tag) can be folded in by
    combining it with this result before returning, without the precedence
    walk in `decide()` above changing at all."""
    _armed, results = workspace_routes.decide(repo_root, config, gh=gh, run=run)
    return results


def decide(repo_root, run=subprocess.run, gh=None, git_bin=None, now=None):
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

    # Self-review finding: the first cut of this call discarded `_fragment_dir`'s
    # own `problem` half, so a genuinely misconfigured `changelog_dir` (refused,
    # unrecognised, a bare `--dir` on a scaffolded gate) fell through to
    # `release_trigger.compute`'s own default-directory fallback exactly like the
    # ordinary, no-fragment-practice repo does -- two different facts rendered as
    # one silent substitution. `release_version.NO_DIRECTORY` alone is the
    # ordinary case (`commands/setup.md` calls it "not a finding on its own");
    # every other named problem is real and blocks the same way an unresolved
    # release-trigger condition already does, a few lines below.
    fragment_dir, fragment_dir_problem = release_version._fragment_dir(
        str(repo_root), None, config
    )
    if fragment_dir is None and fragment_dir_problem != release_version.NO_DIRECTORY:
        return _could_not_decide(
            "changelog_dir could not be resolved ({0}), so whether the release "
            "trigger's user-visible-soak condition holds is unknown".format(
                fragment_dir_problem
            ),
            "release",
            evidence={"fragment_dir_problem": fragment_dir_problem},
        )

    rel = release_trigger.compute(
        str(repo_root),
        config=config,
        findings=None,
        fragment_dir=fragment_dir,
        now=now,
    )
    if rel["state"] == release_trigger.STATE_FIRED:
        return _due(
            "release",
            "release trigger fired on {0}".format(", ".join(rel["fired"])),
            evidence=rel,
        )
    if rel["state"] == release_trigger.STATE_COULD_NOT_TELL:
        return _could_not_decide(
            "the release trigger could not be evaluated ({0} unread), so whether a "
            "release is the most urgent action is unknown".format(
                ", ".join(rel["unevaluated"])
            ),
            "release",
            evidence=rel,
        )

    routes = _routes(repo_root, config, gh=gh, run=run)
    curate = routes.get("curate", {"configured": False})
    if curate.get("configured"):
        if curate.get("state") == workspace_routes.OVER:
            curate_signature = "{0}:{1}".format(
                curate.get("state"), curate.get("count")
            )
            seen, seen_detail = _route_already_seen(
                repo_root, config, "curate", curate_signature
            )
            if not seen:
                return _due(
                    "curate",
                    "trap.d/ has {0} fragment(s), over curate_route_threshold ({1})".format(
                        curate.get("count"), curate.get("threshold")
                    ),
                    evidence=dict(curate, receipt=seen_detail),
                )
            # Unchanged since the last time this exact reading was routed --
            # fall through rather than re-arming forever on a backlog nobody
            # has cleared yet (self-review finding, see `_route_already_seen`).
        if curate.get("state") == workspace_routes.COULD_NOT_COUNT:
            return _could_not_decide(
                "the trap.d/ backlog could not be counted ({0})".format(
                    curate.get("why")
                ),
                "curate",
                evidence=curate,
            )

    # #1386 landed `scripts/triage_trigger.py` after this module's own first
    # cut, which reads exactly the "last sweep older than the last tag" signal
    # #1389's own issue text describes -- checked first, ahead of the
    # label-coverage route below, because it is the more specific of the two:
    # `triggers.triage_after_release` absent means the repo declined it, in
    # which case this call is a clean `not-due` and the label-coverage route
    # still gets its turn.
    state_file = config.get("state_file")
    state_path = (
        str(Path(repo_root) / state_file)
        if isinstance(state_file, str) and state_file.strip()
        else None
    )
    tt = triage_trigger.compute(str(repo_root), config=config, state_path=state_path)
    if tt["state"] == triage_trigger.STATE_DUE:
        return _due("triage", tt.get("detail", "triage_trigger: due"), evidence=tt)
    if tt["state"] == triage_trigger.STATE_COULD_NOT_TELL:
        return _could_not_decide(
            "the post-release triage trigger could not be evaluated ({0})".format(
                tt.get("detail")
            ),
            "triage",
            evidence=tt,
        )

    triage = routes.get("triage", {"configured": False})
    if triage.get("configured"):
        if triage.get("state") == workspace_routes.OVER:
            triage_signature = "{0}:{1}".format(
                triage.get("state"), triage.get("count")
            )
            seen, seen_detail = _route_already_seen(
                repo_root, config, "triage", triage_signature
            )
            if not seen:
                return _due(
                    "triage",
                    "{0}".format(triage.get("why")),
                    evidence=dict(triage, receipt=seen_detail),
                )
            # Unchanged since the last time this exact reading was routed --
            # see the identical comment on the curate branch above.
        if triage.get("state") == workspace_routes.COULD_NOT_COUNT:
            return _could_not_decide(
                "the triage backlog could not be counted ({0})".format(
                    triage.get("why")
                ),
                "triage",
                evidence=triage,
            )

    return _nothing_due(
        "release trigger not fired, the post-release triage trigger is not due, "
        "and neither curate nor the label-coverage triage route is over its "
        "configured threshold (or neither is configured)",
        evidence={
            "release": rel,
            "curate": curate,
            "triage_trigger": tt,
            "triage": triage,
        },
    )


def receipt(payload):
    """One block a human reads, thresholds and evidence named rather than
    recalled -- same argument `release_trigger.receipt` makes for its own
    payload."""
    state = payload["state"]
    lines = ["next-action: {0}".format(state)]
    if state == UNSAFE:
        lines.append("  reason: {0}".format(payload["reason"]))
        lines.append("  remedy: {0}".format(payload["remedy"]))
    elif state == COULD_NOT_DECIDE:
        lines.append("  blocked-on: {0}".format(payload["blocked_on"]))
        lines.append("  reason: {0}".format(payload["reason"]))
    else:
        lines.append("  next: {0}".format(payload["next"]))
        lines.append("  reason: {0}".format(payload["reason"]))
    return "\n".join(lines)


def _build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit the payload as JSON")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    payload = decide(args.root)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
