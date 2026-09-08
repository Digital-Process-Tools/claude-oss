"""#1165: #1157/#1109 hand-converted ~23 call sites to route `gh`/`git`
resolution through `gh_which.safe_which` rather than a bare `shutil.which`
or a literal, unresolved `"gh"`/`"git"` argv[0] -- both of which let a
same-named `.cmd`/`.exe`/`.bat` planted at the root of the inspected repo
win over a real `PATH` entry on Windows (see `scripts/gh_which.py`'s own
docstring for the mechanism). Nothing asserted that no OTHER site does the
same thing. #1163, #1168, #1172 and #1173 are each one more untouched site
found the same way -- by a human or an audit dispatch reading the file --
which is exactly the defect class this repository is named after: an
absence nobody checked, read as an absence that was verified.

This sweep is the check that should have caught each of those in turn. It
scans every `scripts/*.py` file (excluding `gh_which.py` itself, whose job
IS to call `shutil.which`) for four syntactic shapes, via `ast` rather than
a text grep -- precise about *which* `shutil.which`/`subprocess.run` are
meant, not about indentation or quoting style:

1. `shutil.which("gh")` / `shutil.which("git")` -- a literal-string call,
   anywhere outside `gh_which.py`.
2. `subprocess.run(...)` / `subprocess.Popen(...)` / `.call(...)` /
   `.check_call(...)` / `.check_output(...)`, called as `subprocess.<name>`
   directly, whose first positional argument is a list/tuple literal
   (optionally concatenated with `+` onto something else) whose first
   element is the literal string `"gh"` or `"git"`.
3. #1295: the same literal-argv shape as (2), but handed to a LOCAL
   wrapper function by name (`_run(["git", ...])`) instead of directly to
   `subprocess.*` -- see "wrapper-mediated spawns", below.
4. #1295: a literal `["git", ...]`/`["gh", ...]` list first bound to a
   local variable (`command = ["git", ...]`), then that variable handed to
   a spawn (case 2 or 3) some lines later in the same function -- see
   "bound argv", below.

Both are grep-equivalent in spirit (the issue's own suggested fix says
"grep-based is fine") but ast-based in practice, because a plain grep for
`"gh"`/`"git"` inside a docstring or a `#` comment -- of which this
codebase's own `gh_which`-migration commentary has dozens -- would drown
the real hits.

**Wrapper-mediated spawns (#1295).** A local wrapper -- `oss_config._run`,
`statusline._run`, each accepting a bare `["git", ...]` list and resolving
(or not) internally before its own `subprocess.run` call -- used to be
invisible to this sweep, because case 2 only recognised a DIRECT
`subprocess.*` call. A third wrapper of the identical shape,
`scaffold._run`, is not converted by this issue and is not flagged by the
detection below either -- not because it resolves safely (it does not: its
own `command` parameter is handed straight to `subprocess.run` with no
internal resolution), but because every live call site already passes it a
pre-resolved `git_bin`/`gh_bin` variable rather than a literal `["git",
...]`/`["gh", ...]` argv, so there is nothing for a literal-argv scan to
catch there today. A future call site handing it a bare literal would still
be invisible to this heuristic (`_mentions_a_resolver` looks at the
*wrapper's own* body, not its callers' arguments) -- named here rather than
silently left for the next audit to rediscover.

`_WrapperFinder` now does one pre-pass per file: a
module-level function is a "candidate wrapper" if its body calls
`subprocess.<spawn>(PARAM, ...)` where `PARAM` is one of that function's
own parameters (the exact shape `oss_config._run`/`statusline._run` both
had before this issue). A candidate is then read a second time for whether
it resolves that parameter itself before spawning -- any call anywhere in
its body to something named (or attributed) `*which*`, case-insensitive,
covers both `gh_which.safe_which(...)` and a self-contained `_safe_which(
...)` (the shape `statusline.py` needs, since that file is vendored
standalone per its own module docstring and cannot `import gh_which`).
A wrapper that already resolves is dropped from the unsafe set, so a
literal-argv call into it is not re-flagged forever once it is fixed; a
wrapper that does not is added, and every literal-argv call site naming it
is now caught the same way a direct `subprocess.run(["git", ...])` is.
This is still not real interprocedural analysis -- it is a same-file,
presence-based heuristic (does *any* call in the function's body mention
"which"?), not a proof that the resolved value is what actually reaches
the spawn. A wrapper that calls a resolver and then ignores its result
would be silently treated as safe. That gap is accepted rather than
chased: closing it needs real dataflow tracking, which is the same
interprocedural analysis this module's predecessor declined for the same
reason -- "grep-based is fine" was the brief this sweep is built to.

**Bound argv (#1295).** `command = ["git", ...]` then, several lines
later, `subprocess.run(command)` or `_run(command)` -- the shape
`oss_config._ignore_rule` had before this issue -- used to be invisible
because case 2/3 only recognised a literal LIST at the call site, not a
Name referring to one. `_Visitor` now tracks, per function scope (pushed
and popped on `FunctionDef`/`AsyncFunctionDef`, so a binding in one
function is never visible to another), any `NAME = ["git"/"gh", ...]`
assignment, and resolves a later spawn's `Name` argument against that
table. This is flow-insensitive within a function (it does not model
branches, reassignment order across `if`/`else`, or loops) -- a variable
reassigned to something safe after the tracked binding but read from a
branch this walk still sees as "bound" would false-positive rather than
false-negative, which is the direction this sweep should err in.

Every entry in `_ALLOWED` is a real, currently-open site, not a synthetic
exception -- named individually, by file and line, each with why it is not
today's fix. `test_the_allowlist_is_not_hiding_anything_new` is the control
that keeps the allowlist itself honest: it re-derives the live violation
set and asserts it is EXACTLY `_ALLOWLIST`'s keys, so an allowlisted site
that gets fixed (and silently drops out of the scan) fails loudly here
rather than leaving a stale, unused exception sitting around forever.
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

_BAD_NAMES = {"gh", "git"}
_SPAWN_ATTRS = {"run", "Popen", "call", "check_call", "check_output"}

#: Every currently-known, not-yet-converted site this sweep's own AST scan
#: finds -- named by (relative file path, line number), each with a reason
#: this issue does not fix it. A new, unnamed site anywhere else in
#: `scripts/*.py` still fails `test_no_new_bare_gh_or_git_spawn_sites`.
#: Adding an entry here without a reason, or widening a path/line to a
#: pattern, defeats the whole point -- see this module's own docstring.
_ALLOWED = {
    ("scripts/release_delta.py", 451): (
        "shutil.which",
        "An early-return pre-check ('is there any point trying') whose "
        "result is never assigned to a variable or fed to a spawn -- "
        "`_git` two lines below resolves `git` via `gh_which.safe_which` "
        "on its own, independently of this check's answer. Redundant, "
        "not a live bare-spawn route, but still a literal "
        "`shutil.which('git')` call this sweep's own pattern matches, so "
        "named here rather than silently exempted by a broader pattern.",
    ),
}


def _literal_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _unwrap_concat(node):
    """The leftmost operand of a chain of `+` concatenations -- `["git", ...]
    + list(args)` is still a literal-argv-opener even though the whole
    expression is a `BinOp`, not a bare `List`."""
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        node = node.left
    return node


def _mentions_a_resolver(func_node):
    """Does any call anywhere in ``func_node``'s body name (or attribute)
    something containing ``which``, case-insensitively? Covers both
    ``gh_which.safe_which(...)`` and a self-contained ``_safe_which(...)``
    -- see this module's own docstring for why presence, not dataflow, is
    the bar."""
    for child in ast.walk(func_node):
        if child is func_node or not isinstance(child, ast.Call):
            continue
        f = child.func
        if isinstance(f, ast.Attribute) and "which" in f.attr.lower():
            return True
        if isinstance(f, ast.Name) and "which" in f.id.lower():
            return True
    return False


class _WrapperFinder(ast.NodeVisitor):
    """One pre-pass per file: which module-level functions are a local
    ``_run(command, ...)``-shaped wrapper around ``subprocess.*`` that does
    NOT already resolve its own argv[0] -- see "Wrapper-mediated spawns" in
    this module's own docstring."""

    def __init__(self):
        self.wrappers = set()

    def visit_FunctionDef(self, node):
        param_names = {arg.arg for arg in node.args.args}
        is_candidate = False
        for child in ast.walk(node):
            if child is node or not isinstance(child, ast.Call):
                continue
            func = child.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _SPAWN_ATTRS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
                and child.args
            ):
                first = child.args[0]
                if isinstance(first, ast.Name) and first.id in param_names:
                    is_candidate = True
        if is_candidate and not _mentions_a_resolver(node):
            self.wrappers.add(node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


class _Visitor(ast.NodeVisitor):
    def __init__(self, wrapper_names):
        self.hits = []
        self.wrapper_names = wrapper_names
        #: Stack of {varname: bad_name} -- pushed/popped per function scope
        #: (see "Bound argv" in this module's own docstring), so a binding
        #: inside one function is never visible while scanning another.
        self._bound_stack = [{}]

    def visit_FunctionDef(self, node):
        self._bound_stack.append({})
        self.generic_visit(node)
        self._bound_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        value = _unwrap_concat(node.value)
        if (
            isinstance(value, (ast.List, ast.Tuple))
            and value.elts
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = _literal_str(value.elts[0])
            if name in _BAD_NAMES:
                self._bound_stack[-1][node.targets[0].id] = name
        self.generic_visit(node)

    def _bound_lookup(self, varname):
        for scope in reversed(self._bound_stack):
            if varname in scope:
                return scope[varname]
        return None

    def visit_Call(self, node):
        func = node.func
        is_subprocess_call = (
            isinstance(func, ast.Attribute)
            and func.attr in _SPAWN_ATTRS
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        )
        is_wrapper_call = isinstance(func, ast.Name) and func.id in self.wrapper_names
        is_shutil_which = (
            isinstance(func, ast.Attribute)
            and func.attr == "which"
            and isinstance(func.value, ast.Name)
            and func.value.id == "shutil"
        )
        if is_shutil_which and node.args:
            name = _literal_str(node.args[0])
            if name in _BAD_NAMES:
                self.hits.append((node.lineno, "shutil.which", name))
        if (is_subprocess_call or is_wrapper_call) and node.args:
            first = _unwrap_concat(node.args[0])
            if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
                name = _literal_str(first.elts[0])
                if name in _BAD_NAMES:
                    kind = (
                        "argv-literal"
                        if is_subprocess_call
                        else "argv-literal-via-wrapper"
                    )
                    self.hits.append((node.lineno, kind, name))
            elif isinstance(first, ast.Name):
                bad = self._bound_lookup(first.id)
                if bad in _BAD_NAMES:
                    kind = (
                        "argv-literal-bound"
                        if is_subprocess_call
                        else "argv-literal-bound-via-wrapper"
                    )
                    self.hits.append((node.lineno, kind, bad))
        self.generic_visit(node)


def _scan_file(path):
    """`[(lineno, kind, name), ...]` for one file, or `None` if it could not
    be parsed -- reported by the caller as `could-not-scan`, never folded
    into "clean"."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return None
    finder = _WrapperFinder()
    finder.visit(tree)
    visitor = _Visitor(finder.wrappers)
    visitor.visit(tree)
    return visitor.hits


def _scan_repository():
    """`{(relpath, lineno): (kind, name)}` for every live violation in
    `scripts/*.py`, and `[relpath, ...]` for any file that could not be
    scanned at all -- the third state, never silently dropped."""
    violations = {}
    unscannable = []
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name == "gh_which.py":
            continue
        relpath = "scripts/{}".format(path.name)
        hits = _scan_file(path)
        if hits is None:
            unscannable.append(relpath)
            continue
        for lineno, kind, name in hits:
            violations[(relpath, lineno)] = (kind, name)
    return violations, unscannable


def test_the_scan_actually_looked_at_something():
    """A sweep with nothing to scan passes for the wrong reason -- this
    repository's own named defect class, one level up from the finding it
    exists to catch."""
    violations, unscannable = _scan_repository()
    assert not unscannable, "could not scan: {}".format(unscannable)
    scripts_here = list(SCRIPTS_DIR.glob("*.py"))
    assert len(scripts_here) > 10, "scripts/ looks emptier than expected"


def test_gh_which_py_itself_is_excluded():
    """Positive control for the exclusion: `gh_which.py` calling `shutil.
    which` for real is not a finding -- it is the one legitimate call site,
    and this sweep must not flag its own implementation."""
    gh_which_path = SCRIPTS_DIR / "gh_which.py"
    assert gh_which_path.exists()
    hits = _scan_file(gh_which_path)
    assert hits == [], (
        "gh_which.py itself must never be flagged by its own sweep: {}".format(hits)
    )


def test_no_new_bare_gh_or_git_spawn_sites():
    """The sweep this issue asks for: every live violation in `scripts/*.py`
    must be named, individually, in `_ALLOWED` -- an unnamed one is a new
    (or newly rediscovered) bare `gh`/`git` spawn, exactly the shape #1163,
    #1168, #1172 and #1173 each were.
    """
    violations, unscannable = _scan_repository()
    assert not unscannable, "could not scan: {}".format(unscannable)
    unexpected = {
        key: kind_name for key, kind_name in violations.items() if key not in _ALLOWED
    }
    assert not unexpected, (
        "bare gh/git spawn site(s) not in the allowlist -- route each "
        "through gh_which.safe_which, or add a named, reasoned entry to "
        "_ALLOWED if it is a real but out-of-scope follow-up: {}".format(
            {"{}:{}".format(*k): v for k, v in unexpected.items()}
        )
    )


def test_the_allowlist_is_not_hiding_anything_new():
    """The other half of the control: every `_ALLOWED` entry must still be a
    live violation. A site that gets fixed and silently drops out of the
    scan must not leave a stale exception standing -- that is a false
    `pass` on a NEW bare spawn planted at the exact line a real one used to
    live, hidden behind an allowlist entry nobody re-checked.
    """
    violations, unscannable = _scan_repository()
    assert not unscannable, "could not scan: {}".format(unscannable)
    stale = [key for key in _ALLOWED if key not in violations]
    assert not stale, (
        "allowlist entries that are no longer live violations -- remove "
        "them (the site was fixed) rather than leaving a fixed line's "
        "old exception standing: {}".format(["{}:{}".format(*k) for k in stale])
    )


def test_doctor_py_itself_is_fully_clean():
    """#1172/#1173's own scope: after this issue's fix, `scripts/doctor.py`
    -- the file both blocking findings named -- carries zero bare gh/git
    spawn sites of either shape, not merely "no more than the five named
    ones". A sixth, unnoticed site in the same file must fail here, not
    reappear as a seventh audit round."""
    violations, unscannable = _scan_repository()
    assert "scripts/doctor.py" not in unscannable
    doctor_violations = {
        key: kind_name
        for key, kind_name in violations.items()
        if key[0] == "scripts/doctor.py"
    }
    assert not doctor_violations, (
        "scripts/doctor.py still carries a bare gh/git spawn site: {}".format(
            doctor_violations
        )
    )


def test_must_fire_control_a_synthetic_bare_spawn_is_caught():
    """Positive control for the whole sweep, per CLAUDE.md's own rule: an
    assertion that nothing bad is present also passes when the scanner
    itself is broken. Prove the two shapes are actually detected, on
    synthetic source the scanner has never seen, rather than trusting that
    an empty `unexpected` set means the scan ran at all.
    """
    import tempfile

    shutil_which_source = (
        "import shutil\n"
        "\n"
        "def f():\n"
        '    if shutil.which("gh") is None:\n'
        "        return None\n"
    )
    argv_literal_source = (
        "import subprocess\n"
        "\n"
        "def f(root):\n"
        "    return subprocess.run(['git', '-C', str(root)] + ['status'])\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        for name, source, expected_kind in (
            ("a.py", shutil_which_source, "shutil.which"),
            ("b.py", argv_literal_source, "argv-literal"),
        ):
            path = Path(tmp) / name
            path.write_text(source, encoding="utf-8")
            hits = _scan_file(path)
            kinds = [kind for _lineno, kind, _name in hits]
            assert expected_kind in kinds, (
                name,
                source,
                hits,
            )


def test_must_not_fire_control_an_already_resolved_call_is_not_flagged():
    """The other half of the same rule: a call site that already routes
    through the resolved variable -- the shape every converted site in this
    codebase now uses -- must not be flagged. Pairing this with the "must
    fire" control above is what tells a scanner that never runs from one
    that correctly finds nothing."""
    import tempfile

    already_safe_source = (
        "import subprocess\n"
        "import gh_which\n"
        "\n"
        "def f(root):\n"
        "    git_bin = gh_which.safe_which('git')\n"
        "    if git_bin is None:\n"
        "        return None\n"
        "    return subprocess.run([git_bin, '-C', str(root), 'status'])\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "c.py"
        path.write_text(already_safe_source, encoding="utf-8")
        hits = _scan_file(path)
        assert hits == [], hits


def test_a_local_run_wrapper_by_name_is_not_confused_with_subprocess_run():
    """Must-not-fire control for the deliberate limitation this module's own
    docstring names: `run(["gh", ...])` calling a same-named LOCAL
    parameter or variable (the pattern `select_issues_claim_read._run` and
    `oss_config._run` both use) must not be flagged as though it were
    `subprocess.run` -- this sweep only recognises the qualified
    `subprocess.run`/`subprocess.Popen`/etc form."""
    local_wrapper_source = (
        "def _run(args):\n"
        "    raise NotImplementedError\n"
        "\n"
        "def f(run=None):\n"
        "    run = _run if run is None else run\n"
        "    return run(['gh', 'api', 'user'])\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "d.py"
        path.write_text(local_wrapper_source, encoding="utf-8")
        hits = _scan_file(path)
        assert hits == [], hits


def test_wrapper_mediated_literal_argv_is_caught():
    """Must-fire control for #1295's own gap: a local `_run(command, ...)`
    wrapper that spawns `subprocess.run(command, ...)` with no resolution of
    `command[0]` -- exactly `oss_config._run`/`statusline._run`'s shape
    before this issue -- must be caught when called with a literal
    `["git", ...]`/`["gh", ...]` argv, even though the spawn itself is not a
    direct `subprocess.*` call at that line."""
    source = (
        "import subprocess\n"
        "\n"
        "def _run(command, cwd=None):\n"
        "    return subprocess.run(command, cwd=cwd)\n"
        "\n"
        "def f(root):\n"
        "    return _run(['git', '-C', str(root), 'status'])\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "e.py"
        path.write_text(source, encoding="utf-8")
        hits = _scan_file(path)
        kinds = [kind for _lineno, kind, _name in hits]
        assert "argv-literal-via-wrapper" in kinds, (source, hits)


def test_wrapper_that_resolves_its_own_argv_is_not_flagged():
    """The other half of the same control: a wrapper that resolves
    `command[0]` itself before spawning -- `gh_which.safe_which(...)` or a
    self-contained `_safe_which(...)`, either one -- must not be flagged at
    its own call sites, or a fixed wrapper would stay a permanent false
    positive forever."""
    source = (
        "import subprocess\n"
        "\n"
        "def _safe_which(name):\n"
        "    return name\n"
        "\n"
        "def _run(command, cwd=None):\n"
        "    resolved = _safe_which(command[0])\n"
        "    if resolved is None:\n"
        "        return None\n"
        "    command = [resolved] + list(command[1:])\n"
        "    return subprocess.run(command, cwd=cwd)\n"
        "\n"
        "def f(root):\n"
        "    return _run(['git', '-C', str(root), 'status'])\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "f.py"
        path.write_text(source, encoding="utf-8")
        hits = _scan_file(path)
        assert hits == [], hits


def test_bound_argv_then_spawned_is_caught():
    """Must-fire control for #1295's other named gap: `command = ["git",
    ...]` a few lines above `subprocess.run(command)` -- exactly
    `oss_config._ignore_rule`'s shape before this issue -- must be caught
    even though no single line carries both the literal list and the spawn
    call."""
    source = (
        "import subprocess\n"
        "\n"
        "def f(root):\n"
        "    command = ['git', '-C', str(root), 'check-ignore', '-v']\n"
        "    return subprocess.run(command)\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.py"
        path.write_text(source, encoding="utf-8")
        hits = _scan_file(path)
        kinds = [kind for _lineno, kind, _name in hits]
        assert "argv-literal-bound" in kinds, (source, hits)


def test_bound_non_literal_argv_is_not_flagged():
    """Must-not-fire control for the same case: a variable bound to
    anything other than a literal `["git"/"gh", ...]` list -- here, the
    already-resolved-executable shape every converted call site in this
    codebase uses -- must not be flagged just because it is later handed to
    a spawn by name."""
    source = (
        "import subprocess\n"
        "\n"
        "def f(root, git_bin):\n"
        "    command = [git_bin, '-C', str(root), 'status']\n"
        "    return subprocess.run(command)\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "h.py"
        path.write_text(source, encoding="utf-8")
        hits = _scan_file(path)
        assert hits == [], hits


def test_an_unreadable_or_unparseable_file_is_reported_as_could_not_scan():
    """The third state: a file this sweep cannot read or parse must render
    as `could-not-scan`, never silently as `clean` -- the defect class this
    whole repository is named after, one function up from the finding it
    exists to catch."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "broken.py"
        bad.write_text("def f(:\n    pass\n", encoding="utf-8")
        assert _scan_file(bad) is None


if __name__ == "__main__":
    sys.exit(0)
