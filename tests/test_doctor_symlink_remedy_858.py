"""#858: the `not-a-symlink` WARN used to recommend replacing `./supertool`
with the plugin's own version-pinned symlink -- the exact artifact the nearby
`# --- reaches the running install (#288/#289)` comment in `scripts/doctor.py`
warns is a stale-pin hazard, and the one this repo's own `#742` measured this
launcher-shaped entry point as immune to. The honest remedy for a state doctor
has deliberately decided not to measure (#790/#801) is a way for the READER to
measure it themselves, never a substitution of one artifact for another.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def test_the_remedy_never_recommends_a_symlink_replacement(tmp_path):
    """Red before the fix: the old sentence recommended `replace it with the
    plugin's own symlink`, the shape #288/#289 exist to warn against."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "supertool").write_text("not a script\n", encoding="utf-8")

    doctor.FINDINGS.clear()
    doctor.check_supertool_entry_point(project, cache_root=str(tmp_path / "no-cache"))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "symlink" not in message.lower() or "is not a symlink" in message.lower(), message
    assert "replace it with the plugin" not in message, message
    assert "plugin's own symlink" not in message, message


def test_the_remedy_still_keeps_the_unknown_not_confirmed_half_verbatim(tmp_path):
    """Acceptance criteria: keep the `unknown, not confirmed` half -- only the
    remedy sentence changes."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "supertool").write_text("not a script\n", encoding="utf-8")

    doctor.FINDINGS.clear()
    doctor.check_supertool_entry_point(project, cache_root=str(tmp_path / "no-cache"))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "unknown, not confirmed" in message, message


def test_the_remedy_offers_a_way_for_the_reader_to_measure_it(tmp_path):
    """The remedy must be something the READER can do, not doctor running
    repository-supplied code (#790/#801 forbid that) and not a symlink swap."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "supertool").write_text("not a script\n", encoding="utf-8")

    doctor.FINDINGS.clear()
    doctor.check_supertool_entry_point(project, cache_root=str(tmp_path / "no-cache"))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "supertool version" in message, message
