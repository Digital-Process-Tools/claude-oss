"""Is what is installed the thing the plugin currently ships?

Two questions, both reported and neither acted on. Updating tools underneath a running
session changes behaviour mid-flight, and this plugin's posture everywhere else is to
detect and name rather than edit somebody's environment behind them.

So every check here has three outcomes and the third is load-bearing: **unknown** is
not **current**. A version comparison that could not reach the forge, or an owned file
that could not be rendered, must never render as up to date.
"""

import json
import os
import sys
from pathlib import Path

import pytest

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


def test_non_ascii_digits_do_not_raise_or_silently_compare_equal():
    """`str.isdigit()` and `int()` do not agree on a domain (#388).

    U+00B2 SUPERSCRIPT TWO is True for `isdigit()` and `int()` refuses it, so the
    guard passes and the conversion raised -- a traceback where the contract promises
    `unknown`. U+0662 ARABIC-INDIC DIGIT TWO is True for both, and `int()` accepts
    it, so a version string nobody typed compared equal to a real one and a stale
    install reported `current`. Paired with the positive controls so a parser that
    returns `None` for everything cannot satisfy this test.
    """
    assert doctor.compare_versions("0.4.²", "0.5.0") == "unknown"
    assert doctor.compare_versions("0.4.٢", "0.4.2") == "unknown"
    assert doctor.compare_versions("0.4.0", "0.5.0") == "behind"
    assert doctor.compare_versions("0.4.0", "0.4.0") == "current"


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


def test_an_owned_file_that_cannot_be_looked_at_is_unknown_and_not_absent(tmp_path):
    """`absent` sends the reader to `/oss:scaffold`; `unknown` says the question was not
    answered. Reporting the second as the first is this repo's own defect class, and
    which one you get used to depend on the interpreter rather than on the repository:
    before 3.13 `Path.is_file()` raised `PermissionError` here and killed doctor, and
    from 3.13 it answers False and reports the file absent. `os.stat` raises on every
    version, so the distinction is a property of the call.

    The deny is measured rather than assumed -- root ignores the mode bit, some
    filesystems ignore it, and Windows' `os.chmod` on a directory toggles a read-only
    attribute that does not stop a listing.
    """
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    owned = tmp_path / ".oss" / "assemble_changelog.py"
    assert owned.is_file(), "fixture did not produce the file the test is about"

    # Positive control, same fixture: readable, the file is found and reported current.
    # Without this, the unknown assertion below also passes when owned_drift breaks
    # entirely and reports nothing about this path at all.
    before = {f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)}
    assert before[".oss/assemble_changelog.py"]["state"] == "current"

    os.chmod(str(tmp_path / ".oss"), 0o000)
    try:
        try:
            os.stat(str(owned))
        except OSError:
            pass
        else:
            pytest.skip(
                "this platform still stats {} through a 000 directory, so the "
                "unreadable case was not built and went untested".format(owned.name)
            )

        findings = {
            f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)
        }
    finally:
        os.chmod(str(tmp_path / ".oss"), 0o755)

    finding = findings[".oss/assemble_changelog.py"]
    assert finding["state"] == "unknown", finding
    assert "not absent" in finding["detail"]
    assert "/oss:scaffold" not in finding["detail"]


# ------------------------------------------------ absent by design is not absent (#126)
#
# `owned_drift` reported every owned file not on disk as `absent`, remedy
# `Run /oss:scaffold.` -- and scaffold *declines* to write the changelog trio into a
# repo that already runs a changelog gate under another name. So a declined repo was
# told, on every run, mid-tick and before every release, to run the command that had
# just declined and would decline again.
#
# Both halves are individually correct and neither diff contains the defect: it lives
# in the composition. `owned_drift_summary`'s own docstring already argues that a line
# printed regardless of state carries no information.


def _gated(root):
    """A repo that already runs somebody else's changelog gate, so scaffold declines."""
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "their-changelog.yml").write_text(
        "name: changelog\njobs:\n  fragment:\n    steps:\n"
        "      - run: python tools/assemble_changelog.py --check\n",
        encoding="utf-8",
    )
    return root


def test_a_declined_trio_is_declined_and_an_ungated_repo_still_warns(tmp_path):
    """The fix and its positive control in one fixture.

    Two repos, one scaffold call each, differing only in whether a foreign gate is
    present. The gated one must not be told to run /oss:scaffold; the ungated one
    must. Without the second half, an `owned_drift` that returned nothing at all --
    or a doctor that never ran -- satisfies the first half perfectly.
    """
    gated = _gated(tmp_path / "gated")
    scaffold.apply(gated, _config(), plugin_root=REPO_ROOT)
    findings = doctor.owned_drift(gated, _config(), plugin_root=REPO_ROOT)
    assert {f["state"] for f in findings} == {"declined"}, findings
    for finding in findings:
        assert "Run /oss:scaffold." not in finding["detail"], finding
        assert "--force-owned" in finding["detail"], finding
    assert {state for state, _ in doctor.owned_drift_summary(findings)} == {"OK"}

    ungated = tmp_path / "ungated"
    ungated.mkdir(parents=True, exist_ok=True)
    scaffold.apply(ungated, _config(), plugin_root=REPO_ROOT)
    (ungated / ".oss" / "assemble_changelog.py").unlink()
    control = {f["path"]: f for f in doctor.owned_drift(ungated, _config(), plugin_root=REPO_ROOT)}
    assert control[".oss/assemble_changelog.py"]["state"] == "absent"
    assert "Run /oss:scaffold." in control[".oss/assemble_changelog.py"]["detail"]
    assert ("WARN", ".oss/assemble_changelog.py: not in this repo. Run /oss:scaffold.") in (
        doctor.owned_drift_summary(list(control.values()))
    )


def test_a_present_owned_file_is_still_compared_even_when_the_gate_declines(tmp_path):
    """`--force-owned` writes the trio into a gated repo. The file is then on disk and
    a decline says nothing about whether it drifted -- so the gate is consulted only
    where the answer changes, which is the absent branch.
    """
    gated = _gated(tmp_path / "forced")
    scaffold.apply(gated, _config(), plugin_root=REPO_ROOT, force_owned=True)
    (gated / ".oss" / "README.md").write_text("someone edited this\n", encoding="utf-8")
    findings = {f["path"]: f for f in doctor.owned_drift(gated, _config(), plugin_root=REPO_ROOT)}
    assert findings[".oss/README.md"]["state"] == "drifted"
    # Positive control: the other two were written by the same forced run and match.
    assert findings[".oss/assemble_changelog.py"]["state"] == "current"


def test_a_gate_that_could_not_be_detected_is_unknown_and_never_declined(tmp_path, monkeypatch):
    """The third state of the thing doctor is now asking.

    scaffold declines the trio when detection returns `unknown` too -- but that is a
    precaution, not a decision somebody made. Reporting it as `declined` would put
    this repo's own defect class back: an absence produced by the tool, read as an
    absence in the world. `unknown` is the name doctor already has for it.
    """
    monkeypatch.setattr(
        scaffold,
        "check_changelog_gate",
        lambda root, config: [{"state": "unknown", "detail": "could not read: x.yml"}],
    )
    findings = doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert {f["state"] for f in findings} == {"unknown"}, findings
    assert all("Run /oss:scaffold." not in f["detail"] for f in findings)
    assert {state for state, _ in doctor.owned_drift_summary(findings)} == {"WARN"}


def test_a_gate_state_this_doctor_has_never_heard_of_lands_in_unknown(tmp_path, monkeypatch):
    """`_detect_changelog_gate` is being changed concurrently (#124) and may grow a
    fourth state. An unrecognised state must be an addition rather than a break, and
    it must not fall through to `absent` -- which is the exact wrong answer, because
    it restores the remedy that provably changes nothing.
    """
    monkeypatch.setattr(
        scaffold,
        "check_changelog_gate",
        lambda root, config: [{"state": "a-state-invented-tomorrow", "detail": "who knows"}],
    )
    findings = doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert {f["state"] for f in findings} == {"unknown"}, findings
    assert all("Run /oss:scaffold." not in f["detail"] for f in findings)


def test_a_gate_check_that_raises_is_unknown_rather_than_a_traceback(tmp_path, monkeypatch):
    """doctor's whole contract is exit 0 and one VERDICT line. A consultation of
    somebody else's module must not be the thing that breaks it.
    """

    def _boom(root, config):
        raise OSError("the tree could not be walked")

    monkeypatch.setattr(scaffold, "check_changelog_gate", _boom)
    findings = doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert {f["state"] for f in findings} == {"unknown"}, findings


def test_the_changelog_gate_governs_every_owned_file(tmp_path):
    """The coupling doctor now depends on, asserted rather than assumed.

    `owned_drift` reads one gate answer and applies it to all of `scaffold.OWNED`,
    because `scaffold.plan` does exactly that. If the gate is ever narrowed to a
    subset, this fails here rather than silently reporting two of three files as
    declined when scaffold would have written them.
    """
    gated = _gated(tmp_path / "coupling")
    entries = {e["path"]: e["action"] for e in scaffold.plan(gated, _config())}
    assert {entries[name] for name in scaffold.OWNED} == {"decline"}, entries

    # Positive control: the same call on an ungated repo replaces all of them, so the
    # assertion above is about the gate and not about `plan` declining everything.
    plain = tmp_path / "coupling-plain"
    plain.mkdir(parents=True, exist_ok=True)
    plain_entries = {e["path"]: e["action"] for e in scaffold.plan(plain, _config())}
    assert {plain_entries[name] for name in scaffold.OWNED} == {"replace"}, plain_entries


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


# --------------------------------------------- what re-running would change (#26)
#
# The whole point of this section: "these differ" is the same sentence whether the
# difference is a reworded comment or whether the repo's changelog gate is broken
# until it is re-run. Doctor holds exactly two artefacts -- their bytes and ours --
# and can therefore describe the EFFECT of re-running, never the CAUSE of the
# difference. Every assertion below is about effect.


def test_an_identical_file_has_no_effect_to_report():
    """The control the two tests after this one need. A classifier that answered
    "behaviour" unconditionally would pass the behaviour test and fail this one."""
    text = "on:\n  push:\n    branches: [main]\n"
    assert doctor.owned_effect(text, text, "x.yml")["kind"] == "same"


def test_a_comment_only_difference_reports_that_nothing_it_does_changes():
    theirs = "on:\n  push:\n    branches: [main]\n"
    ours = "# why this file exists\non:\n  push:\n    branches: [main]\n"
    effect = doctor.owned_effect(theirs, ours, "x.yml")
    assert effect["kind"] == "cosmetic", effect
    assert effect["sections"] == []


def test_a_behavioural_difference_names_where_it_lands():
    """The positive control for the test above, in the same file type. A classifier
    that called everything cosmetic would report "nothing it does changes" about a
    repo whose gate had been rewritten."""
    theirs = "on:\n  push:\n    branches: [main]\n"
    ours = "on:\n  push:\n    branches: [main, release]\n"
    effect = doctor.owned_effect(theirs, ours, "x.yml")
    assert effect["kind"] == "behaviour", effect
    assert "on.push.branches" in effect["sections"], effect


def test_a_python_change_is_named_by_its_enclosing_definition():
    theirs = "def fold(x):\n    return 1\n"
    ours = "def fold(x):\n    return 2\n"
    effect = doctor.owned_effect(theirs, ours, "a.py")
    assert effect["kind"] == "behaviour"
    assert "fold" in effect["sections"], effect


def test_markdown_prose_is_cosmetic_and_a_fenced_command_is_not():
    """Both halves in one fixture: a README whose wording changed and a README whose
    documented command changed are different decisions, and the same file type."""
    prose_theirs = "# Running it\n\nThis file is owned by the plugin.\n"
    prose_ours = "# Running it\n\nThis file belongs to the plugin.\n"
    assert doctor.owned_effect(prose_theirs, prose_ours, "r.md")["kind"] == "cosmetic"

    fence = "# Running it\n\n```\npython3 .oss/assemble_changelog.py {}\n```\n"
    effect = doctor.owned_effect(fence.format("--check"), fence.format("--check-links"), "r.md")
    assert effect["kind"] == "behaviour", effect
    assert "Running it" in effect["sections"], effect


def test_one_region_is_not_named_twice_at_two_depths():
    """`jobs.gate.steps.name` and `jobs.gate.steps.name.run` are the same region. Four
    slots is the whole budget; two of them pointing at one place is a worse sentence."""
    theirs = "jobs:\n  gate:\n    steps:\n      - name: check\n        run: exit 1\n"
    ours = "jobs:\n  gate:\n    steps:\n      - name: verify\n        run: exit 0\n"
    sections = doctor.owned_effect(theirs, ours, "w.yml")["sections"]
    assert sections == ["jobs.gate.steps.name.run"], sections


def test_an_unknown_file_type_is_treated_as_behavioural():
    """Silent in the safe direction. A suffix nobody taught this function about must
    not be reported as "nothing it does changes"."""
    effect = doctor.owned_effect("a\n", "b\n", "thing.conf")
    assert effect["kind"] == "behaviour"


def test_a_crlf_checkout_of_an_owned_file_is_not_drift(tmp_path):
    """Windows checkouts hold CRLF where the plugin wrote LF. The bytes differ and
    the file is the file -- git converted it, nobody edited it. Reporting that as
    drift would make this check fire on every Windows repo forever, which is how a
    real signal gets ignored."""
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    target = tmp_path / ".oss" / "README.md"
    # The plugin writes with Path.write_text and no newline= argument, so on Windows
    # the scaffolded copy is ALREADY CRLF. Converting again would produce \r\r\n --
    # genuine corruption, not a git checkout, and the assertion below would then be
    # measuring the wrong thing. Normalise to LF first so the fixture is the same
    # file on every platform.
    lf = target.read_bytes().replace(b"\r\n", b"\n")
    target.write_bytes(lf.replace(b"\n", b"\r\n"))
    on_disk = target.read_bytes()
    assert b"\r\n" in on_disk and b"\r\r" not in on_disk, on_disk[:200]
    findings = {f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)}
    assert findings[".oss/README.md"]["state"] == "current", findings[".oss/README.md"]


def test_an_undecodable_owned_file_is_unknown_rather_than_a_crash(tmp_path):
    """The third state, for the half of the comparison that lives in their repo.
    Doctor exits 0 always; an owned file that is not UTF-8 must produce a finding
    that says so, not a traceback out of check_freshness."""
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    (tmp_path / ".oss" / "README.md").write_bytes(b"\xff\xfe not utf-8 \x00")
    findings = {f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)}
    assert findings[".oss/README.md"]["state"] == "unknown", findings[".oss/README.md"]
    assert "could not be read" in findings[".oss/README.md"]["detail"]


def test_the_drift_line_never_claims_the_maintainer_wrote_nothing(tmp_path):
    """Doctor cannot tell a stale copy from one the maintainer edited -- nothing in a
    managed repo records which plugin version wrote the file. The old wording told
    them outright that nothing they wrote was at risk, which is exactly wrong in the
    case it cannot rule out."""
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    (tmp_path / ".oss" / "README.md").write_text("mine now\n", encoding="utf-8")
    findings = {f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)}
    detail = findings[".oss/README.md"]["detail"]
    assert "nothing you wrote is at risk" not in detail, detail
    assert "/oss:scaffold" in detail


def test_a_drifted_workflow_says_what_re_running_would_change(tmp_path):
    """End to end on a real owned file. The maintainer decides whether to re-run from
    this line, so it has to name behaviour rather than announce a difference."""
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    target = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    target.write_text(
        target.read_text(encoding="utf-8").replace("exit 1", "exit 0"), encoding="utf-8"
    )
    findings = {f["path"]: f for f in doctor.owned_drift(tmp_path, _config(), plugin_root=REPO_ROOT)}
    finding = findings[".github/workflows/oss-changelog.yml"]
    assert finding["state"] == "drifted", finding
    assert "what it does" in finding["detail"], finding["detail"]
    # Not just the headline: the sentence has to carry a region, or this whole check is
    # back to announcing that something differs. `jobs.` is the shipped workflow's own
    # top-level key, so a section walk that stopped returning anything fails here.
    assert "jobs." in finding["detail"], finding["detail"]


def test_a_key_shaped_line_inside_a_run_block_is_not_read_as_a_key():
    """Everything under `run: |` is shell. A step echoing `status: pending` declares no
    key, and naming `...run.status` invents a path the document does not have."""
    # The shell line has to be key-shaped at the start of the line: that is the one the
    # key regex matches. A fixture whose colon sits inside an `echo` argument never
    # reproduced this and would have passed against the bug.
    template = (
        "jobs:\n  build:\n    steps:\n      - name: go\n        run: |\n"
        "          status: {}\n"
    )
    effect = doctor.owned_effect(template.format("old"), template.format("new"), "w.yml")
    assert effect["sections"] == ["jobs.build.steps.name.run"], effect


def test_a_backtick_fence_inside_a_tilde_fence_does_not_desync_the_tracker():
    """Only the marker that opened a fence closes it. Toggling on either one classified
    every line after such a block inside out -- prose as behaviour, code as prose.

    The inner marker has to start its line, for the same reason as the test above: the
    tracker only ever looked at the first three characters, so a fixture that indented
    or prefixed it reproduced nothing.
    """
    template = (
        "# Title\n\n~~~\n```markdown\n~~~\n\nProse that {} the same meaning.\n"
    )
    effect = doctor.owned_effect(template.format("keeps"), template.format("holds"), "r.md")
    assert effect["kind"] == "cosmetic", effect


def test_a_truncated_section_list_says_it_was_truncated():
    """Four names read as the whole answer whether or not four was all there was, and
    the region that got cut is as likely as any to be the one worth re-running for."""
    def doc(marker):
        return "".join(
            "job{}:\n  runs-on: {}\n".format(n, marker) for n in range(doctor.MAX_EFFECT_SECTIONS + 3)
        )
    effect = doctor.owned_effect(doc("old"), doc("new"), "w.yml")
    assert len(effect["sections"]) == doctor.MAX_EFFECT_SECTIONS, effect
    assert effect["more"] == 3, effect
    assert "and 3 more" in doctor._drift_detail("w.yml", effect)


def test_a_complete_section_list_does_not_claim_there_is_more():
    """The positive control for the line above: a summary that always appended "and N
    more" would pass the truncation test and lie about every smaller change."""
    effect = doctor.owned_effect("a:\n  b: 1\n", "a:\n  b: 2\n", "w.yml")
    assert effect["more"] == 0, effect
    assert "more" not in doctor._drift_detail("w.yml", effect)


def test_a_cosmetically_drifted_owned_file_says_so_instead(tmp_path):
    """The paired negative for the test above, on the same mechanism: a difference
    that changes no behaviour must not read like one that does."""
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    target = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    target.write_text("# a note somebody added\n" + target.read_text(encoding="utf-8"),
                      encoding="utf-8")
    finding = {f["path"]: f for f in doctor.owned_drift(
        tmp_path, _config(), plugin_root=REPO_ROOT)}[".github/workflows/oss-changelog.yml"]
    assert finding["state"] == "drifted", finding
    assert "nothing it does changes" in finding["detail"], finding["detail"]
    assert "what it does" not in finding["detail"], finding["detail"]
