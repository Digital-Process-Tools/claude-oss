"""Is what is installed the thing the plugin currently ships?

Two questions, both reported and neither acted on. Updating tools underneath a running
session changes behaviour mid-flight, and this plugin's posture everywhere else is to
detect and name rather than edit somebody's environment behind them.

So every check here has three outcomes and the third is load-bearing: **unknown** is
not **current**. A version comparison that could not reach the forge, or an owned file
that could not be rendered, must never render as up to date.
"""

import json
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


# --------------------------------------------------------------- installed record


def test_the_active_version_comes_from_the_install_record(tmp_path):
    """Not from the cache directory listing.

    The first live run reported `supertool 0.22.0 installed` while the active install
    was 0.40.0, and `remember 0.13.0` -- a version not even in that marketplace's
    cache. Old versions stay on disk, several marketplaces can carry the same plugin
    name, and a glob over all of them returns whichever sorts last. The record says
    which one is actually enabled; the directory listing says what was ever unpacked.
    """
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "supertool@dpt-plugins": [{"version": "0.40.0", "installPath": "/x"}],
                    "remember@dpt-plugins": [{"version": "0.20.0", "installPath": "/y"}],
                },
            }
        ),
        encoding="utf-8",
    )
    active = doctor.active_versions(["supertool", "remember"], record=record)
    assert active == {"supertool": "0.40.0", "remember": "0.20.0"}


def test_a_plugin_absent_from_the_record_is_not_installed(tmp_path):
    record = tmp_path / "installed_plugins.json"
    record.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    assert doctor.active_versions(["supertool"], record=record) == {}


def test_an_unreadable_record_yields_nothing_rather_than_a_guess(tmp_path):
    """Empty here means every dependency reports `missing`, which is loud. A guess
    from the cache would report a version nobody is running.
    """
    record = tmp_path / "installed_plugins.json"
    record.write_text("{ broken", encoding="utf-8")
    assert doctor.active_versions(["supertool"], record=record) == {}


def test_the_newest_entry_wins_when_a_plugin_is_recorded_twice(tmp_path):
    """The record holds a list per plugin -- one entry per scope."""
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps(
            {"plugins": {"supertool@dpt-plugins": [
                {"version": "0.9.0"}, {"version": "0.40.0"}]}}
        ),
        encoding="utf-8",
    )
    assert doctor.active_versions(["supertool"], record=record) == {"supertool": "0.40.0"}


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


# ------------------------------------------------- one gap, one fix, one line


def _finding(path, state, detail):
    return {"path": path, "state": state, "detail": "{}: {}".format(path, detail)}


def test_three_files_missing_for_one_reason_report_as_one_finding():
    """The bug: a repo that was never scaffolded printed three warnings, each ending
    in `Run /oss:scaffold.` -- one gap with one fix, rendered as three unrelated
    findings and counted three times in the verdict.
    """
    lines = doctor.owned_drift_summary(
        [_finding(name, "absent", "not in this repo. Run /oss:scaffold.")
         for name in (".oss/README.md", ".oss/x.py", ".github/workflows/oss-changelog.yml")]
    )
    assert len(lines) == 1, lines
    state, message = lines[0]
    assert state == "WARN"
    assert message.count("/oss:scaffold") == 1, message
    for name in (".oss/README.md", ".oss/x.py", ".github/workflows/oss-changelog.yml"):
        assert name in message, message


def test_different_facts_are_never_folded_into_one_line():
    """The positive control for the collapsing above. A summary that merged everything
    would pass the test before this one perfectly. Absent, drifted and unknown have
    different meanings and the same remedy, and the remedy is not the fact.
    """
    lines = doctor.owned_drift_summary(
        [
            _finding(".oss/README.md", "absent", "not in this repo. Run /oss:scaffold."),
            _finding(".oss/x.py", "drifted", "differs from what the plugin ships."),
            _finding(".github/workflows/oss-changelog.yml", "unknown", "no comparison was made"),
        ]
    )
    assert len(lines) == 3, lines
    assert {state for state, _ in lines} == {"WARN"}
    joined = " ".join(message for _, message in lines)
    assert "not in this repo" in joined and "differs from" in joined
    assert "no comparison was made" in joined


def test_a_check_that_could_not_look_is_never_reported_as_clean():
    """`unknown` is the third state this repo is named after. Grouping must not turn
    "I could not compare" into silence, which reads as "current"."""
    lines = doctor.owned_drift_summary(
        [_finding(name, "unknown", "no comparison was made")
         for name in (".oss/README.md", ".oss/x.py")]
    )
    assert [state for state, _ in lines] == ["WARN"]
    assert "no comparison was made" in lines[0][1]


def test_current_files_still_report_one_ok_line_each():
    """The clean repo's output is not the thing being fixed, and a summary that
    swallowed it would make this test's siblings pass on an empty list."""
    lines = doctor.owned_drift_summary(
        [{"path": name, "state": "current", "detail": name}
         for name in (".oss/README.md", ".oss/x.py")]
    )
    assert lines == [("OK", ".oss/README.md"), ("OK", ".oss/x.py")]


def test_a_single_missing_file_is_not_dressed_up_as_a_group():
    lines = doctor.owned_drift_summary(
        [_finding(".oss/README.md", "absent", "not in this repo. Run /oss:scaffold.")]
    )
    assert lines == [("WARN", ".oss/README.md: not in this repo. Run /oss:scaffold.")]


def test_grouping_never_reorders_the_report_around_a_clean_file():
    """Grouping pulls a later file up to an earlier one -- that is the feature. What it
    must not do is move a clean file ahead of a gap that was listed before it, which is
    what emitting the OK lines inline and the grouped ones afterwards did.
    """
    lines = doctor.owned_drift_summary(
        [
            _finding("a.md", "absent", "not in this repo. Run /oss:scaffold."),
            {"path": "b.md", "state": "current", "detail": "b.md"},
            _finding("c.md", "absent", "not in this repo. Run /oss:scaffold."),
        ]
    )
    assert lines == [
        ("WARN", "2 owned files -- a.md, c.md: not in this repo. Run /oss:scaffold."),
        ("OK", "b.md"),
    ]


def test_a_detail_that_does_not_carry_its_own_path_is_left_alone():
    """The prefix strip is how two findings are recognised as the same fact. A detail
    written some other way must still print in full rather than being truncated into
    something that reads like a different finding."""
    lines = doctor.owned_drift_summary(
        [{"path": ".oss/x.py", "state": "drifted", "detail": "no path prefix here"}]
    )
    assert lines == [("WARN", ".oss/x.py: no path prefix here")]


def test_the_summary_of_a_never_scaffolded_repo_is_one_warning(tmp_path):
    """End to end against the real finding shapes, not hand-built ones -- the
    hand-built fixtures above would keep passing if `owned_drift` changed its wording
    and the two stopped meeting."""
    lines = doctor.owned_drift_summary(
        doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)
    )
    assert len(lines) == 1, lines
    assert lines[0][0] == "WARN"
    assert lines[0][1].count("/oss:scaffold") == 1, lines[0][1]
