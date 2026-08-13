"""Is what is installed the thing the plugin currently ships?

Two questions, both reported and neither acted on. Updating tools underneath a running
session changes behaviour mid-flight, and this plugin's posture everywhere else is to
detect and name rather than edit somebody's environment behind them.

So every check here has three outcomes and the third is load-bearing: **unknown** is
not **current**. A version comparison that could not reach the forge, or an owned file
that could not be rendered, must never render as up to date.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import scaffold  # noqa: E402


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "ci": {"required_checks": 0},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


# ------------------------------------------------------------------ version compare


def test_equal_versions_are_current():
    assert doctor.compare_versions("0.3.1", "0.3.1") == "current"


def test_a_lower_installed_version_is_behind():
    assert doctor.compare_versions("0.3.1", "0.4.0") == "behind"


def test_numeric_components_compare_as_numbers_not_strings():
    """`"0.9.0" > "0.10.0"` lexically, and a string compare would call a stale install
    current -- silently, for exactly the versions where it matters most.
    """
    assert doctor.compare_versions("0.9.0", "0.10.0") == "behind"
    assert doctor.compare_versions("0.10.0", "0.9.0") == "ahead"


def test_a_higher_installed_version_is_ahead_not_current():
    """A local checkout ahead of the marketplace is a real state, and calling it
    current hides that somebody is running unreleased code.
    """
    assert doctor.compare_versions("0.5.0", "0.4.0") == "ahead"


def test_a_missing_version_on_either_side_is_unknown():
    assert doctor.compare_versions(None, "0.4.0") == "unknown"
    assert doctor.compare_versions("0.4.0", None) == "unknown"
    assert doctor.compare_versions(None, None) == "unknown"


def test_an_unparseable_version_is_unknown_not_behind():
    """Guessing "behind" would send someone to run an update that changes nothing."""
    assert doctor.compare_versions("main", "0.4.0") == "unknown"
    assert doctor.compare_versions("0.4.0", "unknown") == "unknown"


# --------------------------------------------------------------- dependency report


def test_a_current_dependency_reports_ok():
    findings = doctor.dependency_findings({"remember": "0.19.0"}, {"remember": "0.19.0"})
    assert [f["state"] for f in findings] == ["current"]


def test_a_behind_dependency_names_both_versions_and_the_fix():
    findings = doctor.dependency_findings({"remember": "0.18.0"}, {"remember": "0.19.0"})
    finding = findings[0]
    assert finding["state"] == "behind"
    assert "0.18.0" in finding["detail"] and "0.19.0" in finding["detail"]
    assert "claude plugin update" in finding["detail"]


def test_a_dependency_that_is_not_installed_is_reported_separately():
    """Missing is a broken loop, not a stale one, and the remedy is different."""
    findings = doctor.dependency_findings({}, {"remember": "0.19.0"})
    assert findings[0]["state"] == "missing"
    assert "install" in findings[0]["detail"]


def test_an_unreachable_latest_is_unknown_and_says_it_checked_nothing():
    findings = doctor.dependency_findings({"remember": "0.19.0"}, {"remember": None})
    assert findings[0]["state"] == "unknown"
    assert "could not" in findings[0]["detail"].lower()


def test_every_declared_dependency_is_reported():
    """A dependency absent from both maps would otherwise vanish from the report, and
    a name nobody mentions reads as a name with nothing to say.
    """
    findings = doctor.dependency_findings({}, {}, declared=["supertool", "remember"])
    assert {f["name"] for f in findings} == {"supertool", "remember"}


# ------------------------------------------------------------------- owned drift


def test_owned_files_matching_what_is_shipped_are_current(tmp_path):
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    findings = doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert [f["state"] for f in findings] == ["current"] * len(scaffold.OWNED)


def test_an_edited_owned_file_is_reported_as_drifted(tmp_path):
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    (tmp_path / ".oss" / "README.md").write_text("someone edited this\n", encoding="utf-8")
    findings = {f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)}
    assert findings[".oss/README.md"]["state"] == "drifted"
    assert "/oss:scaffold" in findings[".oss/README.md"]["detail"]


def test_a_missing_owned_file_is_reported_as_absent(tmp_path):
    """A repo scaffolded before a file existed has never seen it. Absent and drifted
    have the same fix and are still different facts.
    """
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    (tmp_path / ".oss" / "assemble_changelog.py").unlink()
    findings = {f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)}
    assert findings[".oss/assemble_changelog.py"]["state"] == "absent"


def test_a_repo_that_was_never_scaffolded_reports_absent_not_drifted(tmp_path):
    findings = doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert {f["state"] for f in findings} == {"absent"}


def test_drift_is_never_reported_as_current_when_it_cannot_be_rendered(tmp_path):
    """If the shipped version cannot be produced, there is nothing to compare against
    and the honest answer is unknown.
    """
    findings = doctor.owned_drift(tmp_path, _config(), plugin_root=tmp_path / "not-a-plugin")
    assert {f["state"] for f in findings} == {"unknown"}
