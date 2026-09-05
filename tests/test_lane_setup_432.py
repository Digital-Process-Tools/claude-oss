"""#432: a lane's local test command narrows to the files an issue names, and a
narrowed command cannot reach a guard whose own file is not in that set -- CI then
reddens on a check the developer never ran. Measured on PR #431: three named test
files, 362 passed locally, and CI failed on `tests/test_gate_state_consumers_328.py`,
which is in none of them, because the diff called `oss_config.scaffolded_changelog_gate`
rather than touching a file that test's name suggests.

The fix is not "run the whole suite always" (declined in the issue: paid by every
lane whether or not it touches one of these) and not "guess from the issue text"
(that is what #431's brief already did, wrong). It is a fact about the repository,
re-derived rather than pasted, the same rule this whole module exists to serve.

`CROSS_CUTTING_GUARDS` enumerates the class -- five guard tests, keyed to *what a
diff does* rather than to a module it renames -- and `guards_for_files` maps a
lane's resolved files (`resolve_lane`'s own canonical form) onto the guard tests a
narrowed run must include. Every "must fire" case here has a "must not fire"
sibling in the same fixture: a lane touching `agents/developer.md` must trip the
content-invariants guard, and a lane touching `tests/test_lane_setup_432.py` itself
must not trip anything, or this file would report every lane as universally guarded
and the mechanism would be indistinguishable from doing nothing.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import lane_setup  # noqa: E402
import spawn_guard  # noqa: E402


# --- sizing: enumerate the class rather than trust the issue's own list ----------


def test_known_guards_is_six_distinct_test_files():
    """#432 asks the sizing question before choosing a mechanism. Five at #432's
    own writing, matching that issue's own list; six as of #1094, which added
    `tests/test_command_references.py` for `skills/manager/SKILL.md` and
    `skills/manager/phases/*.md` -- pinned as a count rather than as a hardcoded
    list of names, so a seventh guard added later fails this assertion instead
    of silently going unenumerated.
    """
    known = lane_setup.known_guards()
    test_paths = [entry["test"] for entry in known]
    assert len(test_paths) == 6
    assert test_paths == sorted(set(test_paths)), (
        "guard list must be deduplicated and sorted"
    )


def test_every_known_guard_test_file_exists_in_this_tree():
    """A guard list is only useful if the paths in it are real. A typo here would
    tell a developer to run a test file that does not exist, silently."""
    for entry in lane_setup.known_guards():
        assert (REPO_ROOT / entry["test"]).is_file(), entry["test"]
        assert entry["triggers"], (
            "a guard with no stated trigger cannot be reached by files"
        )


# --- guards_for_files: must fire, paired with must not fire ----------------------


def test_agent_prose_change_trips_content_invariants_guard():
    hits = lane_setup.guards_for_files(["agents/developer.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_content_invariants.py" in tests_hit


def test_unrelated_test_file_change_trips_no_guard():
    """The must-not-fire sibling: a file outside every declared prefix is not
    silently swept in, or this mechanism would be indistinguishable from "always
    run everything" while claiming to be a targeted list."""
    hits = lane_setup.guards_for_files(["tests/test_lane_setup_432.py"])
    assert hits == []


def test_oss_config_change_trips_gate_state_consumers_guard():
    hits = lane_setup.guards_for_files(["scripts/oss_config.py"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_gate_state_consumers_328.py" in tests_hit


def test_a_script_change_also_trips_unwired_scripts_guard_independently():
    """A file can trip more than one guard for different reasons -- scripts/oss_config.py
    is both a gate-state producer and an ordinary script under scripts/."""
    hits = lane_setup.guards_for_files(["scripts/oss_config.py"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_unwired_scripts_253.py" in tests_hit


def test_a_brand_new_script_still_trips_the_gate_state_guard():
    """Regression: the guard's own real check
    (`tests/test_gate_state_consumers_328.py::unlisted_callers`) scans *every*
    tracked file under `scripts/` and `commands/` for a bare occurrence of the
    gate producer's identifier -- it does not only watch the files that already
    call it. An earlier version of this mapping listed only the four current
    consumer files and reported nothing for a file with no history at all, which
    is exactly the PR #431 shape this issue exists to close: a brand-new
    `scripts/` file that starts calling the gate would trip the real guard on CI
    while this mechanism stayed silent about it."""
    hits = lane_setup.guards_for_files(
        ["scripts/a_file_that_has_never_existed_before.py"]
    )
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_gate_state_consumers_328.py" in tests_hit

    hits = lane_setup.guards_for_files(
        ["commands/a_command_that_has_never_existed_before.md"]
    )
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_gate_state_consumers_328.py" in tests_hit


def test_claude_md_change_trips_currency_guard():
    hits = lane_setup.guards_for_files(["CLAUDE.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_claude_md_currency.py" in tests_hit


def test_pyproject_change_trips_python_floor_guard():
    hits = lane_setup.guards_for_files(["pyproject.toml"])
    tests_hit = [entry["test"] for entry in hits]
    assert "tests/test_python_floor_410.py" in tests_hit


def test_two_files_triggering_the_same_guard_report_it_once():
    hits = lane_setup.guards_for_files(["agents/developer.md", "commands/tick.md"])
    tests_hit = [entry["test"] for entry in hits]
    assert tests_hit.count("tests/test_content_invariants.py") == 1


def test_empty_file_list_trips_no_guard():
    assert lane_setup.guards_for_files([]) == []
    assert lane_setup.guards_for_files(None) == []


# --- integration: lane_report and compute carry guards through ------------------


def test_lane_report_carries_triggered_guards_for_the_lane_side(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "developer.md").write_text("x\n")
    report = lane_setup.lane_report(tmp_path, ["agents/developer.md"], None)
    tests_hit = [entry["test"] for entry in report["guards"]]
    assert "tests/test_content_invariants.py" in tests_hit


def test_lane_report_against_side_does_not_leak_into_triggered_guards(tmp_path):
    """Only the lane a developer is about to touch should trigger a guard --
    not the sibling lane's off-limits files, or a brief would be told to run
    tests for files it must not edit."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "developer.md").write_text("x\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "oss_state.py").write_text("x\n")
    report = lane_setup.lane_report(tmp_path, None, ["scripts/oss_state.py"])
    assert report["guards"] == []


# --- receipt: the CLI surface a developer brief actually reads -----------------


def _cli(tmp_path, *extra_args):
    import json as _json
    import os

    (tmp_path / ".oss.json").write_text(
        _json.dumps(
            {
                "repo": "example/example",
                "default_branch": "main",
                "clone": "/tmp/does-not-matter",
                "worktree_root": "/tmp/does-not-matter-wt",
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": [],
                "changelog_dir": None,
                "docs_targets": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": "/tmp/does-not-matter-state.json",
            }
        )
    )
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return spawn_guard.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_setup.py"),
            "432",
            "--repo",
            str(tmp_path),
        ]
        + list(extra_args),
        subject="the guard set lane_setup.py's receipt names for this lane",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_receipt_shows_the_guard_a_lane_touching_agents_trips(tmp_path):
    """Must fire: a receipt for a lane naming agents/developer.md names the
    content-invariants guard by its test path, in the text a developer reads."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "developer.md").write_text("x\n")
    result = _cli(tmp_path, "--lane", "agents/developer.md")
    assert "tests/test_content_invariants.py" in result.stdout


def test_receipt_says_none_when_the_lane_trips_no_guard(tmp_path):
    """Must not fire: a lane confined to a file outside every declared prefix
    gets an explicit "none" rather than silence a reader could mistake for the
    guard section being absent."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lane_setup_432.py").write_text("x\n")
    result = _cli(tmp_path, "--lane", "tests/test_lane_setup_432.py")
    assert "none of the lane's files match a known cross-cutting guard" in result.stdout
