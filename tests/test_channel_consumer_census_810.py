"""#810: `bin/oss-workspace` arms `--dangerously-load-development-channels` after
verifying its OWN registration, and never asks whether a second, unrelated MCP
server also resolves to `notifiers/claude-channel/channel.ts` -- the consumer
script every claude-channel server shares. Two servers on that script race for one
Unix socket; one binds, one is silently refused, and `channel:health` degrades to
`CANNOT DETERMINE` with no error surfaced anywhere a maintainer is looking.

This file tests the doctor-side mirror the issue's own "Proposed change" step 3
asks for: `channel_consumer_names` parses `claude mcp list` prose the same way
whichever caller reads it (the launcher's own inline parser and this module have
to agree, so `bin/oss-workspace` imports this module rather than carrying a second
regex -- see `tests/test_workspace_launcher.py`'s own #810 cases for the launcher
side of the same fixture), `channel_consumer_census_state` turns that into three
states (`collision` / `single-or-none` folded as `none`/`single` / `could-not-ask`),
and `check_channel_consumer_census` renders each as one doctor line.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_mcp_channel_registration as mod  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


class _FakeCompleted:
    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def _run_answering(text, returncode=0):
    def run(cmd, **kwargs):
        return _FakeCompleted(returncode, text.encode("utf-8"))
    return run


TWO_ROWS = (
    "claude-channel: bun /Users/x/Documents/claude-supertool/notifiers/claude-channel/channel.ts\n"
    "oss-channel:    bun /Users/x/.claude/plugins/cache/dpt-plugins/supertool/0.53.0/notifiers/claude-channel/channel.ts\n"
)

ONE_ROW = (
    "oss-channel:    bun /Users/x/.claude/plugins/cache/dpt-plugins/supertool/0.53.0/notifiers/claude-channel/channel.ts\n"
)

NO_ROWS = (
    "some-other-server: bun /Users/x/somewhere/else/entrypoint.ts\n"
)

WINDOWS_ROW = (
    "oss-channel:    bun C:\\Users\\x\\plugins\\cache\\dpt-plugins\\supertool\\0.53.0\\notifiers\\claude-channel\\channel.ts\n"
)

#: Measured directly against a REAL `claude mcp list` (2.1.219) rather than
#: assumed from the issue's own illustrative example -- every row carries a
#: trailing " - <connection status>" after the args, which an end-anchored
#: suffix pattern misses entirely (found live, not in a fixture: a first
#: version of this check reported 0 servers against this exact repository's
#: own real registrations).
REAL_TWO_ROWS_WITH_STATUS = (
    "claude-channel: bun /Users/x/Documents/claude-supertool/notifiers/claude-channel/channel.ts - X Failed to connect - -32000: MCP error -32000: Connection closed\n"
    "oss-channel: bun /Users/x/.claude/plugins/cache/dpt-plugins/supertool/0.53.0/notifiers/claude-channel/channel.ts - X Failed to connect - -32000: MCP error -32000: Connection closed\n"
)


# --------------------------------------------------------------- channel_consumer_names

def test_parses_two_matching_rows():
    assert mod.channel_consumer_names(TWO_ROWS) == ["claude-channel", "oss-channel"]


def test_parses_one_matching_row():
    assert mod.channel_consumer_names(ONE_ROW) == ["oss-channel"]


def test_a_server_pointing_elsewhere_does_not_match():
    """The must-not-fire control: an unrelated server name must never be counted."""
    assert mod.channel_consumer_names(NO_ROWS) == []


def test_a_windows_backslash_path_still_matches():
    assert mod.channel_consumer_names(WINDOWS_ROW) == ["oss-channel"]


def test_a_line_with_no_colon_is_ignored():
    assert mod.channel_consumer_names("not a server line at all\n") == []


def test_trailing_carriage_returns_do_not_break_the_match():
    text = ONE_ROW.replace("\n", "\r\n")
    assert mod.channel_consumer_names(text) == ["oss-channel"]


def test_a_real_claude_mcp_list_row_still_matches_past_the_connection_status():
    """The instance this repository's own review actually hit: `claude mcp
    list` (2.1.219) appends " - <connection status>" after every row's args,
    so an end-anchored suffix pattern -- which every earlier test above would
    still pass against the issue's own clean example -- matched ZERO real
    rows. Measured against this repository's own two live registrations."""
    assert mod.channel_consumer_names(REAL_TWO_ROWS_WITH_STATUS) == [
        "claude-channel", "oss-channel",
    ]


# --------------------------------------------------------- channel_consumer_census_state

def test_two_rows_is_a_collision():
    state, detail = mod.channel_consumer_census_state(run=_run_answering(TWO_ROWS), which=lambda x: "/usr/bin/claude")
    assert state == "collision"
    assert detail == ["claude-channel", "oss-channel"]


def test_one_row_is_not_a_collision():
    """The must-fire positive control for the flag staying armed: exactly one
    consumer registration must never read as a collision."""
    state, detail = mod.channel_consumer_census_state(run=_run_answering(ONE_ROW), which=lambda x: "/usr/bin/claude")
    assert state == "single"
    assert detail == "oss-channel"


def test_no_rows_is_none():
    state, detail = mod.channel_consumer_census_state(run=_run_answering(NO_ROWS), which=lambda x: "/usr/bin/claude")
    assert state == "none"


def test_claude_not_on_path_is_could_not_ask():
    state, detail = mod.channel_consumer_census_state(run=_run_answering(ONE_ROW), which=lambda x: None)
    assert state == "could-not-ask"
    assert "PATH" in detail


def test_a_nonzero_exit_is_could_not_ask_never_read_as_one_server():
    """The third state the issue names explicitly: `claude mcp list` failing must
    never be read as "exactly one server", which would silently arm a collision."""
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering("boom", returncode=1), which=lambda x: "/usr/bin/claude"
    )
    assert state == "could-not-ask"


def test_a_crashed_probe_is_could_not_ask_not_a_crash():
    def run(cmd, **kwargs):
        raise OSError("no such file")
    state, detail = mod.channel_consumer_census_state(run=run, which=lambda x: "/usr/bin/claude")
    assert state == "could-not-ask"


def test_run_is_handed_the_resolved_path_not_the_bare_name():
    """#753/#810's own Windows CI regression: `which()` was already called to
    check PATH membership, but `run()` was still handed the bare `"claude"`
    string instead of `which()`'s own resolved, extension-qualified answer --
    which `subprocess.run(shell=False)` cannot turn back into `claude.cmd` on
    Windows. Pin the argv `run` actually receives, not just the state it
    returns, so a regression back to the bare name is caught here rather than
    only on a windows-latest CI leg nobody can run locally."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(0, ONE_ROW.encode("utf-8"))

    mod.channel_consumer_census_state(
        run=run, which=lambda name: "/resolved/claude.cmd"
    )
    assert calls and calls[0][0] == "/resolved/claude.cmd", calls


# --------------------------------------------------------- check_channel_consumer_census

def test_check_reports_warn_on_collision():
    doctor.check_channel_consumer_census(run=_run_answering(TWO_ROWS), which=lambda x: "/usr/bin/claude")
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN"
    assert "claude-channel" in message and "oss-channel" in message


def test_check_reports_ok_on_a_single_registration():
    doctor.check_channel_consumer_census(run=_run_answering(ONE_ROW), which=lambda x: "/usr/bin/claude")
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "OK"


def test_check_reports_ok_on_no_registration():
    doctor.check_channel_consumer_census(run=_run_answering(NO_ROWS), which=lambda x: "/usr/bin/claude")
    assert len(doctor.FINDINGS) == 1
    assert doctor.FINDINGS[0][0] == "OK"


def test_check_reports_warn_could_not_ask_never_ok():
    """Must-not-fire: `could-not-ask` must never render as OK, which would claim a
    clean census that never happened."""
    doctor.check_channel_consumer_census(
        run=_run_answering("boom", returncode=1), which=lambda x: "/usr/bin/claude"
    )
    assert len(doctor.FINDINGS) == 1
    assert doctor.FINDINGS[0][0] == "WARN"
    assert "unknown" in doctor.FINDINGS[0][1].lower()

# --------------------------------------------------------- launcher relay (#810 review)

def _crash_run(cmd, **kwargs):
    raise AssertionError("a relayed report must never fall through to a real ask")


def test_a_relayed_collision_report_never_shells_out_again():
    """The must-fire half: a genuine relay must be trusted, not re-asked --
    `_crash_run` would fail the test if `claude mcp list` ran a second time."""
    env = {
        "OSS_WORKSPACE_CENSUS_CHECKED": "1",
        "OSS_WORKSPACE_CENSUS_REPORT": "collision\nclaude-channel\noss-channel",
    }
    state, detail = mod.channel_consumer_census_state(run=_crash_run, which=lambda x: "/usr/bin/claude", env=env)
    assert state == "collision"
    assert detail == ["claude-channel", "oss-channel"]


def test_a_relayed_single_report_never_shells_out_again():
    env = {
        "OSS_WORKSPACE_CENSUS_CHECKED": "1",
        "OSS_WORKSPACE_CENSUS_REPORT": "single\noss-channel",
    }
    state, detail = mod.channel_consumer_census_state(run=_crash_run, which=lambda x: "/usr/bin/claude", env=env)
    assert state == "single"
    assert detail == "oss-channel"


def test_a_relayed_none_report_never_shells_out_again():
    env = {"OSS_WORKSPACE_CENSUS_CHECKED": "1", "OSS_WORKSPACE_CENSUS_REPORT": "none"}
    state, detail = mod.channel_consumer_census_state(run=_crash_run, which=lambda x: "/usr/bin/claude", env=env)
    assert state == "none"


def test_a_relayed_could_not_ask_report_never_shells_out_again():
    env = {
        "OSS_WORKSPACE_CENSUS_CHECKED": "1",
        "OSS_WORKSPACE_CENSUS_REPORT": "could-not-ask\nclaude mcp list exited 1",
    }
    state, detail = mod.channel_consumer_census_state(run=_crash_run, which=lambda x: "/usr/bin/claude", env=env)
    assert state == "could-not-ask"
    assert detail == "claude mcp list exited 1"


def test_no_relay_flag_falls_through_to_a_real_ask():
    """The must-not-fire control: without `OSS_WORKSPACE_CENSUS_CHECKED=1`, a
    stray `OSS_WORKSPACE_CENSUS_REPORT` in the environment must never be
    trusted -- the real ask always runs."""
    env = {"OSS_WORKSPACE_CENSUS_REPORT": "collision\na\nb"}
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering(ONE_ROW), which=lambda x: "/usr/bin/claude", env=env,
    )
    assert state == "single"


def test_an_unrecognised_relay_falls_through_to_a_real_ask():
    env = {"OSS_WORKSPACE_CENSUS_CHECKED": "1", "OSS_WORKSPACE_CENSUS_REPORT": "not-a-real-state"}
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering(ONE_ROW), which=lambda x: "/usr/bin/claude", env=env,
    )
    assert state == "single"


def test_an_empty_relay_report_falls_through_to_a_real_ask():
    env = {"OSS_WORKSPACE_CENSUS_CHECKED": "1", "OSS_WORKSPACE_CENSUS_REPORT": ""}
    state, detail = mod.channel_consumer_census_state(
        run=_run_answering(ONE_ROW), which=lambda x: "/usr/bin/claude", env=env,
    )
    assert state == "single"


def test_check_channel_consumer_census_threads_env_through():
    env = {
        "OSS_WORKSPACE_CENSUS_CHECKED": "1",
        "OSS_WORKSPACE_CENSUS_REPORT": "collision\nclaude-channel\noss-channel",
    }
    doctor.check_channel_consumer_census(run=_crash_run, which=lambda x: "/usr/bin/claude", env=env)
    assert len(doctor.FINDINGS) == 1
    assert doctor.FINDINGS[0][0] == "WARN"
    assert "claude-channel" in doctor.FINDINGS[0][1] and "oss-channel" in doctor.FINDINGS[0][1]

