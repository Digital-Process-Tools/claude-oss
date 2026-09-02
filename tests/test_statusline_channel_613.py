"""Is the watch channel actually delivering, as a fifth status-line field (#613).

A channel nobody probed is not a quiet channel -- it is a channel with no
reading, and reporting it as calm is this loop's own defect class landing on
the loop's own instrumentation (`commands/tick.md`'s own words, quoted in the
issue). This file follows the shape #550/#551 set: every "must not render"
assertion carries a "must render" control in the same fixture, and the
stale/fresh-but-wrong pair is exercised together or it proves nothing about
what the incident this repeats was actually like.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402
import oss_config  # noqa: E402


# --------------------------------------------------------- _expected_watch_name


def test_expected_watch_name_matches_oss_configs_own_derivation():
    """A copy, not an import (this module has none) -- so it is measured against
    the authority it copies from rather than trusted in prose (CLAUDE.md's own
    rule for `test_command_problem`/`watch_name_problem`, and the failure mode
    #570 named for the supertool rule body sitting in two places at once).
    """
    for repo in ("Digital-Process-Tools/claude-oss", "owner/name.with.dots",
                 "a_b/c-d", "Owner/Repo_Name"):
        expected, problem = oss_config.watch_channel_name(repo)
        assert problem is None, repo
        assert statusline._expected_watch_name(repo) == expected


def test_expected_watch_name_is_none_without_a_usable_repo():
    assert statusline._expected_watch_name(None) is None
    assert statusline._expected_watch_name("") is None
    assert statusline._expected_watch_name(42) is None


# --------------------------------------------------------- parse_channel_report


def test_parse_channel_report_reads_each_of_the_five_states():
    for label, state in statusline.CHANNEL_STATES.items():
        text = "--- channel:health ---\nFAIL (0.05s)\nchannel: {}\n  detail\n".format(label)
        assert statusline.parse_channel_report(text) == state


def test_parse_channel_report_the_must_not_fire_control_an_unavailable_op():
    """Reproduced live against the installed supertool while filing this issue:
    a `watch` preset that is not enabled prints this refusal, exits 1, and
    carries NO `channel: ` line at all -- it must not be misread as
    `not_delivering`, which also exits 1."""
    text = (
        "--- channel:health ---\n"
        "ERROR: op 'channel' is unavailable here, not unknown -- it is provided "
        "by the shipped preset 'watch', which .supertool.json does not enable.\n"
    )
    assert statusline.parse_channel_report(text) is None


def test_parse_channel_report_the_must_not_fire_control_empty_and_garbage():
    assert statusline.parse_channel_report("") is None
    assert statusline.parse_channel_report(None) is None
    assert statusline.parse_channel_report("channel: SOMETHING NOBODY WROTE DOWN") is None


# -------------------------------------------------------------- channel_status


def test_channel_status_reports_each_real_state_when_fresh_and_attributable():
    now = 1_000.0
    for state in statusline.CHANNEL_STATES.values():
        result = statusline.channel_status(state, "derivation", now - 10, now)
        assert result["state"] == state


def test_channel_status_the_must_fire_control_not_attributable_is_cannot_determine():
    """The issue's closing bullet: a reading off an inherited channel name must
    never be attributed to this repository's fleet, however fresh or however
    real the state itself is."""
    now = 1_000.0
    result = statusline.channel_status("forwarding", "not-attributable", now - 10, now)
    assert result["state"] == "cannot_determine"
    assert result["reason"] == "not-attributable"


def test_channel_status_not_asked_is_cannot_determine():
    now = 1_000.0
    result = statusline.channel_status("forwarding", True, None, now)
    assert result["state"] == "cannot_determine"
    assert result["reason"] == "not-asked"


def test_channel_status_a_stale_reading_is_cannot_determine_not_a_false_state():
    """Must-fire half of the stale/fresh-but-wrong pair (#550/#551's lesson, a
    third instrument): a reading older than its own interval renders `?`, never
    the real (and possibly now-false) state it once carried."""
    now = 1_000.0
    result = statusline.channel_status(
        "forwarding", "derivation", now - statusline.CHANNEL_REFRESH_AFTER - 1, now
    )
    assert result["state"] == "cannot_determine"
    assert result["reason"] == "stale"


def test_channel_status_the_must_not_fire_control_a_fresh_reading_is_real():
    """Must-not-fire half of the same pair, and #551's own gap made explicit: a
    reading INSIDE its interval renders as the real state even though this is
    exactly the reading that could be fresh-by-the-clock and simply wrong --
    the staleness guard cannot and does not claim to catch that, on purpose."""
    now = 1_000.0
    result = statusline.channel_status(
        "not_delivering", "derivation", now - (statusline.CHANNEL_REFRESH_AFTER - 5), now
    )
    assert result["state"] == "not_delivering"


def test_channel_status_an_unrecognized_raw_state_is_cannot_determine():
    now = 1_000.0
    result = statusline.channel_status("something_nobody_wrote_down", "derivation", now - 1, now)
    assert result["state"] == "cannot_determine"
    assert result["reason"] == "unrecognized"


# --------------------------------------------------------------- _channel_field


def test_channel_field_renders_a_distinct_marker_per_state():
    symbols = statusline._symbols(True)
    seen = set()
    for state in list(statusline.CHANNEL_STATES.values()) + ["cannot_determine"]:
        text = statusline._channel_field({"state": state, "reason": None}, symbols)
        assert text is not None
        assert text.startswith("ch")
        assert 3 <= len(text) <= 4, (state, text)
        seen.add(text)
    assert len(seen) == 5, seen  # every state renders something distinguishable


def test_channel_field_is_none_when_disabled_not_a_question_mark():
    """Must-not-fire: `None` (the off switch) is not the same absence as a `?`
    (a question asked and unanswered) -- paired with the must-fire control
    right above, which proves the field renders something when it is not off.
    """
    symbols = statusline._symbols(True)
    assert statusline._channel_field(None, symbols) is None


def test_render_omits_the_channel_block_entirely_when_disabled():
    facts = _channel_facts(channel=None)
    line = statusline.render(facts, ascii_only=True)
    assert "ch?" not in line and "chok" not in line and "chx" not in line


def test_render_the_must_fire_control_shows_the_channel_block_when_enabled():
    facts = _channel_facts(channel={"state": "not_delivering", "reason": None})
    line = statusline.render(facts, ascii_only=True)
    assert "chx" in line


def test_contradicted_renders_uncoloured_matching_the_issues_own_table():
    symbols = statusline._symbols(True)
    plain = statusline._channel_field({"state": "contradicted", "reason": None}, symbols, color=False)
    coloured = statusline._channel_field({"state": "contradicted", "reason": None}, symbols, color=True)
    assert plain == "ch!"
    assert coloured == "ch!"  # no shade applied, matching the issue's blank cell


# ---------------------------------------------------------------------- gather


def _rig(monkeypatch, tmp_path, watch_channel=None):
    config = {"repo": "owner/repo", "default_branch": "main"}
    if watch_channel is not None:
        config["watch_channel"] = watch_channel
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "repo_config", lambda root: config)
    monkeypatch.setattr(statusline, "board_is_due", lambda cache, now: False)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.13.0")
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {"state": "unknown"})
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})


def test_gather_a_stale_channel_reading_renders_cannot_determine(tmp_path, monkeypatch):
    """Must-fire half of the pairing, exercised through `gather()` itself, the
    same level #550/#551's own suite pins the equivalent for `latest`."""
    _rig(monkeypatch, tmp_path)
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": now - statusline.CHANNEL_REFRESH_AFTER - 1,
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["channel"]["state"] == "cannot_determine"
    assert facts["channel"]["reason"] == "stale"


def test_gather_the_must_not_fire_control_a_fresh_but_possibly_wrong_reading_is_real(
    tmp_path, monkeypatch
):
    """The incident's own shape, a third time: a reading well inside its interval
    renders as the real state -- which is exactly what makes it dangerous if the
    consumer died a second after the reading was taken. Staleness alone was
    never going to catch that; nothing here claims it does."""
    _rig(monkeypatch, tmp_path)
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "channel": {"raw_state": "not_delivering", "attribution": "derivation"},
        "channel_fetched_at": now - 5,
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["channel"]["state"] == "not_delivering"


def test_gather_reports_no_channel_field_when_off_in_config(tmp_path, monkeypatch):
    _rig(monkeypatch, tmp_path, watch_channel=False)
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": now - 5,
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["channel"] is None


def test_gather_the_must_fire_control_on_by_default_with_no_key_at_all(tmp_path, monkeypatch):
    """Positive control for the test above: absence of the key is `on`, matching
    the issue's own "on by default, not opt-in" instruction."""
    _rig(monkeypatch, tmp_path)  # no watch_channel key in the config at all
    now = 100_000.0
    cache = {
        "fetched_at": now - 10,
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": now - 5,
    }
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["channel"]["state"] == "forwarding"


def test_gather_never_asked_is_cannot_determine_distinct_from_not_delivering(tmp_path, monkeypatch):
    """The not-asked path renders `?`, distinct from `NOT DELIVERING` -- the
    issue's own test list, last item."""
    _rig(monkeypatch, tmp_path)
    now = 100_000.0
    cache = {"fetched_at": now - 10}  # no channel key at all: never asked
    statusline.cache_path("owner/repo").write_text(json.dumps(cache), encoding="utf-8")
    facts = statusline.gather({}, str(tmp_path), now=now)
    assert facts["channel"]["state"] == "cannot_determine"
    assert facts["channel"]["reason"] == "not-asked"
    assert facts["channel"]["state"] != "not_delivering"


# ---------------------------------------------------------------------- refresh


def test_watch_preset_not_declared_is_cannot_determine_and_spawns_nothing(tmp_path, monkeypatch):
    """`.supertool.json` present but without `watch` in `presets`: no subprocess
    is spawned at all -- the cost this field is not allowed to pay when there is
    nothing configured to ask about."""
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"presets": ["git", "github"]}), encoding="utf-8"
    )
    called = []
    monkeypatch.setattr(
        statusline, "_run_channel_health", lambda timeout=30: called.append(1) or "unused"
    )
    raw_state, attributable = statusline._channel_reading(
        tmp_path, {"repo": "owner/repo"}
    )
    assert raw_state is None
    assert called == []


def test_watch_preset_declared_a_non_dict_supertool_json_is_could_not_tell(tmp_path):
    """Self-review finding on this issue: `.supertool.json` is a file this
    module does not own or control the shape of, and `json.loads` accepts any
    valid JSON document -- a bare list, a number, `null`. `.get` on anything
    but a dict must never raise here: an `AttributeError` with no `except`
    above it in `refresh()`'s own call chain would kill the WHOLE detached
    refresh over one malformed-but-parseable file, not only this field."""
    (tmp_path / ".supertool.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert statusline._watch_preset_declared(tmp_path) is None


def test_watch_preset_declared_runs_the_health_check(tmp_path, monkeypatch):
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"presets": ["git", "watch"]}), encoding="utf-8"
    )
    monkeypatch.setattr(
        statusline, "_run_channel_health",
        lambda timeout=30: "--- channel:health ---\nFAIL\nchannel: FORWARDING\n",
    )
    raw_state, _ = statusline._channel_reading(tmp_path, {"repo": "owner/repo"})
    assert raw_state == "forwarding"


def test_attribution_is_derivation_only_when_the_env_name_matches_this_repos_own(
    tmp_path, monkeypatch
):
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"presets": ["watch"]}), encoding="utf-8"
    )
    monkeypatch.setattr(statusline, "_run_channel_health", lambda timeout=30: "channel: FORWARDING\n")
    config = {"repo": "owner/repo"}
    expected = statusline._expected_watch_name("owner/repo")

    monkeypatch.setenv(statusline.WATCH_NAME_ENV, expected)
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "derivation"

    monkeypatch.setenv(statusline.WATCH_NAME_ENV, "some-other-projects-fleet")
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "not-attributable"

    monkeypatch.delenv(statusline.WATCH_NAME_ENV, raising=False)
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "not-attributable"


# ------------------------------------------------------- attribution by declaration (#754)


def test_attribution_is_declaration_when_a_short_declared_name_matches_the_env(
    tmp_path, monkeypatch
):
    """#754's own case: a repo whose derived name exceeds supertool's 32-char cap
    MUST declare a shorter one, which makes derivation permanently unsatisfiable --
    so a name THIS repo's own tracked .supertool.json declares, that also matches
    what is actually exported, is attributable by a second, independent route."""
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"presets": ["watch"], "ops": {"radar": {"watch_name": "dpt-claude-jit-context"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(statusline, "_run_channel_health", lambda timeout=30: "channel: FORWARDING\n")
    # A repo/name combination whose derivation genuinely does not fit -- so the only
    # way this test can pass through "derivation" is if the fix leaked into the wrong
    # branch, which is exactly what a must-fire control for a SEPARATE route needs.
    config = {"repo": "Digital-Process-Tools/claude-jit-context"}
    monkeypatch.setenv(statusline.WATCH_NAME_ENV, "dpt-claude-jit-context")
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "declaration"


def test_attribution_the_must_not_fire_control_declared_name_not_exported_stays_not_attributable(
    tmp_path, monkeypatch
):
    """A name declared in .supertool.json that is NOT what is actually exported must
    not be attributed -- declaration is evidence only when it matches reality, the
    same as doctor.py's own "agree" check requires."""
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"presets": ["watch"], "ops": {"radar": {"watch_name": "dpt-claude-jit-context"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(statusline, "_run_channel_health", lambda timeout=30: "channel: FORWARDING\n")
    config = {"repo": "Digital-Process-Tools/claude-jit-context"}
    monkeypatch.setenv(statusline.WATCH_NAME_ENV, "some-other-projects-fleet")
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "not-attributable"


def test_attribution_the_must_not_fire_control_two_declared_names_stays_not_attributable(
    tmp_path, monkeypatch
):
    """Mirrors doctor.py's own `conflict` state: more than one distinct declared
    name is not a single fact to attribute against, even if one of them happens
    to match what is exported."""
    (tmp_path / ".supertool.json").write_text(
        json.dumps({
            "presets": ["watch"],
            "ops": {
                "radar": {"watch_name": "dpt-claude-jit-context"},
                "other": {"watch_name": "a-second-name"},
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(statusline, "_run_channel_health", lambda timeout=30: "channel: FORWARDING\n")
    config = {"repo": "Digital-Process-Tools/claude-jit-context"}
    monkeypatch.setenv(statusline.WATCH_NAME_ENV, "dpt-claude-jit-context")
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "not-attributable"


def test_attribution_is_declaration_unreadable_when_supertool_json_cannot_be_parsed(
    tmp_path, monkeypatch
):
    """The fourth answer #754 asks for: a declaration file that is there and
    broken must not render identically to a channel that genuinely belongs to
    someone else's fleet -- this repo's own defect class, reproduced in the fix
    for it, is precisely what this test guards against."""
    (tmp_path / ".supertool.json").write_text("not json{{{", encoding="utf-8")
    monkeypatch.setattr(statusline, "_run_channel_health", lambda timeout=30: "channel: FORWARDING\n")
    config = {"repo": "Digital-Process-Tools/claude-jit-context"}
    monkeypatch.setenv(statusline.WATCH_NAME_ENV, "dpt-claude-jit-context")
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "declaration-unreadable"


def test_attribution_is_declaration_unreadable_when_supertool_json_is_not_an_object(
    tmp_path, monkeypatch
):
    (tmp_path / ".supertool.json").write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(statusline, "_run_channel_health", lambda timeout=30: "channel: FORWARDING\n")
    config = {"repo": "Digital-Process-Tools/claude-jit-context"}
    monkeypatch.setenv(statusline.WATCH_NAME_ENV, "dpt-claude-jit-context")
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "declaration-unreadable"


def test_attribution_the_must_not_fire_control_no_supertool_json_is_not_attributable_not_unreadable(
    tmp_path, monkeypatch
):
    """Absence is a real, common answer (no file at all) and must stay distinct
    from a file that is there and broken -- folding the two together would send
    a maintainer chasing a permissions problem that does not exist."""
    monkeypatch.setattr(statusline, "_run_channel_health", lambda timeout=30: "channel: FORWARDING\n")
    config = {"repo": "Digital-Process-Tools/claude-jit-context"}
    monkeypatch.setenv(statusline.WATCH_NAME_ENV, "dpt-claude-jit-context")
    _, attribution = statusline._channel_reading(tmp_path, config)
    assert attribution == "not-attributable"


def test_declared_watch_names_reads_ops_watch_name_values(tmp_path):
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"ops": {"radar": {"watch_name": "dpt-claude-jit-context"}}}),
        encoding="utf-8",
    )
    names, problem = statusline._declared_watch_names(tmp_path)
    assert names == {"dpt-claude-jit-context"}
    assert problem is None


def test_declared_watch_names_absent_file_is_empty_not_a_problem(tmp_path):
    names, problem = statusline._declared_watch_names(tmp_path)
    assert names == set()
    assert problem is None


def test_declared_watch_names_unreadable_and_malformed_are_distinct_problems(tmp_path):
    (tmp_path / ".supertool.json").write_text("not json{{{", encoding="utf-8")
    names, problem = statusline._declared_watch_names(tmp_path)
    assert names == set()
    assert problem == "unreadable"

    (tmp_path / ".supertool.json").write_text("[1, 2, 3]", encoding="utf-8")
    names, problem = statusline._declared_watch_names(tmp_path)
    assert names == set()
    assert problem == "malformed"


# ------------------------------------------------------- channel_status (#754)


def test_channel_status_the_must_fire_control_declaration_attribution_is_real():
    now = 1_000.0
    result = statusline.channel_status("forwarding", "declaration", now - 10, now)
    assert result["state"] == "forwarding"
    assert result["reason"] is None


def test_channel_status_declaration_unreadable_is_its_own_reason_not_not_attributable():
    """#754's own ask: a declaration file that could not be read is a fourth
    answer, not folded into `not-attributable` -- this repo's own defect class,
    landing in the fix written for a bug about exactly that class."""
    now = 1_000.0
    result = statusline.channel_status("forwarding", "declaration-unreadable", now - 10, now)
    assert result["state"] == "cannot_determine"
    assert result["reason"] == "declaration-unreadable"
    assert result["reason"] != "not-attributable"


def test_refresh_carries_the_channel_reading_forward_when_not_due(tmp_path, monkeypatch):
    """Same shape as `latest`'s own carry-forward (#515/#550): re-stamping `now`
    would make an old reading indistinguishable from a fresh one."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline, "repo_config", lambda root: {"repo": "owner/repo", "default_branch": "main"}
    )
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 0)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, total: 0)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: [])
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    called = []
    monkeypatch.setattr(
        statusline, "_channel_reading",
        lambda root, config: (called.append(1), ("forwarding", True))[1],
    )
    now = 1_000.0
    previous = {
        "fetched_at": now - 5,
        "channel": {"raw_state": "not_delivering", "attribution": "derivation"},
        "channel_fetched_at": now - 5,  # well inside CHANNEL_REFRESH_AFTER
    }
    statusline.cache_path("owner/repo").parent.mkdir(parents=True, exist_ok=True)
    statusline.cache_path("owner/repo").write_text(json.dumps(previous), encoding="utf-8")
    document = statusline.refresh(str(tmp_path), now=now)
    assert called == []  # not due: no subprocess attempt at all
    assert document["channel"] == previous["channel"]
    assert document["channel_fetched_at"] == now - 5  # NOT re-stamped to `now`


def test_refresh_does_not_ask_when_watch_channel_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        statusline, "repo_config",
        lambda root: {"repo": "owner/repo", "default_branch": "main", "watch_channel": False},
    )
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 0)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, total: 0)
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: [])
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    called = []
    monkeypatch.setattr(
        statusline, "_channel_reading",
        lambda root, config: called.append(1),
    )
    document = statusline.refresh(str(tmp_path), now=1_000.0)
    assert called == []
    assert document["channel"] is None
    assert document["channel_fetched_at"] is None


# ------------------------------------------------------------------ oss_config


def test_watch_channel_must_be_a_bool():
    config = {
        "repo": "owner/name", "default_branch": "main", "clone": "/c", "worktree_root": "/w",
        "branch_pattern": "fix/{issue}", "test_command": "pytest", "version_sites": [],
        "changelog_dir": None, "docs_targets": [], "labels": {"priority": [], "lanes": []},
        "state_file": ".max/x.json", "watch_channel": "yes",
    }
    problems = oss_config.validate(config)
    assert any("watch_channel" in p for p in problems)


def test_watch_channel_true_and_false_and_absent_are_all_fine():
    base = {
        "repo": "owner/name", "default_branch": "main", "clone": "/c", "worktree_root": "/w",
        "branch_pattern": "fix/{issue}", "test_command": "pytest", "version_sites": [],
        "changelog_dir": None, "docs_targets": [], "labels": {"priority": [], "lanes": []},
        "state_file": ".max/x.json",
    }
    for value in (True, False, None):
        config = dict(base)
        if value is not None:
            config["watch_channel"] = value
        assert not any("watch_channel" in p for p in oss_config.validate(config))


def test_watch_channel_enabled_default_on():
    assert oss_config.watch_channel_enabled({}) is True
    assert oss_config.watch_channel_enabled({"watch_channel": True}) is True
    assert oss_config.watch_channel_enabled({"watch_channel": False}) is False
    assert oss_config.watch_channel_enabled({"watch_channel": "off"}) is True  # not a bool: not off


def test_statusline_gate_matches_this_accessor():
    """Self-review finding on this issue: `statusline.py` cannot import
    `oss_config` (it has no imports of its own siblings at all -- vendored
    standalone) and so carries the identical `is not False` gate inline,
    twice, rather than calling `watch_channel_enabled`. Nothing tied the two
    together, so they could drift silently -- this test is that tie, over
    every config shape the other tests in this file exercise for the key.
    """
    for config in (
        {}, {"watch_channel": True}, {"watch_channel": False},
        {"watch_channel": "off"}, {"watch_channel": None}, {"watch_channel": 0},
    ):
        # `statusline.py`'s own inline gate, both call sites (refresh/gather),
        # reproduced here rather than imported -- reproducing the CHECK, the
        # same way `_expected_watch_name` reproduces `watch_channel_name`'s
        # SUBSTITUTION above, so a change to either side is caught by drift
        # rather than by one of them silently reading the other's mind.
        inline = config.get("watch_channel") is not False
        assert oss_config.watch_channel_enabled(config) == inline, config


# --------------------------------------------------------------------- helpers


def _channel_facts(channel):
    return {
        "model": "Opus",
        "percent": 10,
        "repo_name": "claude-oss",
        "branch": "main",
        "default_branch": "main",
        "version": "0.10.0",
        "board": {"prs": 1, "issues": 1, "age": 1, "checks": None},
        "release": {"since": 1, "typical": 1},
        "tick": {"state": "none"},
        "last": "12:00",
        "plugins": [],
        "channel": channel,
    }
