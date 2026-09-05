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
    text = (
        GOOD
        + "\n\nSupertool required: {{PASTE THE FULL CONTENTS OF <scratchpad path> HERE}}\n"
    )
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
    """Not just the one recorded phrase -- any leftover `{{...}}` marker."""
    text = GOOD + "\n\nFix the thing in {{module_name}}.\n"
    payload = brief_schema.check_text(text)
    assert "placeholder" in payload["missing"]


def test_a_placeholder_spanning_a_line_wrap_is_still_caught():
    """oss:auditor's self-review finding on #1022: the earlier bound
    excluded a newline inside the braces, so a marker wrapped across a line
    -- an ordinary thing for prose to do -- fell through to the same clean
    payload as no marker at all."""
    text = (
        GOOD
        + "\n\nSupertool required: {{PASTE THE FULL CONTENTS OF\n<scratchpad path> HERE}}\n"
    )
    payload = brief_schema.check_text(text)
    assert "placeholder" in payload["missing"]


def test_a_placeholder_longer_than_the_old_200_char_bound_is_still_caught():
    """The same finding, the other axis: the recorded phrase embeds a full
    scratchpad path, which grows with repo/branch/session-id length and can
    plausibly exceed a tight single-line character cap."""
    long_path = "/very/long/scratchpad/path" * 10
    text = GOOD + "\n\n{{PASTE THE FULL CONTENTS OF " + long_path + " HERE}}\n"
    payload = brief_schema.check_text(text)
    assert "placeholder" in payload["missing"]


def test_a_genuine_github_actions_expression_does_not_fire():
    """The must-not-fire half, found on self-review (#1022): this repo's own
    workflow files and `scripts/scaffold.py`'s generated YAML use GitHub
    Actions' `${{ ... }}` expression syntax, which a brief scoping a
    CI/workflow lane can legitimately quote. That is real double-brace
    syntax this repo's own tree does use, unlike a bare `{{...}}`, and it
    must not be confused with a leftover template placeholder."""
    text = GOOD + "\n\nUpdate the workflow: `GH_TOKEN: ${{ github.token }}`.\n"
    payload = brief_schema.check_text(text)
    assert "placeholder" not in payload["missing"]
    text = GOOD + "\n\ngroup: ${{ github.workflow }}-${{ github.ref }}\n"
    payload = brief_schema.check_text(text)
    assert "placeholder" not in payload["missing"]
