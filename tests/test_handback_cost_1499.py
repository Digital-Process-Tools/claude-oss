"""Optional `COST:` line on a handback -- #1499.

`schemas/agent-report.schema.json` carries a `cost` block for a developer
report (max_context, turns, bash_calls, three-state) wired via
`scripts/agent_cost.py`, but a sub-manager's own tick handback
(`scripts/tick_handback.py`) and a releaser's own handback
(`scripts/release_handback.py`) are plain text-frame classifiers with no
equivalent field -- decision item 2 in #1499's own checklist ("each agent
records its max context, turn count and Bash-call count in its handback and
report") names both, not only the developer report.

The judgment call: a new JSON schema for these two would be a second
convention sitting beside an existing text-frame one for no reason but the
developer report already being JSON. Both `tick_handback.py` and
`release_handback.py` are plain text-frame classifiers today (a `TICK:`/
`RELEASE:` header plus companion fields like `BLOCKER:`, `WAIT-DISPATCH:`),
so `COST:` is one more such field: free text, folded to one line, exactly
like `BLOCKER:`/`REASON:`/`detail`. It is OPTIONAL and never blocks
classification -- missing or duplicated is folded to the same "absent"
answer, the same deliberate choice `release_handback.py` already makes for
`GATE:` on a `paused` release (see that module's own comment on why an
ambiguous optional field does not promote to `could-not-classify`).

Every negative assertion here carries a positive control in the same
fixture, per this repo's own rule.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import tick_handback  # noqa: E402
import release_handback  # noqa: E402


def test_tick_completed_with_cost_captures_it():
    verdict = tick_handback.classify(
        "TICK: completed\n"
        "TICK-ENDS: work-started\n"
        "COST: agent-cost: measured  sub-manager  max_context=180,000  turns=40  bash=88\n"
        "summary paragraph\n"
    )
    assert verdict["state"] == "completed"
    assert "max_context=180,000" in verdict["cost"]


def test_tick_completed_without_cost_still_classifies():
    """Negative control: COST: is optional and must never block a state that
    is otherwise perfectly classifiable."""
    verdict = tick_handback.classify(
        "TICK: completed\nTICK-ENDS: nothing-left\nsummary paragraph\n"
    )
    assert verdict["state"] == "completed"
    assert verdict["cost"] is None


def test_tick_paused_with_cost_captures_it():
    verdict = tick_handback.classify(
        "TICK: paused\n"
        "WAIT-DISPATCH: PR #825 opened, CI running\n"
        "WAIT-OBSERVABLE: PR #825 checks all green or one leg failing\n"
        "COST: agent-cost: no-match  none of 3 transcripts carries foo\n"
    )
    assert verdict["state"] == "paused"
    assert "no-match" in verdict["cost"]


def test_tick_duplicated_cost_folds_to_absent_not_could_not_classify():
    """A second COST: line is exactly as undecidable as a genuinely missing
    one for GATE: on a paused release (release_handback.py's own precedent)
    -- COST: gets the identical treatment here, deliberately, since it never
    decides the outcome."""
    verdict = tick_handback.classify(
        "TICK: blocked\n"
        "BLOCKER: waiting on maintainer input\n"
        "COST: agent-cost: measured max_context=100000\n"
        "COST: agent-cost: measured max_context=200000\n"
    )
    assert verdict["state"] == "blocked"
    assert verdict["cost"] is None


def test_release_released_with_cost_captures_it():
    verdict = release_handback.classify(
        "RELEASE: released\nTAG: v0.26.0\nCOST: agent-cost: measured  releaser  max_context=90,000\n"
    )
    assert verdict["state"] == "released"
    assert "max_context=90,000" in verdict["cost"]


def test_release_released_without_cost_still_classifies():
    """Negative control: COST: is optional here too."""
    verdict = release_handback.classify("RELEASE: released\nTAG: v0.26.0\n")
    assert verdict["state"] == "released"
    assert verdict["cost"] is None
