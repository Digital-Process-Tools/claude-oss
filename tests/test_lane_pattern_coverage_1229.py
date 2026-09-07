"""#1229: `.oss.json`'s `labels.lane_patterns` claims disjointness -- see
`docs/pick-the-work.md` -- and nothing derives whether it actually holds for a
given repo. `oss_config.py` validates only the shape (an object mapping a lane
label to a list of globs, or null); it never resolves a pattern against the
tree.

Per the maintainer's own ruling on this issue (see the tracker comments):
overlap between two lanes is a REFACTORING SIGNAL ("a file resolving into two
lanes means the file is doing two jobs"), not a dispatch gate -- git already
catches the merge-conflict case a disjointness gate would target, and misses
the one that costs real time (a clean merge with semantic interaction). So
this module reports; it does not, and must not be read to, protect dispatch.

Three states, and the third is load-bearing, per the issue's own three-state
proposal:

    ok                 lane_patterns declared; every pattern resolves to at
                        least one file; no two lanes claim the same path
    finding            a pattern matches nothing on disk, a pattern is
                        malformed (refused), or two lanes overlap -- all named
    not-configured      labels.lane_patterns is null/absent/empty -- the
                        ordinary state for a repo that has not adopted the
                        convention, and must never render as "ok" (a check
                        that never ran must not look like one that found
                        nothing)

Every "must not fire" case here (disjoint lanes; a live literal pattern for a
file not yet created) is paired with a "must fire" case in the same fixture,
per CLAUDE.md's own rule that a negative assertion needs a positive control.

Resolution goes through `select_issues_overlap.resolve_lane` -- the identical
function `select_issues.py`'s own held-lane collision check uses -- never a
hand-rolled prefix match that could disagree with it (the issue's own explicit
requirement).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_pattern_coverage  # noqa: E402


def _touch(repo, *rels):
    for rel in rels:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def test_not_configured_when_lane_patterns_is_none(tmp_path):
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, None)
    assert result["state"] == "not-configured"


def test_not_configured_when_lane_patterns_is_empty_dict(tmp_path):
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, {})
    assert result["state"] == "not-configured"


def test_disjoint_lanes_report_ok_the_must_not_fire_control(tmp_path):
    _touch(tmp_path, "a/one.py", "b/two.py")
    lane_patterns = {"lane-a": ["a/one.py"], "lane-b": ["b/two.py"]}
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, lane_patterns)
    assert result["state"] == "ok"
    assert result["overlaps"] == []
    assert result["dead_patterns"] == []
    assert result["refused"] == []


def test_two_lanes_claiming_the_same_file_is_a_finding_the_must_fire_case(tmp_path):
    _touch(tmp_path, "shared.py")
    lane_patterns = {"lane-a": ["shared.py"], "lane-b": ["shared.py"]}
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, lane_patterns)
    assert result["state"] == "finding"
    assert result["overlaps"] == [("shared.py", ["lane-a", "lane-b"])]


def test_glob_matching_nothing_is_a_dead_pattern_finding(tmp_path):
    _touch(tmp_path, "a/one.py")
    lane_patterns = {"lane-a": ["a/one.py"], "lane-b": ["scripts/gone_*.py"]}
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, lane_patterns)
    assert result["state"] == "finding"
    assert ("lane-b", "scripts/gone_*.py") in result["dead_patterns"]


def test_a_literal_pattern_for_a_not_yet_created_file_is_not_a_dead_pattern(tmp_path):
    """A literal (non-glob, non-directory) pattern is asserted, not checked --
    the file may not exist yet (a changelog fragment about to be created).
    `resolve_lane` already draws this line; this pins that the coverage
    report inherits it rather than re-flagging every literal as dead."""
    lane_patterns = {"lane-a": ["changelog.d/1229.added.md"]}
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, lane_patterns)
    assert result["state"] == "ok"
    assert result["dead_patterns"] == []


def test_malformed_pattern_is_reported_refused_not_silently_dropped(tmp_path):
    lane_patterns = {"lane-a": ["/etc/passwd"]}
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, lane_patterns)
    assert result["state"] == "finding"
    assert result["refused"] and result["refused"][0][0] == "lane-a"


def test_uncovered_count_is_scoped_to_directories_a_lane_already_touches(tmp_path):
    """#1229's own maintainer ruling: universal coverage must never become a
    failing invariant, and the noise answer in a freshly scaffolded repo (the
    whole tree comes back) is worse than no check. Scope the count to the
    top-level directories some lane already claims, and report only a count,
    never a path list."""
    _touch(tmp_path, "scripts/covered.py", "scripts/leftover.py", "docs/untouched.md")
    lane_patterns = {"lane-a": ["scripts/covered.py"]}
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, lane_patterns)
    # Uncovered count never gates the state on its own (the maintainer's own
    # ruling: universal coverage is not a failing invariant -- lane-other
    # legitimately owns an uncovered file), so this is still "ok" even
    # though a real gap exists in the count below.
    assert result["state"] == "ok"
    # scripts/leftover.py is in-scope (scripts/ is claimed) and uncovered;
    # docs/untouched.md is out of scope (no lane touches docs/) and must not
    # be counted -- that is the noise the scoping rule exists to suppress.
    assert result["uncovered_count"] == 1


def test_uncovered_count_is_none_when_no_lane_resolves_any_file(tmp_path):
    """No scope has been established at all -- not the same as a scope of
    zero uncovered files, so this must not collapse to 0."""
    lane_patterns = {"lane-a": ["scripts/gone_*.py"]}
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, lane_patterns)
    assert result["uncovered_count"] is None


def test_non_dict_lane_patterns_is_a_finding_not_ok(tmp_path):
    """`labels.lane_patterns` failing `oss_config.py`'s own shape check (a
    list instead of an object) must not be misread as clean here -- and
    must not iterate `.items()` on something that has none (the auditor's
    own reproduction: this crashed doctor.py's whole process before the
    fix, an `AttributeError` with no `except` anywhere in the call chain)."""
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, ["not", "a", "dict"])
    assert result["state"] == "finding"
    assert result["malformed"]


def test_non_list_per_lane_value_is_a_finding_not_a_char_by_char_walk(tmp_path):
    """A lane's own value failing shape validation (a bare string instead
    of a list of globs) must not be resolved character-by-character as a
    string of one-letter literal patterns -- each of which `resolve_lane`
    reports clean because a literal is asserted, never checked -- which
    silently renders 'OK' on the same run `check_config` already FAILs for
    this exact field."""
    result = lane_pattern_coverage.lane_pattern_report(tmp_path, {"lane-a": "abc"})
    assert result["state"] == "finding"
    assert result["malformed"] == [("lane-a", "abc")]
    assert result["dead_patterns"] == []
    assert result["refused"] == []
