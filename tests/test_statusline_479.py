"""The status line, and the three states it must not round off (#479).

A status line renders on every message, so every fact in it is either cached, cheap, or
absent. The defect this repository is named after is exactly what a status line invites:
a count nobody took renders as `0`, a version comparison nobody could make renders as
`ok`, and a tick nobody armed renders the same as a transcript nobody could read.

Every assertion below pairs a must-not-fire with a must-fire, because an assertion that
`?` does not appear also passes against a renderer that produces nothing at all.
"""

import ast
import inspect
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402
import scaffold  # noqa: E402


# --------------------------------------------------------------------------- board


def test_absent_cache_renders_unknown_and_never_zero():
    """A count nobody took is not a count that came back zero."""
    board = statusline.board_from_cache(None)
    assert board["state"] == "unknown"
    assert board["prs"] is None and board["issues"] is None


def test_a_cache_that_answered_zero_is_a_measurement():
    """The must-fire control: zero is a real answer and must survive as one."""
    board = statusline.board_from_cache(
        {"prs": 0, "issues": 0, "issues_external": 0, "fetched_at": 0}
    )
    assert board["state"] == "measured"
    assert board["prs"] == 0 and board["issues"] == 0 and board["issues_external"] == 0


def test_a_cache_missing_a_count_is_unknown_for_that_count_alone():
    board = statusline.board_from_cache({"prs": 2, "fetched_at": 0})
    assert board["prs"] == 2
    assert board["issues"] is None


# ----------------------------------------------------------------------- next tick


def _transcript(tmp_path, lines):
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def _wakeup(timestamp, delay, stop=False):
    payload = {"stop": True} if stop else {"delaySeconds": delay, "reason": "ci"}
    return {
        "timestamp": timestamp,
        "message": {
            "content": [
                {"type": "tool_use", "name": "ScheduleWakeup", "input": payload}
            ]
        },
    }


def test_no_transcript_is_unknown_not_none():
    tick = statusline.next_tick(None, now=0.0)
    assert tick["state"] == "unknown"


def test_scanned_transcript_without_a_wakeup_reports_none(tmp_path):
    """The must-fire control for the arm above: a file that was read and held nothing."""
    path = _transcript(tmp_path, [{"timestamp": "2026-08-22T10:00:00.000Z", "message": {}}])
    tick = statusline.next_tick(str(path), now=0.0)
    assert tick["state"] == "none"


def test_an_armed_wakeup_reports_the_seconds_left(tmp_path):
    path = _transcript(tmp_path, [_wakeup("2026-08-22T10:00:00.000Z", 600)])
    now = statusline.parse_timestamp("2026-08-22T10:05:00.000Z")
    tick = statusline.next_tick(str(path), now=now)
    assert tick["state"] == "armed"
    assert tick["seconds"] == pytest.approx(300, abs=1)


def test_a_wakeup_whose_time_has_passed_is_due_not_armed(tmp_path):
    path = _transcript(tmp_path, [_wakeup("2026-08-22T10:00:00.000Z", 600)])
    now = statusline.parse_timestamp("2026-08-22T10:20:00.000Z")
    tick = statusline.next_tick(str(path), now=now)
    assert tick["state"] == "due"


def test_a_stop_is_not_an_armed_tick(tmp_path):
    path = _transcript(tmp_path, [_wakeup("2026-08-22T10:00:00.000Z", 600),
                                  _wakeup("2026-08-22T10:01:00.000Z", None, stop=True)])
    now = statusline.parse_timestamp("2026-08-22T10:02:00.000Z")
    tick = statusline.next_tick(str(path), now=now)
    assert tick["state"] == "stopped"


def test_the_last_wakeup_wins(tmp_path):
    path = _transcript(tmp_path, [_wakeup("2026-08-22T10:00:00.000Z", 60),
                                  _wakeup("2026-08-22T10:01:00.000Z", 3600)])
    now = statusline.parse_timestamp("2026-08-22T10:02:00.000Z")
    tick = statusline.next_tick(str(path), now=now)
    assert tick["state"] == "armed"
    assert tick["seconds"] == pytest.approx(3540, abs=1)


def test_a_truncated_scan_reports_unknown_rather_than_none(tmp_path):
    """A tail-scan that did not reach the top of the file cannot say `none`.

    This is the whole reason the scan carries a `truncated` flag: a wakeup armed at the
    start of a long session is below the window, and "I did not look there" must not
    render as "nothing is armed".
    """
    path = _transcript(tmp_path, [{"timestamp": "2026-08-22T10:00:00.000Z", "message": {}}] * 40)
    tick = statusline.next_tick(str(path), now=0.0, max_bytes=200)
    assert tick["state"] == "unknown"


# ------------------------------------------------------------------ plugin currency


def test_a_behind_plugin_names_the_version_it_is_behind():
    status = statusline.version_status("0.9.0", "0.10.0")
    assert status["state"] == "behind"
    assert status["latest"] == "0.10.0"


def test_a_current_plugin_is_current():
    assert statusline.version_status("0.10.0", "0.10.0")["state"] == "current"


def test_a_missing_latest_is_unknown_not_current():
    """Nobody asked the forge. That is not the same as the answer being `yes`."""
    assert statusline.version_status("0.10.0", None)["state"] == "unknown"


def test_a_missing_installed_is_unknown_not_behind():
    assert statusline.version_status(None, "0.10.0")["state"] == "unknown"


def test_a_leading_v_does_not_make_a_version_look_behind():
    assert statusline.version_status("0.10.0", "v0.10.0")["state"] == "current"


def test_the_newest_recorded_install_wins_over_dict_order(tmp_path):
    """One plugin, many entries, different versions -- measured on a real machine.

    `installed_plugins.json` never rewrites an old project's entry when a newer copy is
    installed elsewhere, so `oss` was recorded at 0.1.0, 0.5.0, 0.9.0 and 0.10.0 at
    once. Reading the last one is reading dict order, and it rendered a current machine
    as a release behind.
    """
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt": [
                        {"version": "0.10.0", "installPath": str(tmp_path / "new")},
                        {"version": "0.5.0", "installPath": str(tmp_path / "old")},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert statusline.installed_plugins(None, tmp_path)["oss"]["version"] == "0.10.0"


def test_an_unparseable_version_does_not_erase_a_readable_one(tmp_path):
    """The must-fire control's other half: `unknown` is not a version and never wins."""
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt": [
                        {"version": "0.10.0", "installPath": str(tmp_path / "new")},
                        {"version": "unknown", "installPath": str(tmp_path / "huh")},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert statusline.installed_plugins(None, tmp_path)["oss"]["version"] == "0.10.0"


def test_installed_plugins_is_resolved_per_project_not_the_newest_anywhere_521(tmp_path):
    """#521: two projects, two entries, two different versions. The pre-fix behaviour
    (`max()` over the whole table) reported the higher one for both projects; resolved
    per project, each sees its own pin."""
    behind = tmp_path / "behind-project"
    ahead = tmp_path / "ahead-project"
    behind.mkdir()
    ahead.mkdir()
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt": [
                        {"version": "9.9.8", "scope": "project", "projectPath": str(behind)},
                        {"version": "9.9.9", "scope": "project", "projectPath": str(ahead)},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert statusline.installed_plugins(behind, tmp_path)["oss"]["version"] == "9.9.8"
    assert statusline.installed_plugins(ahead, tmp_path)["oss"]["version"] == "9.9.9"


def test_a_project_current_on_its_own_entry_still_reports_current_521(tmp_path):
    """The must-not-fire control: a project whose own entry already carries the newest
    version keeps reporting it, not `?` and not another project's number."""
    here = tmp_path / "here"
    here.mkdir()
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt": [
                        {"version": "9.9.9", "scope": "project", "projectPath": str(here)},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert statusline.installed_plugins(here, tmp_path)["oss"]["version"] == "9.9.9"


def test_a_project_with_no_matching_entry_has_no_version_521(tmp_path):
    """No entry names this project -- the plugin is absent from the result entirely,
    which `version_status` upstream renders as `unknown` (`?`), never as the newest
    version recorded for some other project."""
    here = tmp_path / "here"
    elsewhere = tmp_path / "elsewhere"
    here.mkdir()
    (tmp_path / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt": [
                        {"version": "9.9.9", "scope": "project", "projectPath": str(elsewhere)},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert "oss" not in statusline.installed_plugins(here, tmp_path)


def test_normalized_path_folds_case_on_windows_521():
    """Self-review finding on #521: an installed-plugin `projectPath` and the path this
    session resolves can differ only in case on a case-insensitive filesystem, which
    `Path.resolve()` alone does not fold. `os.path.normcase` folds case on Windows
    (`ntpath`) and is a no-op on POSIX (`posixpath`), so this is real on Windows and
    intentionally unobserved here -- this test runs on every platform and only asserts
    the Windows-observable half."""
    if os.name == "nt":
        assert statusline._normalized_path("C:\\Users\\Me\\Proj") == statusline._normalized_path(
            "c:\\users\\me\\proj"
        )
    else:
        assert statusline._normalized_path("/tmp/Proj") != statusline._normalized_path("/tmp/proj")


# --------------------------------------------------------------------- gather


def test_gather_populates_the_render_stamp_and_last_user_age(tmp_path, monkeypatch):
    """End to end: `gather()` is what turns a transcript path and a clock into the
    two facts `render()` merely formats (#504).
    """
    # Not what this test is about, and a real fork here would launch a detached
    # `gh`-calling subprocess per test run.
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    (tmp_path / ".oss.json").write_text(
        json.dumps({"repo": "owner/name"}), encoding="utf-8"
    )
    transcript = _transcript(tmp_path, [_wakeup("2026-08-22T10:00:00.000Z", 600)])
    now = statusline.parse_timestamp("2026-08-22T10:04:00.000Z")
    payload = {"transcript_path": str(transcript)}
    facts = statusline.gather(payload, str(tmp_path), now=now)
    # The local reading of that instant, not "10:04" (#511): the stamp is compared by
    # the reader against their own clock, so it is rendered in their own zone. Asserted
    # against the platform's own answer rather than a fixed string, which would pin this
    # test to the runner that happened to write it.
    assert facts["last"] == time.strftime("%H:%M", time.localtime(now))
    assert facts["tick"]["state"] == "armed"


def test_gather_reports_the_render_stamp_in_the_local_zone():
    """A wall-clock reading of `now` in the zone the person reading it lives in (#511).

    This shipped as UTC, reasoning from the transcript's zone-less ISO stamps. That
    reasoning was about parsing -- `parse_timestamp` hands back epoch seconds, which are
    unambiguous -- and the field's own purpose is a subtraction against the reader's clock,
    which UTC makes silently wrong outside one zone. Measured at `last 10:11` on a wall
    clock reading 12:15. See tests/test_statusline_width_511_512.py for the pair of
    assertions that distinguishes the two zones where the runner allows it.
    """
    now = statusline.parse_timestamp("2026-08-22T10:04:00.000Z")
    assert statusline._render_stamp(now) == time.strftime("%H:%M", time.localtime(now))


# ------------------------------------------------------------------------- render


def _facts(**overrides):
    facts = {
        "model": "Opus",
        "percent": 42,
        "repo_name": "claude-oss",
        "branch": "main",
        # #547 instance 2: `render()` reads both `default_branch` (`:827`) and
        # `release` (`:838`) and this fixture carried neither, so `_leaf_paths`
        # -- itself derived from `_facts()` -- could never walk into them. Kept
        # different from `branch` so the "not the default" fold at `:826-830`
        # has something real to compare against.
        "default_branch": "main-upstream",
        "version": "0.10.0",
        "board": {
            "state": "measured",
            "prs": 2,
            "issues": 18,
            "age": 30,
            "checks": {"green": 1, "red": 0, "running": 0, "unknown": 0},
        },
        "release": {"since": 4, "typical": 17},
        "tick": {"state": "armed", "seconds": 480},
        "last": "23:47",
        "plugins": [
            ("oss", {"state": "current", "installed": "0.10.0", "latest": "0.10.0"}),
            ("supertool", {"state": "behind", "installed": "0.48.0", "latest": "0.49.0"}),
        ],
    }
    facts.update(overrides)
    return facts


def _leaf_paths(value, path=()):
    """Every position in a nested dict/list/tuple structure holding a leaf value.

    Recurses through everything `_facts()` is built from -- dicts, lists, tuples -- so a
    value nested inside `board` or `plugins` is visited exactly like a top-level one, and a
    structure that grows a new nested field costs this walker nothing (#535).
    """
    if isinstance(value, dict):
        for key, sub in value.items():
            yield from _leaf_paths(sub, path + (key,))
    elif isinstance(value, (list, tuple)):
        for index, sub in enumerate(value):
            yield from _leaf_paths(sub, path + (index,))
    else:
        yield path


def _with_leaf(value, path, replacement):
    """A deep copy of `value` with the leaf at `path` replaced by `replacement`."""
    if not path:
        return replacement
    key, rest = path[0], path[1:]
    if isinstance(value, dict):
        result = dict(value)
        result[key] = _with_leaf(value[key], rest, replacement)
        return result
    if isinstance(value, list):
        result = list(value)
        result[key] = _with_leaf(value[key], rest, replacement)
        return result
    if isinstance(value, tuple):
        result = list(value)
        result[key] = _with_leaf(value[key], rest, replacement)
        return tuple(result)
    raise TypeError("cannot set a leaf inside {!r}".format(value))


def _leaf_value(value, path):
    for key in path:
        value = value[key]
    return value


def test_render_states_the_measured_board():
    line = statusline.render(_facts(), ascii_only=True)
    assert "2pr" in line and "18is" in line


def test_render_never_prints_a_zero_for_an_unknown_board():
    """The must-not-fire half. Paired with the test above, which proves it can print."""
    line = statusline.render(_facts(board={"state": "unknown", "prs": None, "issues": None}),
                             ascii_only=True)
    assert "?pr" in line and "?is" in line
    assert "0pr" not in line and "0is" not in line


def test_render_distinguishes_a_zero_board_from_an_unknown_one():
    zero = statusline.render(_facts(board={"state": "measured", "prs": 0, "issues": 0, "age": 1}),
                             ascii_only=True)
    unknown = statusline.render(_facts(board={"state": "unknown", "prs": None, "issues": None}),
                                ascii_only=True)
    assert zero != unknown
    assert "0pr" in zero


def test_a_plugin_label_is_derived_not_tabled():
    """`claude-` goes, four characters stay -- and a name nobody wrote down still gets one."""
    assert statusline._short_name("claude-jit-context") == "jit"
    assert statusline._short_name("supertool") == "supe"
    assert statusline._short_name("a-plugin-invented-tomorrow") == "a-pl"


def test_render_names_the_version_a_behind_plugin_is_behind():
    line = statusline.render(_facts(), ascii_only=True)
    assert "0.49.0" in line


def test_render_marks_an_unknown_tick_apart_from_no_tick():
    unknown = statusline.render(_facts(tick={"state": "unknown"}), ascii_only=True)
    none = statusline.render(_facts(tick={"state": "none"}), ascii_only=True)
    assert unknown != none
    assert "?" in unknown


def test_render_shows_the_wall_clock_stamp_of_this_render():
    """#504: a frozen clock time stays readable against the reader's own clock,
    which is the whole reason it is a stamp rather than an age.
    """
    line = statusline.render(_facts(last="23:47"), ascii_only=True)
    assert "23:47" in line


def test_render_shows_dash_when_no_render_stamp_is_available():
    """The must-fire control above proves the field can render text; this is the
    third state -- nobody computed one -- and it must not print an empty clock.
    """
    line = statusline.render(_facts(last=None), ascii_only=True)
    assert "last ?" in line


def test_no_field_reports_how_long_since_the_user_last_spoke():
    """#513 removed that field rather than fixing it a second time.

    It counted tool results as the user speaking, then -- once those were excluded --
    could still only see the last message the transcript had recorded, which lags the
    conversation by the length of the turn. `last` already says when the line was
    rendered, which is the same staleness without a second number to be wrong about.
    """
    line = statusline.render(_facts(), ascii_only=True)
    assert "you " not in line
    assert "last " in line  # the field that replaced it is still there


def test_ascii_only_render_survives_a_codepage_that_cannot_encode_the_symbols():
    """cp1252 kills a `print` at the arrow, after the work it reports already happened."""
    line = statusline.render(_facts(), ascii_only=True)
    line.encode("cp1252")


def test_console_sample_is_derived_from_the_guarded_symbol_set():
    """The probe is the guarded set, not a copy of it (#535).

    The previous probe hardcoded four of the seven symbols `_symbols(False)` renders --
    a fixture mirroring the guard exactly, the shape #535 is about. This asserts the
    sample equals the guarded set by construction rather than by a literal string typed
    out beside it, so a symbol added to `_symbols` later is in the sample the day it
    starts rendering, with nothing here to edit.
    """
    assert statusline._console_sample() == "".join(statusline._symbols(False).values())


def test_console_sample_grows_when_symbols_does_without_editing_the_probe():
    """The must-fire control for the probe above.

    Proves the derivation rather than assuming it: inject a symbol nobody wrote into
    any probe and confirm the sample -- and `_ascii_only` itself -- notice, with
    nothing here or in `scripts/statusline.py` touched to make it so.
    """
    original = statusline._symbols

    def with_extra(ascii_only):
        symbols = dict(original(ascii_only))
        symbols["future"] = "⓪"  # a symbol nobody wrote into any probe
        return symbols

    statusline._symbols = with_extra
    try:
        assert "⓪" in statusline._console_sample()

        class _AsciiStream:
            encoding = "ascii"

        assert statusline._ascii_only(_AsciiStream()) is True
    finally:
        statusline._symbols = original


def test_the_unicode_render_is_still_the_default_where_it_encodes():
    line = statusline.render(_facts(), ascii_only=False)
    line.encode("utf-8")


# ------------------------------------------------------------- untrusted manifest text


def test_a_newline_and_escape_in_the_tracked_version_do_not_reach_the_line():
    """`version` comes from this repo's own tracked manifest, written by a contributor.

    A newline would put attacker-chosen text at column 0 of the terminal chrome; an
    ESC would let it rewrite what the terminal has already printed. Neither may reach
    the rendered line.
    """
    hostile = "0.1.0\nFAKE STATUS LINE\x1b[31mX"
    line = statusline.render(_facts(version=hostile), ascii_only=True)
    assert "\n" not in line
    assert "\x1b" not in line


def test_the_must_fire_control_an_ordinary_version_still_renders():
    """Paired with the test above: a renderer that prints nothing also has no newline."""
    line = statusline.render(_facts(version="0.10.0"), ascii_only=True)
    assert "0.10.0" in line


def test_a_newline_and_escape_in_a_remote_latest_do_not_reach_the_line():
    """`latest` is fetched from another repository's manifest, over the network."""
    hostile = "0.1.0\nFAKE STATUS LINE\x1b[31mX"
    facts = _facts(
        plugins=[
            ("oss", {"state": "behind", "installed": "0.10.0", "latest": hostile}),
        ]
    )
    line = statusline.render(facts, ascii_only=True)
    assert "\n" not in line
    assert "\x1b" not in line


def test_the_must_fire_control_an_ordinary_latest_still_renders():
    facts = _facts(
        plugins=[
            ("oss", {"state": "behind", "installed": "0.10.0", "latest": "9.9.9"}),
        ]
    )
    line = statusline.render(facts, ascii_only=True)
    assert "9.9.9" in line
    assert line != statusline.render(_facts(), ascii_only=True)


def test_the_walker_finds_a_field_nobody_enumerated():
    """The must-fire control for the walker itself (#535).

    A fixture that names every path by hand reproduces the class the day a new
    sub-field is added and nobody remembers to add its path too -- exactly what
    happened between the `v0.12.0` and `v0.13.0` audits, when `board` grew a
    `checks` sub-field the old flat, string-only walk below could not have seen
    even if it had looked inside `board` at all. This proves `_leaf_paths` and
    `_with_leaf` need no such list: a synthetic field, invented here and never
    named in either helper, is still discovered and still replaceable.
    """
    synthetic = _facts(board=dict(_facts()["board"], future_subfield="ordinary"))
    paths = list(_leaf_paths(synthetic))
    assert ("board", "future_subfield") in paths
    hostile = _with_leaf(synthetic, ("board", "future_subfield"), "\nHOSTILE")
    assert hostile["board"]["future_subfield"] == "\nHOSTILE"
    assert synthetic["board"]["future_subfield"] == "ordinary"  # original untouched


def test_no_hostile_leaf_anywhere_in_facts_reaches_the_line_unfolded():
    """A property over every leaf `_facts()` carries, nested or not (#535).

    The previous version of this test walked only the top level and `continue`d
    on anything that was not already a string, so `board`, `tick`, `release` and
    `plugins` -- every fact that is itself a dict or a list -- was never hostiled
    at all: the set covered was exactly the set already folded. This walks every
    leaf `_leaf_paths` finds, string-valued or not, and drops the hostile string
    in its place regardless of what was there before -- the crash this test
    exists to catch (`_tick_field`'s `abs()` on a hostile `seconds`) was a *type*
    confusion, a string landing where an int was expected, not only a string
    carrying control characters.

    `branch` is excluded -- not because the fold protects it, but because git
    itself refuses a ref name containing these characters, confirmed by the
    control test right below rather than assumed.
    """
    hostile = "\nFAKE STATUS LINE\x1b[31mX"
    unreachable = {("branch",)}
    base = _facts()
    for path in _leaf_paths(base):
        if path in unreachable:
            continue
        facts = _with_leaf(base, path, hostile)
        line = statusline.render(facts, ascii_only=True)
        assert "\n" not in line, path
        assert "\x1b" not in line, path


def test_the_must_fire_control_for_the_leaf_property_above():
    """Paired with the property test above.

    Substituting a leaf back to its own original value reconstructs `_facts()`
    exactly, so a walker that silently dropped structure -- and would trivially
    "pass" every hostile case above by rendering nothing distinctive -- is itself
    caught. And the baseline still renders the values a reader actually needs.
    """
    base = _facts()
    for path in _leaf_paths(base):
        assert _with_leaf(base, path, _leaf_value(base, path)) == base, path
    line = statusline.render(base, ascii_only=True)
    assert "2pr" in line and "Opus" in line and "23:47" in line


def test_a_branch_name_with_hostile_control_characters_is_refused_by_git():
    """`branch` is excluded from the property above because git makes the hostile
    value unreachable at the source, not because `render` folds it. Confirmed
    with the same check statusline's own audit used (#493), not assumed.
    """
    import subprocess

    result = subprocess.run(
        ["git", "check-ref-format", "--branch", "main\nFAKE\x1b[31mX"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert result.returncode != 0


def test_a_newline_and_escape_in_a_dependency_name_do_not_reach_the_line():
    """A dependency name is declared inside another plugin's own tracked manifest --
    `plugin_facts`'s `record["dependencies"]` -- the same class of foreign text as
    `version`/`installed`/`latest`, reached through `_short_name` rather than
    `_short_version`. The hostile bytes sit in the first four characters -- after the
    `claude-` strip -- so a fold applied only after the four-character truncation
    would still miss them.
    """
    # Not `current`: since #512 the block collapses to a count and names only what is not
    # current, so a hostile name on a current plugin never reaches the line and this test
    # would pass without folding anything.
    hostile = "\nFAKE STATUS LINE\x1b[31mX"
    facts = _facts(
        plugins=[(hostile, {"state": "behind", "installed": "1.0.0", "latest": "2.0.0"})]
    )
    line = statusline.render(facts, ascii_only=True)
    assert "\n" not in line
    assert "\x1b" not in line


def test_the_must_fire_control_an_ordinary_dependency_name_still_renders():
    facts = _facts(
        plugins=[
            ("claude-jit-context", {"state": "behind", "installed": "1.0.0", "latest": "2.0.0"})
        ]
    )
    line = statusline.render(facts, ascii_only=True)
    assert "jit>2.0.0" in line


def test_latest_is_asked_of_the_manifest_the_installer_would_read(monkeypatch):
    """One question, one source -- the same one `doctor.published_versions` uses.

    `releases/latest` is a different question: `claude-jit-context` carries tag `v0.5.0`
    and a latest release object of `v0.4.0`, so reading releases reported a current
    install as `ahead`. A status line and a diagnostic disagreeing in front of the same
    person is worse than either being wrong alone.
    """
    seen = []

    def fake_run(command, timeout=5):
        seen.append(list(command))
        return None

    monkeypatch.setattr(statusline, "_run", fake_run)
    statusline._latest_release("owner/name")
    assert seen, "nothing was asked -- this test would pass against a stub that never calls"
    asked = " ".join(seen[0])
    assert "contents/.claude-plugin/plugin.json" in asked, asked
    assert "releases/latest" not in asked, asked


# ------------------------------------------------------- scaffold: the owned file


def _config():
    return {
        "repo": "owner/name",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "clone": "/tmp/clone",
        "worktree_root": "/tmp/wt",
        "state_file": ".max/state.json",
        "test_command": "pytest",
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "version_sites": ["README.md"],
    }


def test_the_statusline_is_an_owned_file():
    assert ".oss/statusline.py" in scaffold.OWNED


def test_the_owned_statusline_carries_the_overwrite_note():
    body = scaffold.render_owned(".oss/statusline.py", _config(), REPO_ROOT)
    assert "OVERWRITTEN" in body
    assert "def render(" in body


def test_the_owned_statusline_is_not_gated_on_the_changelog_gate(tmp_path, monkeypatch):
    """A repo running its own changelog gate still gets a status line.

    The gate is about the changelog trio. Applying it to every member of OWNED declines
    a file for a reason that has nothing to do with it -- and a declined file and a file
    this plugin does not ship render the same on disk.
    """
    monkeypatch.setattr(scaffold, "_detect_changelog_gate",
                        lambda root, config: ("found", "release.yml"))
    entries = {e["path"]: e for e in scaffold.plan(str(tmp_path), _config())}
    assert entries[".oss/statusline.py"]["action"] == "replace"
    assert entries[".oss/assemble_changelog.py"]["action"] == "decline"


# --------------------------------------------------- scaffold: the settings default


def test_settings_are_created_when_the_file_is_absent(tmp_path):
    entry = scaffold.settings_plan(str(tmp_path))
    assert entry["action"] == "create"


def test_an_existing_statusline_key_is_never_overwritten(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"statusLine": {"type": "command", "command": "mine.sh"}}),
                        encoding="utf-8")
    entry = scaffold.settings_plan(str(tmp_path))
    assert entry["action"] == "present"
    scaffold.apply_settings(str(tmp_path))
    assert json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"] == "mine.sh"


def test_a_settings_file_without_the_key_is_extended_and_keeps_its_other_keys(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"enabledPlugins": {"oss@dpt-plugins": True}}),
                        encoding="utf-8")
    assert scaffold.settings_plan(str(tmp_path))["action"] == "extend"
    scaffold.apply_settings(str(tmp_path))
    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["enabledPlugins"] == {"oss@dpt-plugins": True}
    assert "statusline.py" in written["statusLine"]["command"]


def test_unparseable_settings_are_declined_rather_than_replaced(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")
    entry = scaffold.settings_plan(str(tmp_path))
    assert entry["action"] == "decline"
    scaffold.apply_settings(str(tmp_path))
    assert settings.read_text(encoding="utf-8") == "{not json"


# --------------------------------------- render() reads vs _facts()'s coverage (#547)


def _string_from_slice(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _render_reads_from_tree(tree):
    """Every top-level key `facts["X"]` or `facts.get("X")` names, anywhere in the
    given AST -- used both against the real `render()` and against a synthetic
    snippet in the must-fire control below.
    """
    keys = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "facts"
        ):
            key = _string_from_slice(node.slice)
            if key:
                keys.add(key)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "facts"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


def _render_top_level_reads():
    """Parsed straight out of `statusline.render`'s own source (#547 instance 2),
    not kept as a second list beside `_facts()` -- a key `render()` starts reading
    and this fixture omits is then a failure here rather than a silent absence,
    which is the coverage gap #535's own fix left in place: `_facts()` derived
    `_leaf_paths` from ITSELF, not from what `render()` actually reads.
    """
    source = inspect.getsource(statusline.render)
    return _render_reads_from_tree(ast.parse(source))


def test_the_reader_itself_catches_a_read_it_has_never_seen_before():
    """The must-fire control for `_render_reads_from_tree`, decoupled from the
    real `render()`: a synthetic function reading a brand-new key must still be
    picked up, so the derivation is not merely reporting what happens to be in
    `render()` today by coincidence of how this parser was written.
    """
    synthetic = (
        "def render(facts, ascii_only=False, color=False):\n"
        "    x = facts.get(\"totally_new_key_nobody_wrote_down\")\n"
        "    y = facts[\"another_brand_new_key\"]\n"
    )
    keys = _render_reads_from_tree(ast.parse(synthetic))
    assert "totally_new_key_nobody_wrote_down" in keys
    assert "another_brand_new_key" in keys


def test_facts_fixture_carries_every_top_level_key_render_reads():
    """The real assertion (#547 instance 2): every key `render()` reads must be a
    key `_facts()` carries. Before this fix, `default_branch` and `release` were
    read by `render()` (`:827`, `:838`) and absent from `_facts()` -- two whole
    top-level keys `_leaf_paths` could never walk into, silently narrowing the
    hostile-leaf property test above to 23 of the 26 reachable leaves.
    """
    reads = _render_top_level_reads()
    missing = reads - set(_facts())
    assert not missing, sorted(missing)


def test_default_branch_and_release_are_reachable_by_the_leaf_walker():
    """Exercised, not just counted (per the issue): with both keys present, the
    walker must actually reach into them, and the hostile-leaf property must
    still hold for both -- `default_branch` is folded (`:827`) and `release`'s
    leaves are `isinstance(..., int)`-coerced (`_release_field`), so neither
    should crash or leak control characters into the rendered line.
    """
    base = _facts()
    assert ("default_branch",) in list(_leaf_paths(base))
    assert ("release", "since") in list(_leaf_paths(base))
    assert ("release", "typical") in list(_leaf_paths(base))

    hostile = "\nFAKE STATUS LINE\x1b[31mX"
    for path in (("default_branch",), ("release", "since"), ("release", "typical")):
        facts = _with_leaf(base, path, hostile)
        line = statusline.render(facts, ascii_only=True)
        assert "\n" not in line, path
        assert "\x1b" not in line, path
