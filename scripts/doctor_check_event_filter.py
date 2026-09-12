"""``check_event_filter`` -- its own module per the #497/#630 convention (#1499).

`doctor.py` keeps `main()`, the check registry and the shared contract (exit 0
always, one VERDICT line, `report()`); this module holds one check. Every
shared name -- `report`, `_supertool_document` -- is reached through
`import doctor`, never `from doctor import name`, so a test's
`monkeypatch.setattr(doctor, ...)` still reaches this code.

## What it checks

The scheduler session (`/oss:run`) is supposed to stay flat and reached
419-503k tokens of context in one overnight run, because every channel event
the `gh-prs` radar tier emits -- `checks_pending`, `checks_succeeded`,
`conflicts_appeared`, ... -- lands in that session as a turn, and
a turn re-sends the whole scheduler context. 12 of the 17 events one scheduler
received in a morning were per-PR noise the running tick already polls for.

supertool's `gh-prs` tier gains a `pr_exclude_events` option -- a list of
event keys its per-PR pollers never publish. It lives in this repo's own
`.supertool.json` at `ops.radar.radar_tiers["gh-prs"].pr_exclude_events`, and
this check reports whether it is set, because an unfiltered scheduler renders
identically to a filtered one until the quota is gone.

## The four outcomes, per `doctor-check-contract.md`

* `OK` -- the list is present and non-empty; the excluded events are named.
* `WARN unfiltered` -- the tier is registered and the key is absent, empty, or
  not a list. Clearable by one edit, which the message spells out with the
  initial value.
* `NOTICE not-configured` -- the file registers no `gh-prs` tier at all, so
  no per-PR pollers run and there is nothing to filter: structurally unable
  to answer, never gating the VERDICT (#764).
* `WARN could-not-read` -- the file is missing, is not valid JSON, or is not
  an object. Never folded into either answer.

Read, never written: this file is supertool's, and a default the plugin
scaffolds once; `doctor` names the edit and leaves the decision to the session.

Python 3.9 compatible.
"""

import json

import doctor

TIER = "gh-prs"
KEY = "pr_exclude_events"

#: The initial blacklist #1499 decided on: the per-PR events a running tick
#: already polls for. A repo widens it in its own `.supertool.json`.
#:
#: Keys here must be ones `github-pr` (the per-PR poller) can emit -- radar
#: refuses the WHOLE tier otherwise, zero pollers, and this check reports `ok`
#: over it. `pr_opened` is a `github-pr-feed` event and shipped here for a day
#: before supertool 0.61.0 refused it; `tests/test_event_filter_keys_1499.py`
#: reads supertool's own events.json rather than a copy of the valid set.
INITIAL_EXCLUDE = [
    "checks_pending",
    "checks_succeeded",
    "conflicts_appeared",
]


def event_filter_state(project_dir):
    """``(state, detail)`` -- ``ok`` / ``unfiltered`` / ``not-configured`` /
    ``could-not-read``.

    ``detail`` is the excluded events for ``ok``, the reason for the other
    three. Absence of the file is ``could-not-read`` here rather than a fourth
    answer: without the file nothing can say whether a tier is registered, and
    the remedy (write or fix the file) is the same one a parse failure needs.
    """
    doc, problem, detail = doctor._supertool_document(project_dir)
    if problem is not None:
        return "could-not-read", detail
    if doc is None:
        return "could-not-read", "{} is not there".format(doctor.WATCH_CONFIG)
    ops = doc.get("ops")
    radar = ops.get(doctor.RADAR_OP) if isinstance(ops, dict) else None
    tiers = radar.get(doctor.RADAR_TIERS_KEY) if isinstance(radar, dict) else None
    if not isinstance(tiers, dict) or TIER not in tiers:
        return "not-configured", "no {} tier under ops.{}.{}".format(
            TIER, doctor.RADAR_OP, doctor.RADAR_TIERS_KEY
        )
    tier = tiers[TIER]
    value = tier.get(KEY) if isinstance(tier, dict) else None
    if value is None:
        return "unfiltered", "{} is absent".format(KEY)
    if not isinstance(value, list):
        return "unfiltered", "{} is not a list".format(KEY)
    events = [e for e in value if isinstance(e, str) and e]
    if not events:
        return "unfiltered", "{} is empty".format(KEY)
    return "ok", events


def check_event_filter(project_dir):
    """#1499: is the scheduler's per-PR event noise filtered at the source?"""
    state, detail = event_filter_state(project_dir)
    key_path = "ops.{}.{}.{}.{}".format(
        doctor.RADAR_OP, doctor.RADAR_TIERS_KEY, TIER, KEY
    )
    if state == "ok":
        doctor.report(
            "OK",
            "event filter: {} excludes {} from the channel ({}). Every other event the "
            "per-PR pollers emit still lands in the scheduler session as a turn.".format(
                TIER, ", ".join(detail), key_path
            ),
        )
        return
    if state == "unfiltered":
        doctor.report(
            "WARN",
            "event filter: unfiltered -- {} in {}. Every per-PR channel event "
            "(checks_pending, checks_succeeded, conflicts_appeared, ...) then "
            "lands in the scheduler session as a turn, and each turn re-sends the whole "
            "scheduler context; that is how one /oss:run session reached 419-503k tokens "
            "overnight (#1499). Set {} to {} in {} -- the running tick already polls for "
            "those four.".format(
                detail,
                doctor.WATCH_CONFIG,
                key_path,
                json.dumps(INITIAL_EXCLUDE),
                doctor.WATCH_CONFIG,
            ),
        )
        return
    if state == "not-configured":
        doctor.report(
            "NOTICE",
            "event filter: not-configured -- {} in {}. No per-PR pollers run, so there "
            "is nothing to filter; this line cannot be cleared and does not gate the "
            "verdict.".format(detail, doctor.WATCH_CONFIG),
        )
        return
    doctor.report(
        "WARN",
        "event filter: could-not-read -- {}. UNKNOWN, not unfiltered: whether the "
        "scheduler's per-PR events are filtered has not been shown either way. Fix or "
        "create {} so it parses as a JSON object.".format(detail, doctor.WATCH_CONFIG),
    )
