"""#1737: the scheduler's own `tick_handback.py` call is the backstop for a
sub-manager that skipped its own `--clear-marker-root` step.

`agents/sub-manager.md` clears the `sub-manager` role marker as a side effect
of its own `tick_handback.py --clear-marker-root .` validate-step call. When a
sub-manager skips that call -- observed on claude-supertool, 2026-09-24, tick
8 reported `TICK: completed` with no mention of the validate call and the
marker still on disk -- the marker stays `live` for
`agent_role.MARKER_TTL_SECONDS` (4 hours), and the next `/oss:run` step 1
doctor spawn refuses on it (`agent_role.py --write doctor` exit 3).

`commands/tick.md` already runs `tick_handback.py --framed -` on every
sub-manager handback, without `--clear-marker-root`. At that point the
scheduler is the one actor that knows for certain the tick is over: it holds
the handback and has spawned nothing since. Passing `--clear-marker-root
<clone>` on that same call means a sub-manager that forgot is covered by the
one call that always runs -- `tick_handback.py` only fires the clear on a
`completed` verdict (#1585), so this is a safe no-op on every other verdict.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TICK_MD = REPO_ROOT / "commands" / "tick.md"


def _text() -> str:
    return TICK_MD.read_text(encoding="utf-8")


def test_scheduler_tick_handback_call_clears_the_marker_root():
    text = _text()
    assert (
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tick_handback.py" --framed - '
        "--clear-marker-root <clone>" in text
    )


def test_scheduler_backstop_is_explained_as_a_backstop():
    """Must say why: the sub-manager's own clear can stay, since clearing
    twice is harmless, and tick_handback.py only fires the clear on a
    `completed` verdict -- so this never clears a marker while a tick is
    still genuinely in flight."""
    text = _text()
    idx = text.index("--clear-marker-root <clone>")
    nearby = text[max(0, idx - 200) : idx + 1200]
    assert "completed" in nearby
    assert "harmless" in nearby or "clearing twice" in nearby
