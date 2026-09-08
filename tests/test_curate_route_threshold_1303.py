"""#1303 -- trap.d curation had no owner and no cadence, deliberately for
THIS repository's own `.oss.json`: `scripts/workspace_routes.py` (#1155)
already built and tested the mechanism -- `bin/oss-workspace`'s job 2 opens
a session with `/oss:curate` when `trap.d/` fragments cross a per-repo
`curate_route_threshold` -- but the key was never set here, so the route
sat inert. This is not a code gap; it is a config gap this test pins so it
cannot silently reopen.

Measured 2026-09-08: 49 fragments in trap.d/, 0 configured threshold. A
route with no configured threshold is never evaluated at all
(`workspace_routes.decide`'s own rule, shared with `changelog_untagged` and
`user_visible_paths`) -- so "the mechanism exists" and "curation actually
runs on a trigger for this repo" were two different facts, and only the
first one was true.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import workspace_routes  # noqa: E402


def _real_config():
    return json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))


def test_curate_route_threshold_is_configured():
    """The config gap itself: absent means #1155's route is never armed for
    /oss:curate, no matter how large trap.d/ grows -- indistinguishable from
    a mechanism that was never built."""
    config = _real_config()
    threshold = config.get("curate_route_threshold")
    assert threshold is not None, (
        "curate_route_threshold is not set in .oss.json -- the #1155 "
        "/oss:curate threshold route (scripts/workspace_routes.py) exists "
        "and is tested, but this repository never opted in, so it never "
        "fires no matter how large trap.d/'s backlog grows"
    )
    assert workspace_routes._valid_threshold(threshold), (
        "curate_route_threshold={!r} is not a usable non-negative integer "
        "-- workspace_routes.decide() would report could-not-count for a "
        "malformed threshold rather than a real comparison".format(threshold)
    )


def test_curate_route_arms_at_the_configured_threshold():
    """Wiring check, not just presence: with the real, configured threshold,
    a count one over it must arm the curate route, and a count at or below
    it must not -- proving the number in .oss.json actually reaches
    workspace_routes.decide() rather than merely existing as an unused key.
    """
    config = _real_config()
    threshold = config["curate_route_threshold"]

    def over_count(_repo_root):
        return threshold + 1, "fixture: one over the real configured threshold"

    def at_count(_repo_root):
        return threshold, "fixture: exactly at the real configured threshold"

    real_curate_count = workspace_routes.curate_count
    try:
        workspace_routes.curate_count = over_count
        armed, results = workspace_routes.decide(str(REPO_ROOT), config)
        assert (
            armed == "curate"
            or results["release"]["state"] == "over"
            or (results.get("triage", {}).get("state") == "over")
        ), (
            "a trap.d/ count one over the configured threshold did not arm "
            "/oss:curate (armed={!r}, curate={!r}) -- either a higher-"
            "precedence route legitimately preempted it (release, then "
            "triage) or the wiring is broken".format(armed, results.get("curate"))
        )
        assert results["curate"]["state"] == "over", (
            "curate's own state must read 'over' once the count exceeds "
            "the real configured threshold: {!r}".format(results["curate"])
        )

        workspace_routes.curate_count = at_count
        _armed, results = workspace_routes.decide(str(REPO_ROOT), config)
        assert results["curate"]["state"] == "under", (
            "a count exactly AT the threshold must read 'under' -- over is "
            "strictly greater than the threshold, per workspace_routes' "
            "own _count_state: {!r}".format(results["curate"])
        )
    finally:
        workspace_routes.curate_count = real_curate_count
