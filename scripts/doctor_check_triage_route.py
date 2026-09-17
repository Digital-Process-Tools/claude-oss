"""``check_triage_route`` -- one check, in its own module per the #497/#630 convention.

#1651: next_action.py has two triage signals -- triage_trigger.py's post-release
sweep, and workspace_routes's label-coverage route (open issues missing a
priority-* or lane-* label, gated on triage_route_threshold). When the second is
unconfigured, _triage_candidate returns CANDIDATE_NOT_CONFIGURED, and rank()'s own
nothing-due fold names it -- but nothing surfaces that to a maintainer or a session
that never calls next_action.py --json directly. This mirrors
doctor_check_trap_queue.py's four arms for the curate route, one population over.

Does **not** import doctor at module scope -- see
.claude/jit-context/paths/00-manual/doctor-check-module-scope-import.md: doctor.py
imports every doctor_check_* submodule, so importing it back at module scope is a
circular ImportError the moment this module (or its own test) loads first.
doctor_check_claude_md_size.py is the sibling that already gets this right; the older
doctor_check_trap_queue.py this module is otherwise modelled on does not, and is not
copied on this one point.

## Reuses the statusline's own counting, never a second gh call

scripts/statusline.py's _gh_unlabelled_issue_counts already counts open issues
missing a priority-* label and open issues missing a lane-* label, separately, and
refresh() already caches both under issues_no_priority/issues_no_lane in the same
cache file the status line itself renders from. This module reads that cache back --
statusline.cache_path(repo), statusline.read_cache, statusline.board_from_cache --
rather than re-deriving a third gh api call for a fact the loop already asked for. If
nothing has ever refreshed the board for this repo (no cache file, or a cache file with
neither count populated), that is a real, reportable third state, not a silent 0.

## Two populations, kept apart

Per _unlabelled_field's own docstring: an issue with no priority label and an issue
with no lane label are different facts, and select_issues_rank.py cannot rank an issue
missing the first. Summing them answers neither question, so this reports both counts
in the same line rather than a merged total -- unlike workspace_routes.triage_count,
which deliberately takes the larger of the two for the route's own over/under threshold
decision. This check's own "is anything waiting" test uses that same larger-of-two
value (so it agrees with what actually arms the route), but never prints only that
number.

## config (#1610's own reasoning, unchanged one route over)

A non-empty backlog with no triage_route_threshold configured is a check that could
look, had the facts, and would otherwise say nothing more than NOTICE -- the "route
unconfigured, and there is work it would have surfaced" shape next_action.py's own
CANDIDATE_NOT_CONFIGURED fold was found silently discarding (#1651's own issue text).
Optional and defaulted to None so a caller with no config in hand never crashes on
.get, but a repo with no config reachable here now gets WARN, not NOTICE: a route this
check cannot confirm is configured is not the same fact as a route confirmed configured
and merely with nothing waiting. config=None also covers ".oss.json could not be read
at all", which doctor.py's own caller already reports as a separate FAIL line before
this check ever runs -- a caller that invokes this function directly, bypassing that
FAIL line, cannot yet tell "could not read" from "read cleanly and the key is genuinely
absent" from this WARN text alone, the identical limitation doctor_check_trap_queue.py
already documents for curate_route_threshold.

Python 3.9 compatible.
"""

try:
    import statusline
except ImportError:  # pragma: no cover - statusline.py sits beside this file
    statusline = None

TRIAGE_ROUTE_THRESHOLD_KEY = "triage_route_threshold"


def _unlabelled_counts(config):
    """``(no_priority, no_lane, reason_or_None)`` off the last cached board
    reading -- never a fresh ``gh`` call of this check's own (see module
    docstring). ``reason`` is set, and both counts are ``None``, only when
    nothing usable could be read at all: no ``repo`` configured to look a
    cache up by, ``statusline`` itself unavailable, no cache file, or a
    cache file carrying neither count. Either individual count may still be
    ``None`` on its own when the other is a real int -- that is a repo that
    has declared no priority (or no lane) label spellings at all, a
    deliberate per-repo choice ``_unlabelled_field`` already renders as ``?``
    for that axis alone, not a failure of this check.
    """
    if statusline is None:
        return None, None, "the statusline module could not be imported"
    repo = (config or {}).get("repo") if isinstance(config, dict) else None
    if not isinstance(repo, str) or not repo.strip():
        return (
            None,
            None,
            "no repo configured in .oss.json, so the cached board could not be located",
        )
    cache = statusline.read_cache(statusline.cache_path(repo))
    if cache is None:
        return (
            None,
            None,
            "no cached board reading exists yet for this repo (open a session, or "
            "run python3 scripts/statusline.py --refresh --root . to populate one)",
        )
    board = statusline.board_from_cache(cache)
    no_priority = board.get("issues_no_priority")
    no_lane = board.get("issues_no_lane")
    if no_priority is None and no_lane is None:
        return (
            None,
            None,
            "the cached board carries no unlabelled-issue reading (either this repo "
            "declares no priority-*/lane-* label spellings at all, or the last count "
            "could not be taken)",
        )
    return no_priority, no_lane, None


def check_triage_route(project_dir, config=None):
    """#1651: is a label-coverage triage backlog waiting with no route configured
    to surface it? See the module docstring for the four arms and the third-state
    reasoning behind ``config``."""
    import doctor

    no_priority, no_lane, reason = _unlabelled_counts(config)
    if reason is not None:
        doctor.report(
            "WARN",
            "triage route: could not be read -- {}. UNKNOWN, not zero: nothing here "
            "has been shown to be empty.".format(reason),
        )
        return
    waiting = max(no_priority or 0, no_lane or 0)
    detail = (
        "{} issue(s) with no priority-* label, {} issue(s) with no lane-* label".format(
            "?" if no_priority is None else no_priority,
            "?" if no_lane is None else no_lane,
        )
    )
    if waiting == 0:
        doctor.report(
            "OK",
            "triage route: none waiting -- no open issue is missing a priority-*/"
            "lane-* label ({}). Deciding when to sweep is for /oss:triage, not "
            "this check.".format(detail),
        )
        return
    threshold_configured = (
        isinstance(config, dict) and config.get(TRIAGE_ROUTE_THRESHOLD_KEY) is not None
    )
    if threshold_configured:
        doctor.report(
            "NOTICE",
            "triage route: {} waiting for /oss:triage. Not a fault and nothing is "
            "blocked -- next_action.py rank() already tracks this route; "
            "deciding when to sweep is for /oss:triage, not this check.".format(detail),
        )
        return
    doctor.report(
        "WARN",
        "triage route: {} waiting for /oss:triage, and no triage_route_threshold is "
        "set in .oss.json -- the label-coverage triage route this loop owns cannot "
        "fire on this backlog at all (#1651). Clears with one config edit: set "
        "triage_route_threshold to the number of unlabelled issues that should "
        "accumulate before /oss:triage is due.".format(detail),
    )
