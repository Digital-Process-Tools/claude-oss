"""Does a `tests/*.py` file reference repo files that sit in more than one
declared lane (`.oss.json`'s `labels.lane_patterns`) -- generalizing #1201's
own manual fix, which added four bookkeeping scripts to `lane-prose`'s
pattern by hand after two disjoint lanes collided on adjacent lines of both
(see this module's own test, `tests/test_lane_coupling_1234.py`, for the
incident in full).

#1201's fix and its own test (`test_lane_pattern_coverage_1201.py`) hold one
pair of files together because a human noticed the collision after the
fact. Nothing generalizes that: a *different* pair of files, coupled the
identical way through a *different* shared test, is invisible to every
existing check -- `lane_pattern_coverage.py` (#1229) asks whether each
lane's own declared pattern resolves and stays disjoint from every other
lane's, never whether a *test* asserts across two lanes' files. This module
answers the second question, by reading each test file's own source rather
than by asking a human to notice a second incident.

**Static references only -- two of #1234's three explicitly-named open
judgment calls are deliberately NOT resolved here.** `extract_references`
walks a test file's AST for (a) string literal constants and (b) top-level
`import`/`from ... import` statements, and resolves each to an existing
repo file. An f-string, an `os.path.join(...)` call or a `Path(...) / var`
join -- runtime-assembled, invisible to a static reader -- is not resolved;
resolving it would mean either evaluating arbitrary test code (unsafe: test
sources are ordinary files, but partially executing them at diagnostic time
to resolve a path is a different risk than reading them) or building a
constant-folding interpreter for a fragment of Python, neither of which
this issue asks for. A glob-driven read (`Path(...).glob(...)`) is the
third open question and is equally out of scope: this module has no way to
know at parse time what such a glob would match without running it. Both
are named here as the concrete boundary, not silently dropped -- a test
using only these two shapes reports no findings and no error, which is
correct (nothing WAS found) rather than a claim that nothing IS there.

**Left to a follow-up, per the issue's own invitation to scope narrower
when the open questions warrant it**: whether a test referencing a file NO
lane's pattern covers at all is worth its own finding. #1229's own ruling
on the sibling question (lane_pattern_coverage.py's `uncovered_count`) is
that "uncovered" needs deliberate scoping -- most files in this repo are
covered by no lane at all (`lane-other` is a designed bucket, not a
defect) -- and a test-suite-wide version of that same question would be
almost entirely noise: nearly every test in this repo references
`scripts/oss_config.py`, `conftest.py`, or another test file, none of
which any lane's pattern claims. This module reports only the "spans two
lanes" shape (#1201's own actual incident), not "references an uncovered
file".

**This is informational, matching #1229's own maintainer ruling on the
closely related lane_pattern_coverage.py: a refactoring signal, never a
merge or dispatch gate.** A real collision is still caught, loudly and for
free, by `select_issues.py`'s own held-lane check and by ordinary git
conflict detection the moment two lanes' PATCHES actually overlap; what
this module adds is visibility BEFORE that moment, for a resource neither
lane declared. Nothing in this module or its caller may be read as a merge
or dispatch precondition.

Three states, the third load-bearing (this plugin's own defect class, one
layer up): a repo that has never declared `lane_patterns` and a repo whose
test suite has no cross-lane coupling must never render identically, and
neither may look like a repo that DOES have a problem.

    ok               lane_patterns declared; no test file's own static
                      references span two or more lanes
    finding          `lane_patterns` is malformed (not an object, or a
                      lane's value is not a non-empty list of strings --
                      the same shape check `lane_pattern_coverage.py`
                      already applies, repeated here rather than imported
                      because the two checks can run independently), a
                      test file could not be parsed (`unreadable`), or at
                      least one test file's references span two-plus lanes
                      (`spans`)
    not-configured   labels.lane_patterns is null, absent, or an empty
                      object

Python 3.9 compatible.
"""

import ast
from pathlib import Path

import select_issues_overlap

#: Where a bare `import x` / `from x import y` is resolved from, matching
#: the `sys.path.insert(0, ROOT / "scripts")` convention this repo's own
#: tests use before importing a script module by its bare name.
_IMPORT_ROOTS = ("scripts",)


def _looks_like_path_literal(value):
    """A conservative filter on which string constants are even worth an
    `is_file()` stat -- not every string in a test file is a path, and
    most are not. Whitespace, an empty string, a leading `/` (absolute,
    never a repo-relative reference), a drive letter or a `~` are refused
    outright; anything else is a *candidate*, checked against the real
    tree by the caller before being trusted."""
    if not value or not value.strip() or value != value.strip():
        return False
    if "\n" in value or "\t" in value:
        return False
    if value.startswith("/") or value.startswith("~"):
        return False
    if ":" in value:
        return False
    return True


def _string_literal_candidates(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _looks_like_path_literal(node.value):
                found.append(node.value)
    return found


def _import_module_names(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.append(node.module)
    return names


def _candidate_paths_for_module(module_name):
    rel = module_name.replace(".", "/")
    candidates = []
    for root in _IMPORT_ROOTS:
        candidates.append("{}/{}.py".format(root, rel))
        candidates.append("{}/{}/__init__.py".format(root, rel))
    return candidates


def extract_references(repo, source_text):
    """``(files, problem)`` -- the sorted, deduplicated repo-relative POSIX
    paths that `source_text` (one test file's own source) statically
    references and that exist on disk under `repo`; `problem` is a
    `SyntaxError` detail string when the source could not even be parsed,
    or `None`. A parse failure returns `([], "SyntaxError: ...")`, never a
    bare `[]` a caller could mistake for "this file references nothing" --
    the same distinction this module's own docstring names as load-bearing
    one level up.
    """
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        return [], "SyntaxError: {}".format(exc)
    repo = Path(repo)
    found = set()
    for literal in _string_literal_candidates(tree):
        try:
            is_file = (repo / literal).is_file()
        except (OSError, ValueError):
            continue
        if is_file:
            found.add(Path(literal).as_posix())
    for module_name in _import_module_names(tree):
        for candidate in _candidate_paths_for_module(module_name):
            if (repo / candidate).is_file():
                found.add(candidate)
                break
    return sorted(found), None


def _lane_shape_problem(patterns):
    if not isinstance(patterns, list) or not patterns:
        return True
    return not all(isinstance(p, str) and p.strip() for p in patterns)


def _file_to_lanes(repo, lane_patterns):
    """``(file -> sorted [lane, ...], [malformed lane names])``, resolved
    through `select_issues_overlap.resolve_lane` -- the identical function
    `select_issues.py`'s own held-lane collision check and
    `lane_pattern_coverage.py` (#1229) both use, never a hand-rolled prefix
    match that could disagree with either."""
    mapping = {}
    malformed = []
    for lane, patterns in lane_patterns.items():
        if _lane_shape_problem(patterns):
            malformed.append(lane)
            continue
        resolved = select_issues_overlap.resolve_lane(repo, patterns)
        for f in resolved["files"]:
            mapping.setdefault(f, []).append(lane)
    return mapping, malformed


def lane_coupling_report(repo, lane_patterns, test_dir="tests"):
    """``dict`` -- see this module's own docstring for the three states and
    the `spans`/`unreadable`/`malformed` fields.

    `spans` is a sorted list of ``(test_file, [(lane, [refs...]), ...])``
    for every test file whose static references resolve into two or more
    lanes. `unreadable` lists ``(test_file, detail)`` for a file that could
    not be parsed. `malformed` lists the lane names whose own
    `lane_patterns` value has the wrong shape.
    """
    repo = Path(repo)
    if not lane_patterns:
        return {
            "state": "not-configured",
            "spans": [],
            "unreadable": [],
            "malformed": [],
        }
    if not isinstance(lane_patterns, dict):
        return {
            "state": "finding",
            "spans": [],
            "unreadable": [],
            "malformed": [None],
        }
    file_lanes, malformed = _file_to_lanes(repo, lane_patterns)
    spans = []
    unreadable = []
    test_root = repo / test_dir
    if test_root.is_dir():
        for path in sorted(test_root.glob("*.py")):
            rel = path.relative_to(repo).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                unreadable.append((rel, "{}: {}".format(type(exc).__name__, exc)))
                continue
            refs, problem = extract_references(repo, source)
            if problem is not None:
                unreadable.append((rel, problem))
                continue
            lanes_touched = {}
            for ref in refs:
                for lane in file_lanes.get(ref, []):
                    lanes_touched.setdefault(lane, []).append(ref)
            if len(lanes_touched) >= 2:
                spans.append((rel, sorted(lanes_touched.items())))
    state = "finding" if (spans or malformed or unreadable) else "ok"
    return {
        "state": state,
        "spans": spans,
        "unreadable": unreadable,
        "malformed": malformed,
    }
