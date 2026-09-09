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
    # doctor_verdict/doctor_fetched_at present and fresh so the always-on
    # `dr` field is also OK -- this test is about the two deliberate
    # off-switches (watch_channel, no default_branch), not about `dr`.
    cache = {"doctor_verdict": "ok", "doctor_fetched_at": NOW - 5}
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
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
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
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


def test_channel_not_attributable_stays_warn_with_a_fixable_remedy(
    monkeypatch, tmp_path
):
    """#764's own contract cuts the other way here than a first draft assumed:
    `not-attributable` is not structurally unclearable (declaring `watch_name`
    in `.supertool.json` can fix it), so it must stay WARN, never NOTICE --
    downgrading it would misreport a class of findings that often does have a
    manual-op remedy as permanently non-actionable. The remedy text still
    names the legitimate-permanent possibility, without demoting the state."""
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "not-attributable"},
        "channel_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    mod.check_statusline_unknowns(str(tmp_path), {"repo": "a/b"}, now=NOW)
    channel_findings = [
        (state, msg)
        for state, msg in doctor.FINDINGS
        if msg.startswith("statusline channel")
    ]
    state, msg = channel_findings[0]
    assert state == "WARN", msg
    assert "declare it explicitly" in msg
    assert "MAY already be correct and permanent" in msg


def test_cache_file_unreadable_is_distinct_from_never_asked(monkeypatch, tmp_path):
    """Self-review finding: an existing-but-broken cache file must not read
    identically to a repo nobody has ever probed -- the remedies differ (fix
    or delete the file, versus just run a refresh)."""
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (None, True))
    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )
    assert len(doctor.FINDINGS) == 1
    state, msg = doctor.FINDINGS[0]
    assert state == "WARN"
    assert "could not be read or parsed" in msg
    assert "statusline.py" in msg and "--refresh --root" in msg


def test_statusline_import_failure_is_unmeasured_not_an_unclearable_warn(
    monkeypatch, tmp_path
):
    """Self-review finding: nothing on this repository can clear a broken
    `statusline` import -- it is an install-time fact, not a repo finding --
    so it must route through `doctor.unmeasured`, the same convention the
    top-level `config is None` branch already uses, never a bare WARN with
    no remedy to name."""
    monkeypatch.setattr(mod, "statusline", None)
    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )
    assert doctor.FINDINGS
    assert all(state == "WARN" for state, _ in doctor.FINDINGS)
    joined = " ".join(msg for _, msg in doctor.FINDINGS)
    assert "could not be imported" in joined


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
        monkeypatch.setattr(
            mod, "_read_cache_or_unreadable", lambda path, c=cache: (c, False)
        )
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
        monkeypatch.setattr(
            mod, "_read_cache_or_unreadable", lambda path, c=cache: (c, False)
        )
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
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )
    assert doctor.FINDINGS
    assert all(state == "OK" for state, _ in doctor.FINDINGS)


# --------------------------------------------------------------------------
# #1345 finding 1: `repo` missing must not collapse onto "not-asked".
# --------------------------------------------------------------------------


def test_channel_repo_missing_is_distinct_from_not_asked():
    result = mod.channel_cause({}, {}, NOW, repo_missing=True)
    assert result["applicable"] is True
    assert result["reason"] == "repo-missing"


def test_default_branch_repo_missing_is_distinct_from_not_asked():
    result = mod.default_branch_cause(
        {"default_branch": "main"}, {}, NOW, repo_missing=True
    )
    assert result["applicable"] is True
    assert result["reason"] == "repo-missing"


def test_check_statusline_unknowns_repo_missing_names_the_real_cause(tmp_path):
    """A `.oss.json` with no `repo` key must not tell the reader to run
    `--refresh` -- that remedy cannot resolve without `repo` either."""
    mod.check_statusline_unknowns(str(tmp_path), {"default_branch": "main"}, now=NOW)
    joined = " ".join(msg for _, msg in doctor.FINDINGS)
    assert "repo" in joined
    assert "not-asked" not in joined
    # must not tell the reader to run --refresh as the whole remedy: that
    # command cannot resolve anything until `repo` itself is set.
    assert "Add `repo`" in joined or "add `repo`" in joined.lower()


def test_check_statusline_unknowns_real_repo_is_not_repo_missing(monkeypatch, tmp_path):
    """Positive control: a real `repo` value must not be misread as missing."""
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": NOW - 5,
        "fetched_at": NOW - 5,
        "default_branch_state": "green",
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )
    joined = " ".join(msg for _, msg in doctor.FINDINGS)
    assert "repo-missing" not in joined
    assert "declares no `repo`" not in joined


# --------------------------------------------------------------------------
# #1345 finding 2: the `dr` field's five collapsed causes.
# --------------------------------------------------------------------------


def test_doctor_not_asked_when_never_cached():
    result = mod.doctor_cause({}, NOW)
    assert result["reason"] == "not-asked"


def test_doctor_stale_when_reading_older_than_interval():
    cache = {
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - statusline.DOCTOR_REFRESH_AFTER - 10,
    }
    result = mod.doctor_cause(cache, NOW)
    assert result["reason"] == "stale"


def test_doctor_no_answer_when_verdict_is_none():
    cache = {"doctor_verdict": None, "doctor_fetched_at": NOW - 5}
    result = mod.doctor_cause(cache, NOW)
    assert result["reason"] == "no-answer"


def test_doctor_unrecognized_verdict_shape():
    cache = {"doctor_verdict": "some future shape", "doctor_fetched_at": NOW - 5}
    result = mod.doctor_cause(cache, NOW)
    assert result["reason"] == "unrecognized"
    assert result["value"] == "some future shape"


def test_doctor_real_reading_has_no_reason():
    """Positive control: a genuine, fresh verdict is not `dr?` at all."""
    cache = {
        "doctor_verdict": "usable with gaps -- 2 warning(s)",
        "doctor_fetched_at": NOW - 5,
    }
    result = mod.doctor_cause(cache, NOW)
    assert result["reason"] is None
    assert result["state"] == "usable with gaps -- 2 warning(s)"


def test_doctor_repo_missing_is_distinct_from_not_asked():
    result = mod.doctor_cause({}, NOW, repo_missing=True)
    assert result["reason"] == "repo-missing"


def test_doctor_classification_agrees_with_statusline_own_classifier():
    """Cross-check, #383/#124's own convention applied here: this module
    duplicates statusline.py's three-shape VERDICT match rather than reach
    into its private `_doctor_verdict_state` (leading underscore -- every
    other cross-module call in this file goes through a public name). A
    drift between the two would make this field lie about a `dr?` that is
    actually a real, classifiable reading.
    """
    samples = [
        "ok",
        "usable with gaps -- 3 warning(s)",
        "not usable -- 1 failure(s), 2 warning(s)",
        "some unrecognised shape",
    ]
    for verdict in samples:
        cache = {"doctor_verdict": verdict, "doctor_fetched_at": NOW - 5}
        mine = mod.doctor_cause(cache, NOW)
        theirs = statusline._doctor_verdict_state(verdict)
        if theirs is None:
            assert mine["reason"] == "unrecognized", verdict
        else:
            assert mine["reason"] is None and mine["state"] == verdict, verdict


def test_check_statusline_unknowns_reports_all_three_fields(monkeypatch, tmp_path):
    cache = {}
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )
    joined = " ".join(msg for _, msg in doctor.FINDINGS)
    assert "statusline channel" in joined
    assert "statusline default-branch" in joined
    assert "/oss:doctor" in joined


def test_check_statusline_unknowns_doctor_ok_when_real_verdict(monkeypatch, tmp_path):
    cache = {
        "channel": {"raw_state": "forwarding", "attribution": "derivation"},
        "channel_fetched_at": NOW - 5,
        "fetched_at": NOW - 5,
        "default_branch_state": "green",
        "doctor_verdict": "ok",
        "doctor_fetched_at": NOW - 5,
    }
    monkeypatch.setattr(mod, "_read_cache_or_unreadable", lambda path: (cache, False))
    mod.check_statusline_unknowns(
        str(tmp_path), {"repo": "a/b", "default_branch": "main"}, now=NOW
    )
    assert doctor.FINDINGS
    assert all(state == "OK" for state, _ in doctor.FINDINGS)
