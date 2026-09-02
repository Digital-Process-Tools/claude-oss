"""#809: three false-negative shapes in the disjointness check, all rendering
`available` where the honest answer is BLOCKED or a distinct "resolved to
nothing" state.

1. A bare directory literal (`presets/gitlab/`) never expanded, so it can
   never intersect a held file inside it even though the equivalent glob
   (`presets/gitlab/*.py`) correctly reports BLOCKED.
2. A glob (or now, a directory) resolving to zero files reads `available`,
   sharing a verdict with a lane genuinely checked and found disjoint.
3. A comma-separated multi-pattern lane, given as one `--lane` value, was
   never split into members at all -- the whole string was compared as one
   literal path, so `overlap: none` even when one member is plainly held.

Every case below pairs the fix with a positive control: a case that must
still read `available`/`BLOCKED` exactly as before, so a guard that fires on
everything would pass half of this file.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


def _make_tree(root):
    (root / "presets" / "gitlab").mkdir(parents=True)
    (root / "presets" / "gitlab" / "job.py").write_text("x\n")
    (root / "presets" / "gitlab" / "api.py").write_text("x\n")
    (root / "presets" / "empty_dir").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "lane_setup.py").write_text("x\n")
    (root / "commands").mkdir(parents=True)
    (root / "commands" / "tick.md").write_text("x\n")
    (root / "skills" / "manager" / "phases").mkdir(parents=True)
    (root / "skills" / "manager" / "phases" / "dispatch.md").write_text("x\n")


def _derived_held(held):
    return {"state": "resolved", "held": held, "lanes": {"stale_pruned": []}, "detail": ""}


# --- 1. bare directory literal expands ------------------------------------------


def test_bare_directory_literal_expands_to_files_under_it(tmp_path):
    _make_tree(tmp_path)
    resolved = lane_setup.resolve_lane(tmp_path, ["presets/gitlab/"])
    entry = resolved["patterns"][0]
    assert entry["state"] == "dir-expanded"
    assert entry["files"] == ["presets/gitlab/api.py", "presets/gitlab/job.py"]
    assert resolved["files"] == ["presets/gitlab/api.py", "presets/gitlab/job.py"]


def test_bare_directory_literal_without_trailing_slash_also_expands(tmp_path):
    _make_tree(tmp_path)
    resolved = lane_setup.resolve_lane(tmp_path, ["presets/gitlab"])
    assert resolved["patterns"][0]["state"] == "dir-expanded"
    assert resolved["files"] == ["presets/gitlab/api.py", "presets/gitlab/job.py"]


def test_directory_lane_now_reports_blocked_like_the_equivalent_glob(tmp_path):
    """The issue's own repro: a bare directory and the equivalent glob must
    render the identical verdict against the same held set."""
    _make_tree(tmp_path)
    held = {"presets/gitlab/job.py": ["PR #2145"]}
    dir_report = lane_setup.lane_report(
        tmp_path, ["presets/gitlab/"], [], _derived_held(held)
    )
    glob_report = lane_setup.lane_report(
        tmp_path, ["presets/gitlab/*.py"], [], _derived_held(held)
    )
    assert dir_report["availability"]["state"] == "blocked"
    assert glob_report["availability"]["state"] == "blocked"
    assert dir_report["availability"]["files"] == glob_report["availability"]["files"]


def test_control_a_literal_file_path_is_unaffected(tmp_path):
    """Control: an ordinary literal file (not a directory) still resolves the
    old way -- not checked against the tree, may not exist yet."""
    _make_tree(tmp_path)
    resolved = lane_setup.resolve_lane(tmp_path, ["changelog.d/809.fixed.md"])
    assert resolved["patterns"][0]["state"] == "literal"
    assert resolved["files"] == ["changelog.d/809.fixed.md"]


def test_control_a_glob_still_glob_resolves(tmp_path):
    """Control: a real glob pattern is unaffected by the directory-expansion path."""
    _make_tree(tmp_path)
    resolved = lane_setup.resolve_lane(tmp_path, ["presets/gitlab/*.py"])
    assert resolved["patterns"][0]["state"] == "glob-resolved"


# --- 2. a lane resolving to zero files gets its own state -----------------------


def test_glob_matching_nothing_does_not_read_available(tmp_path):
    _make_tree(tmp_path)
    held = {}
    report = lane_setup.lane_report(
        tmp_path, ["formatters/**/*.py"], [], _derived_held(held)
    )
    assert report["availability"]["state"] != "available"
    assert report["availability"]["state"] == "resolved-to-nothing"


def test_empty_directory_also_reads_resolved_to_nothing(tmp_path):
    _make_tree(tmp_path)
    held = {}
    report = lane_setup.lane_report(
        tmp_path, ["presets/empty_dir/"], [], _derived_held(held)
    )
    assert report["availability"]["state"] == "resolved-to-nothing"


def test_control_a_real_disjoint_lane_still_reads_available(tmp_path):
    """Control: a lane that genuinely resolves to real files and does not
    collide with the held set must still read `available`."""
    _make_tree(tmp_path)
    held = {"presets/gitlab/job.py": ["PR #2145"]}
    report = lane_setup.lane_report(
        tmp_path, ["commands/tick.md"], [], _derived_held(held)
    )
    assert report["availability"]["state"] == "available"


def test_control_a_real_blocked_lane_still_reads_blocked(tmp_path):
    """Control: a lane that genuinely collides still reads BLOCKED, not
    swallowed by the new resolved-to-nothing state."""
    _make_tree(tmp_path)
    held = {"presets/gitlab/job.py": ["PR #2145"]}
    report = lane_setup.lane_report(
        tmp_path, ["presets/gitlab/*.py"], [], _derived_held(held)
    )
    assert report["availability"]["state"] == "blocked"


# --- 3. a comma-separated multi-pattern lane resolves each member independently -


def test_comma_separated_lane_resolves_each_member_independently():
    """The issue's own repro, reproduced without a filesystem: three files
    named in one comma-joined --lane value must overlap the same way three
    repeated --lane flags do."""
    resolved_comma = lane_setup.resolve_lane(
        REPO_ROOT,
        ["commands/tick.md,skills/manager/phases/dispatch.md,scripts/lane_setup.py"],
    )
    resolved_repeated = lane_setup.resolve_lane(
        REPO_ROOT,
        ["commands/tick.md", "skills/manager/phases/dispatch.md", "scripts/lane_setup.py"],
    )
    assert resolved_comma["files"] == resolved_repeated["files"]
    assert "scripts/lane_setup.py" in resolved_comma["files"]


def test_comma_separated_lane_report_overlaps_like_repeated_flags():
    against = lane_setup.resolve_lane(REPO_ROOT, ["scripts/lane_setup.py"])
    report = lane_setup.lane_report(
        REPO_ROOT,
        ["commands/tick.md,skills/manager/phases/dispatch.md,scripts/lane_setup.py"],
        ["scripts/lane_setup.py"],
    )
    assert report["overlap"] == ["scripts/lane_setup.py"]


def test_one_non_matching_comma_member_does_not_collapse_the_whole_lane(tmp_path):
    """The issue's third instance: adding a second, non-matching pattern to a
    comma list used to remove the first pattern's real matches entirely."""
    _make_tree(tmp_path)
    single = lane_setup.resolve_lane(tmp_path, ["presets/gitlab/*.py"])
    combined = lane_setup.resolve_lane(
        tmp_path, ["presets/gitlab/*.py,formatters/**/*.py"]
    )
    assert combined["files"] == single["files"]
    states = [e["state"] for e in combined["patterns"]]
    assert "glob-resolved" in states
    assert "glob-no-match" in states


def test_control_a_pattern_with_no_comma_is_unaffected(tmp_path):
    """Control: an ordinary single pattern with no comma resolves exactly as
    it did before this fix."""
    _make_tree(tmp_path)
    resolved = lane_setup.resolve_lane(tmp_path, ["presets/gitlab/*.py"])
    assert len(resolved["patterns"]) == 1
    assert resolved["patterns"][0]["pattern"] == "presets/gitlab/*.py"


# --- plain --against mode also distinguishes resolved-to-nothing from a real disjoint pair ---


def test_plain_against_mode_glob_no_match_reports_resolved_to_nothing(tmp_path):
    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["formatters/**/*.py"], ["scripts/lane_setup.py"])
    assert report["overlap_state"] == "resolved-to-nothing"


def test_control_plain_against_mode_real_disjoint_pair_still_reads_resolved(tmp_path):
    """Control: an ordinary, well-formed, genuinely disjoint pair in plain
    --against mode is unaffected by the new state."""
    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["commands/tick.md"], ["scripts/lane_setup.py"])
    assert report["overlap_state"] == "resolved"
    assert report["overlap"] == []
