"""#1113 -- `_render` puts forge-supplied text (`detail`, a leg's `name`) into
a line-structured receipt this loop parses (`#N | STATE | ...`) without
flattening embedded newlines first. A `detail` or leg name containing its own
newline plus something shaped like `#999 | GREEN |` would land at column 0
of the rendered output, forging what looks like a second, unrelated row.

Paired with a clean-value positive control in the same fixture, per this
repo's own rule that a negative assertion needs one.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pr_green  # noqa: E402

_INJECTION = "boom\n#999 | GREEN | branch: evil | sha: deadbeef"


def test_could_not_read_detail_with_embedded_newline_stays_one_row():
    entry = {"pr": 1, "state": pr_green.STATE_COULD_NOT_READ, "detail": _INJECTION}
    rendered = pr_green._render(entry)
    lines = rendered.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("#1 | COULD-NOT-READ |")


def test_could_not_read_clean_detail_positive_control():
    entry = {"pr": 1, "state": pr_green.STATE_COULD_NOT_READ, "detail": "gh exit 1"}
    rendered = pr_green._render(entry)
    assert rendered == "#1 | COULD-NOT-READ | gh exit 1"


def test_red_leg_name_with_embedded_newline_stays_one_row_per_leg():
    entry = {
        "pr": 2,
        "state": pr_green.STATE_RED,
        "branch": "fix/1",
        "sha": "abc123",
        "failing": [
            {"name": _INJECTION, "workflow": "tests.yml", "conclusion": "FAILURE"}
        ],
    }
    rendered = pr_green._render(entry)
    lines = rendered.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("#2 | RED |")
    assert lines[1].startswith("  FAILED boom #999 | GREEN | branch: evil | sha: deadbeef")


def test_red_leg_name_clean_positive_control():
    entry = {
        "pr": 2,
        "state": pr_green.STATE_RED,
        "branch": "fix/1",
        "sha": "abc123",
        "failing": [
            {"name": "unit-tests", "workflow": "tests.yml", "conclusion": "FAILURE"}
        ],
    }
    rendered = pr_green._render(entry)
    lines = rendered.splitlines()
    assert len(lines) == 2
    assert lines[1] == "  FAILED unit-tests (workflow: tests.yml, conclusion: FAILURE)"


def test_red_leg_workflow_with_embedded_newline_stays_one_row_per_leg():
    """Self-review finding: `leg.get("workflow")` sits two tokens after the
    now-flattened `leg["name"]` on the identical `.format()` call, and for a
    legacy StatusContext check both fields are populated from the same
    forge-controlled `row.get("context")` (see `read_pr` in pr_green.py) --
    so leaving `workflow` unflattened reopens the identical injection one
    field over."""
    entry = {
        "pr": 2,
        "state": pr_green.STATE_RED,
        "branch": "fix/1",
        "sha": "abc123",
        "failing": [
            {"name": "unit-tests", "workflow": _INJECTION, "conclusion": "FAILURE"}
        ],
    }
    rendered = pr_green._render(entry)
    lines = rendered.splitlines()
    assert len(lines) == 2
    assert lines[1].startswith(
        "  FAILED unit-tests (workflow: boom #999 | GREEN | branch: evil | sha: deadbeef"
    )


def test_pending_leg_name_with_embedded_newline_stays_one_row():
    """Self-review finding: `pending_legs` entries come from the same
    forge-controlled `name`/`context` source as the RED branch's
    `leg["name"]`, joined and printed raw with no flattening at all."""
    entry = {
        "pr": 4,
        "state": pr_green.STATE_PENDING,
        "branch": "fix/1",
        "sha": "abc123",
        "pending_legs": [_INJECTION],
    }
    rendered = pr_green._render(entry)
    lines = rendered.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("#4 | PENDING | branch: fix/1 | sha: abc123 | still running: boom")


def test_pending_leg_name_clean_positive_control():
    entry = {
        "pr": 4,
        "state": pr_green.STATE_PENDING,
        "branch": "fix/1",
        "sha": "abc123",
        "pending_legs": ["unit-tests"],
    }
    rendered = pr_green._render(entry)
    assert rendered == "#4 | PENDING | branch: fix/1 | sha: abc123 | still running: unit-tests"
