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
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import spawn_guard  # noqa: E402


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
# os.path answers True/False for a given string -- posixpath.isabs("/etc/passwd")
# and ntpath.isabs("/etc/passwd") have disagreed with EACH OTHER (True vs False),
# and ntpath.isabs alone has disagreed with ITSELF across CPython versions on the
# identical input: True on 3.9-3.12 (observed on CI, #435 -- a 3.9.25 run failed
# an earlier version of this test that asserted the opposite), False on 3.13
# (observed locally). A check built on `os.path.isabs` is therefore not safe on
# any single platform either, once the interpreter axis is in play -- so the
# fixture below does not assert a real ntpath/posixpath answer at all, which
# would only ever be true for the interpreter running the suite at that moment.
# It fabricates a path module whose `isabs` always answers False and confirms
# `_lane_pattern_problem`'s own answer does not move when that stand-in is
# substituted for the real one -- deterministic on every CPython version,
# because there is no live stdlib fact left to change under it. -----------------


def test_absolute_pattern_refusal_does_not_depend_on_os_path_isabs(tmp_path, monkeypatch):
    """Review finding on #267, corrected after #435: the fix (a normalized
    string test replacing `os.path.isabs`) was right; the first version of this
    test pinned a *specific* `ntpath.isabs` answer as though it were a platform
    fact, and CPython changed that answer between the interpreters CI gates
    (3.9-3.12) and the one this suite happened to run on locally (3.13) -- so
    the test failed on CI for a reason that had nothing to do with the fix
    under test. This version asserts only that `_lane_pattern_problem` still
    refuses when the underlying path module cannot be trusted to say so,
    without claiming to know what any particular Python version's `ntpath`
    or `posixpath` actually answers.
    """
    import lane_setup  # noqa: E402

    class _NeverAbs:
        """Stands in for "whatever os.path this host aliases might answer" --
        deliberately the least favourable case, since a real isabs() that says
        False for an obviously-rooted string is exactly what made #267's
        containment gap reachable in the first place.
        """

        @staticmethod
        def isabs(path):
            return False

    monkeypatch.setattr(lane_setup.os, "path", _NeverAbs)
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


# --- _lane_pattern_problem: `~` refusal (#898) ------------------------------------
# #898: `_derive_declared_files` (#851) feeds backtick-quoted tokens pulled out of
# an issue's own title and body straight into this guard, so the guard's own
# containment now has to hold against untrusted text, not only a human-typed
# `--lane` value. Home-directory expansion (`~`) was the one spelling of
# "outside the repo" this guard did not refuse in either form -- `~/.ssh/id_rsa`
# came back accepted as a literal file entry. Nothing in `lane_setup.py` calls
# `expanduser` on a lane member today, so this was not a live escape, but the
# guard is defense in depth and should not depend on that staying true forever.


def test_home_directory_pattern_is_refused(tmp_path):
    """Must-fire case: a `~`-leading pattern is refused at the guard itself,
    the same way an absolute or drive-prefixed pattern already is.
    """
    import lane_setup  # noqa: E402

    problem = lane_setup._lane_pattern_problem("~/.ssh/id_rsa")
    assert problem is not None
    assert "~" in problem

    problem_user = lane_setup._lane_pattern_problem("~someuser/x")
    assert problem_user is not None
    assert "~" in problem_user


def test_home_directory_pattern_refused_with_backslashes_too(tmp_path):
    """The same refusal has to hold on the backslash-normalized form, the way
    the absolute-path check above already normalizes `\\` to `/` before
    testing -- a Windows-flavoured `~\\.ssh\\id_rsa` must not slip through
    because the leading `~` is not immediately followed by `/`.
    """
    import lane_setup  # noqa: E402

    problem = lane_setup._lane_pattern_problem("~\\.ssh\\id_rsa")
    assert problem is not None
    assert "~" in problem


def test_tilde_not_at_the_start_is_still_accepted(tmp_path):
    """Control for the case above: `~` only matters as a leading character.
    A pattern that merely contains one elsewhere is not home-directory
    expansion and must not be refused by tightening this check.
    """
    import lane_setup  # noqa: E402

    assert lane_setup._lane_pattern_problem("scripts/a~b.py") is None


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
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), "267", "--repo", str(tmp_path), "--json"] + list(extra_args),
        subject="the JSON payload lane_setup.py emits for this tree",
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
