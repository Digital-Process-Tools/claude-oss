"""#1236 -- `tests/import_closure.py`'s `local_import_closure` is `ast`-based
and only ever followed static `ast.Import`/`ast.ImportFrom` nodes, so a
dependency reached only via `importlib.import_module("name")` or
`__import__("name")` (a pattern already live in `scripts/borrowed_
authority.py`, though not on any path this closure's own seeds reach today
-- #1236's own "verified dormant" note) was invisible to it. This is a
direct unit test of the closure itself, isolated from the two launcher-
fixture suites (#1064, #1155) that consume it, using throwaway fixture
modules rather than anything in the real `scripts/` tree.

Both call shapes are covered, plus the negative control every "must not
follow" claim in this repo needs: a non-literal argument (a name, not a
string) must not be treated as though it named a module, because that
would be guessing at a value this closure cannot see statically.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import import_closure  # noqa: E402


def _write(dir_path, name, body):
    (dir_path / (name + ".py")).write_text(body, encoding="utf-8")


def test_importlib_import_module_with_a_string_literal_is_followed(tmp_path):
    """MUST FIRE: `importlib.import_module("target")` names a real local
    module, and the closure must reach it even though no `ast.Import` or
    `ast.ImportFrom` node names it anywhere."""
    _write(tmp_path, "seed", "import importlib\nimportlib.import_module('target')\n")
    _write(tmp_path, "target", "x = 1\n")

    reached = import_closure.local_import_closure(["seed"], tmp_path)

    assert reached == {"seed", "target"}


def test_dunder_import_with_a_string_literal_is_followed(tmp_path):
    """MUST FIRE: the `__import__("target")` builtin-call spelling, the
    other shape #1236 names."""
    _write(tmp_path, "seed", "__import__('target')\n")
    _write(tmp_path, "target", "x = 1\n")

    reached = import_closure.local_import_closure(["seed"], tmp_path)

    assert reached == {"seed", "target"}


def test_a_non_literal_importlib_argument_is_not_followed(tmp_path):
    """MUST NOT FIRE (negative control): a computed argument -- a name, not
    a string constant -- cannot be resolved statically, and treating it as
    though it named `target` would be a guess this closure must not make.
    `target` exists on disk and is never reached, proving the closure
    genuinely evaluated the argument shape rather than following anything
    reachable by that name."""
    _write(
        tmp_path,
        "seed",
        "import importlib\nname = 'target'\nimportlib.import_module(name)\n",
    )
    _write(tmp_path, "target", "x = 1\n")

    reached = import_closure.local_import_closure(["seed"], tmp_path)

    assert reached == {"seed"}


def test_static_imports_still_work_alongside_the_new_call_forms(tmp_path):
    """Ordinary `import x` is unaffected by the extension -- same behaviour
    as before #1236."""
    _write(tmp_path, "seed", "import target\n")
    _write(tmp_path, "target", "x = 1\n")

    reached = import_closure.local_import_closure(["seed"], tmp_path)

    assert reached == {"seed", "target"}
