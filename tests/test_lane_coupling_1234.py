"""#1234: generalizes #1201's manual CLAUDE.md/skill_phases.py binding --
which repo files does each `tests/*.py` file actually reference, and do
those references sit in more than one declared lane (`.oss.json`'s
`labels.lane_patterns`)?

#1201's own incident: PR #1195 (lane-prose) and PR #1194 (lane-release,
mechanically touching `scripts/skill_phases.py` as a side effect of its
own re-baseline convention) collided on adjacent lines of `CLAUDE.md` and
`scripts/skill_phases.py`, and neither lane's own declared pattern named
those two files, so the dispatch-time collision check
(`select_issues.py`/`lane_setup.py --derive-held`) never saw it coming.
#1201's own fix was a *manual* edit -- add the four bookkeeping scripts to
lane-prose's pattern by hand -- plus a hand-written test
(`test_lane_pattern_coverage_1201.py`) asserting exactly those four
scripts are covered by *some* lane. Nothing generalizes that: a future pair
of files sharing the identical "two lanes' tests silently reference the
same file" shape has to be caught by a human noticing a collision again.

This module (`scripts/lane_coupling.py`) is the derivation: parse each
`tests/*.py` file's own literal string constants and top-level import
statements (the static, non-dynamic half -- an f-string or a `Path(...) /
var` join is explicitly out of scope, see `extract_references`'s own
docstring) for repo files that exist on disk, resolve each to the lane(s)
whose `lane_patterns` cover it, and flag any test file whose references
span two or more lanes.

Every "must not fire" case (a test referencing files in one lane only) is
paired with a "must fire" case (a test referencing files in two) in the
same fixture, per this repo's own rule that a negative assertion needs a
positive control.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_coupling  # noqa: E402


def _real_lane_patterns():
    config = json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))
    return config["labels"]["lane_patterns"]


def _scaffold_two_lane_repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts" / "beta.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()


def test_not_configured_when_lane_patterns_absent():
    result = lane_coupling.lane_coupling_report(REPO_ROOT, None)
    assert result["state"] == "not-configured"


def test_non_dict_lane_patterns_is_finding_not_a_crash(tmp_path):
    result = lane_coupling.lane_coupling_report(tmp_path, ["not", "a", "dict"])
    assert result["state"] == "finding"


def test_extract_references_literal_string(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
    source = 'PATH = "scripts/foo.py"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert problem is None
    assert refs == ["scripts/foo.py"]


def test_extract_references_import_statement(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "bar.py").write_text("x = 1\n", encoding="utf-8")
    source = "import bar\n"
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == ["scripts/bar.py"]


def test_extract_references_ignores_runtime_assembled_path(tmp_path):
    """#1234's own stated open question 1 (how to resolve a runtime-
    assembled path) is deliberately NOT resolved here: `Path("scripts") /
    "baz.py"` is two literals joined at runtime, invisible to a static
    reader, and must not be silently guessed at."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "baz.py").write_text("x = 1\n", encoding="utf-8")
    source = 'from pathlib import Path\nP = Path("scripts") / "baz.py"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_reports_syntax_error_not_silently_empty(tmp_path):
    refs, problem = lane_coupling.extract_references(tmp_path, "def f(:\n")
    assert refs == []
    assert problem is not None


def test_single_lane_test_does_not_span_the_must_not_fire_control(tmp_path):
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_ok.py").write_text(
        'REF = "scripts/alpha.py"\n', encoding="utf-8"
    )
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": ["scripts/beta*.py"]}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["state"] == "ok"
    assert result["spans"] == []


def test_two_lane_test_spans_the_must_fire_case(tmp_path):
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_spans.py").write_text(
        'A = "scripts/alpha.py"\nB = "scripts/beta.py"\n', encoding="utf-8"
    )
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": ["scripts/beta*.py"]}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["state"] == "finding"
    files = [entry[0] for entry in result["spans"]]
    assert "tests/test_spans.py" in files


def test_import_and_literal_together_span_two_lanes(tmp_path):
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_mixed.py").write_text(
        'import alpha\nB = "scripts/beta.py"\n', encoding="utf-8"
    )
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": ["scripts/beta*.py"]}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["state"] == "finding"
    files = [entry[0] for entry in result["spans"]]
    assert "tests/test_mixed.py" in files


def test_extract_references_ignores_fstring_literal_segments(tmp_path):
    """#1234 self-review finding: `ast.walk` descends into a `JoinedStr`
    (f-string)'s own literal segments, each a separate `ast.Constant` --
    without filtering those out, an f-string whose literal prefix happens
    to equal a real repo file (`f"CLAUDE.md{suffix}"`) was silently
    resolved, contradicting the "runtime-assembled path is not resolved"
    claim this module's docstring and
    `test_extract_references_ignores_runtime_assembled_path` both make."""
    (tmp_path / "CLAUDE.md").write_text("x\n", encoding="utf-8")
    source = 'suffix = ""\nX = f"CLAUDE.md{suffix}"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert problem is None
    assert refs == []


def test_extract_references_rejects_backslash_literal(tmp_path):
    """#1234 self-review finding: a backslash-separated literal resolves
    inconsistently by platform (`pathlib` treats a backslash as a
    separator on Windows, a literal character on POSIX). Refused outright,
    on every platform, so this module's own verdict cannot silently
    disagree between CI legs."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
    source = 'PATH = "scripts\\\\foo.py"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert problem is None
    assert refs == []


def test_malformed_per_lane_value_is_finding_the_must_fire_case(tmp_path):
    """#1234 self-review finding: only the top-level "lane_patterns is not
    a dict" shape had a test; a single lane's own value being malformed
    (empty list, non-string item) had no positive control at all."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": []}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["state"] == "finding"
    assert result["malformed"] == ["lane-b"]


def test_well_formed_lanes_do_not_report_malformed_the_must_not_fire_control(
    tmp_path,
):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    lane_patterns = {"lane-a": ["scripts/alpha*.py"]}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["malformed"] == []


def test_missing_test_dir_is_finding_not_a_silent_ok(tmp_path):
    """#1234 self-review finding: a missing/mistyped `test_dir` used to
    fall through the scan loop with nothing to iterate, reporting `ok` --
    identical to a real scan that found zero coupling. This plugin's own
    defect class, one level up: an absence the tool produced must not
    render as an absence in the world."""
    (tmp_path / "scripts").mkdir()
    lane_patterns = {"lane-a": ["scripts/alpha*.py"]}
    result = lane_coupling.lane_coupling_report(
        tmp_path, lane_patterns, test_dir="no-such-tests-dir"
    )
    assert result["state"] == "finding"
    assert any("no-such-tests-dir" in rel for rel, _detail in result["unreadable"])


def test_present_test_dir_with_no_coupling_is_ok_the_must_not_fire_control(tmp_path):
    _scaffold_two_lane_repo(tmp_path)
    (tmp_path / "tests" / "test_ok.py").write_text(
        'REF = "scripts/alpha.py"\n', encoding="utf-8"
    )
    lane_patterns = {"lane-a": ["scripts/alpha*.py"], "lane-b": ["scripts/beta*.py"]}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["state"] == "ok"
    assert result["unreadable"] == []


def test_non_utf8_test_file_is_unreadable_not_a_crash(tmp_path):
    """#1234 self-review finding: `except OSError` alone does not catch
    `UnicodeDecodeError` (a `ValueError` subclass) -- a non-UTF-8 test file
    used to crash the whole derivation instead of being recorded as
    `unreadable`, the exact silent-crash shape `unreadable` exists to
    avoid."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_bad_encoding.py").write_bytes(b"\xff\xfe\x00\x01")
    lane_patterns = {"lane-a": ["scripts/alpha*.py"]}
    result = lane_coupling.lane_coupling_report(tmp_path, lane_patterns)
    assert result["state"] == "finding"
    files = [rel for rel, _detail in result["unreadable"]]
    assert "tests/test_bad_encoding.py" in files


def test_real_repo_finds_the_1201_incident():
    """The definitive check: run against this repo's own real .oss.json
    and its own real test suite, the mechanism finds
    `tests/test_lane_pattern_coverage_1201.py` spanning lane-prose
    (CLAUDE.md/scripts/skill_phases.py/etc, referenced as literal strings)
    and lane-dispatch (`scripts/select_issues_overlap.py`, referenced via
    `import select_issues_overlap`) -- the exact shape #1201's own
    incident was about, discovered mechanically rather than by a human
    noticing a merge conflict after the fact."""
    result = lane_coupling.lane_coupling_report(REPO_ROOT, _real_lane_patterns())
    files = dict(result["spans"])
    assert "tests/test_lane_pattern_coverage_1201.py" in files
    lanes_hit = set(
        lane for lane, _refs in files["tests/test_lane_pattern_coverage_1201.py"]
    )
    assert "lane-prose" in lanes_hit
    assert "lane-dispatch" in lanes_hit
