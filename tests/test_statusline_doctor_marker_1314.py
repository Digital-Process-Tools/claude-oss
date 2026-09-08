"""`/oss:doctor`'s own verdict, cached and detached, as a sixth status-line field
(#1314) -- the same three-clock discipline #856/#613/#550 already argue for, applied
to a field the issue's own body says is `/oss:doctor`'s own verdict, too expensive to
take at render time.

Every "must not render confidently" assertion below carries a "must render" control in
the same fixture, per this repository's own convention (#550): a positive control
proving the marker DOES change when the verdict changes, and a stale/absent control
proving the `?` fallback fires, exercised together rather than either alone.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------------ _doctor_verdict_state


def test_verdict_state_reads_the_clean_case():
    assert statusline._doctor_verdict_state("ok") == "ok"


def test_verdict_state_reads_gaps_with_its_warning_count_attached():
    assert (
        statusline._doctor_verdict_state("usable with gaps -- 2 warning(s)") == "gaps"
    )


def test_verdict_state_reads_not_usable_with_its_counts_attached():
    assert (
        statusline._doctor_verdict_state("not usable -- 1 failure(s), 3 warning(s)")
        == "bad"
    )


def test_verdict_state_is_none_for_an_absent_or_unrecognised_verdict():
    """The must-not-guess control: neither a missing reading nor a verdict shape
    `doctor.py` has never printed is read as any of the three real states."""
    assert statusline._doctor_verdict_state(None) is None
    assert statusline._doctor_verdict_state("") is None
    assert statusline._doctor_verdict_state("something nobody wrote down") is None


# ------------------------------------------------------------------- _doctor_reading


def test_doctor_reading_parses_the_last_verdict_line(monkeypatch):
    class _Result:
        returncode = 0
        stdout = (
            b"OK oss plugin version 1.2.3\n"
            b"WARN something\n"
            b"VERDICT: usable with gaps -- 1 warning(s)\n"
        )

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    assert statusline._doctor_reading(".") == "usable with gaps -- 1 warning(s)"


def test_doctor_reading_is_none_when_the_subprocess_cannot_be_run(monkeypatch):
    def _raise(*a, **k):
        raise OSError("no such interpreter")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert statusline._doctor_reading(".") is None


def test_doctor_reading_is_none_when_it_times_out(monkeypatch):
    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="doctor.py", timeout=60)

    monkeypatch.setattr(subprocess, "run", _raise)
    assert statusline._doctor_reading(".") is None


def test_doctor_reading_is_none_on_a_nonzero_exit(monkeypatch):
    """Doctor's own contract is exit 0 always -- if it ever does not, that is
    treated as a real absence, never trusted for a VERDICT line it should not
    have produced."""

    class _Result:
        returncode = 1
        stdout = b"VERDICT: ok\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    assert statusline._doctor_reading(".") is None


def test_doctor_reading_is_none_with_no_verdict_line_at_all(monkeypatch):
    class _Result:
        returncode = 0
        stdout = b"OK something\nWARN something else\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    assert statusline._doctor_reading(".") is None


# ----------------------------------------------------------------------------- live


def test_real_doctor_reading_produces_a_recognisable_verdict_against_this_repo():
    """Runs the real `doctor.py` against this checkout's own root, skipped rather
    than failed if the interpreter cannot be found (the same three-state discipline
    this whole module is about, applied to the test that checks it)."""
    if sys.executable is None:
        import pytest

        pytest.skip("no interpreter to run doctor.py with")
    raw = statusline._doctor_reading(str(REPO_ROOT))
    assert raw is not None, "doctor.py produced no VERDICT line against its own repo"
    assert statusline._doctor_verdict_state(raw) in ("ok", "gaps", "bad")


# ---------------------------------------------------------------------- _doctor_field


def test_field_maps_all_three_real_states_to_the_documented_glyph():
    symbols = statusline._symbols(ascii_only=False)
    assert statusline._doctor_field("ok", symbols) == "dr" + symbols["ok"]
    assert statusline._doctor_field("gaps", symbols) == "dr" + symbols["own"]
    assert statusline._doctor_field("bad", symbols) == "dr" + symbols["bad"]


def test_field_is_the_unk_glyph_when_the_reading_is_absent():
    symbols = statusline._symbols(ascii_only=False)
    assert statusline._doctor_field(None, symbols) == "dr" + symbols["unk"]


def test_field_survives_the_ascii_fallback():
    symbols = statusline._symbols(ascii_only=True)
    assert statusline._doctor_field("ok", symbols) == "dr" + symbols["ok"]
    assert statusline._doctor_field(None, symbols) == "dr" + symbols["unk"]


# -------------------------------------------------------------------------- render()


def _facts(doctor_state=None, **overrides):
    facts = {
        "model": "Opus",
        "percent": 10,
        "repo_name": "claude-oss",
        "branch": "main",
        "default_branch": "main",
        "version": "0.19.0",
        "board": {},
        "release": {},
        "last": "12:00",
        "plugins": [],
        "channel": None,
        "default_branch_state": None,
        "doctor_state": doctor_state,
    }
    facts.update(overrides)
    return facts


def test_render_shows_ok_glyph_when_doctor_verdict_is_clean():
    line = statusline.render(_facts("ok"), ascii_only=True)
    assert "dr" + statusline._symbols(True)["ok"] in line


def test_render_shows_a_different_glyph_when_the_verdict_changes():
    """The positive control the issue's own acceptance criterion asks for: the
    marker DOES change when the underlying verdict changes."""
    ok_line = statusline.render(_facts("ok"), ascii_only=True)
    bad_line = statusline.render(_facts("bad"), ascii_only=True)
    assert ok_line != bad_line
    assert "dr" + statusline._symbols(True)["bad"] in bad_line
    assert "dr" + statusline._symbols(True)["bad"] not in ok_line


def test_render_falls_back_to_unk_when_the_reading_is_absent():
    line = statusline.render(_facts(None), ascii_only=True)
    assert "dr" + statusline._symbols(True)["unk"] in line


# --------------------------------------------------------------------- gather()


def _cache(doctor_verdict, doctor_fetched_at, now):
    return {
        "repo": "owner/repo",
        "fetched_at": now,
        "prs": 0,
        "issues": 0,
        "doctor_verdict": doctor_verdict,
        "doctor_fetched_at": doctor_fetched_at,
    }


def _stub_common(monkeypatch, tmp_path, cache):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: cache)
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "owner/repo"})
    monkeypatch.setattr(statusline, "board_is_due", lambda c, n: False)
    monkeypatch.setattr(statusline, "_fork_refresh", lambda root, repo: None)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    monkeypatch.setattr(statusline, "repo_version", lambda root: "0.19.0")
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "git_release_progress", lambda root: {})


def test_gather_reads_a_fresh_reading_through(tmp_path, monkeypatch):
    now = 1_000_000.0
    cache = _cache("ok", now - 1, now)
    _stub_common(monkeypatch, tmp_path, cache)
    facts = statusline.gather({}, ".", now=now)
    assert facts["doctor_state"] == "ok"


def test_gather_folds_a_stale_reading_to_none_even_though_it_says_ok(
    tmp_path, monkeypatch
):
    """The must-not-render-confidently case. A reading older than
    `DOCTOR_REFRESH_AFTER` must never render as a confident `ok`."""
    now = 1_000_000.0
    cache = _cache("ok", now - statusline.DOCTOR_REFRESH_AFTER - 1, now)
    _stub_common(monkeypatch, tmp_path, cache)
    facts = statusline.gather({}, ".", now=now)
    assert facts["doctor_state"] is None


def test_gather_is_none_when_no_reading_was_ever_taken(tmp_path, monkeypatch):
    now = 1_000_000.0
    cache = _cache(None, None, now)
    _stub_common(monkeypatch, tmp_path, cache)
    facts = statusline.gather({}, ".", now=now)
    assert facts["doctor_state"] is None


# ----------------------------------------------------------------------- refresh()


def test_refresh_fetches_a_new_reading_when_due(tmp_path, monkeypatch):
    now = 1_000_000.0
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: {})
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": None})
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 0)
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(statusline, "_doctor_reading", lambda root: "ok")
    document = statusline.refresh(str(tmp_path), now=now)
    assert document["doctor_verdict"] == "ok"
    assert document["doctor_fetched_at"] == now


def test_refresh_carries_a_fresh_reading_forward_under_its_own_stamp(
    tmp_path, monkeypatch
):
    now = 1_000_000.0
    previous = {
        "doctor_verdict": "ok",
        "doctor_fetched_at": now - 5,
        "fetched_at": now - 5,
    }
    calls = []
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "read_cache", lambda path: previous)
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": None})
    monkeypatch.setattr(statusline, "installed_plugins", lambda root: {})
    monkeypatch.setattr(
        statusline, "_doctor_reading", lambda root: calls.append(1) or "bad"
    )
    document = statusline.refresh(str(tmp_path), now=now)
    assert document["doctor_verdict"] == "ok"
    assert document["doctor_fetched_at"] == now - 5
    assert calls == []
