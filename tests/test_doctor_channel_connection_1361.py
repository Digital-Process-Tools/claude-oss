"""#1361: every channel check that existed before this one answers a question
strictly upstream of delivery -- which name resolves, whether a registration
exists, whether the file it names is on disk and current, whether two servers
race one socket. On the failure this was written for, all of them were `OK` or
`WARN cosmetic` while nothing was delivered at all.

Two checks, and they are deliberately separate facts:

* `check_mcp_channel_connection` -- does the consumer script start and speak
  MCP when `claude mcp list` probes it. That probe forks its own consumer and
  lets it exit, so an `OK` here is about the SCRIPT, never about a live one.
* `check_channel_delivery` -- is a consumer live now, and is a session
  subscribed to it. This is the question that decides whether an event arrives,
  and no check asked it before.

Every negative assertion here is paired with a positive control in the same
fixture, per this repository's own rule: an assertion that a WARN did not fire
also passes when no check ran at all.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_mcp_channel_connection as conn  # noqa: E402

CONSUMER = (
    "/Users/x/.claude/plugins/cache/dpt-plugins/supertool/0.58.0"
    "/notifiers/claude-channel/channel.ts"
)

FAILED_ROW = (
    "plugin:supertool:claude-channel: bun "
    + CONSUMER
    + " - ✘ Failed to connect — CONNECTION_CLOSED: Connection closed"
)
CONNECTED_ROW = "oss-channel: bun " + CONSUMER + " - ✔ Connected"
UNRELATED_ROW = "claude.ai Gmail: https://gmailmcp.googleapis.com/mcp/v1 - ✔ Connected"
BANNER = "Checking MCP server health…"


def setup_function(_):
    doctor.FINDINGS.clear()


def _levels():
    return [level for level, _ in doctor.FINDINGS]


def _text():
    return "\n".join(message for _, message in doctor.FINDINGS)


def _run(stdout, returncode=0):
    """A `claude mcp list` whose output is `stdout`, with `claude` on PATH."""
    return conn.mcp_channel_connection_state(
        run=lambda *a, **k: type(
            "C", (), {"returncode": returncode, "stdout": stdout}
        )(),
        which=lambda _name: "/usr/bin/claude",
        env={},
    )


# ---------------------------------------------------------------- the parser


def test_a_plugin_prefixed_name_is_parsed_and_its_failure_is_read():
    """The name carries two colons of its own. The shared
    `_MCP_LIST_LINE_RE` in doctor_check_mcp_channel_registration cannot match
    this row at all -- that gap is this check's whole reason for owning a
    regex, and this is the assertion that would catch reusing it."""
    rows = conn.channel_consumer_connections(BANNER + "\n" + FAILED_ROW)
    assert len(rows) == 1
    name, state, detail = rows[0]
    assert (name, state) == ("plugin:supertool:claude-channel", "failed")
    # The detail is asserted on its WORDS, not byte-for-byte: `doctor._one_line`
    # folds non-ASCII to `?`, so the check mark and the em dash in the real row
    # do not survive into it. Asserting the raw row here measured the reporting
    # helper rather than this check, and failed for that reason.
    assert CONSUMER in detail
    assert "Failed to connect" in detail
    assert "CONNECTION_CLOSED" in detail


def test_a_connected_row_is_read_as_connected_and_unrelated_servers_are_skipped():
    """Positive control for the negative half: the Gmail row is `Connected`
    too, so a parser that ignored the consumer suffix would return two rows."""
    rows = conn.channel_consumer_connections(
        "\n".join([BANNER, UNRELATED_ROW, CONNECTED_ROW])
    )
    assert rows == [("oss-channel", "connected", "")]


def test_an_unrecognised_status_is_unknown_and_never_folded_into_either():
    """The third state, which is the whole point: a status that was not read
    is not a status that was OK."""
    row = "oss-channel: bun " + CONSUMER + " - reticulating splines"
    rows = conn.channel_consumer_connections(row)
    assert rows[0][0] == "oss-channel"
    assert rows[0][1] == "unknown"
    assert "reticulating splines" in rows[0][2]


# ------------------------------------------------------------- the state fn


def test_claude_missing_from_path_is_could_not_ask_never_none():
    state, detail = conn.mcp_channel_connection_state(
        run=None, which=lambda _name: None, env={}
    )
    assert state == "could-not-ask"
    assert "PATH" in detail


def test_a_listing_with_no_consumer_row_is_none_and_one_with_no_rows_is_could_not_read():
    """Two absences that must not render alike: a listing that was read and
    holds no consumer, and output this parser cannot speak for at all."""
    assert _run(BANNER + "\n" + UNRELATED_ROW)[0] == "none"
    # A nonzero exit, not the shape of the output: `error: something went
    # sideways` parses as a `name: rest` row, which is exactly why the first
    # version of this branch answered a clean `none` for a call that had failed.
    assert _run("error: something went sideways", returncode=1)[0] == "could-not-read"
    # ... and the same text at exit 0 is a listing holding no consumer, a
    # different fact. The pair is the control: without it, a branch answering
    # `could-not-read` for everything would satisfy the line above.
    assert _run("error: something went sideways")[0] == "none"


def test_all_failed_is_failed_and_any_connected_is_connected():
    assert _run(FAILED_ROW)[0] == "failed"
    assert _run(FAILED_ROW + "\n" + CONNECTED_ROW)[0] == "connected"


# ----------------------------------------------------------------- the check


def test_a_failed_transport_warns_rather_than_passing():
    """The defect this check exists to remove: on this exact machine state the
    registration checks reported OK twice and nothing was delivered."""
    conn.check_mcp_channel_connection(
        run=lambda *a, **k: type("C", (), {"returncode": 0, "stdout": FAILED_ROW})(),
        which=lambda _name: "/usr/bin/claude",
        env={},
    )
    assert _levels() == ["WARN"]
    assert "failed transport" in _text()


def test_a_live_transport_passes_and_says_what_it_does_not_prove():
    """Positive control, and a content assertion: an OK that did not disclaim
    the probe would be the same false confidence in a new place."""
    conn.check_mcp_channel_connection(
        run=lambda *a, **k: type("C", (), {"returncode": 0, "stdout": CONNECTED_ROW})(),
        which=lambda _name: "/usr/bin/claude",
        env={},
    )
    assert _levels() == ["OK"]
    assert "FORKS ITS OWN" in _text()


# -------------------------------------------------------------- delivery


def test_not_delivering_warns_and_names_the_reopen():
    conn.check_channel_delivery(
        "/repo", resolve=lambda _d: ("not_delivering", "cached", 12.0)
    )
    assert _levels() == ["WARN"]
    assert "NOT DELIVERING" in _text()
    assert "bin/oss-workspace" in _text()


def test_bound_but_not_subscribed_is_its_own_warning():
    conn.check_channel_delivery(
        "/repo", resolve=lambda _d: ("not_subscribed", "cached", 12.0)
    )
    assert _levels() == ["WARN"]
    assert "BOUND, NOT SUBSCRIBED" in _text()


def test_forwarding_is_the_only_ok_state():
    conn.check_channel_delivery(
        "/repo", resolve=lambda _d: ("forwarding", "cached", 12.0)
    )
    assert _levels() == ["OK"]


def test_nothing_established_is_a_notice_rather_than_work_nobody_can_do():
    """The line this module draws: WARN only where a fault is POSITIVELY
    established; NOTICE wherever nothing could be established at all.

    Warning on the second kind invents work nobody can do. It took a
    fully-scaffolded fixture asserting `VERDICT: ok` red on four CI legs -- a
    runner has no `claude` and no channel, so a first version of these checks
    warned there permanently, which by this repository's own doctor rule is a
    bug in the check rather than work. #764's NOTICE is the state for a check
    declaring itself unable to answer, and it does not gate the verdict.

    Four such states, asserted together because they must not diverge: no
    reading, a reading too old to speak for the present, `claude` absent, and a
    listing whose shape was not understood. Each keeps its own remedy text, so
    a reader who does want a reading still knows how to take one."""
    conn.check_channel_delivery("/repo", resolve=lambda _d: (None, None, None))
    conn.check_channel_delivery(
        "/repo", resolve=lambda _d: (None, "cached-stale", 4000.0)
    )
    conn.check_mcp_channel_connection(run=None, which=lambda _n: None, env={})
    conn.check_mcp_channel_connection(
        run=lambda *_a, **_k: type("C", (), {"returncode": 1, "stdout": "boom"})(),
        which=lambda _n: "/usr/bin/claude",
        env={},
    )
    assert _levels() == ["NOTICE", "NOTICE", "NOTICE", "NOTICE"]
    assert "not established" in _text()


def test_an_established_fault_is_still_a_warning():
    """The positive control the four NOTICEs above need. Without it, a module
    that answered NOTICE to everything would pass every assertion in this file
    that is not an OK -- and this check would have been written to warn about
    nothing at all, which is the defect it exists to remove wearing the other
    mask."""
    conn.check_mcp_channel_connection(
        run=lambda *_a, **_k: type("C", (), {"returncode": 0, "stdout": FAILED_ROW})(),
        which=lambda _n: "/usr/bin/claude",
        env={},
    )
    conn.check_channel_delivery(
        "/repo", resolve=lambda _d: ("not_delivering", "cached", 12.0)
    )
    assert _levels() == ["WARN", "WARN"]


def test_an_unrecognised_health_state_is_reported_verbatim_not_folded():
    conn.check_channel_delivery(
        "/repo", resolve=lambda _d: ("contradicted", "cached", 12.0)
    )
    assert _levels() == ["WARN"]
    assert "contradicted" in _text()


# ------------------------------------------------------- arm-target liveness


GET_FAILED = "\n".join(
    [
        "plugin:supertool:claude-channel:",
        "  Scope: Dynamic config (from command line)",
        "  Status: ✘ Failed to connect",
        "  Issue: CONNECTION_CLOSED: Connection closed",
    ]
)
GET_CONNECTED = "\n".join(
    [
        "plugin:supertool:claude-channel:",
        "  Scope: Dynamic config (from command line)",
        "  Status: ✔ Connected",
    ]
)


def _liveness(name, stdout, returncode=0):
    return conn.arm_target_liveness(
        name,
        run=lambda *a, **k: type(
            "C", (), {"returncode": returncode, "stdout": stdout}
        )(),
        which=lambda _n: "/usr/bin/claude",
        env={},
    )


def test_a_declared_consumer_that_does_not_connect_is_not_a_reason_to_decline():
    """The composition #1361 was filed from: a plugin declares the consumer,
    the harness does not start it, and the launcher declines to register its
    own on the strength of the declaration alone. The harness's own reason is
    carried through, not the bare word `failed`."""
    state, detail = _liveness("plugin:supertool:claude-channel", GET_FAILED)
    assert state == "failed"
    assert "CONNECTION_CLOSED" in detail


def test_a_live_declared_consumer_still_suppresses_the_fallback():
    """Positive control. Without this, a gate answering `failed` for
    everything would satisfy the test above and recreate #1307's collision on
    every launch."""
    assert _liveness("plugin:supertool:claude-channel", GET_CONNECTED) == (
        "connected",
        "plugin:supertool:claude-channel",
    )


def test_every_answer_short_of_a_confirmed_failure_declines_to_fall_back():
    """The narrow trigger, which is the whole safety property: only a status
    positively read as failed may register a second server. A first version of
    this gate also fell back on `not-listed`, and broke four existing
    #1307/#1343 launcher fixtures by falling back where the declared consumer
    was fine and merely invisible to this ask.

    `bin/oss-workspace` acts on `failed` alone, so each state below must be
    something other than `failed` -- asserted by name rather than as a group,
    because folding them together is what this function exists to prevent."""
    assert conn.arm_target_liveness("x", which=lambda _n: None)[0] == "could-not-ask"
    assert _liveness("x", "", returncode=1)[0] == "not-listed"
    assert _liveness("x", "x:\n  Scope: Local config")[0] == "could-not-ask"
    assert _liveness("x", "x:\n  Status: reticulating splines")[0] == "could-not-ask"


# --------------------------------------------------------------- the relay


def test_the_launcher_relay_is_used_instead_of_a_second_ask():
    """`bin/oss-workspace` asks `claude mcp list` once and exports the answer.
    A reader that asked again made a launch pay for three starts of a ~1.3s
    binary, and `test_the_launcher_relays_its_own_census_to_doctor_sh_rather_
    than_asking_twice` counts them."""

    def _explode(*_a, **_k):  # pragma: no cover -- fails the test if reached
        raise AssertionError("asked claude despite a relayed answer")

    state, _ = conn.mcp_channel_connection_state(
        run=_explode,
        which=_explode,
        env={"OSS_WORKSPACE_MCP_LIST_OUTPUT": FAILED_ROW},
    )
    assert state == "failed"


def test_an_absent_or_blank_relay_falls_through_rather_than_reading_as_empty():
    """The positive control, and the whole third-state point: an empty relay
    must not render as a listing that holds no consumer."""
    asked = []

    def _run(argv, **_k):
        asked.append(argv)
        return type("C", (), {"returncode": 0, "stdout": CONNECTED_ROW})()

    for relay in ({}, {"OSS_WORKSPACE_MCP_LIST_OUTPUT": "   "}):
        state, _ = conn.mcp_channel_connection_state(
            run=_run, which=lambda _n: "/usr/bin/claude", env=relay
        )
        assert state == "connected"
    assert len(asked) == 2
