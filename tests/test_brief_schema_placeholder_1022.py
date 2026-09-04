"""#1022: a leftover template placeholder in a composed brief is unfixable
after dispatch.

There is no templating step between a sub-manager composing an `Agent()`
prompt and it being sent -- whatever string is typed is what the agent
receives verbatim. A sub-manager dispatching three lanes in one tick wrote
each brief's "supertool required" section as the literal placeholder string
("{{PASTE THE FULL CONTENTS OF <scratchpad path> HERE}}") instead of the real
blockquote content, caught it only after all three `Agent()` calls had
already returned, and found `SendMessage` unavailable to correct it -- so the
only reachable moment to catch this is before the call, on the composed
text (see trap.d/1022.brief-placeholder-not-substituted.md).

`brief_schema.py` already validates a brief's draft file before the spawn
(#967), so a structural check for a literal `{{...}}` marker slots into the
existing, already-run mechanism rather than inventing a new one.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import brief_schema  # noqa: E402

from test_brief_schema_967 import GOOD  # noqa: E402


def test_a_leftover_placeholder_marker_is_a_finding():
    """The recorded failure, verbatim."""
    text = GOOD + "\n\nSupertool required: {{PASTE THE FULL CONTENTS OF <scratchpad path> HERE}}\n"
    payload = brief_schema.check_text(text)
    assert payload["state"] == brief_schema.STATE_FINDINGS
    assert "placeholder" in payload["missing"]
    why = [r["why"] for r in payload["elements"] if r["element"] == "placeholder"][0]
    assert "PASTE THE FULL CONTENTS" in why


def test_a_complete_brief_with_no_placeholder_passes():
    """The positive control paired with the assertion above, in the same
    fixture family: a brief with no `{{...}}` marker is not flagged."""
    payload = brief_schema.check_text(GOOD)
    assert payload["state"] == brief_schema.STATE_OK
    assert "placeholder" not in payload["missing"]
    row = [r for r in payload["elements"] if r["element"] == "placeholder"][0]
    assert row["state"] == "found"
    assert row["checked"] == brief_schema.STRUCTURAL


def test_a_generic_double_brace_marker_is_also_caught():
    """Not just the one recorded phrase -- any leftover `{{...}}` marker, since
    this repo's loop prose never legitimately uses double-brace syntax."""
    text = GOOD + "\n\nFix the thing in {{module_name}}.\n"
    payload = brief_schema.check_text(text)
    assert "placeholder" in payload["missing"]
