"""One place where a spawn that never answered stops looking like a wrong answer.

#712 fixed this in exactly one site. `tests/test_oss_rules.py`'s `_ere_matches`
spawned `awk` with `timeout=10`; a Windows runner did not answer inside ten
seconds, the `subprocess.TimeoutExpired` propagated uncaught, and pytest reported
a **failed ERE assertion** on a release commit that touched neither the rule, the
pattern nor the function under test. The defect was never the timeout. It is that
a spawn producing no answer rendered identically to one producing the wrong
answer, and this repository's whole subject is not letting those share a verdict.

#716 is the sweep that one fix asked for: about fifty spawns in `tests/` carry a
`timeout=`, and most of them let it escape.

## Two halves

`run()` is the runtime half -- `subprocess.run` with one behaviour changed. Only
the no-answer case: a non-zero exit is a real answer about a real invocation and
still comes back for the caller to assert on, `check=True` still raises, and an
unspawnable binary still raises `OSError`, because that is a different finding and
several call sites already have their own sentence for it.

`scan_source()` / `scan_tree()` are the static half. Fourteen hand-written skip
messages drift and a guard hand-named at one site goes quietly narrower than its
subject the next time the set grows -- which is exactly what happened between #712
and #716. So the sweep is re-derived from the tree on every run rather than
recorded as a list.

## What the static half deliberately cannot see

Stated rather than left as silence, because an analyzer's silence and a clean tree
render identically, which is the defect this module is named after:

- **A spawn with no `timeout=` at all.** That hangs rather than misreports; a
  different defect, and not this one. It is not counted and not reported.
- **A `timeout` arriving through `**kwargs`** or held in a variable. The kwarg is
  matched by name in the call's own AST; nothing here evaluates anything.
- **A spawn reached through a name this module's `import` statements did not bind.**
  Aliases and `from` imports ARE resolved -- see `_Bindings` -- but a spawn stored in
  a dict, returned by a factory or reached through a class attribute is not.
- **`Popen(...).communicate(timeout=...)`.** Measured at the time of writing:
  `tests/` contains no `communicate` or `wait` call on a `Popen`, so the shape is
  out of the analyzer rather than silently mishandled by it. If one appears, this
  is the paragraph that is wrong.
- **Whether a `pytest.skip` actually follows the `except`.** A handler that
  catches the timeout and then asserts something anyway would pass this check.
  That is a judgement about a body, not a shape.

Python 3.9 compatible.
"""

import ast
import collections
import os
import subprocess
import sys
from functools import lru_cache

import pytest

#: Handler types that genuinely catch a `subprocess.TimeoutExpired`. Measured, not
#: reasoned from names: `TimeoutExpired -> SubprocessError -> Exception ->
#: BaseException`. Two near misses are deliberately absent -- `OSError`, which
#: several call sites here catch for an unspawnable binary and which is nowhere in
#: that chain, and the builtin `TimeoutError`, which is an `OSError` subclass and
#: has nothing to do with this one.
CATCHES_TIMEOUT = frozenset(
    ("TimeoutExpired", "SubprocessError", "Exception", "BaseException")
)

#: `subprocess.<name>(...)` calls treated as a spawn. `Popen` is here for
#: completeness; see the module docstring for what happens to `communicate`.
SPAWNS = frozenset(("run", "check_output", "check_call", "call", "Popen"))


# --- the runtime half ----------------------------------------------------------------


def skip_reason(argv, exc, subject):
    """The sentence a timed-out spawn skips with.

    Split out from `run()` so it can be read and asserted on without raising, and
    so every converted call site produces the same four facts: which binary, how
    long it was given, which platform said nothing, and what therefore went
    unmeasured. The last is the one a hand-written message loses first.
    """
    command = getattr(exc, "cmd", None) or argv
    if isinstance(command, (list, tuple)):
        shown = " ".join(str(part) for part in command)
    else:
        shown = str(command)
    if len(shown) > 200:
        shown = shown[:200] + " ..."
    return (
        "{} did not answer within {}s on {!r} -- this measures nothing about {}, "
        "and a no-answer is not the same outcome as an answer (#716)".format(
            shown, getattr(exc, "timeout", "?"), sys.platform, subject
        )
    )


def run(argv, *, subject, timeout, **kwargs):
    """`subprocess.run(argv, timeout=timeout, **kwargs)`, with one change.

    `subject` and `timeout` are both required keywords, and neither has a default
    on purpose. A call with no timeout cannot time out and cannot be skipped -- it
    hangs -- so routing one through here must not quietly drop the thing this
    exists to handle. A subject that defaulted would give every converted site the
    same useless skip reason, which is a hand-written message's failure mode
    arriving centrally instead.
    """
    try:
        return subprocess.run(argv, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        # `pytest.skip` raises immediately, which is what skips the WHOLE test
        # rather than one assertion. That is load-bearing wherever a caller has a
        # negative control after the first assertion: a run in which only the
        # "must not fire" half survived would report a passing negative assertion
        # with nothing left proving it can fire.
        pytest.skip(skip_reason(argv, exc, subject))


# --- the static half -----------------------------------------------------------------


Site = collections.namedtuple("Site", "path lineno func")
Unscannable = collections.namedtuple("Unscannable", "path reason")
Scan = collections.namedtuple("Scan", "spawns unguarded unscannable")


def _handler_names(handler):
    """Every class name an `except` clause names, by its last dotted segment.

    `subprocess.TimeoutExpired` and a bare `TimeoutExpired` from a `from ... import`
    are the same handler, so the segment is what is compared -- not the spelling.
    """
    node = handler.type
    if node is None:
        return ["<bare except>"]
    names = []
    for part in node.elts if isinstance(node, ast.Tuple) else [node]:
        if isinstance(part, ast.Attribute):
            names.append(part.attr)
        elif isinstance(part, ast.Name):
            names.append(part.id)
        else:
            names.append("<computed>")
    return names


def _try_catches_timeout(node):
    for handler in node.handlers:
        for name in _handler_names(handler):
            if name == "<bare except>" or name in CATCHES_TIMEOUT:
                return True
    return False


class _Bindings(object):
    """Which local names in one module refer to what.

    Resolved from the module's own `import` statements rather than matched against
    the literal spellings `subprocess.` and `spawn_guard.`. `import subprocess as
    sp` and `from subprocess import run` are both ordinary Python, and an analyzer
    that knows only one spelling reports a file using another as **clean** -- the
    same absence this module exists to stop, one level up in the tool. There is no
    such import in `tests/` today (measured), which is exactly why it was worth
    closing: the first one to arrive would produce no signal at all.
    """

    def __init__(self, tree):
        self.subprocess_modules = set()
        self.bare_spawns = set()
        self.helper_modules = set()
        self.helper_runs = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    if alias.name == "subprocess":
                        self.subprocess_modules.add(bound)
                    elif alias.name == "spawn_guard":
                        self.helper_modules.add(bound)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    for alias in node.names:
                        if alias.name in SPAWNS:
                            self.bare_spawns.add(alias.asname or alias.name)
                elif node.module == "spawn_guard":
                    for alias in node.names:
                        if alias.name == "run":
                            self.helper_runs.add(alias.asname or alias.name)

    def is_spawn(self, call):
        """A bare spawn, which is the shape that can go wrong."""
        func = call.func
        if isinstance(func, ast.Attribute):
            return (
                func.attr in SPAWNS
                and isinstance(func.value, ast.Name)
                and func.value.id in self.subprocess_modules
            )
        return isinstance(func, ast.Name) and func.id in self.bare_spawns

    def is_helper_spawn(self, call):
        """A call into this module's own `run`, which is guarded by construction.

        Counted as a spawn anyway, deliberately. If converting a site removed it
        from the population, the sweep's own positive control -- "did this analyzer
        reach the suite at all" -- would weaken by exactly as much as the fix
        improved things, and a suite in which every site had been converted would
        look identical to one the analyzer never read.
        """
        func = call.func
        if isinstance(func, ast.Attribute):
            return (
                func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id in self.helper_modules
            )
        return isinstance(func, ast.Name) and func.id in self.helper_runs


def scan_source(source, path):
    """`Scan` for one module's text. `path` is carried through for the report only.

    A `SyntaxError` returns an `unscannable` entry rather than an empty result: a
    file nothing could read has not been shown to be clean.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return Scan([], [], [Unscannable(str(path), "does not parse: {}".format(exc))])

    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    bindings = _Bindings(tree)
    spawns = []
    unguarded = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        through_helper = bindings.is_helper_spawn(node)
        if not through_helper and not bindings.is_spawn(node):
            continue
        if not any(kw.arg == "timeout" for kw in node.keywords):
            continue
        func_name = None
        guarded = through_helper
        cursor = node
        while cursor in parents:
            parent = parents[cursor]
            if isinstance(parent, ast.Try) and cursor in parent.body:
                if _try_catches_timeout(parent):
                    guarded = True
                    break
            if func_name is None and isinstance(
                parent, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                func_name = parent.name
            cursor = parent
        site = Site(str(path), node.lineno, func_name or "<module>")
        spawns.append(site)
        if not guarded:
            unguarded.append(site)
    return Scan(spawns, unguarded, [])


@lru_cache(maxsize=8)
def scan_tree(directory):
    """`Scan` over every `*.py` under `directory`.

    Walked with `os.walk(onerror=...)` rather than `Path.rglob`, for the reason
    CLAUDE.md records: pathlib's recursive glob swallows a `PermissionError` while
    walking and yields nothing for that subtree, so an unreadable directory would
    arrive here indistinguishable from an empty one.

    Cached per `directory` -- not the same thing the module docstring warns
    against ("re-derived from the tree on every run rather than recorded as a
    list"), which is about not letting a stale answer ship across runs. This
    only reuses the answer within the lifetime of one process, and `tests/`
    does not change under it mid-run; three sibling tests in
    `test_spawn_guard_716.py` each called this with the identical directory
    and paid a fresh walk-and-parse of the whole tree for it (#933).
    """
    spawns = []
    unguarded = []
    unscannable = []

    def _onerror(exc):
        unscannable.append(
            Unscannable(
                str(getattr(exc, "filename", directory)), "walk failed: {}".format(exc)
            )
        )

    for dirpath, _dirnames, filenames in os.walk(str(directory), onerror=_onerror):
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            full = os.path.join(dirpath, filename)
            try:
                with open(full, "rb") as handle:
                    source = handle.read().decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                unscannable.append(
                    Unscannable(full, "could not be read: {}".format(exc))
                )
                continue
            # Reported relative to the scanned directory's parent, so a finding
            # reads `tests/test_x.py:41` rather than one machine's absolute path.
            shown = os.path.relpath(
                full, os.path.dirname(os.path.abspath(str(directory)))
            )
            scan = scan_source(source, shown)
            spawns.extend(scan.spawns)
            unguarded.extend(scan.unguarded)
            unscannable.extend(scan.unscannable)
    return Scan(spawns, unguarded, unscannable)
