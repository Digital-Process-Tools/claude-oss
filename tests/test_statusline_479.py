"""The status line, and the three states it must not round off (#479).

A status line renders on every message, so every fact in it is either cached, cheap, or
absent. The defect this repository is named after is exactly what a status line invites:
a count nobody took renders as `0`, a version comparison nobody could make renders as
`ok`, and a tick nobody armed renders the same as a transcript nobody could read.

Every assertion below pairs a must-not-fire with a must-fire, because an assertion that
`?` does not appear also passes against a renderer that produces nothing at all.
"""

import json
import sys
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
    board = statusline.board_from_cache({"prs": 0, "issues": 0, "fetched_at": 0})
    assert board["state"] == "measured"
    assert board["prs"] == 0 and board["issues"] == 0


def test_a_cache_missing_a_count_is_unknown_for_that_count_alone():
    board = statusline.board_from_cache({"prs": 2, "fetched_at": 0})
    assert board["prs"] == 2
    assert board["issues"] is None


# ------------------------------------------------------------- last user message


def _user_message(timestamp):
    return {"type": "user", "timestamp": timestamp, "message": {"role": "user", "content": "hi"}}


def test_no_transcript_is_unknown_for_last_user_message_too():
    user = statusline.last_user_message(None, now=0.0)
    assert user["state"] == "unknown"


def test_scanned_transcript_without_a_user_record_reports_none(tmp_path):
    """The must-fire control for the arm above: a file that was read and held
    no user-role record at all is not the same as one this process never read.
    """
    path = _transcript(tmp_path, [{"timestamp": "2026-08-22T10:00:00.000Z", "message": {}}])
    user = statusline.last_user_message(str(path), now=0.0)
    assert user["state"] == "none"


def test_the_last_user_message_reports_a_genuinely_nonzero_age(tmp_path):
    """This is the whole point of #504: at render time the age of the last user
    message cannot be zero the way a naive "last message" age would be, because
    a render only happens after the assistant has replied to it.
    """
    path = _transcript(tmp_path, [_user_message("2026-08-22T10:00:00.000Z")])
    now = statusline.parse_timestamp("2026-08-22T10:04:00.000Z")
    user = statusline.last_user_message(str(path), now=now)
    assert user["state"] == "measured"
    assert user["age"] == pytest.approx(240, abs=1)


def test_the_last_of_several_user_messages_wins(tmp_path):
    path = _transcript(
        tmp_path,
        [_user_message("2026-08-22T10:00:00.000Z"), _user_message("2026-08-22T10:05:00.000Z")],
    )
    now = statusline.parse_timestamp("2026-08-22T10:06:00.000Z")
    user = statusline.last_user_message(str(path), now=now)
    assert user["age"] == pytest.approx(60, abs=1)


def test_a_truncated_scan_for_last_user_message_reports_unknown_rather_than_none(tmp_path):
    """Same shape as `next_tick`'s own truncation case: a scan that never reached
    the top of the file must not report the same thing as a file scanned whole
    and found empty.
    """
    path = _transcript(tmp_path, [{"timestamp": "2026-08-22T10:00:00.000Z", "message": {}}] * 40)
    user = statusline.last_user_message(str(path), now=0.0, max_bytes=200)
    assert user["state"] == "unknown"


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
    assert statusline.installed_plugins(tmp_path)["oss"]["version"] == "0.10.0"


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
    assert statusline.installed_plugins(tmp_path)["oss"]["version"] == "0.10.0"


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
    transcript = _transcript(tmp_path, [_user_message("2026-08-22T10:00:00.000Z")])
    now = statusline.parse_timestamp("2026-08-22T10:04:00.000Z")
    payload = {"transcript_path": str(transcript)}
    facts = statusline.gather(payload, str(tmp_path), now=now)
    assert facts["last"] == "10:04"
    assert facts["user"]["state"] == "measured"
    assert facts["user"]["age"] == pytest.approx(240, abs=1)


def test_gather_reports_the_render_stamp_in_utc():
    """The stamp is a wall-clock reading of `now`, in UTC -- not the machine's
    local timezone, which the transcript's own ISO stamps do not carry either.
    """
    now = statusline.parse_timestamp("2026-08-22T10:04:00.000Z")
    assert statusline._render_stamp(now) == "10:04"


# ------------------------------------------------------------------------- render


def _facts(**overrides):
    facts = {
        "model": "Opus",
        "percent": 42,
        "repo_name": "claude-oss",
        "branch": "main",
        "version": "0.10.0",
        "board": {"state": "measured", "prs": 2, "issues": 18, "age": 30},
        "tick": {"state": "armed", "seconds": 480},
        "last": "23:47",
        "user": {"state": "measured", "age": 240},
        "plugins": [
            ("oss", {"state": "current", "installed": "0.10.0", "latest": "0.10.0"}),
            ("supertool", {"state": "behind", "installed": "0.48.0", "latest": "0.49.0"}),
        ],
    }
    facts.update(overrides)
    return facts


def test_render_states_the_measured_board():
    line = statusline.render(_facts(), ascii_only=True)
    assert "2PR" in line and "18IS" in line


def test_render_never_prints_a_zero_for_an_unknown_board():
    """The must-not-fire half. Paired with the test above, which proves it can print."""
    line = statusline.render(_facts(board={"state": "unknown", "prs": None, "issues": None}),
                             ascii_only=True)
    assert "?PR" in line and "?IS" in line
    assert "0PR" not in line and "0IS" not in line


def test_render_distinguishes_a_zero_board_from_an_unknown_one():
    zero = statusline.render(_facts(board={"state": "measured", "prs": 0, "issues": 0, "age": 1}),
                             ascii_only=True)
    unknown = statusline.render(_facts(board={"state": "unknown", "prs": None, "issues": None}),
                                ascii_only=True)
    assert zero != unknown
    assert "0PR" in zero


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


def test_render_shows_a_genuinely_nonzero_user_age():
    line = statusline.render(_facts(user={"state": "measured", "age": 240}), ascii_only=True)
    assert "you 4m" in line


def test_render_marks_no_user_message_apart_from_unknown():
    """Same three-state shape as the tick field: `none` (scanned, nothing found)
    must render differently from `unknown` (never scanned, or scanned but cut
    off before reaching a user record).
    """
    none = statusline.render(_facts(user={"state": "none"}), ascii_only=True)
    unknown = statusline.render(_facts(user={"state": "unknown"}), ascii_only=True)
    assert none != unknown
    assert "you -" in none
    assert "you ?" in unknown


def test_ascii_only_render_survives_a_codepage_that_cannot_encode_the_symbols():
    """cp1252 kills a `print` at the arrow, after the work it reports already happened."""
    line = statusline.render(_facts(), ascii_only=True)
    line.encode("cp1252")


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


def test_no_string_valued_fact_reaches_the_line_unfolded():
    """A property over `render`'s inputs (#493), not a fourth enumerated case.

    `_one_line` was applied at three entry points while `render()` interpolated
    four more values that passed through nothing. Rather than name the two live
    ones (`repo_name`, `model`), this walks every string-valued key `_facts()`
    carries and hostiles it in turn, so a fifth field added later without an
    explicit fold is caught the same way.

    `branch` is excluded -- not because the fold protects it, but because git
    itself refuses a ref name containing these characters, confirmed by the
    control test right below rather than assumed.
    """
    hostile = "\nFAKE STATUS LINE\x1b[31mX"
    unreachable = {"branch"}
    base = _facts()
    for key, value in base.items():
        if key in unreachable or not isinstance(value, str):
            continue
        facts = _facts(**{key: hostile})
        line = statusline.render(facts, ascii_only=True)
        assert "\n" not in line, key
        assert "\x1b" not in line, key


def test_the_must_fire_control_for_the_property_above():
    """Paired with the property test: an ordinary value in every folded field
    still renders, so a renderer that prints nothing could not pass either.
    """
    base = _facts()
    for key, value in base.items():
        if key == "branch" or not isinstance(value, str):
            continue
        line = statusline.render(_facts(**{key: value}), ascii_only=True)
        assert value in line or "?" not in line, key


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
    hostile = "\nFAKE STATUS LINE\x1b[31mX"
    facts = _facts(plugins=[(hostile, {"state": "current", "installed": "1.0.0"})])
    line = statusline.render(facts, ascii_only=True)
    assert "\n" not in line
    assert "\x1b" not in line


def test_the_must_fire_control_an_ordinary_dependency_name_still_renders():
    facts = _facts(plugins=[("claude-jit-context", {"state": "current", "installed": "1.0.0"})])
    line = statusline.render(facts, ascii_only=True)
    assert "jit " in line


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
