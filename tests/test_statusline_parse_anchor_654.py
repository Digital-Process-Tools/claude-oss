"""`parse_channel_report` anchors at column 0, not on the first stripped match (#654).

`parse_channel_report` used to strip each line before testing it against
`"channel: "`, so an INDENTED line earlier in the report that merely looked
like a state line outranked the genuine, un-indented one further down. The
fix anchors the match at column 0 -- before any stripping -- so indentation
protects a decoy line from ever being read as the real state.

The fixture pairs the failing case (an indented decoy ahead of the real,
un-indented line) with the control that already passed before this fix (a
single un-indented state line, unaffected by anchoring).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def test_parse_channel_report_ignores_an_indented_decoy_ahead_of_the_real_line():
    """The must-not-fire half: an indented line that merely LOOKS like a state
    line must never outrank the genuine, un-indented state line that follows it.
    """
    text = "  channel: FORWARDING\nchannel: NOT DELIVERING\n"
    assert statusline.parse_channel_report(text) == "not_delivering"


def test_parse_channel_report_still_reads_an_unindented_line_normally():
    """The must-fire control, in the same fixture: an un-indented state line on
    its own must still be read -- anchoring at column 0 must not stop matching
    the ordinary case the old, stripping implementation already handled.
    """
    text = "channel: NOT DELIVERING\n"
    assert statusline.parse_channel_report(text) == "not_delivering"
