"""#1311: `/oss:doctor` must name the exact cause of every statusline `?`
(the watch channel's five states, the default-branch marker's collapsed
`unknown`), each with an executable remedy -- never a permanent,
never-clearable WARN unless the cause genuinely cannot be cleared by any
manual op or scaffold run.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_statusline_unknowns as mod  # noqa: E402
import statusline  # noqa: E402


def setup_function(_):
    doctor.FINDINGS.clear()


NOW = 1_000_000.0


# --------------------------------------------------------------------------
# channel_cause: the five real states plus the off-switch, each distinguishable.
# --------------------------------------------------------------------------


def test_channel_off_switch_is_not_applicable():
    result = mod.channel_cause({"watch_channel": False}, {}, NOW)
    assert result == {"applicable": False}


def test_channel_not_asked_when_no_cache_entry():
    result = mod.channel_cause({}, {}, NOW)
    assert result["applicable"] is True
    assert result["reason"] == "not-asked"


def test_channel_stale_when_reading_older_than_interval():
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": NOW - statusline.CHANNEL_REFRESH_AFTER - 10,
    }
    result = mod.channel_cause({}, cache, NOW)
    assert result["reason"] == "stale"


def test_channel_not_attributable_when_neither_route_settles_it():
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "not-attributable"},
        "channel_fetched_at": NOW - 5,
    }
    result = mod.channel_cause({}, cache, NOW)
    assert result["reason"] == "not-attributable"


def test_channel_declaration_unreadable_distinct_from_not_attributable():
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "declaration-unreadable"},
        "channel_fetched_at": NOW - 5,
    }
    result = mod.channel_cause({}, cache, NOW)
    assert result["reason"] == "declaration-unreadable"
    assert result["reason"] != "not-attributable"


def test_channel_unrecognized_raw_state():
    cache = {
        "channel": {"raw_state": "some-future-state", "attribution": "derivation"},
        "channel_fetched_at": NOW - 5,
    }
    result = mod.channel_cause({}, cache, NOW)
    assert result["reason"] == "unrecognized"


def test_channel_real_reading_has_no_reason():
    """Positive control: a genuine, fresh, attributed reading is not `?` at
    all, and must not be explained as though it were."""
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": NOW - 5,
    }
    result = mod.channel_cause({}, cache, NOW)
    assert result["state"] == "forwarding"
    assert result["reason"] is None


# --------------------------------------------------------------------------
# default_branch_cause: the collapsed `unknown`, split into its own causes.
# --------------------------------------------------------------------------


def test_default_branch_not_applicable_when_unconfigured():
    result = mod.default_branch_cause({}, {}, NOW)
    assert result == {"applicable": False}


def test_default_branch_not_asked_when_never_cached():
    result = mod.default_branch_cause({"default_branch": "main"}, {}, NOW)
    assert result["applicable"] is True
    assert result["reason"] == "not-asked"


def test_default_branch_stale_outranks_a_present_raw_value():
    cache = {
        "fetched_at": NOW - statusline.REFRESH_AFTER - 5,
        "default_branch_state": "green",
    }
    result = mod.default_branch_cause({"default_branch": "main"}, cache, NOW)
    assert result["reason"] == "stale"


def test_default_branch_no_answer_when_gh_call_failed():
    cache = {"fetched_at": NOW - 5, "default_branch_state": None}
    result = mod.default_branch_cause({"default_branch": "main"}, cache, NOW)
    assert result["reason"] == "no-answer"


def test_default_branch_unrecognized_when_cache_corrupted():
    cache = {"fetched_at": NOW - 5, "default_branch_state": "purple"}
    result = mod.default_branch_cause({"default_branch": "main"}, cache, NOW)
    assert result["reason"] == "unrecognized"
    assert result["value"] == "purple"


def test_default_branch_real_reading_has_no_reason():
    """Positive control: a fresh, real reading is not `unknown`."""
    cache = {"fetched_at": NOW - 5, "default_branch_state": "green"}
    result = mod.default_branch_cause({"default_branch": "main"}, cache, NOW)
    assert result["reason"] is None
    assert result["state"] == "green"


# --------------------------------------------------------------------------
# check_statusline_unknowns: doctor states, distinguishable messages, and a
# runnable remedy in every WARN.
# --------------------------------------------------------------------------


def test_config_none_is_unmeasured_not_silence():
    mod.check_statusline_unknowns("/tmp/nowhere", None, now=NOW)
    assert doctor.FINDINGS
    assert all(state != "OK" for state, _ in doctor.FINDINGS)


def test_off_and_unconfigured_are_both_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(statusline, "read_cache", lambda path: {})
    mod.check_statusline_unknowns(
        str(tmp_path), {"watch_channel": False, "repo": "a/b"}, now=NOW
    )
    assert doctor.FINDINGS
    assert all(state == "OK" for state, _ in doctor.FINDINGS)


def test_every_channel_warn_names_a_runnable_command(monkeypatch, tmp_path):
    cache = {
        "channel": {"raw_state": None, "attribution": "not-attributable"},
        "channel_fetched_at": None,
    }
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    mod.check_statusline_unknowns(str(tmp_path), {"repo": "a/b"}, now=NOW)
    channel_findings = [
        (state, msg)
        for state, msg in doctor.FINDINGS
        if msg.startswith("statusline channel")
    ]
    assert channel_findings
    state, msg = channel_findings[0]
    # not-asked is checked before attribution (statusline.py's own docstring
    # for `channel_status` -- an unasked question must never read as "not
    # this repo's fleet").
    assert "not-asked" not in msg  # reason word isn't literally required...
    assert "channel:health" in msg
    assert "statusline.py" in msg and "--refresh --root" in msg


def test_channel_not_attributable_gets_notice_not_permanent_warn(monkeypatch, tmp_path):
    """#764's own contract: a cause that CAN be a genuine, permanent,
    correct answer must not render as an unclearable WARN forever."""
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "not-attributable"},
        "channel_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    mod.check_statusline_unknowns(str(tmp_path), {"repo": "a/b"}, now=NOW)
    channel_findings = [
        (state, msg)
        for state, msg in doctor.FINDINGS
        if msg.startswith("statusline channel")
    ]
    state, msg = channel_findings[0]
    assert state == "NOTICE", msg
    assert "declare it explicitly" in msg


def test_all_five_channel_reasons_are_distinguishable(monkeypatch, tmp_path):
    reasons_and_caches = {
        "not-asked": {"channel": {}, "channel_fetched_at": None},
        "stale": {
            "channel": {"raw_state": "forwarding", "attribution": "derivation"},
            "channel_fetched_at": NOW - statusline.CHANNEL_REFRESH_AFTER - 10,
        },
        "not-attributable": {
            "channel": {"raw_state": "forwarding", "attribution": "not-attributable"},
            "channel_fetched_at": NOW - 5,
        },
        "declaration-unreadable": {
            "channel": {
                "raw_state": "forwarding",
                "attribution": "declaration-unreadable",
            },
            "channel_fetched_at": NOW - 5,
        },
        "unrecognized": {
            "channel": {"raw_state": "future-state", "attribution": "derivation"},
            "channel_fetched_at": NOW - 5,
        },
    }
    messages = {}
    for reason, cache in reasons_and_caches.items():
        doctor.FINDINGS.clear()
        monkeypatch.setattr(statusline, "read_cache", lambda path, c=cache: c)
        mod.check_statusline_unknowns(str(tmp_path), {"repo": "a/b"}, now=NOW)
        channel_findings = [
            msg
            for state, msg in doctor.FINDINGS
            if msg.startswith("statusline channel")
        ]
        messages[reason] = channel_findings[0]
    assert len(set(messages.values())) == len(messages), messages


def test_all_default_branch_reasons_are_distinguishable(monkeypatch, tmp_path):
    reasons_and_caches = {
        "not-asked": {},
        "stale": {
            "fetched_at": NOW - statusline.REFRESH_AFTER - 5,
            "default_branch_state": "green",
        },
        "no-answer": {"fetched_at": NOW - 5, "default_branch_state": None},
        "unrecognized": {"fetched_at": NOW - 5, "default_branch_state": "purple"},
    }
    messages = {}
    for reason, cache in reasons_and_caches.items():
        doctor.FINDINGS.clear()
        monkeypatch.setattr(statusline, "read_cache", lambda path, c=cache: c)
        mod.check_statusline_unknowns(
            str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
        )
        branch_findings = [
            msg
            for state, msg in doctor.FINDINGS
            if msg.startswith("statusline default-branch")
        ]
        messages[reason] = branch_findings[0]
        assert (
            "statusline.py" in branch_findings[0]
            and "--refresh --root" in branch_findings[0]
        )
    assert len(set(messages.values())) == len(messages), messages


def test_real_readings_are_ok_and_never_confused_with_a_finding(monkeypatch, tmp_path):
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": NOW - 5,
        "fetched_at": NOW - 5,
        "default_branch_state": "green",
    }
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )
    assert doctor.FINDINGS
    assert all(state == "OK" for state, _ in doctor.FINDINGS)
