#!/usr/bin/env python3
"""Freeze a cohort AND record it, in one call a releaser makes -- #1410.

`cohort_freeze.py` (#917) already makes the LABEL WRITE reproducible: membership is
derived from the tag object's own timestamp, never from `now`, and it reports one of
four states so a wall of per-issue failures never renders as an empty cohort. Its own
docstring names what it deliberately leaves undone: "It does not yet feed the two-route
`cohort_freeze` check ... still confirm a second route before recording
`detail.cohort_freeze`" (`skills/manager/phases/accounting.md`). That confirmation, the
state-file write, and refreshing the label's own description were three more steps a
maintainer ran by hand, from a paragraph rather than from anything a test can hold --
and a hand step at the tag is exactly the class #917 already fixed the label-write half
of. `v0.31.0` froze cohort-28 at 14; it became 15 minutes later when #383 was reopened.
Every step was correct when taken -- the count was read at one moment and trusted at
another, the same drift #917's own docstring names for label membership, one layer up.

This module composes `cohort_freeze.freeze` (labels) with
`oss_state.cohort_freeze_from_pairs` (the two-route count) and a `gh label edit` for the
description. When `--execute` runs the actual write, it reports one of three states,
never `cohort_freeze.py`'s four -- the caller here is a releaser deciding whether the
freeze is *done*, not a maintainer reading which finer-grained reason applied:

  frozen            the cohort is labelled, the two routes agree on a count, the state
                     file carries that decision (or already did -- see idempotency
                     below), and the label's own description names the tag and date (or
                     already did).
  partial           SOME of the above happened and something after it did not: labels
                     applied but the two routes disagreed or one could not be read, or
                     the state file could not be written, or the description could not be
                     updated. `count`, `added` and `description` together say exactly
                     what completed, so a re-run is never a guess about what is left.
  could-not-freeze  nothing was written at all -- the tag could not be resolved, the
                     issue list could not be read, or the label does not exist yet. Same
                     meaning as `cohort_freeze.py`'s own `could-not-read` /
                     `label-missing` when neither one left a partial write behind.

Without `--execute` this is a fourth, separate thing -- a `preview` of what
`cohort_freeze.freeze`'s own dry run would do -- reported as `mode: "preview"` rather
than folded into the three states above. The two-route count is only trustworthy once
the last label write of the run has actually happened (`accounting.md`), so a dry run
never reads or writes the state file or the label's description at all.

Two routes, same two the hand process already ran: `cutoff_scan` is `cohort_freeze.py`'s
own independent read of every issue against the tag's cutoff (computed before any label
write this call made); `label_filter` is GitHub's label index, re-read *after* the last
label write of this call -- never before it, since a count taken first measures a set
still being edited (`accounting.md`). Disagreement is a finding, never an average:
`oss_state.cohort_freeze_from_pairs` is the same two-or-more-routes check #407 built and
this module changes nothing about its refusal to pick a side.

Idempotent by construction, not by convention. `cohort_freeze.freeze` is already a no-op
once every member carries the label. On top of that, this module reads the state file for
an existing entry naming the same cohort label before appending a second one, and reads
the label's current description before writing a new one -- a re-run always reads every
route again, so a later disagreement is never masked by a stale "already done", but
changes nothing on disk when what it reads back already matches.

The description carries no count on purpose (`cohort-27`: "Open at the v0.30.0 tag,
2026-09-09. Frozen: nothing joins a cohort.") -- #1122 records a releaser reporting a
count that the label's own text never mentioned, so a count baked into the description
would be exactly the copy this repository's own governing rule (`CLAUDE.md`) says never
to make: a second place for a number that already lives in the state file, silently able
to drift from it. The description is refreshed whenever the labels themselves are frozen
or already were, regardless of whether the two-route count agrees -- it names the tag and
the date, neither of which the route check can change.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cohort_freeze  # noqa: E402
import gh_which  # noqa: E402
import oss_state  # noqa: E402

STATE_FROZEN = "frozen"
STATE_PARTIAL = "partial"
STATE_COULD_NOT_FREEZE = "could-not-freeze"
MODE_PREVIEW = "preview"

RECORD_STATES = (STATE_FROZEN, STATE_PARTIAL, STATE_COULD_NOT_FREEZE)

EXIT_OK = 0
EXIT_PARTIAL = 2
EXIT_COULD_NOT_FREEZE = 3

DESCRIPTION_UPDATED = "updated"
DESCRIPTION_ALREADY_SET = "already-set"
DESCRIPTION_COULD_NOT_UPDATE = "could-not-update"
DESCRIPTION_SKIPPED = "skipped"


def _result(
    state,
    reason,
    label,
    tag,
    cohort,
    count=None,
    added=None,
    cutoff=None,
    state_written=False,
    description=DESCRIPTION_SKIPPED,
    route_check=None,
    mode="execute",
):
    return {
        "state": state,
        "reason": reason,
        "label": label,
        "tag": tag,
        "cohort": cohort,
        "count": count,
        "added": added,
        "cutoff": cutoff,
        "state_written": state_written,
        "description": description,
        "route_check": route_check,
        "mode": mode,
    }


def _label_description(repo, label, gh, run, timeout=25):
    """The label's current `description`, or ``None`` if it could not be read.

    Reuses `cohort_freeze`'s own private JSON-fetch helper rather than a second
    copy of the same `gh api` plumbing -- this module and `cohort_freeze.py`
    were built together (#917, #1410) for the same feature.
    """
    state, data, reason = cohort_freeze._gh_api_json(
        gh, ["repos/{}/labels/{}".format(repo, label)], run, timeout=timeout
    )
    if state != "ok":
        return None, reason
    if not isinstance(data, dict):
        return None, "labels/{} did not return an object".format(label)
    return data.get("description"), ""


def _desired_description(tag, cutoff):
    date = cutoff.split("T")[0] if cutoff else "an unknown date"
    return "Open at the {} tag, {}. Frozen: nothing joins a cohort.".format(tag, date)


def ensure_label_description(repo, label, tag, cutoff, gh, run, timeout=25):
    """Refresh `label`'s description to name `tag` and `cutoff`'s date.

    Never creates a label (`cohort_freeze.py` already refuses that -- creating one
    is the maintainer's own act) and never touches `--color`. Returns
    ``(state, reason)`` where `state` is one of `DESCRIPTION_UPDATED` /
    `DESCRIPTION_ALREADY_SET` / `DESCRIPTION_COULD_NOT_UPDATE`.
    """
    desired = _desired_description(tag, cutoff)
    current, read_reason = _label_description(repo, label, gh, run, timeout=timeout)
    if current is None and read_reason:
        return DESCRIPTION_COULD_NOT_UPDATE, read_reason
    if current == desired:
        return DESCRIPTION_ALREADY_SET, ""

    command = [gh, "label", "edit", label, "--repo", repo, "--description", desired]
    try:
        done = run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return DESCRIPTION_COULD_NOT_UPDATE, "{} did not run ({})".format(
            " ".join(command), exc
        )
    if done.returncode != 0:
        message = (
            cohort_freeze._decode_output(done.stderr)
            or cohort_freeze._decode_output(done.stdout)
            or ""
        ).strip()
        return DESCRIPTION_COULD_NOT_UPDATE, "{} failed: {}".format(
            " ".join(command), message
        )
    return DESCRIPTION_UPDATED, ""


def _last_cohort_entry(state_path, label):
    """The most recent state entry recording a freeze decision for `label`, or
    ``(None, None, "ok")``. Returns ``(record_or_None, tag_or_None, reason)`` --
    never raises; a read failure returns ``(None, None, reason)``,
    indistinguishable in shape from "no prior entry" only by the caller
    checking `reason`.

    The tag travels alongside the route-check record rather than inside it
    (`oss_state.cohort_freeze` itself carries no tag or cutoff at all -- #1410
    self-review) because `record_freeze`'s idempotency check must not treat a
    re-run under a *different* tag for the same cohort number as "already
    recorded, nothing changed" merely because the two-route count happened to
    come out the same. Without the tag, that coincidence would both skip the
    state-file write and still let `ensure_label_description` overwrite the
    label's description with the new tag -- exactly the label/state-file
    drift #1122 is cited elsewhere in this module to justify preventing.
    """
    try:
        entries = oss_state.read(state_path)
    except oss_state.StateError as exc:
        return None, None, "could not read {}: {}".format(state_path, exc)
    for entry in reversed(entries):
        detail = entry.get("detail") if isinstance(entry, dict) else None
        if not isinstance(detail, dict):
            continue
        record = detail.get("cohort_freeze")
        if isinstance(record, dict) and record.get("cohort") == label:
            return record, detail.get("cohort_freeze_tag"), "ok"
    return None, None, "ok"


def _decision_for(record):
    label = record.get("cohort") or "an unstated cohort"
    state = record.get("state")
    if state == oss_state.COHORT_MEASURED:
        return "froze {} at {}".format(label, record.get("count"))
    if state == oss_state.COHORT_UNKNOWN:
        return "{} freeze count disagreed, re-count needed".format(label)
    return "{} freeze count could not be confirmed".format(label)


def _preview(freeze_result, label, tag, cohort):
    """A preview never writes, but it must not hide a real failure behind a
    clean-looking exit code either (#1410 self-review). `mode` always reads
    `MODE_PREVIEW` -- nothing was ever going to be written -- but the
    top-level `state` reports `STATE_COULD_NOT_FREEZE` when the underlying
    `cohort_freeze.freeze` dry run itself could not even resolve the tag or
    found the label missing, so `_exit_code` still returns non-zero for a
    preview that hit a real problem. A dry run that resolved cleanly (it
    "would" freeze, or is already frozen) keeps the informational `preview`
    state, which is not one of `RECORD_STATES` and always exits 0.
    """
    if freeze_result["state"] in (
        cohort_freeze.STATE_COULD_NOT_READ,
        cohort_freeze.STATE_LABEL_MISSING,
    ):
        state = STATE_COULD_NOT_FREEZE
    else:
        state = MODE_PREVIEW
    return _result(
        state,
        freeze_result["reason"] or "dry run",
        label,
        tag,
        cohort,
        count=freeze_result.get("count"),
        added=freeze_result.get("added"),
        cutoff=freeze_result.get("cutoff"),
        mode=MODE_PREVIEW,
    )


def record_freeze(repo, tag, cohort, gh, run, state_path, at, execute=False):
    """Freeze `cohort-{cohort}` for `tag` and record the two-route decision.

    Without `execute` this only previews `cohort_freeze.freeze`'s own dry run and
    never touches the state file or the label's description -- see the module
    docstring for why.
    """
    label = "{}{}".format(cohort_freeze.LABEL_PREFIX, cohort)
    freeze_result = cohort_freeze.freeze(repo, tag, cohort, gh, run, execute=execute)

    if not execute:
        return _preview(freeze_result, label, tag, cohort)

    if freeze_result["state"] in (
        cohort_freeze.STATE_COULD_NOT_READ,
        cohort_freeze.STATE_LABEL_MISSING,
    ):
        if freeze_result.get("added"):
            return _result(
                STATE_PARTIAL,
                freeze_result["reason"],
                label,
                tag,
                cohort,
                count=freeze_result.get("count"),
                added=freeze_result["added"],
                cutoff=freeze_result.get("cutoff"),
            )
        return _result(
            STATE_COULD_NOT_FREEZE,
            freeze_result["reason"],
            label,
            tag,
            cohort,
            cutoff=freeze_result.get("cutoff"),
        )

    # freeze_result["state"] is now FROZEN or ALREADY -- the label write (if any
    # was needed) fully succeeded. Refresh the description first: it names only
    # the tag and the date, neither of which the route check below can change.
    cutoff = freeze_result["cutoff"]
    cutoff_scan = freeze_result["count"]
    description_state, description_reason = ensure_label_description(
        repo, label, tag, cutoff, gh, run
    )

    read_back = cohort_freeze.label_members(repo, label, gh, run)
    if read_back["state"] != "ok":
        route_record = oss_state.cohort_freeze_from_pairs(
            label,
            [("cutoff_scan", cutoff_scan), ("label_filter", None)],
            why="label_filter route could not be read after the freeze: {}".format(
                read_back["reason"]
            ),
        )
    else:
        route_record = oss_state.cohort_freeze_from_pairs(
            label,
            [("cutoff_scan", cutoff_scan), ("label_filter", len(read_back["numbers"]))],
        )

    existing, existing_tag, _existing_reason = _last_cohort_entry(state_path, label)
    if existing == route_record and existing_tag == tag:
        state_written = True
        reason = "already recorded ({}): nothing changed".format(
            oss_state.cohort_freeze_line(route_record)
        )
    else:
        try:
            oss_state.append(
                state_path,
                at,
                _decision_for(route_record),
                detail={"cohort_freeze": route_record, "cohort_freeze_tag": tag},
            )
            state_written = True
            reason = oss_state.cohort_freeze_line(route_record)
        except oss_state.StateError as exc:
            state_written = False
            reason = (
                "route check {}, but the state file could not be written: {}".format(
                    oss_state.cohort_freeze_line(route_record), exc
                )
            )

    if route_record["state"] == oss_state.COHORT_MEASURED and state_written:
        top_state = STATE_FROZEN
        count = route_record["count"]
    else:
        top_state = STATE_PARTIAL
        count = None

    if description_state == DESCRIPTION_COULD_NOT_UPDATE:
        top_state = STATE_PARTIAL
        reason = "{}; label description could not be updated: {}".format(
            reason, description_reason
        )

    return _result(
        top_state,
        reason,
        label,
        tag,
        cohort,
        count=count,
        added=freeze_result.get("added"),
        cutoff=cutoff,
        state_written=state_written,
        description=description_state,
        route_check=route_record,
    )


def _exit_code(state):
    if state == STATE_PARTIAL:
        return EXIT_PARTIAL
    if state == STATE_COULD_NOT_FREEZE:
        return EXIT_COULD_NOT_FREEZE
    return EXIT_OK


def _emit(payload, as_json):
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print("cohort_freeze_record: {}".format(payload.get("state")))
    for key in (
        "label",
        "tag",
        "cutoff",
        "count",
        "added",
        "state_written",
        "description",
        "mode",
        "reason",
    ):
        if key in payload:
            print("  {}: {}".format(key, payload[key]))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Freeze a cohort and record the two-route decision (#1410).",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="repository root (reads .oss.json for `repo`) or an owner/name slug",
    )
    parser.add_argument("--tag", required=True, help="the tag to freeze, e.g. v0.31.0")
    parser.add_argument(
        "--cohort", required=True, type=int, help="the cohort number, e.g. 28"
    )
    parser.add_argument("--state", required=True, help="path to the state file")
    parser.add_argument(
        "--at", required=True, help="ISO-8601 timestamp for the state entry, e.g. now"
    )
    parser.add_argument("--gh", default=None, help="the gh executable (default: PATH)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually write labels, the description and the state entry.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    # These two pre-flight checks run before `record_freeze` is ever called, so
    # they answer independently of `--execute` -- but the mode they report must
    # still say which one was asked for (#1410 self-review), or a caller reading
    # `mode` back cannot tell a preview's pre-flight failure from an execute run
    # that never got past its own pre-flight check.
    mode = "execute" if args.execute else MODE_PREVIEW

    slug, problem = cohort_freeze._resolve_repo_slug(args.repo)
    if problem:
        payload = _result(
            STATE_COULD_NOT_FREEZE, problem, None, args.tag, args.cohort, mode=mode
        )
        _emit(payload, args.as_json)
        return _exit_code(payload["state"])

    gh = args.gh or gh_which.safe_which("gh")
    if not gh:
        payload = _result(
            STATE_COULD_NOT_FREEZE,
            "gh is not on PATH",
            None,
            args.tag,
            args.cohort,
            mode=mode,
        )
        _emit(payload, args.as_json)
        return _exit_code(payload["state"])

    payload = record_freeze(
        slug,
        args.tag,
        args.cohort,
        gh,
        subprocess.run,
        args.state,
        args.at,
        execute=args.execute,
    )
    _emit(payload, args.as_json)
    return _exit_code(payload["state"])


if __name__ == "__main__":
    sys.exit(main())
