"""#1516: `_drop_dead_plugin_consumers`'s liveness ask (`claude mcp get`,
via `arm_target_liveness`) is unmemoised -- `channel_consumer_census_state`
is called from three places (`doctor.py`'s own `/oss:doctor` run,
`doctor_check_channel_health_agreement.py`, and `bin/oss-workspace`'s own
census heredoc), and one `/oss:doctor` run alone therefore pays for the same
plugin-declared consumer's liveness twice in the same process.

The fix is an opt-in `cache` dict threaded through `_drop_dead_plugin_
consumers` -> `channel_consumer_census_state` -> `check_channel_consumer_
census` / `check_channel_health_agreement`, keyed on the RESOLVED server
name (`resolvable_plugin_server_name`), `None` by default so `doctor.py`'s
own `main()` -- which deliberately does not share one answer between
checks (see `check_channel_consumer_pin`'s own `precomputed` docstring,
reverted once for that exact reason) -- keeps asking fresh unless it opts
in.

Run before the fix, each `test_..._counts_the_real_liveness_asks` case
fails for the stated reason: `_drop_dead_plugin_consumers` had no `cache`
parameter at all.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor_check_mcp_channel_registration as reg  # noqa: E402


def _liveness_counter():
    calls = []

    def liveness(name):
        calls.append(name)
        return "connected", "Status: Connected"

    return liveness, calls


def test_a_shared_cache_asks_liveness_once_for_two_calls():
    """Must-fire: two separate calls into `channel_consumer_census_state`
    that share the SAME `cache` dict, both censusing the same plugin-
    declared consumer, must only ask liveness once between them -- proving
    the cache is actually consulted rather than merely accepted and
    ignored."""
    liveness, calls = _liveness_counter()
    cache = {}
    names = ["plugin:supertool@dpt-plugins:claude-channel"]

    first = reg._drop_dead_plugin_consumers(list(names), liveness=liveness, cache=cache)
    second = reg._drop_dead_plugin_consumers(
        list(names), liveness=liveness, cache=cache
    )

    assert first == names
    assert second == names
    assert calls == ["plugin:supertool:claude-channel"], calls


def test_with_no_cache_liveness_is_asked_every_time():
    """Positive control: the same two calls, with NO cache shared (today's
    default), must ask liveness twice -- proving the fixture above is
    actually measuring the cache and not some other effect (e.g. the
    dedup a fresh call would perform on its own)."""
    liveness, calls = _liveness_counter()
    names = ["plugin:supertool@dpt-plugins:claude-channel"]

    reg._drop_dead_plugin_consumers(list(names), liveness=liveness)
    reg._drop_dead_plugin_consumers(list(names), liveness=liveness)

    assert calls == [
        "plugin:supertool:claude-channel",
        "plugin:supertool:claude-channel",
    ], calls


def test_two_independent_census_calls_share_one_cache_across_the_module_boundary():
    """Must-fire: the cache threads all the way through `channel_consumer_
    census_state`, the function `doctor.py`'s own check and `doctor_check_
    channel_health_agreement.py`'s check both call -- not just the inner
    helper directly."""
    liveness, calls = _liveness_counter()
    cache = {}

    def _plugin_names(*_a, **_k):
        return (["plugin:supertool@dpt-plugins:claude-channel"], None)

    orig = reg._plugin_channel_consumer_names
    reg._plugin_channel_consumer_names = _plugin_names
    try:

        def _run_stub(argv, **_kwargs):
            class _Completed:
                returncode = 0
                stdout = b""

            return _Completed()

        state1, _ = reg.channel_consumer_census_state(
            run=_run_stub,
            which=lambda _n: "/usr/bin/claude",
            liveness=liveness,
            cache=cache,
        )
        state2, _ = reg.channel_consumer_census_state(
            run=_run_stub,
            which=lambda _n: "/usr/bin/claude",
            liveness=liveness,
            cache=cache,
        )
    finally:
        reg._plugin_channel_consumer_names = orig

    assert state1 == "single", state1
    assert state2 == "single", state2
    assert calls == ["plugin:supertool:claude-channel"], calls
