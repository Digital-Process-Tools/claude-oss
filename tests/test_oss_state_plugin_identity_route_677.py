"""#677 -- both operands of a plugin identity comparison must come from the
same route, or a changed/unchanged verdict describes nothing that occurred.

#477's `plugin_identity_check` compared two identity strings with no record of
HOW either was obtained. Filed from a real incident: `commands/tick.md` step 1
read a version-pinned `${CLAUDE_PLUGIN_ROOT}`, which reported `unchanged`
straight through a real 0.14.0 -> 0.15.0 update (the pinned path can never see
its own version move), and the very next tick mixed a hand-recorded prior taken
from the copy that actually answers with a current reading taken the old,
pinned way -- producing `changed`, backwards, with nothing having happened.

This is the route-mismatch half of the fix: two readings taken by different
routes are not the same measurement, so comparing them is its own state
(`PLUGIN_ROUTE_MISMATCH`), never folded into `changed` or `unchanged`. Paired
throughout with the positive control -- two readings via the SAME route really
do compare as changed/unchanged, exactly as before #677.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

IDENTITY_A = "0.14.0, git HEAD a66d174, content 0e728690e041 over 58 file(s)"
IDENTITY_B = "0.15.0, no git HEAD here, content 1b674225086a over 58 file(s)"
STAMP = "2026-08-29T07:06:00Z"


def test_same_route_unchanged_must_fire():
    """MUST FIRE (positive control): two readings via the same route, same
    string, compare as unchanged -- routing must not break the ordinary case."""
    record = oss_state.plugin_identity_check(
        IDENTITY_A, IDENTITY_A,
        current_route="resolved-install", prior_route="resolved-install",
    )
    assert record["state"] == oss_state.PLUGIN_UNCHANGED


def test_same_route_changed_must_fire():
    """MUST FIRE: two readings via the same route, differing strings, compare
    as changed -- a real version move is still detected once routed."""
    record = oss_state.plugin_identity_check(
        IDENTITY_B, IDENTITY_A,
        current_route="resolved-install", prior_route="resolved-install",
    )
    assert record["state"] == oss_state.PLUGIN_CHANGED


def test_different_routes_is_route_mismatch_not_changed():
    """The #677 comment's own second failure mode: a prior taken by one route
    and a current reading taken by another must not render as `changed` (nor
    `unchanged`), because the comparison describes nothing that occurred."""
    record = oss_state.plugin_identity_check(
        IDENTITY_A, IDENTITY_B,
        current_route="resolved-install", prior_route="pinned-root",
    )
    assert record["state"] == oss_state.PLUGIN_ROUTE_MISMATCH
    assert record["state"] != oss_state.PLUGIN_CHANGED
    assert record["state"] != oss_state.PLUGIN_UNCHANGED
    assert record["why"]


def test_new_route_against_an_unrouted_prior_is_also_a_mismatch():
    """The tick this fix ships in: every repo's prior entry was recorded by the
    OLD tick.md, which never called --plugin-identity-route at all. A current
    reading that IS routed must not compare against that silently -- treating
    'no route recorded' as though it matched every route would reproduce
    exactly the false-changed the #677 comment warned a naive fix would
    produce on its very first tick."""
    record = oss_state.plugin_identity_check(
        IDENTITY_A, IDENTITY_A,
        current_route="resolved-install", prior_route=None,
    )
    assert record["state"] == oss_state.PLUGIN_ROUTE_MISMATCH


def test_neither_side_routed_falls_back_to_the_pre_677_comparison():
    """MUST NOT FIRE: a caller that never opts into route tracking at all (both
    routes None) keeps comparing exactly as #477 always did -- no mismatch
    manufactured out of nothing."""
    record = oss_state.plugin_identity_check(IDENTITY_A, IDENTITY_A)
    assert record["state"] == oss_state.PLUGIN_UNCHANGED
    record = oss_state.plugin_identity_check(IDENTITY_B, IDENTITY_A)
    assert record["state"] == oss_state.PLUGIN_CHANGED


def test_could_not_tell_takes_priority_over_route_when_there_is_no_prior_at_all():
    """No prior recorded at all outranks a route question -- there is nothing
    to have a route mismatch WITH."""
    record = oss_state.plugin_identity_check(
        IDENTITY_A, None, current_route="resolved-install",
    )
    assert record["state"] == oss_state.PLUGIN_COULD_NOT_TELL


def test_plugin_identity_line_renders_route_mismatch():
    record = oss_state.plugin_identity_check(
        IDENTITY_A, IDENTITY_B,
        current_route="resolved-install", prior_route="pinned-root",
    )
    line = oss_state.plugin_identity_line(record)
    assert "route mismatch" in line
    assert "not comparable" in line


def test_last_plugin_identity_carries_the_recorded_route(tmp_path):
    state_path = tmp_path / "state.json"
    oss_state.append(
        str(state_path), STAMP, "first tick",
        detail={
            "plugin_identity": IDENTITY_A,
            "plugin_identity_route": "resolved-install",
        },
    )
    entry, identity, route = oss_state._last_plugin_identity(str(state_path))
    assert identity == IDENTITY_A
    assert route == "resolved-install"


def test_cli_records_and_compares_a_route_end_to_end(tmp_path, capsys):
    """The full round trip commands/tick.md now drives: record with a route,
    then check the next tick's reading against it via the SAME route."""
    path = tmp_path / "state.json"
    rc = oss_state._main(
        [str(path), "--decision", "first tick", "--at", STAMP,
         "--plugin-identity", IDENTITY_A,
         "--plugin-identity-route", "resolved-install"]
    )
    assert rc == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["detail"]["plugin_identity_route"] == "resolved-install"

    rc = oss_state._main(
        [str(path), "--check-plugin-identity", IDENTITY_A,
         "--plugin-identity-route", "resolved-install"]
    )
    assert rc == 0
    record = json.loads(capsys.readouterr().out)
    assert record["state"] == oss_state.PLUGIN_UNCHANGED


def test_cli_a_route_change_is_reported_as_mismatch_not_changed(tmp_path, capsys):
    """The exact shape of the #677 incident's second failure, reproduced through
    the CLI: a prior recorded via the old pinned-root route, a current reading
    routed the new way, byte-identical identity strings even -- must not read
    as `changed`."""
    path = tmp_path / "state.json"
    oss_state._main(
        [str(path), "--decision", "first tick", "--at", STAMP,
         "--plugin-identity", IDENTITY_A, "--plugin-identity-route", "pinned-root"]
    )
    capsys.readouterr()
    rc = oss_state._main(
        [str(path), "--check-plugin-identity", IDENTITY_A,
         "--plugin-identity-route", "resolved-install"]
    )
    assert rc == 0
    record = json.loads(capsys.readouterr().out)
    assert record["state"] == oss_state.PLUGIN_ROUTE_MISMATCH


def test_cli_plugin_identity_route_alone_is_refused(tmp_path, capsys):
    """A route with nothing to attach it to (no --check-plugin-identity, no
    --plugin-identity) names nothing and is refused rather than silently
    dropped."""
    path = tmp_path / "state.json"
    rc = oss_state._main([str(path), "--last", "--plugin-identity-route", "x"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out
