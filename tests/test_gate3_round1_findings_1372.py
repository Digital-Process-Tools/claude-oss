"""Gate 3 round one, v0.31.0 (dispatch token gate3-r1-4f2a9c7e1b83): four
findings, three of them defects introduced by the same release's own delta.

Each test below is the audit's own reproduction, written before the fix.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402  -- first, per the circular-import convention
import doctor_check_mcp_channel_connection as conn  # noqa: E402
import doctor_check_mcp_channel_registration as reg  # noqa: E402
import statusline  # noqa: E402
import trap_curate  # noqa: E402

CONSUMER = "/x/notifiers/claude-channel/channel.ts"


# ------------------------------------------------- finding 1: the parity


def test_the_two_trap_counters_agree_on_a_directory_holding_the_owned_readme(
    tmp_path,
):
    """`statusline._trap_count`'s own docstring claims it matches
    `trap_curate.waiting`'s filter. #1348 excluded the scaffolded README from
    one of them and not the other, so on this repository they read 16 and 17.

    The visible harm: a fully drained `trap.d/` renders `trap 1` on the status
    line forever, with no fragment anyone can delete to clear it, while
    doctor's own trap-queue check says `none waiting` in the same run."""
    d = tmp_path / "trap.d"
    d.mkdir()
    (d / "README.md").write_text("owned\n", encoding="utf-8")
    (d / "904.a-slug.md").write_text("frag\n", encoding="utf-8")

    assert statusline._trap_count(tmp_path) == trap_curate.waiting(tmp_path)["count"]


def test_a_drained_trap_directory_counts_zero_on_both(tmp_path):
    """The end state that must render as done rather than as one outstanding
    fragment. Positive control for the parity above: a fix that made both
    counters return the same wrong number would satisfy that test alone."""
    d = tmp_path / "trap.d"
    d.mkdir()
    (d / "README.md").write_text("owned\n", encoding="utf-8")

    assert statusline._trap_count(tmp_path) == 0
    assert trap_curate.waiting(tmp_path)["count"] == 0


# --------------------------------------- finding 2: the unguarded relay


def test_a_relay_with_no_sentinel_does_not_answer_connected(tmp_path):
    """#1344 hardened the sibling relay against exactly this and said why: a
    stale export left over from an earlier session, or one inherited from an
    unrelated parent shell, otherwise converts a real finding into a clean OK
    forever. #1361 added a new relay one check over with none of those guards.

    Reproduced by the audit: a forged variable reported `connected` on a
    machine with no `claude` binary at all."""
    forged = "oss-channel: bun " + CONSUMER + " - ✔ Connected"
    state, _ = conn.mcp_channel_connection_state(
        which=lambda _n: None,
        env={"OSS_WORKSPACE_MCP_LIST_OUTPUT": forged},
    )
    assert state != "connected"
    assert state == "could-not-ask"


def test_a_sentinel_bearing_relay_is_still_used(tmp_path):
    """Positive control. The relay exists to save a ~1.3s process at session
    open (#629/#810's own economy); a fix that ignored it entirely would pass
    the test above and cost that back on every launch."""
    relayed = "oss-channel: bun " + CONSUMER + " - ✔ Connected"

    def _explode(*_a, **_k):  # pragma: no cover -- fails the test if reached
        raise AssertionError("asked claude despite a sentinel-bearing relay")

    state, _ = conn.mcp_channel_connection_state(
        run=_explode,
        which=_explode,
        env={
            "OSS_WORKSPACE_MCP_LIST_CHECKED": "1",
            "OSS_WORKSPACE_MCP_LIST_OUTPUT": relayed,
        },
    )
    assert state == "connected"


# ----------------------- finding 3: the census counts a dead consumer


def test_a_plugin_consumer_the_harness_does_not_have_live_is_not_a_collision():
    """The composition the audit found, and the reason it matters: the
    `declared-but-not-live` arm registers `oss-channel` precisely because the
    plugin's own consumer is dead -- and the census then counts BOTH, reports
    `collision`, and disarms the channel flag. That is #1361's own
    zero-consumer state, reproduced one layer inside the fix for it, plus a
    stale registration that collides on every launch afterwards.

    Only a transport positively read as failed is dropped. `could-not-ask`
    and `not-listed` keep the server counted -- an unread answer is not
    evidence a consumer is dead, and dropping one on that basis would hide a
    real collision."""
    names = ["oss-channel", "plugin:supertool@dpt-plugins:claude-channel"]

    dead = reg._drop_dead_plugin_consumers(
        names, liveness=lambda _n: ("failed", "CONNECTION_CLOSED")
    )
    assert dead == ["oss-channel"]

    for unread in ("could-not-ask", "not-listed"):
        assert (
            reg._drop_dead_plugin_consumers(names, liveness=lambda _n: (unread, ""))
            == names
        ), unread

    alive = reg._drop_dead_plugin_consumers(
        names, liveness=lambda _n: ("connected", "")
    )
    assert alive == names


# ------------------------- finding 4: the shell arm has no control


def test_the_declared_but_not_live_payload_and_its_shell_reader_agree_on_line_order():
    """`declared-but-not-live` is emitted by a Python heredoc as three lines
    and read back by the shell positionally with `sed -n '1p'` / `'2p'` over
    the payload's tail. Gate 3 round one found `grep -rn declared-but-not-live`
    returning two hits, both inside `bin/oss-workspace`, and nothing under
    `tests/`: if the emitter's order and the reader's offsets ever disagree, no
    leg reddens and the launcher silently arms against the wrong string.

    This is a COUPLING check over the two sources, not an execution of the
    launcher -- it cannot prove the arm behaves correctly at session open, and
    saying so is the point rather than a caveat. What it does catch is the one
    drift that is otherwise invisible: a line reordered on one side only."""
    launcher = (REPO_ROOT / "bin" / "oss-workspace").read_text(encoding="utf-8")

    # The emitter: state, then the resolvable name, then the reason.
    emitter = launcher.split('print("declared-but-not-live")', 1)
    assert len(emitter) == 2, "the emitter no longer prints this state"
    body = emitter[1].split("raise SystemExit(0)", 1)[0]
    printed = [line.strip() for line in body.splitlines() if "print(" in line]
    assert len(printed) == 2, printed
    assert "_resolvable" in printed[0], printed
    assert "_live_state" in printed[1] and "_live_detail" in printed[1], printed

    # The reader: rest-line 1 is the target, rest-line 2 is the reason.
    arm = launcher.split("declared-but-not-live)", 1)[1].split(";;", 1)[0]
    target_line = [ln for ln in arm.splitlines() if "plugin_channel_target=" in ln]
    reason_line = [ln for ln in arm.splitlines() if "plugin_channel_reason=" in ln]
    assert target_line and "sed -n '1p'" in target_line[0], target_line
    assert reason_line and "sed -n '2p'" in reason_line[0], reason_line


def test_the_arm_blanks_the_target_so_the_launcher_falls_through_to_registering():
    """The behaviour the arm exists for: having reported the declared consumer
    dead, it must NOT leave `plugin_channel_target` set, or the arming block
    further down arms the channel flag against the very server it just found
    dead. Positive control for the line-order test above, which would pass on
    an arm that read both lines correctly and then did nothing with them."""
    launcher = (REPO_ROOT / "bin" / "oss-workspace").read_text(encoding="utf-8")
    arm = launcher.split("declared-but-not-live)", 1)[1].split(";;", 1)[0]
    assert 'plugin_channel_target=""' in arm
