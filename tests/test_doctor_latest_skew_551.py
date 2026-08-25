"""``check_latest_skew`` -- doctor cross-references the status line's cached
`latest` for this repo against the newest published version read live (#551).

Two mechanisms in this plugin answer "am I current": `plugin_update`'s receipt
(`check_auto_update`, a different question about a different clock) and the
status line's cache. When the status line rendered a stale `ahead` marker on
2026-08-25, `doctor` said nothing about it -- nothing compared the two. This
check is that comparison, and its own third state (#216's reasoning): no cache,
an unreadable cache, and a wrong-shape cache are distinct answers with distinct
remedies, and none of them is agreement.

Must never repair: `doctor`'s contract is diagnose, exit 0, one VERDICT line. No
test here calls anything that could delete or refresh the cache -- there is
nothing in `doctor_check_latest_skew.py` that does.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_latest_skew  # noqa: E402
import statusline  # noqa: E402


def _reset():
    doctor.FINDINGS.clear()


def _write_cache(tmp_path, document):
    path = statusline.cache_path("owner/name")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _finding():
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    return doctor.FINDINGS[0]


# --------------------------------------------------------------- not-checked


def test_no_config_is_not_checked_not_agreement():
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", None)
    state, message = _finding()
    assert state == "WARN"
    assert "latest skew" in message


def test_a_config_with_no_repo_declared_is_not_checked():
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {})
    state, message = _finding()
    assert state == "WARN"
    assert "latest skew" in message


def test_a_missing_statusline_module_is_not_checked_not_a_crash(monkeypatch):
    monkeypatch.setattr(doctor_check_latest_skew, "statusline", None)
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"})
    state, message = _finding()
    assert state == "WARN"
    assert "statusline.py" in message


# -------------------------------------------------------- could not be determined


def test_no_cache_file_could_not_be_determined_never_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"})
    state, message = _finding()
    assert state == "WARN"
    assert "could not be determined" in message
    assert "no cache" in message


def test_an_unparseable_cache_could_not_be_determined(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    path = statusline.cache_path("owner/name")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"})
    state, message = _finding()
    assert state == "WARN"
    assert "could not be determined" in message


def test_a_wrong_shape_cache_could_not_be_determined(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    path = statusline.cache_path("owner/name")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"})
    state, message = _finding()
    assert state == "WARN"
    assert "could not be determined" in message


def test_a_cache_carrying_no_reading_for_this_repo_could_not_be_determined(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    _write_cache(tmp_path, {"fetched_at": 1.0, "prs": 0, "issues": 0})
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"})
    state, message = _finding()
    assert state == "WARN"
    assert "could not be determined" in message
    assert "no `latest` reading" in message


def test_a_live_read_that_does_not_answer_could_not_be_determined(tmp_path, monkeypatch):
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "_latest_release", lambda repo: None)
    _write_cache(
        tmp_path,
        {"fetched_at": 1.0, "latest_fetched_at": 1.0, "latest": {"owner/name": "0.12.0"}},
    )
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"}, now=1.0)
    state, message = _finding()
    assert state == "WARN"
    assert "could not be determined" in message
    assert "did not answer" in message


# ---------------------------------------------------------------------- OK / WARN


def test_agreement_is_ok_and_still_carries_the_stamp(tmp_path, monkeypatch):
    """The must-not-fire control for the disagreement test below: OK, and the
    stamp is reported anyway -- a fresh agreement and an hour-old one are not
    the same evidence."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "_latest_release", lambda repo: "0.13.0")
    _write_cache(
        tmp_path,
        {"fetched_at": 1000.0, "latest_fetched_at": 1000.0, "latest": {"owner/name": "0.13.0"}},
    )
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"}, now=1000.0 + 120)
    state, message = _finding()
    assert state == "OK"
    assert "0.13.0" in message
    assert "120s old" in message


def test_the_must_fire_control_disagreement_is_warn_not_agreement(tmp_path, monkeypatch):
    """This is the exact incident the cluster was filed from: the cache says
    0.12.0, live says 0.13.0 -- the fixture is the numbers from #549's own
    report (17:54 cache, 18:06 publish, 18:46 read)."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "_latest_release", lambda repo: "0.13.0")
    _write_cache(
        tmp_path,
        {"fetched_at": 1000.0, "latest_fetched_at": 1000.0, "latest": {"owner/name": "0.12.0"}},
    )
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"}, now=1000.0 + 3120)
    state, message = _finding()
    assert state == "WARN"
    assert "0.12.0" in message and "0.13.0" in message
    assert "not a fault in the repo" in message


def test_a_leading_v_does_not_read_as_disagreement(tmp_path, monkeypatch):
    """`0.13.0` and `v0.13.0` are the same version -- the same reasoning
    `statusline.version_status` already applies."""
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "_latest_release", lambda repo: "v0.13.0")
    _write_cache(
        tmp_path,
        {"fetched_at": 1000.0, "latest_fetched_at": 1000.0, "latest": {"owner/name": "0.13.0"}},
    )
    _reset()
    doctor_check_latest_skew.check_latest_skew(".", {"repo": "owner/name"}, now=1000.0)
    state, _ = _finding()
    assert state == "OK"


# ---------------------------------------------------------- doctor.py wiring


def test_doctor_module_exposes_the_check_after_the_relocation_import():
    """`doctor.py` imports this back out immediately after the module's own
    definition, same as every other #497-relocated check."""
    assert doctor.check_latest_skew is doctor_check_latest_skew.check_latest_skew
