"""#766: `--lane a|b` is accepted silently as one literal filename, matches no
tracked file, and the receipt annotates it `(literal)` -- the overlap check then
reads `none` for a pattern that was never resolved at all, rather than for two
lanes genuinely checked and found disjoint. A disjointness gate is what decides
whether a second agent is dispatched onto files another lane already holds, so
rendering "could not be read as a pattern" identically to "checked, no overlap"
is exactly this repository's own defect class sitting in the mechanism built to
catch it.

`|` cannot be part of a filename on any platform this runs on in the shape a
maintainer's hand reaches for -- the flag's own metavar is PATTERN, and every
other pattern surface this loop's neighbourhood offers (radar filters, the
jit-context `match` field, `gh-issues` selectors) IS an alternation, which is
why the mistake is likely rather than exotic (the issue's own argument). So a
`|` in a `--lane`/`--against` value is refused before it ever reaches
`Path.glob` or a literal-path comparison, the same shape `_lane_pattern_problem`
already uses for an absolute path or a `..` traversal.

Every case below that asserts the refusal fires also has a sibling asserting an
ordinary pattern -- with no `|` -- still resolves normally in the same
fixture: a refusal that fires on everything would pass half of this file.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import lane_setup  # noqa: E402
import spawn_guard  # noqa: E402


def _make_tree(root):
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "rebuild-tsv.sh").write_text("x\n")
    (root / "scripts" / "common.sh").write_text("x\n")


# --- _lane_pattern_problem: the refusal itself, and its positive control --------


def test_pipe_in_pattern_is_refused():
    problem = lane_setup._lane_pattern_problem(
        "scripts/rebuild-tsv.sh|scripts/common.sh"
    )
    assert problem is not None
    assert "|" in problem
    assert "repeat" in problem.lower() or "--lane" in problem


def test_ordinary_pattern_with_no_pipe_is_still_accepted():
    """Control: the new refusal must not widen to swallow an ordinary pattern."""
    assert lane_setup._lane_pattern_problem("scripts/common.sh") is None
    assert lane_setup._lane_pattern_problem("commands/*.md") is None


# --- resolve_lane: the alternation never renders as a matched, literal file -----


def test_resolve_lane_refuses_a_pipe_alternation_rather_than_treating_it_as_literal(
    tmp_path,
):
    """The issue's own reproduction: a `|`-joined pattern used to resolve as one
    literal path (`entries[0]["state"] == "literal"`) that matched nothing on
    disk and contributed nothing to `files` -- silently, with no signal that the
    pattern was never actually read as two files.
    """
    _make_tree(tmp_path)
    result = lane_setup.resolve_lane(
        tmp_path, ["scripts/rebuild-tsv.sh|scripts/common.sh"]
    )
    assert result["patterns"][0]["state"] == "refused"
    assert result["files"] == []


def test_resolve_lane_still_resolves_the_same_two_files_given_separately(tmp_path):
    """Control for the case above: the documented, repeatable-flag form -- one
    call per file -- must keep resolving exactly as it always has.
    """
    _make_tree(tmp_path)
    result = lane_setup.resolve_lane(
        tmp_path, ["scripts/rebuild-tsv.sh", "scripts/common.sh"]
    )
    assert result["files"] == ["scripts/common.sh", "scripts/rebuild-tsv.sh"]
    assert all(entry["state"] == "literal" for entry in result["patterns"])


def test_a_pipe_alternation_never_fabricates_an_overlap(tmp_path):
    """The issue's own harm, end to end: a `|`-joined --lane checked against a
    single real --against file must not render `overlap: none` as though a real
    disjointness check had run -- the refused side contributes no files, so
    `lane_overlap` has nothing to compare, and the caller is told that plainly.

    #774: `overlap` itself is `None` here rather than `[]` -- an empty list is
    what a real, checked, disjoint comparison also produces, and the wider
    half of this issue (left unbuilt when the narrower half landed) gives the
    unresolved case its own `overlap_state` rather than folding it into the
    same value.
    """
    _make_tree(tmp_path)
    report = lane_setup.lane_report(
        tmp_path,
        ["scripts/rebuild-tsv.sh|scripts/common.sh"],
        ["scripts/common.sh"],
    )
    assert report["lane"]["patterns"][0]["state"] == "refused"
    assert report["overlap"] is None
    assert report["overlap_state"] == "could-not-check"
    assert report["lane"]["files"] == []


# --- CLI: the refusal reaches the JSON payload, and the receipt names it --------


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
        [sys.executable, str(SCRIPT), "766", "--repo", str(tmp_path), "--json"]
        + list(extra_args),
        subject="the JSON payload lane_setup.py emits for a --lane containing '|'",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_reports_the_pipe_pattern_as_refused_not_as_a_clean_overlap(tmp_path):
    _make_tree(tmp_path)
    done = _cli(
        tmp_path,
        "--lane",
        "scripts/rebuild-tsv.sh|scripts/common.sh",
        "--against",
        "scripts/common.sh",
    )
    payload = json.loads(done.stdout)
    assert payload["lane"]["lane"]["patterns"][0]["state"] == "refused"
    # #774: never the same `[]` a real, checked, disjoint comparison produces.
    assert payload["lane"]["overlap"] is None
    assert payload["lane"]["overlap_state"] == "could-not-check"


def test_cli_reports_the_true_overlap_for_the_documented_repeated_form(tmp_path):
    """Control: the documented shape -- one --lane per file -- must keep
    reporting the real collision, unaffected by the new refusal."""
    _make_tree(tmp_path)
    done = _cli(
        tmp_path,
        "--lane",
        "scripts/rebuild-tsv.sh",
        "--lane",
        "scripts/common.sh",
        "--against",
        "scripts/common.sh",
    )
    payload = json.loads(done.stdout)
    assert payload["lane"]["overlap"] == ["scripts/common.sh"]
