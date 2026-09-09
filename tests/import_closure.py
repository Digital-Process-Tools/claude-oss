"""The on-disk local-import closure two launcher-fixture suites both need
(#1237 follow-up to #1229/#1064): every module under a `scripts_dir`
reachable from a set of seed module names, by following local imports --
static `import x` / `from x import y`, plus a string-literal
`importlib.import_module("x")` or `__import__("x")` call (#1236) -- to a
fixed point, via `ast.parse` alone, so nothing here is executed.

Lived first as `tests/test_workspace_doctor_route_receipt_1064.py`'s own
private `_local_import_closure`. #1237 found `tests/test_workspace_routes_
launcher_1155.py` still carrying a hand-kept `_REAL_MODULES` list -- the
exact gap #1229 already paid for once, on the sibling file -- and pulling
the derivation out to one shared module is what stops a second copy from
drifting the same way the first one did (this repo's own CLAUDE.md names
that as the standing failure mode, not a hypothetical one).

A dotted submodule of a local name, or a relative import, is never
followed -- this repo's `scripts/` modules use neither.
"""

import ast


def _string_literal(node):
    """The literal string an ``ast`` argument node holds, or ``None`` --
    covers both ``ast.Constant`` (3.8+) and never assumes a older node
    shape this repo's floor does not need to support."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _import_call_func(node):
    """True if ``node``'s callee is the ``importlib.import_module`` or
    ``__import__`` shape this closure knows how to follow -- independent of
    whether the argument itself turns out to be a literal. Used to tell
    "not an import call at all" apart from "an import call with an argument
    this closure declines to follow" (#1326): both used to render the
    identical ``[]`` from ``_call_candidates`` alone, with nothing to tell a
    caller which one actually happened."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "__import__":
        return True
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Name)
        and func.value.id == "importlib"
    ):
        return True
    return False


def _call_candidates(node):
    """The module name(s) a call node names, if it is an
    ``importlib.import_module("x")`` or ``__import__("x")`` call with a
    string-literal first argument -- ``[]`` for anything else, including a
    computed or non-literal argument, which this closure cannot follow
    statically and must not guess at."""
    if not node.args or not _import_call_func(node):
        return []
    literal = _string_literal(node.args[0])
    if literal is None:
        return []
    return [literal.split(".")[0]]


def local_import_closure(seed_names, scripts_dir):
    """Every module under ``scripts_dir`` reachable from ``seed_names`` by
    following an ``import x`` / ``from x import y`` statement, or a
    string-literal ``importlib.import_module(...)`` / ``__import__(...)``
    call, whose ``x`` resolves to another file in ``scripts_dir`` (never a
    dotted submodule of one, and never a relative import). Found via
    ``ast.walk``, so a nested import -- inside a function body, an ``if``,
    a ``try`` -- is followed exactly like a module-level one; it is not
    limited to top-level statements despite this repo's `scripts/` modules
    only ever using those in practice (self-review, #1237/#1236: an
    earlier draft of this docstring, and its own predecessor in `tests/
    test_workspace_doctor_route_receipt_1064.py`, said "top-level" and
    that was never actually true of the implementation). Read via
    ``ast.parse``, so nothing here is executed.

    Returns ``(seen, unresolved)`` -- ``seen`` is the same reached-module
    set this function always returned; ``unresolved`` is a sorted list of
    ``"<module>.py:<lineno>"`` strings, one per ``importlib.import_module``
    / ``__import__`` call this closure found but declined to follow because
    its argument was not a string literal (#1326). Both `[]` (nothing to
    follow) and "declined to follow a real import call" used to render as
    the identical `[]` return, so a caller reading `seen` alone could not
    tell a genuinely complete closure from one that silently gave up on a
    real call it could not resolve -- ``unresolved`` is what lets a caller
    tell the two apart, rather than trusting completeness it cannot see."""
    available = {p.stem: p for p in scripts_dir.glob("*.py")}
    seen = set()
    unresolved = []
    queue = list(seed_names)
    while queue:
        name = queue.pop()
        if name in seen or name not in available:
            continue
        seen.add(name)
        tree = ast.parse(available[name].read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                candidates = [node.module.split(".")[0]]
            elif isinstance(node, ast.Call):
                candidates = _call_candidates(node)
                if not candidates and _import_call_func(node):
                    unresolved.append("{}.py:{}".format(name, node.lineno))
            else:
                continue
            for candidate in candidates:
                if candidate in available and candidate not in seen:
                    queue.append(candidate)
    # Deduplicated as well as sorted: two distinct declined calls on the
    # same physical line (`a(x); b(y)`, or one nested inside the other's
    # arguments) would otherwise render as indistinguishable duplicate
    # strings -- a reviewer finding on this same round (#1326) -- which is
    # exactly the "can a caller tell two different things apart" question
    # this companion list exists to answer.
    return seen, sorted(set(unresolved))
