"""The two right-hand fields, at the width they are worth (#511, #512).

`last` (#511) renders the machine's local zone. The field's own reason for existing is that
a reader subtracts it from their own clock to recover how stale the line is, and a UTC
stamp under a label that means "now" makes that subtraction quietly wrong everywhere but
one zone -- measured at 10:11 on a wall clock reading 12:15. The zone the stamp is produced
in and the zone it is read in are the same zone: one machine, one second.

The plugin block (#512) collapses to `plug 4ok` while everything is current, and expands to
name what is not. The count is what makes the collapse safe: `plugin_facts` already argues
that a plugin absent because it is fine and a plugin absent because nothing looked at it
render identically, and only the second is a problem. `4ok` says four were looked at, `?`
says nobody did, and the assertions below pair those two so neither can pass for the other.
"""

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------------------ #511 local time


def test_the_stamp_is_the_local_reading_of_that_instant():
    """Not a fixed string: this asserts against the platform's own answer for the same
    epoch second, so it holds in whatever zone the runner is in -- including UTC, where
    the two readings coincide and this test proves nothing on its own. The control below
    is what makes it mean something."""
    now = 1_755_940_260.0
    assert statusline._render_stamp(now) == time.strftime("%H:%M", time.localtime(now))


def test_the_stamp_is_not_utc_when_the_runner_is_not_on_utc():
    """The control for the test above, and it declines rather than asserting when the
    runner cannot tell the two apart -- a CI leg on UTC has nothing to measure here."""
    import datetime

    now = 1_755_940_260.0
    utc = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%H:%M")
    local = time.strftime("%H:%M", time.localtime(now))
    if local == utc:
        import pytest

        pytest.skip(
            "this runner's local zone reads {} at that instant, the same as UTC, so a "
            "stamp in either zone is indistinguishable here and the UTC bug this covers "
            "cannot be reproduced on it".format(local)
        )
    assert statusline._render_stamp(now) == local
    assert statusline._render_stamp(now) != utc


def test_a_stamp_the_platform_cannot_resolve_is_unknown_not_utc():
    """`localtime` raises on a value it cannot convert. A fallback to UTC under a label
    that means local is the same defect one layer down, so the field goes `?` instead."""
    assert statusline._render_stamp(float("inf")) is None
    assert statusline._last_field(None) == "last ?"


def test_the_must_fire_control_for_that_one():
    assert statusline._render_stamp(1_755_940_260.0) is not None
    assert statusline._last_field("12:15") == "last 12:15"


# --------------------------------------------------------------- #512 plugin block


def _status(state, installed="0.12.0", latest=None):
    return {"state": state, "installed": installed, "latest": latest}


def test_all_current_collapses_to_a_count():
    field = statusline._plugins_field(
        [("oss", _status("current")), ("claude-supertool", _status("current"))],
        statusline._symbols(True),
    )
    assert field == "plug 2ok"


def test_the_count_is_what_keeps_the_collapse_honest():
    """Two plugins fine and no plugins at all must not render alike."""
    symbols = statusline._symbols(True)
    assert statusline._plugins_field([], symbols) == "plug ?"
    assert statusline._plugins_field([], symbols) != statusline._plugins_field(
        [("oss", _status("current")), ("claude-supertool", _status("current"))], symbols
    )


def test_a_plugin_that_is_behind_is_named_and_the_rest_stay_a_count():
    field = statusline._plugins_field(
        [
            ("oss", _status("current")),
            ("claude-supertool", _status("behind", "0.48.0", "0.49.0")),
            ("claude-remember", _status("current")),
        ],
        statusline._symbols(True),
    )
    assert field == "plug 2ok supe>0.49.0"


def test_a_comparison_nobody_could_make_is_its_own_group_never_a_tick():
    field = statusline._plugins_field(
        [
            ("oss", _status("current")),
            ("claude-jit-context", _status("unknown", None, None)),
        ],
        statusline._symbols(True),
    )
    assert field == "plug 1ok 1?"


def test_an_install_ahead_of_the_published_version_is_named_too():
    """Ahead is not current: it is the state where a local checkout is being run."""
    field = statusline._plugins_field(
        [("oss", _status("ahead", "0.13.0"))], statusline._symbols(True)
    )
    assert field == "plug 0ok oss+0.13.0"


def test_several_at_once_are_all_named():
    field = statusline._plugins_field(
        [
            ("oss", _status("behind", "0.11.0", "0.12.0")),
            ("claude-supertool", _status("behind", "0.48.0", "0.49.0")),
            ("claude-remember", _status("current")),
            ("claude-jit-context", _status("unknown", None, None)),
        ],
        statusline._symbols(True),
    )
    assert field == "plug 1ok oss>0.12.0 supe>0.49.0 1?"


def test_the_glyphs_are_used_where_the_console_encodes_them():
    field = statusline._plugins_field(
        [("oss", _status("current")), ("claude-supertool", _status("behind", "0.48.0", "0.49.0"))],
        statusline._symbols(False),
    )
    assert field == "plug 1✓ supe⇡0.49.0"


def test_the_whole_line_carries_the_collapsed_block():
    facts = {
        "model": "Opus",
        "percent": 10,
        "repo_name": "oss",
        "branch": "main",
        "default_branch": "main",
        "board": {"prs": 1, "issues": 2, "checks": None},
        "release": {"state": "measured", "since": 4, "typical": 17},
        "plugins": [("oss", _status("current")), ("claude-supertool", _status("current"))],
    }
    line = statusline.render(facts, ascii_only=True)
    assert "plug 2ok" in line
    assert "0.12.0 " not in line.split("plug")[1]
