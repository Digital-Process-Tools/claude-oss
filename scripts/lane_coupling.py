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

**Static references, plus a narrow, literal-only fold -- #1245 closes part
of what #1234 left open, and names what still cannot be.** `extract_
references` walks a test file's AST for (a) string literal constants, (b)
top-level `import`/`from ... import` statements, and (c) a `Path(...)`,
`os.path.join(...)` or `<expr> / <expr>` chain where every leaf is a
literal string constant -- `Path("scripts") / "foo.py"` folds to
`scripts/foo.py` because both operands are already known, the same way the
Python interpreter itself would join them. That is a conservative constant
fold, not a general interpreter for a fragment of Python: the moment any
leaf is a variable, a function call this module does not recognise, or an
f-string `{}` interpolation, the fold stops and returns nothing for that
expression -- `Path(root) / "foo.py"` and `f"CLAUDE.md{suffix}"` are still
genuinely unresolvable, because their value is only known at runtime, and
resolving THAT would mean either evaluating arbitrary test code (unsafe:
test sources are ordinary files, but partially executing them at
diagnostic time to resolve a path is a different risk than reading them)
or a constant-folding interpreter far past what this module builds. #1245's
second named gap -- a glob-driven read (`Path(...).glob(...)`) -- IS
resolved when its base and pattern are both literal (or literal-foldable):
this module already has the real repo tree in hand to check a plain
literal against, so it runs the glob against that same tree at diagnostic
time rather than trying to know what it would match without one. A glob
whose base or pattern is not literal falls through unresolved, the same as
an unfoldable join. Every case that stays unresolved reports no findings
and no error, which is correct (nothing WAS found) rather than a claim
that nothing IS there.

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
                      test file could not be parsed or read (`unreadable`
                      -- also carries the case `test_dir` itself does not
                      exist, so "nothing coupled" and "nothing scanned"
                      never render the same way), or at least one test
                      file's references span two-plus lanes (`spans`)
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
    never a repo-relative reference), a `~`, any `:` (a drive letter is
    the concrete case, but every colon is refused), a backslash (#1234 --
    `pathlib` treats it as a separator on Windows and a literal character
    on POSIX, so a backslash-bearing literal would resolve inconsistently
    by platform), and a `..` path segment anywhere in the literal (#1256
    -- otherwise a caller's own `(repo / literal).is_file()` stat could
    land outside `repo`) are all refused outright; anything else is a
    *candidate*, checked against the real tree by the caller before being
    trusted."""
    if not value or not value.strip() or value != value.strip():
        return False
    if "\n" in value or "\t" in value:
        return False
    if value.startswith("/") or value.startswith("~"):
        return False
    if ":" in value:
        return False
    # #1234 self-review finding: a backslash-separated literal
    # ("tests\\foo.py") resolves inconsistently by platform -- `pathlib`
    # treats `\` as a separator on Windows (so the same literal can match a
    # real file there and nowhere else) but as a literal character on
    # POSIX. Refusing it outright, on every platform, keeps this module's
    # own verdict identical across every CI leg rather than silently
    # disagreeing between them; this repo's own real path literals are
    # forward-slash-only (confirmed by survey), so nothing genuine is lost.
    if "\\" in value:
        return False
    # #1256: a `..` path segment was not refused here, so a literal like
    # "../secret.txt" survived as a "candidate" and `extract_references`'s
    # own `(repo / literal).is_file()` stat could then resolve outside
    # `repo` -- contradicting this module's own docstring claim that it
    # only returns paths that exist under `repo`. Split on "/" (this
    # module's own literals are forward-slash-only, per the backslash
    # refusal above) and refuse `..` as a segment anywhere in the literal,
    # not only when it leads -- the same check `select_issues_overlap.
    # resolve_lane` already applies on the sibling (pattern) side.
    if ".." in value.split("/"):
        return False
    return True


def _joined_str_segment_ids(tree):
    """`id()`s of every `ast.Constant` node that is a literal *segment* of an
    f-string (`ast.JoinedStr`), not a standalone string. #1234 self-review
    finding: `ast.walk` descends into a `JoinedStr`'s own `values`, and each
    literal segment is itself an `ast.Constant` -- so `f"CLAUDE.md{suffix}"`
    put `"CLAUDE.md"` into the same walk as a genuine top-level literal,
    silently resolving exactly the runtime-assembled shape this module's own
    docstring says is out of scope. Filtering by identity here (rather than
    tracking parents while walking) keeps `_string_literal_candidates` a
    plain, single-pass `ast.walk`."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant):
                    ids.add(id(value))
    return ids


def _string_literal_candidates(tree):
    skip = _joined_str_segment_ids(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip:
                continue
            if _looks_like_path_literal(node.value):
                found.append(node.value)
    return found


def _is_path_call(node):
    """True for `Path(<one arg>)` or `pathlib.Path(<one arg>)`, no
    keywords -- the only `Path(...)` shape this module folds. A multi-arg
    `Path("a", "b")` is real but rare enough in this repo's own tests that
    resolving it is a further follow-up, not this one."""
    if not (isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "Path":
        return True
    return isinstance(func, ast.Attribute) and func.attr == "Path"


def _is_os_path_join_call(node):
    """True for `os.path.join(...)` -- the flat `import os` convention this
    repo's own scripts use, not `from os.path import join` (rare enough
    here that resolving that second import shape is not worth it)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "path"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "os"
    )


def _join_two(left, right):
    """`left`/`right` joined the way `os.path.join`/`pathlib`'s `/` operator
    actually behave, not naive string concatenation -- self-review finding
    (#1245): an earlier version of this fold always concatenated, so
    `os.path.join("scripts", "/etc/passwd")` folded to
    `"scripts/etc/passwd"` while the real call returns `"/etc/passwd"` (an
    absolute right-hand part DISCARDS everything to its left, in both
    `os.path.join` and `Path.__truediv__`). Left uncorrected, that mismatch
    could hide an absolute-path join from `_looks_like_path_literal`'s own
    leading-`/` refusal: the folded (wrong) result never starts with `/`,
    even though the real target the source names is an absolute path this
    module must refuse the same way a hand-typed absolute literal already
    is."""
    if right.startswith("/"):
        return right
    return left.rstrip("/") + "/" + right.lstrip("/")


def _fold_literal_path_expr(node):
    """#1245's genuinely resolvable slice of "runtime-assembled path" -- a
    conservative constant-fold, NOT a general interpreter for a fragment of
    Python (the thing #1234's own docstring already refused to build).
    Resolves only `Path(<foldable>)`, `os.path.join(<foldable>, ...)` and a
    chain of `<foldable> / <foldable>` (`ast.BinOp` with `ast.Div`) where
    every leaf is a literal string constant, returning the joined string
    (via `_join_two`, which replicates the real join/`/`-operator
    semantics rather than naive concatenation). Falls through to `None` the
    moment anything in the chain is not one of these shapes -- a bare
    `Name` (a variable), an f-string `FormattedValue`, a function call this
    module does not recognise -- so `Path("scripts") / "foo.py"` folds
    (both operands are already literal) but `Path(root) / "foo.py"` and
    `f"scripts/{name}.py"` do not, because their value is genuinely only
    known at runtime. Those two are #1245's own stated remaining boundary,
    not silently dropped: `extract_references` reports no reference for
    them, which is correct (nothing WAS resolved) rather than a claim that
    nothing IS there.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _fold_literal_path_expr(node.left)
        right = _fold_literal_path_expr(node.right)
        if left is None or right is None:
            return None
        return _join_two(left, right)
    if _is_path_call(node):
        return _fold_literal_path_expr(node.args[0])
    if _is_os_path_join_call(node):
        parts = []
        for arg in node.args:
            part = _fold_literal_path_expr(arg)
            if part is None:
                return None
            parts.append(part)
        if not parts:
            return None
        joined = parts[0]
        for part in parts[1:]:
            joined = _join_two(joined, part)
        return joined
    return None


def _joined_path_candidates(tree):
    """Every literal path this module can constant-fold out of a
    `Path(...)`/`os.path.join(...)`/`a / b` chain, filtered through the
    identical `_looks_like_path_literal` safety check a hand-typed literal
    goes through -- a folded literal is exactly as capable of naming
    something outside `repo` (`Path("..") / "secret"`) as one typed by
    hand, so it earns no exemption from the #1256 traversal refusal."""
    found = []
    for node in ast.walk(tree):
        is_candidate_shape = (
            (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div))
            or _is_path_call(node)
            or _is_os_path_join_call(node)
        )
        if not is_candidate_shape:
            continue
        folded = _fold_literal_path_expr(node)
        if folded is not None and _looks_like_path_literal(folded):
            found.append(folded)
    return found


def _glob_call_targets(tree):
    """``(base, pattern, recursive)`` for every `<foldable>.glob(<literal>)`
    or `<foldable>.rglob(<literal>)` call this module can resolve -- #1245's
    second named gap, closed the same way this module already answers "does
    this literal exist": run the glob against the real repo tree at
    diagnostic time, rather than trying to know what it would match
    without one. `base` independently passes `_looks_like_path_literal` (a
    bare `..`/absolute base is refused before the glob ever touches the
    filesystem, exactly as a plain literal is). `pattern` gets three of its
    own refusals, each closing a gap a self-review round found real:

    * a `..` segment (so a glob cannot be used to walk outside `repo` even
      through the pattern rather than the base);
    * a backslash anywhere in it -- `pathlib.Path.glob` splits a pattern on
      `/` only on POSIX but on both `/` and `\\\\` on Windows (`ntpath`), so
      the identical literal pattern in a test file's source can resolve to
      different matches purely by which OS runs the diagnostic. This
      module's own `_looks_like_path_literal` already refuses a backslash
      in a plain literal for the identical reason; the glob pattern earns
      no exemption from it;
    * a leading `/` (absolute) -- `Path.glob`/`rglob` raise
      `NotImplementedError("Non-relative patterns are unsupported")` for a
      non-relative pattern, and an uncaught exception here used to take
      down the scan for every OTHER test file in the same run, not just
      record this one as unreadable. Refused before the glob call is ever
      made, the same as the base's own absolute-path refusal.

    A dynamic base (`Path(root).glob(...)`) or a non-literal pattern folds
    to `None`/fails the isinstance check and is silently skipped --
    genuinely unresolvable, the same as an unfoldable `Path(...) / var`
    join above.
    """
    targets = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("glob", "rglob")
            and len(node.args) == 1
            and not node.keywords
        ):
            continue
        pattern_node = node.args[0]
        if not (
            isinstance(pattern_node, ast.Constant)
            and isinstance(pattern_node.value, str)
        ):
            continue
        pattern = pattern_node.value
        if "\\" in pattern:
            continue
        if pattern.startswith("/"):
            continue
        if ".." in pattern.split("/"):
            continue
        base = _fold_literal_path_expr(node.func.value)
        if base is None or not _looks_like_path_literal(base):
            continue
        targets.append((base, pattern, node.func.attr == "rglob"))
    return targets


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
    """A dotted module name resolved against `_IMPORT_ROOTS`, matching the
    flat `sys.path.insert(0, ROOT / "scripts")` convention this repo's own
    tests use before `import bare_module_name` -- e.g. `select_issues_
    overlap` -> `scripts/select_issues_overlap.py`. #1234 self-review: an
    earlier version also generated a `.../__init__.py` candidate for a
    package-style import, but `scripts/` has no subpackages in this repo
    and nothing exercised that shape -- speculative, untested code for a
    layout this module has no way to resolve correctly without knowing
    which segment of a dotted name is the package boundary. Dropped rather
    than left untested; a repo with real subpackages under `scripts/` is a
    real follow-up, not a guess landed here."""
    rel = module_name.replace(".", "/")
    return ["{}/{}.py".format(root, rel) for root in _IMPORT_ROOTS]


def extract_references(repo, source_text):
    """``(files, problem)`` -- the sorted, deduplicated repo-relative POSIX
    paths that `source_text` (one test file's own source) statically
    references and that exist on disk under `repo`; `problem` is a
    `SyntaxError` detail string when the source could not even be parsed, an
    `OSError` detail string (or several, joined) when a glob walk hit one
    mid-scan (#1327 -- unreadable directory, permission problem, a race),
    or `None`. A parse failure or a glob-walk `OSError` returns a non-`None`
    `problem`, never a bare `[]` a caller could mistake for "this file
    references nothing" -- the same distinction this module's own docstring
    names as load-bearing one level up.
    """
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        return [], "SyntaxError: {}".format(exc)
    repo = Path(repo)
    found = set()
    # #1327: an `OSError` mid-glob-walk (an unreadable directory, a
    # permission problem, a race during a `doctor_check_lane_coupling.py`
    # scan) used to be indistinguishable from a legitimately empty match --
    # the catch below folded `OSError` into the same silent `continue` as a
    # genuine "nothing here" `ValueError`/`NotImplementedError`, so
    # `problem` was only ever set for a `SyntaxError`. `OSError` is now
    # collected into `problems` and surfaced through the return value
    # instead of swallowed; `ValueError`/`NotImplementedError` stay silent,
    # since those mean the base or pattern was well-formed and simply
    # matched nothing (a legitimate empty result, not a failed walk). The
    # literal-candidate and import-resolution loops below deliberately keep
    # their original broad `(OSError, ValueError)` catch: an over-long or
    # otherwise unstat-able string is a routine outcome of stray sentence-
    # shaped literals that are not paths at all (confirmed on this repo's
    # own suite -- a docstring sentence can raise `OSError: [Errno 63] File
    # name too long` when stat'd, deep worktree paths make this worse, and
    # is-this-a-path is exactly what `.is_file()` is being asked here, not
    # "did a directory walk succeed").
    problems = []
    literals = _string_literal_candidates(tree) + _joined_path_candidates(tree)
    for literal in literals:
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
    for base, pattern, recursive in _glob_call_targets(tree):
        base_dir = repo / base
        try:
            if not base_dir.is_dir():
                continue
            matches = base_dir.rglob(pattern) if recursive else base_dir.glob(pattern)
            for match in matches:
                try:
                    if not match.is_file():
                        continue
                    rel = match.relative_to(repo)
                except (OSError, ValueError):
                    continue
                found.add(rel.as_posix())
        except OSError as exc:
            problems.append("{}: {}".format(type(exc).__name__, exc))
            continue
        except (ValueError, NotImplementedError):
            # `NotImplementedError` is `pathlib.Path.glob`/`rglob`'s own
            # reaction to a non-relative pattern (self-review finding,
            # #1245) -- `_glob_call_targets` already refuses a leading `/`
            # before it ever reaches here, but this is defense in depth
            # against a pathlib version raising it for a pattern shape
            # this module has not enumerated, so one unresolvable glob in
            # one test file cannot take the whole scan down with it.
            continue
    if problems:
        return sorted(found), "; ".join(problems)
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


def lane_coupling_report(repo, lane_patterns, test_dir="tests", allowlist=None):
    """``dict`` -- see this module's own docstring for the three states and
    the `spans`/`unreadable`/`malformed`/`acknowledged` fields.

    `spans` is a sorted list of ``(test_file, [(lane, [refs...]), ...])``
    for every UNACKNOWLEDGED test file whose static references resolve into
    two or more lanes -- this is what drives `state`. `unreadable` lists
    ``(test_file, detail)`` for a file that could not be parsed. `malformed`
    lists the lane names whose own `lane_patterns` value has the wrong
    shape.

    ``allowlist`` (#1244) is an optional iterable of test-file paths
    (repo-relative POSIX, matching `spans`' own `test_file` spelling) that
    this repository's maintainer has reviewed and confirmed span multiple
    lanes ON PURPOSE -- a whole-repo guard test reading several lanes' files
    to check a cross-cutting invariant, not an accidental #1201-shaped
    collision. A real trial run over this repo's own suite found 48 of 465
    test files already span two or more lanes, almost all of that shape,
    and wiring this module into `doctor.py` unconditionally would either
    warn permanently on a healthy repo -- this repo's own doctor-check-
    contract rule is "if nothing can clear it, the bug is in the check" --
    or need exactly this kind of noise reduction.

    A span whose `test_file` is in ``allowlist`` moves from `spans` into
    the new `acknowledged` list (identical shape) and does not, by itself,
    make `state` `"finding"` -- but it is never silently dropped: it is
    still visible in `acknowledged` for a caller (`doctor_check_lane_
    coupling.py`) to report as an informational count, the same shape
    `lane_pattern_coverage.py`'s own `uncovered_count` already uses one
    checker over. ``allowlist=None`` (the default) is #1234's own original
    module, byte-for-byte -- every span is unacknowledged, so nothing
    calling this function before #1244 changes behaviour. The allowlist
    itself is a fact about THIS repository (which tests intentionally span
    lanes), so it is read from `.oss.json` by the caller, never hardcoded
    here -- this repo's own governing rule that a fact about one repository
    never lives in shared code.
    """
    repo = Path(repo)
    if not lane_patterns:
        return {
            "state": "not-configured",
            "spans": [],
            "acknowledged": [],
            "unreadable": [],
            "malformed": [],
        }
    if not isinstance(lane_patterns, dict):
        return {
            "state": "finding",
            "spans": [],
            "acknowledged": [],
            "unreadable": [],
            "malformed": [None],
        }
    allowed = set(allowlist) if allowlist else set()
    file_lanes, malformed = _file_to_lanes(repo, lane_patterns)
    spans = []
    acknowledged = []
    unreadable = []
    test_root = repo / test_dir
    if not test_root.is_dir():
        # #1234 self-review finding: a missing/mistyped `test_dir` used to
        # fall straight through to the loop below with nothing to iterate,
        # reporting `ok` -- identical to a real scan that found zero
        # coupling. A caller cannot tell "this repo's tests are clean" from
        # "nothing was scanned at all", which is exactly the absence this
        # plugin is named after, one level up. Recorded in `unreadable`
        # (reusing the existing field rather than adding a new one) so the
        # state is `finding`, never a silent `ok`.
        unreadable.append((test_dir, "directory does not exist"))
    else:
        for path in sorted(test_root.glob("*.py")):
            rel = path.relative_to(repo).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                # `UnicodeDecodeError` is a `ValueError`, not an `OSError`
                # -- a non-UTF-8 test file used to propagate uncaught out
                # of this function instead of being recorded as
                # `unreadable`, the same silent-crash shape this module's
                # own docstring says `unreadable` exists to avoid (#1234
                # self-review finding).
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
                entry = (rel, sorted(lanes_touched.items()))
                if rel in allowed:
                    acknowledged.append(entry)
                else:
                    spans.append(entry)
    state = "finding" if (spans or malformed or unreadable) else "ok"
    return {
        "state": state,
        "spans": spans,
        "acknowledged": acknowledged,
        "unreadable": unreadable,
        "malformed": malformed,
    }
