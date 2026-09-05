"""#774: the wider half of #766, left unbuilt when the narrower half landed in
#770. A refused lane pattern (`--lane '/etc/passwd'`, `--lane 'a|b'`, or any
other `_lane_pattern_problem` refusal) still rendered `overlap : none` --
byte-for-byte the same receipt line a real, checked, disjoint pair prints --
because the refused side never contributed to the comparison at all, and an
empty contribution reads identically to an empty *result*. Measured by the
maintainer at `18df56f`, with a positive control proving the collision path
is untouched (the issue's own three calls).

`#766` named this itself: "an overlap of `none` computed from a pattern that
matched nothing never renders as an overlap of `none` computed from two real,
disjoint file sets. Those are two different answers today and the receipt
prints one word for both." `lane_report` now carries a third `overlap_state`
-- `resolved` / `n/a` / `could-not-check` -- alongside `overlap` itself, and
the receipt's own `overlap :` and `verdict :` lines say `COULD NOT CHECK`
rather than folding into `none` or `available`. `available` is the dangerous
direction in `--derive-held` mode: a real collision hiding behind an
unresolved pattern must never read as clear to dispatch on.

Every case below that proves the unresolved state fires also has a sibling
proving an ordinary, fully-resolved comparison (both disjoint and colliding)
still renders exactly as it always has -- a `could-not-check` that fires on
everything would pass half of this file.
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
    (root / "scripts" / "a.py").write_text("x\n")
    (root / "scripts" / "b.py").write_text("x\n")


def _derived_held(held):
    return {
        "state": "resolved",
        "held": held,
        "lanes": {"stale_pruned": []},
        "detail": "",
    }


# --- _refused_patterns: the primitive #774 is built on ---------------------------


def test_refused_patterns_is_empty_for_none():
    assert lane_setup._refused_patterns(None) == []


def test_refused_patterns_names_only_refused_entries(tmp_path):
    _make_tree(tmp_path)
    resolved = lane_setup.resolve_lane(
        tmp_path, ["scripts/a.py", "/etc/passwd", "scripts/no-such-glob-*.zzz"]
    )
    assert lane_setup._refused_patterns(resolved) == ["/etc/passwd"]


def test_refused_patterns_control_a_glob_no_match_is_not_refused(tmp_path):
    """Control: a well-formed pattern that matched nothing on disk is a real,
    checked fact -- #774 must not treat it the same as a pattern that was
    never read as a pattern at all."""
    _make_tree(tmp_path)
    resolved = lane_setup.resolve_lane(tmp_path, ["scripts/no-such-glob-*.zzz"])
    assert resolved["patterns"][0]["state"] == "glob-no-match"
    assert lane_setup._refused_patterns(resolved) == []


# --- lane_report, plain --lane/--against mode: could-not-check on either side ---


def test_lane_report_overlap_state_could_not_check_for_a_refused_lane_pattern(tmp_path):
    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["/etc/passwd"], ["scripts/a.py"])
    assert report["overlap"] is None
    assert report["overlap_state"] == "could-not-check"
    assert "1 of 1 lane pattern(s) refused" in report["overlap_detail"]


def test_lane_report_overlap_state_could_not_check_for_a_refused_against_pattern(
    tmp_path,
):
    """Symmetric: a refused pattern on the --against side is exactly as
    unchecked as one on --lane, and must read the same way."""
    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["scripts/a.py"], ["/etc/passwd"])
    assert report["overlap"] is None
    assert report["overlap_state"] == "could-not-check"
    assert "1 of 1 against pattern(s) refused" in report["overlap_detail"]


def test_lane_report_overlap_state_resolved_for_a_genuine_disjoint_pair(tmp_path):
    """Control: two real, disjoint file sets must still render `resolved`,
    with `overlap == []` -- #774 must not turn a genuinely clean comparison
    into `could-not-check`."""
    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["scripts/a.py"], ["scripts/b.py"])
    assert report["overlap"] == []
    assert report["overlap_state"] == "resolved"
    assert report["overlap_detail"] == ""


def test_lane_report_overlap_state_resolved_for_a_genuine_collision(tmp_path):
    """Control: a real collision must still be reported, unaffected."""
    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["scripts/a.py"], ["scripts/a.py"])
    assert report["overlap"] == ["scripts/a.py"]
    assert report["overlap_state"] == "resolved"


def test_lane_report_overlap_state_n_a_when_only_one_side_is_given(tmp_path):
    """Control: the pre-existing "only one side given" case is untouched --
    it is not the same claim as `could-not-check`, and must keep its own
    state."""
    _make_tree(tmp_path)
    report = lane_setup.lane_report(tmp_path, ["scripts/a.py"], None)
    assert report["overlap"] is None
    assert report["overlap_state"] == "n/a"


# --- lane_report, --derive-held mode: could-not-check must never read `available`


def test_lane_report_availability_could_not_check_for_a_refused_lane_pattern(tmp_path):
    """#774's more dangerous case: a refused lane pattern in --derive-held
    mode must not read as `available` -- that is exactly a real collision
    hiding behind an unchecked pattern rendering as clear to dispatch on."""
    _make_tree(tmp_path)
    derived_held = _derived_held({"scripts/a.py": ["PR #9"]})
    report = lane_setup.lane_report(
        tmp_path, ["/etc/passwd"], None, derived_held=derived_held
    )
    assert report["overlap_state"] == "could-not-check"
    assert report["availability"]["state"] == "could-not-check"
    assert report["availability"]["state"] not in ("available", "blocked")


def test_lane_report_availability_available_for_a_genuinely_disjoint_lane(tmp_path):
    """Control: an ordinary, fully-resolved lane must still read `available`."""
    _make_tree(tmp_path)
    derived_held = _derived_held({"scripts/b.py": ["PR #9"]})
    report = lane_setup.lane_report(
        tmp_path, ["scripts/a.py"], None, derived_held=derived_held
    )
    assert report["overlap_state"] == "resolved"
    assert report["availability"]["state"] == "available"


def test_lane_report_availability_blocked_still_fires_with_a_real_collision(tmp_path):
    """Control: a real collision with the derived held set must still read
    `blocked`, unaffected by #774."""
    _make_tree(tmp_path)
    derived_held = _derived_held({"scripts/a.py": ["PR #9"]})
    report = lane_setup.lane_report(
        tmp_path, ["scripts/a.py"], None, derived_held=derived_held
    )
    assert report["overlap_state"] == "resolved"
    assert report["availability"]["state"] == "blocked"


def test_lane_report_availability_could_not_check_for_a_refused_held_file(tmp_path):
    """Audit round: a held FILE (from an open pull request's own file list, or
    a sibling lane's own recorded files) can trip `_lane_pattern_problem`
    exactly the way a hand-typed --lane/--against pattern can -- a real
    git-tracked path containing '|' is legal on the filesystems this loop
    runs on. Checking only the --lane side's own refused patterns left a
    refused held file silently dropping out of the comparison, so a lane
    with no real collision against its *resolvable* held files still read
    `available` while one of the files it was meant to be checked against
    was never actually compared -- the same dangerous direction #774's
    `a_refused` handling exists to close, on the other side of the
    comparison."""
    _make_tree(tmp_path)
    derived_held = _derived_held({"scripts/weird|file.py": ["PR #9"]})
    report = lane_setup.lane_report(
        tmp_path, ["scripts/a.py"], None, derived_held=derived_held
    )
    assert report["overlap_state"] == "could-not-check"
    assert report["availability"]["state"] == "could-not-check"
    assert report["availability"]["state"] not in ("available", "blocked")
    assert "1 of 1 against pattern(s) refused" in report["availability"]["detail"]


def test_lane_report_availability_available_when_the_held_set_is_fully_clean(tmp_path):
    """Must-fire control: a held set with no refused entries at all, and no
    real collision, must still read `available` -- #774's fix for the held
    side must not turn a genuinely clean derivation into `could-not-check`."""
    _make_tree(tmp_path)
    derived_held = _derived_held({"scripts/b.py": ["PR #9"]})
    report = lane_setup.lane_report(
        tmp_path, ["scripts/a.py"], None, derived_held=derived_held
    )
    assert report["overlap_state"] == "resolved"
    assert report["availability"]["state"] == "available"


# --- receipt: the answer line itself, the issue's own measurement ----------------


def _minimal_payload(
    repo, lane_patterns, against_patterns=None, derived_held=None, issue=774
):
    return {
        "issue": issue,
        "repo": str(repo),
        "config": {"state": "ok", "problems": []},
        "base": {
            "state": "resolved",
            "remote": "origin",
            "ref": "origin/main",
            "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "detail": "",
        },
        "branch": {
            "state": "resolved",
            "pattern": "fix/{issue}",
            "name": "fix/{0}".format(issue),
            "detail": "",
            "exists_local": False,
            "exists_remote": False,
        },
        "worktree": {
            "state": "resolved",
            "root": "/tmp",
            "path": "/tmp/{0}".format(issue),
            "detail": "",
            "exists": False,
        },
        "board": {"state": "ok", "lines": []},
        "lanes": None,
        "lane": lane_setup.lane_report(
            repo, lane_patterns, against_patterns, derived_held=derived_held
        ),
    }


def test_receipt_says_could_not_check_rather_than_none_for_a_refused_pattern(tmp_path):
    """The issue's own suggested shape: `overlap : COULD NOT CHECK -- ...`,
    never the bare word `none` standing in for "this was never compared"."""
    _make_tree(tmp_path)
    payload = _minimal_payload(tmp_path, ["/etc/passwd"], ["scripts/a.py"])
    text = lane_setup.receipt(payload)
    assert "overlap : COULD NOT CHECK" in text
    assert "overlap : none" not in text


def test_receipt_still_says_none_for_a_genuine_disjoint_pair(tmp_path):
    """Control: the ordinary, checked-disjoint case must still print `none`."""
    _make_tree(tmp_path)
    payload = _minimal_payload(tmp_path, ["scripts/a.py"], ["scripts/b.py"])
    text = lane_setup.receipt(payload)
    assert "overlap : none" in text
    assert "COULD NOT CHECK" not in text


def test_receipt_verdict_says_could_not_check_for_a_refused_lane_pattern_in_derive_held_mode(
    tmp_path,
):
    _make_tree(tmp_path)
    derived_held = _derived_held({"scripts/a.py": ["PR #9"]})
    payload = _minimal_payload(
        tmp_path, ["/etc/passwd"], None, derived_held=derived_held
    )
    text = lane_setup.receipt(payload)
    assert "verdict : COULD NOT CHECK" in text
    assert "verdict : available" not in text


def test_receipt_verdict_still_says_available_for_a_genuinely_disjoint_lane(tmp_path):
    """Control: the ordinary, fully-resolved case must still print `available`."""
    _make_tree(tmp_path)
    derived_held = _derived_held({"scripts/b.py": ["PR #9"]})
    payload = _minimal_payload(
        tmp_path, ["scripts/a.py"], None, derived_held=derived_held
    )
    text = lane_setup.receipt(payload)
    assert "verdict : available" in text
    assert "COULD NOT CHECK" not in text


# --- CLI: end to end, the issue's own three calls (--against mode) --------------


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
        [sys.executable, str(SCRIPT), "774", "--repo", str(tmp_path), "--json"]
        + list(extra_args),
        subject="the JSON payload lane_setup.py emits for a refused --lane pattern (#774)",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_json_carries_overlap_state_could_not_check_for_a_refused_pattern(tmp_path):
    """The issue's own first two calls (an absolute-path refusal, and #766's
    alternation refusal) both land here."""
    _make_tree(tmp_path)
    done = _cli(tmp_path, "--lane", "/etc/passwd", "--against", "scripts/a.py")
    payload = json.loads(done.stdout)
    assert payload["lane"]["overlap"] is None
    assert payload["lane"]["overlap_state"] == "could-not-check"


def test_cli_json_carries_overlap_state_resolved_for_a_real_collision(tmp_path):
    """The issue's own positive control: a real lane, a real collision."""
    _make_tree(tmp_path)
    done = _cli(tmp_path, "--lane", "scripts/a.py", "--against", "scripts/a.py")
    payload = json.loads(done.stdout)
    assert payload["lane"]["overlap"] == ["scripts/a.py"]
    assert payload["lane"]["overlap_state"] == "resolved"
