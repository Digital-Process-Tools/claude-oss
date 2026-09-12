"""A developer brief names the recon brief it starts from -- #1499.

Decision 4 of #1499: an implementing lane starts from a short summary a
read-only recon spawn produced, rather than from thirty file reads it then
carries for three hundred turns. `lane_setup_brief_schema` gains a ninth
element, `recon`, presence only: a brief that never mentions a recon brief
renders a finding, not a refusal, because a lane briefed without one still
works -- it just pays the orientation reads itself.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup_brief_schema as brief_schema  # noqa: E402


def _row(payload, name):
    return next(row for row in payload["elements"] if row["element"] == name)


def test_recon_is_a_presence_only_element():
    row = _row(brief_schema.check_text("# Recon brief\n\nsites: a.py:10"), "recon")
    assert row["state"] == "found"
    assert row["checked"] == brief_schema.PRESENCE


def test_a_brief_with_no_recon_section_is_a_finding_not_a_refusal():
    payload = brief_schema.check_text("no orientation here at all")
    row = _row(payload, "recon")
    assert row["state"] == "missing"
    assert row["checked"] == brief_schema.PRESENCE
    # presence-only: the receipt still renders the Agent() line on this alone
    assert "recon" in row["why"]


def test_the_supertool_block_does_not_satisfy_recon():
    """The word must appear outside the supertool blockquote, which never
    mentions recon today and must not be what a future edit relies on."""
    text = "> use supertool recon read\n\nnothing else"
    assert _row(brief_schema.check_text(text), "recon")["state"] == "missing"


def test_nine_elements_now():
    assert len(brief_schema.check_text("x")["elements"]) == 9
