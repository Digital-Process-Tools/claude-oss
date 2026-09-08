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
IS to call `shutil.which`) for two syntactic shapes, via `ast` rather than
a text grep -- precise about *which* `shutil.which`/`subprocess.run` are
meant, not about indentation or quoting style:

1. `shutil.which("gh")` / `shutil.which("git")` -- a literal-string call,
   anywhere outside `gh_which.py`.
2. `subprocess.run(...)` / `subprocess.Popen(...)` / `.call(...)` /
   `.check_call(...)` / `.check_output(...)`, called as `subprocess.<name>`
   specifically (never a same-named local wrapper -- see below), whose
   first positional argument is a list/tuple literal (optionally
   concatenated with `+` onto something else) whose first element is the
   literal string `"gh"` or `"git"`.

Both are grep-equivalent in spirit (the issue's own suggested fix says
"grep-based is fine") but ast-based in practice, because a plain grep for
`"gh"`/`"git"` inside a docstring or a `#` comment -- of which this
codebase's own `gh_which`-migration commentary has dozens -- would drown
the real hits.

**What this sweep cannot see, by construction, and does not claim to.**
Case 2 only fires on a DIRECT `subprocess.*` call. A local wrapper --
`oss_config._run`, `scaffold._run`, `statusline._run`, each accepting a
bare `["git", ...]` list and resolving (or not) internally before ITS OWN
`subprocess.run` call -- is invisible to a single-function, non-dataflow
scan; tracing that would mean interprocedural analysis, which is well past
"grep-based is fine". Some of those wrappers already resolve safely
(`release_delta._git`, `plugin_update._run`, `doctor_check_branch_
protection._gh_api`, `select_issues_claim_read._run`, all confirmed by
reading them for this issue); others do not yet
(`doctor_check_clone_head._git_run`'s own `run` parameter defaults to the
real `subprocess.run`, unconverted). That gap is real and is exactly
`_ALLOWED` below's job to hold by name rather than let this sweep either
false-positive on a wrapper's own internal list literal or silently miss a
wrapper's un-resolved default.

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


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.hits = []

    def visit_Call(self, node):
        func = node.func
        is_subprocess_call = (
            isinstance(func, ast.Attribute)
            and func.attr in _SPAWN_ATTRS
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        )
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
        if is_subprocess_call and node.args:
            first = _unwrap_concat(node.args[0])
            if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
                name = _literal_str(first.elts[0])
                if name in _BAD_NAMES:
                    self.hits.append((node.lineno, "argv-literal", name))
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
    visitor = _Visitor()
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
