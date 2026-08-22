"""#267: a lane an agent implements gets asserted into a brief from a maintainer's
memory of what an issue is about, or from a topic-shaped pattern that does not
intersect visibly with a filename -- two live instances, filed against this
plugin's own dispatch. `fix/247-244`'s lane was `skills/manager/SKILL.md`;
`fix/262-248`'s lane was `commands/*.md`; the second agent's fix correctly
touched `commands/tick.md`, and nothing checked that intersection because a
glob and a path cannot be compared by eye.

The issue's own conclusion: "whatever derives lanes should render them in one
form -- resolved paths -- before any second brief is written." This file pins
that rendering (`resolve_lane`) and the comparison it makes possible
(`lane_overlap`), plus the CLI surface that exposes both from `lane_setup.py`
so a maintainer never eyeballs a glob against a path again.

Every case that asserts overlap fires also has a sibling that asserts it does
not fire on a disjoint pair, in the same fixture -- a check that always
reports "no overlap" would pass half of this file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _make_tree(root):
    (root / "commands").mkdir()
    (root / "commands" / "tick.md").write_text("tick\n")
    (root / "commands" / "release.md").write_text("release\n")
    (root / "skills" / "manager").mkdir(parents=True)
    (root / "skills" / "manager" / "SKILL.md").write_text("skill\n")
    (root / "scripts").mkdir()
    (root / "scripts" / "lane_setup.py").write_text("x\n")


# --- resolve_lane: a literal path and a glob render as the same shape ------------


def test_literal_pattern_resolves_to_itself(tmp_path):
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    result = lane_setup.resolve_lane(tmp_path, ["skills/manager/SKILL.md"])
    assert result["files"] == ["skills/manager/SKILL.md"]
    assert result["patterns"][0]["state"] == "literal"


def test_glob_pattern_expands_to_the_files_it_actually_matches(tmp_path):
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    result = lane_setup.resolve_lane(tmp_path, ["commands/*.md"])
    assert result["files"] == ["commands/release.md", "commands/tick.md"]
    assert result["patterns"][0]["state"] == "glob-resolved"


def test_glob_pattern_matching_nothing_is_its_own_state_not_silently_empty(tmp_path):
    """A glob that matches nothing must not render identically to a glob that
    matched everything and happened to overlap with nothing -- the third state
    this repository keeps needing.
    """
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    result = lane_setup.resolve_lane(tmp_path, ["docs/*.md"])
    assert result["files"] == []
    assert result["patterns"][0]["state"] == "glob-no-match"


def test_traversal_pattern_is_refused_not_silently_dropped(tmp_path):
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    result = lane_setup.resolve_lane(tmp_path, ["../outside.md"])
    assert result["patterns"][0]["state"] == "refused"
    assert result["files"] == []


# --- resolve_lane: a backslash-separated glob must match the same files a
# forward-slash one does -- the literal branch already normalizes separators
# and the glob branch silently did not, so a Windows-typed pattern reported
# glob-no-match against files that plainly exist. -------------------------------


def test_glob_pattern_with_backslash_separators_still_matches(tmp_path):
    """Review finding on #267: the literal branch normalizes `\\` to `/` before
    touching the filesystem and the glob branch passed the raw pattern straight
    to `Path.glob`, which treats a backslash as a literal filename character on
    POSIX -- so `commands\\*.md` silently resolved to zero files while
    `commands/*.md` found two. A silent empty match here is exactly the
    laundered false negative #267 exists to close.
    """
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    forward = lane_setup.resolve_lane(tmp_path, ["commands/*.md"])
    backslash = lane_setup.resolve_lane(tmp_path, ["commands\\*.md"])
    assert backslash["patterns"][0]["state"] == "glob-resolved"
    assert backslash["files"] == forward["files"] == ["commands/release.md", "commands/tick.md"]


# --- _lane_pattern_problem: the absolute-path refusal must not depend on which
# platform's os.path happens to be running -- posixpath.isabs("/etc/passwd") is
# True and ntpath.isabs("/etc/passwd") is False, so a check built on
# `os.path.isabs` alone refuses a POSIX-rooted pattern on Linux/macOS and lets
# the identical string through, unrefused, on Windows. -----------------------


def test_posix_rooted_pattern_is_refused_regardless_of_os_path_isabs(tmp_path, monkeypatch):
    """Review finding on #267: simulate the platform this repository's own CI
    tests -- Windows' ntpath.isabs, which answers False for a driveless
    POSIX-style root -- and confirm the refusal still fires. If the refusal
    were still built on `os.path.isabs`, this would pass on Windows and fail
    here, one call away from the containment gap the audit measured directly
    with ntpath/posixpath.
    """
    import lane_setup  # noqa: E402
    import ntpath

    assert ntpath.isabs("/etc/passwd") is False  # the platform fact that made this reachable
    monkeypatch.setattr(lane_setup.os, "path", ntpath)
    try:
        problem = lane_setup._lane_pattern_problem("/etc/passwd")
    finally:
        monkeypatch.undo()
    assert problem is not None
    assert "not relative" in problem


def test_ordinary_relative_pattern_is_still_accepted(tmp_path):
    """Control for the case above: an ordinary relative lane pattern must not
    be refused by tightening the absolute-path check.
    """
    import lane_setup  # noqa: E402

    assert lane_setup._lane_pattern_problem("scripts/lane_setup.py") is None
    assert lane_setup._lane_pattern_problem("commands/*.md") is None


# --- lane_overlap: the actual disjointness check, both directions ----------------


def test_lane_overlap_fires_when_a_glob_and_a_path_name_the_same_file(tmp_path):
    """The #267 fixture: one brief's lane is a glob, the other's is a literal
    path, and the file both actually touch is the intersection -- this is the
    check that would have caught fix/247-244 and fix/262-248 colliding on
    commands/tick.md.
    """
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    lane_a = lane_setup.resolve_lane(tmp_path, ["skills/manager/SKILL.md", "commands/tick.md"])
    lane_b = lane_setup.resolve_lane(tmp_path, ["commands/*.md"])
    overlap = lane_setup.lane_overlap(lane_a["files"], lane_b["files"])
    assert overlap == ["commands/tick.md"]


def test_lane_overlap_is_empty_for_genuinely_disjoint_lanes(tmp_path):
    """Control for the case above: two lanes touching different files must not
    report an overlap that is not there.
    """
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    lane_a = lane_setup.resolve_lane(tmp_path, ["skills/manager/SKILL.md"])
    lane_b = lane_setup.resolve_lane(tmp_path, ["scripts/lane_setup.py"])
    overlap = lane_setup.lane_overlap(lane_a["files"], lane_b["files"])
    assert overlap == []


# --- lane_report: the payload shape compute()/main() expose -----------------------


def test_lane_report_is_none_when_no_lane_was_asked_for(tmp_path):
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    assert lane_setup.lane_report(tmp_path, [], []) is None


def test_lane_report_carries_overlap_only_when_both_sides_are_given(tmp_path):
    import lane_setup  # noqa: E402

    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["skills/manager/SKILL.md"], None)
    assert report["against"] is None
    assert report["overlap"] is None

    report = lane_setup.lane_report(
        tmp_path, ["skills/manager/SKILL.md", "commands/tick.md"], ["commands/*.md"]
    )
    assert report["overlap"] == ["commands/tick.md"]


# --- CLI: --lane / --against reach the JSON payload -------------------------------


def _cli(tmp_path, *extra_args):
    (tmp_path / ".oss.json").write_text(
        json.dumps(
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
    return subprocess.run(
        [sys.executable, str(SCRIPT), "267", "--repo", str(tmp_path), "--json"] + list(extra_args),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_lane_and_against_reach_the_json_payload(tmp_path):
    _make_tree(tmp_path)
    done = _cli(
        tmp_path,
        "--lane",
        "skills/manager/SKILL.md",
        "--lane",
        "commands/tick.md",
        "--against",
        "commands/*.md",
    )
    payload = json.loads(done.stdout)
    assert payload["lane"]["overlap"] == ["commands/tick.md"]


def test_cli_with_no_lane_flags_reports_lane_as_none(tmp_path):
    """Control: nothing asked for, nothing rendered -- an absent flag must not
    read as a checked, empty lane.
    """
    _make_tree(tmp_path)
    done = _cli(tmp_path)
    payload = json.loads(done.stdout)
    assert payload["lane"] is None
