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


def test_extract_references_resolves_a_fully_literal_path_join(tmp_path):
    """#1245: a `Path(<literal>) / <literal>` chain where every leaf is a
    literal string constant is now resolved -- an AST walker can see both
    operands are already known and fold them exactly as the interpreter
    itself would, which is a narrower claim than "invisible to a static
    reader" (#1234's own original wording for this exact shape)."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "baz.py").write_text("x = 1\n", encoding="utf-8")
    source = 'from pathlib import Path\nP = Path("scripts") / "baz.py"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == ["scripts/baz.py"]
    assert problem is None


def test_extract_references_resolves_os_path_join_of_literals(tmp_path):
    """The same fold, through `os.path.join(...)` rather than `Path(...) /
    ...` -- both are #1245's genuinely resolvable slice."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "qux.py").write_text("x = 1\n", encoding="utf-8")
    source = 'import os\nP = os.path.join("scripts", "qux.py")\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == ["scripts/qux.py"]
    assert problem is None


def test_extract_references_still_ignores_a_variable_path_join(tmp_path):
    """Positive control for the two tests above: #1245's own stated
    boundary against building a constant-folding interpreter for arbitrary
    Python. `root` is a variable here -- its value is only known at
    runtime -- so the join stays genuinely unresolved, not silently
    guessed at."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "baz.py").write_text("x = 1\n", encoding="utf-8")
    source = 'from pathlib import Path\nroot = "scripts"\nP = Path(root) / "baz.py"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_resolved_join_still_rejects_traversal(tmp_path):
    """#1256's traversal refusal reused here rather than re-litigated: a
    folded literal is exactly as capable of naming something outside
    `repo` as a hand-typed one, and must be refused the same way."""
    (tmp_path / "scripts").mkdir()
    (tmp_path.parent / "secret.txt").write_text("shh\n", encoding="utf-8")
    source = 'from pathlib import Path\nP = Path("..") / "secret.txt"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_resolves_glob_driven_read(tmp_path):
    """#1245's second named gap, closed the same way this module already
    answers "does this literal exist" -- by checking against the real repo
    tree. `Path("scripts").glob("*.py")` is run at diagnostic time and
    every match added as a reference."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "one.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts" / "two.py").write_text("x = 1\n", encoding="utf-8")
    source = (
        'from pathlib import Path\nfor p in Path("scripts").glob("*.py"):\n    pass\n'
    )
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == ["scripts/one.py", "scripts/two.py"]
    assert problem is None


def test_extract_references_resolves_rglob_driven_read(tmp_path):
    """The recursive sibling of the test above."""
    (tmp_path / "scripts" / "sub").mkdir(parents=True)
    (tmp_path / "scripts" / "sub" / "nested.py").write_text("x = 1\n", encoding="utf-8")
    source = (
        'from pathlib import Path\nfor p in Path("scripts").rglob("*.py"):\n    pass\n'
    )
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == ["scripts/sub/nested.py"]
    assert problem is None


def test_extract_references_glob_base_still_refuses_traversal(tmp_path):
    """Positive control: a glob whose base literal tries to escape `repo`
    is refused the same way a plain literal is (#1256's own rule), before
    the glob ever touches the filesystem."""
    (tmp_path / "scripts").mkdir()
    (tmp_path.parent / "outside.py").write_text("x = 1\n", encoding="utf-8")
    source = 'from pathlib import Path\nfor p in Path("..").glob("*.py"):\n    pass\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_still_ignores_glob_with_dynamic_base(tmp_path):
    """Genuinely unresolvable: the base directory of the glob is a
    variable, not a literal -- this module cannot know what it names
    without running the test."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "one.py").write_text("x = 1\n", encoding="utf-8")
    source = (
        "from pathlib import Path\n"
        'root = "scripts"\n'
        'for p in Path(root).glob("*.py"):\n'
        "    pass\n"
    )
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_refuses_absolute_glob_pattern_without_crashing(tmp_path):
    """Self-review finding (Explore spawn, #1245): `Path.glob`/`rglob` raise
    `NotImplementedError("Non-relative patterns are unsupported")` for a
    non-relative pattern -- an earlier version of `_glob_call_targets` did
    not refuse this shape, so one test file anywhere in the scanned tree
    with an absolute glob pattern took the whole scan down instead of being
    recorded per-file, the way a `SyntaxError` already is. Refused before
    the glob call is ever made: no crash, no reference."""
    (tmp_path / "scripts").mkdir()
    source = (
        'from pathlib import Path\nfor p in Path("scripts").glob("/etc/*"):\n    pass\n'
    )
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_refuses_backslash_glob_pattern(tmp_path):
    """Self-review finding (oss:auditor spawn, #1245): `pathlib.Path.glob`
    splits a pattern on `/` only on POSIX but on both `/` and a backslash
    on Windows (`ntpath`), so an identical literal pattern containing a
    backslash could resolve to different matches purely by which OS runs
    the diagnostic -- the same platform inconsistency
    `_looks_like_path_literal` already refuses for a plain literal. The
    glob pattern earns no exemption from it."""
    (tmp_path / "scripts" / "sub").mkdir(parents=True)
    (tmp_path / "scripts" / "sub" / "nested.py").write_text("x = 1\n", encoding="utf-8")
    source = (
        "from pathlib import Path\n"
        'for p in Path("scripts").glob("sub\\\\*.py"):\n'
        "    pass\n"
    )
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_fold_join_replicates_real_absolute_tail_semantics(tmp_path):
    """Self-review finding (Explore spawn, #1245): real `os.path.join`/
    `Path.__truediv__` DISCARD every earlier component when a later part is
    absolute (`os.path.join("scripts", "/etc/passwd") == "/etc/passwd"`).
    An earlier version of `_fold_literal_path_expr`'s join step always
    concatenated instead, producing `"scripts/etc/passwd"` -- a result that
    does not start with `/` and so could slip past `_looks_like_path_
    literal`'s own absolute-path refusal, hiding an absolute-path join
    from the same safety check a hand-typed absolute literal cannot avoid.
    """
    import ast

    tree = ast.parse('import os\nP = os.path.join("scripts", "/etc/passwd")\n')
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert lane_coupling._fold_literal_path_expr(call) == "/etc/passwd"


def test_extract_references_still_refuses_the_absolute_tail_join(tmp_path):
    """Positive control for the fold-semantics fix above, through the full
    `extract_references` path: the corrected fold now produces an absolute
    string, which `_looks_like_path_literal`'s own leading-`/` refusal
    correctly rejects -- so the join is refused, not silently mis-resolved
    to a wrong repo-relative path."""
    (tmp_path / "scripts").mkdir()
    source = 'import os\nP = os.path.join("scripts", "/etc/passwd")\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_reports_syntax_error_not_silently_empty(tmp_path):
    refs, problem = lane_coupling.extract_references(tmp_path, "def f(:\n")
    assert refs == []
    assert problem is not None


def test_extract_references_reports_oserror_mid_glob_walk_not_silently_empty(
    tmp_path, monkeypatch
):
    """#1327: an `OSError` raised mid-glob-walk (an unreadable directory, a
    permission problem, a race during a `doctor_check_lane_coupling.py`
    scan) used to be swallowed by the same `except (OSError, ...)` that
    correctly refuses a non-relative pattern -- `problem` was only ever
    set for a `SyntaxError`, so a failed walk was indistinguishable from a
    glob that legitimately matched nothing. `Path.rglob` is monkeypatched
    to raise `PermissionError` (an `OSError` subclass) to reproduce this
    without needing a real unreadable directory, which is not reliably
    constructible across every CI platform."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "one.py").write_text("x = 1\n", encoding="utf-8")
    source = (
        'from pathlib import Path\nfor p in Path("scripts").rglob("*.py"):\n    pass\n'
    )

    from pathlib import Path as RealPath

    def _boom(self, pattern):
        raise PermissionError("[Errno 13] Permission denied: 'scripts'")

    monkeypatch.setattr(RealPath, "rglob", _boom)
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert problem is not None, (
        "an OSError mid-glob-walk must be reported, not indistinguishable "
        "from a legitimately empty match"
    )
    assert "permission" in problem.lower()


def test_extract_references_reports_oserror_mid_import_resolution_1427(
    tmp_path, monkeypatch
):
    """#1347 finding 1 first gave the import-resolution loop exception
    handling at all (before that it crashed `extract_references` outright).
    #1427 is the maintainer call on what that handling should do: this
    loop's candidates (`scripts/foo.py`-shaped, module-derived relative
    paths) are short and well-formed, unlike the literal-candidate loop's
    free-text string literals just above it -- so a stat-time `OSError`
    here is more plausibly a genuine access failure than a "this wasn't a
    path" outcome, and is now surfaced via `problems.append`, matching the
    glob-walk loop's own #1327 precedent, rather than swallowed identically
    to an ordinary unresolved import."""
    (tmp_path / "scripts").mkdir()
    source = "import select_issues_overlap\n"

    from pathlib import Path as RealPath

    def _boom(self):
        raise PermissionError("[Errno 13] Permission denied: 'scripts'")

    monkeypatch.setattr(RealPath, "is_file", _boom)
    # The call itself completing (rather than raising `PermissionError`) is
    # still asserted implicitly: a crash would fail this test before the
    # assertions below ever ran.
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is not None, (
        "a genuine OSError during import-candidate resolution must be "
        "reported, not indistinguishable from 'module never referenced'"
    )
    assert "permission" in problem.lower()


def test_extract_references_import_resolving_nothing_is_still_the_must_not_fire_control(
    tmp_path,
):
    """Positive control for the test above: an import that resolves to no
    real file on disk (no OSError) must still report `problem is None` --
    the fix for the OSError case must not start reporting a problem for an
    ordinary, clean, unresolved import."""
    (tmp_path / "scripts").mkdir()
    source = "import no_such_module_at_all\n"
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


def test_extract_references_glob_matching_nothing_is_still_the_must_not_fire_control(
    tmp_path,
):
    """Positive control for the test above: a glob that legitimately
    matches nothing (no OSError, no SyntaxError) must still report
    `problem is None` -- the fix for the OSError case must not start
    reporting a problem for an ordinary, clean, empty match."""
    (tmp_path / "scripts").mkdir()
    source = (
        'from pathlib import Path\nfor p in Path("scripts").rglob("*.py"):\n    pass\n'
    )
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert refs == []
    assert problem is None


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


def test_extract_references_rejects_dotdot_traversal(tmp_path):
    """#1256: `_looks_like_path_literal` refused an absolute path, `~`, `:`
    and a backslash, but not a `..` segment -- so `extract_references`'s own
    `(repo / literal).is_file()` stat could land outside `repo` for a
    literal like `"../secret.txt"`, contradicting this module's own
    docstring claim that it only returns paths that exist under `repo`.
    Positive control: `secret.txt` is created one directory *above*
    `tmp_path` (the fake repo root), so a wrong fix that still resolves the
    traversal would find a real file and report it."""
    (tmp_path / "scripts").mkdir()
    (tmp_path.parent / "secret.txt").write_text("shh\n", encoding="utf-8")
    source = 'PATH = "../secret.txt"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert problem is None
    assert refs == []


def test_extract_references_rejects_dotdot_in_middle_of_literal(tmp_path):
    """The same traversal shape, one segment deeper -- `_looks_like_path_
    literal` must refuse `..` wherever it appears as a path segment, not
    only when the literal starts with it."""
    (tmp_path / "scripts").mkdir()
    (tmp_path.parent / "secret.txt").write_text("shh\n", encoding="utf-8")
    source = 'PATH = "scripts/../../secret.txt"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert problem is None
    assert refs == []


def test_extract_references_accepts_ordinary_in_repo_relative_literal(tmp_path):
    """Must-not-fire control for the two `..` cases above: an ordinary
    relative literal naming a real in-repo file is still accepted."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "ordinary.py").write_text("x = 1\n", encoding="utf-8")
    source = 'PATH = "scripts/ordinary.py"\n'
    refs, problem = lane_coupling.extract_references(tmp_path, source)
    assert problem is None
    assert refs == ["scripts/ordinary.py"]


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
