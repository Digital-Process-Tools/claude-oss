"""#350 -- no test may assert against a literal equal to this repo's current version.

`tests/test_oss_workspace_launcher_289.py` carried `assert ours_version == "0.6.0"`.
It passed for the whole of the 0.6.0 cycle, for the wrong reason: the value under
test came from a global that read this repository's own manifest, so the assertion
was `<the current version> == <a literal spelling of the current version>`. The
first thing a release does is bump that manifest, so the assertion reddened on the
release commit itself -- after the fold had already emptied `changelog.d/`, which is
the most expensive moment in the cycle to discover anything.

**The guard is worth more than the fix**, because the fix is one call site and the
class is every test file. So: no string literal *in code* anywhere under `tests/`
may equal the version `.claude-plugin/plugin.json` currently declares.

Three deliberate narrowings, each of which is the difference between a guard and a
nuisance that gets disabled within a week:

* **Code only.** Docstrings and comments are excluded, because narrative about a
  past release is a legitimate and permanent use --
  `test_release_gate_unmeasured_clean_280.py` opens by describing what happened
  during the 0.6.0 gate, and always will. Comments never reach the AST; docstrings
  are recognised and dropped by identity.
* **Exact equality, not containment.** `0.1.0` in a cache-path fixture is fine and
  must stay fine; that fixture is #350's own named trap. Only the version the
  manifest declares *right now* is refused, so a fixture is caught at the moment it
  becomes ambiguous and never before.
* **A named exception list with a reason each**, and a test that fails when an entry
  stops being an exception -- an exception list that has drifted is a licence.

What this cannot catch, said out loud rather than implied: a test that reads the
current version at runtime and asserts something wrong about it, and a literal
spelled in pieces or built by concatenation. Both are out of reach of a literal
scan, and neither is the class that cost a release.
"""

import ast
import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# A version string this repository cannot reach, used as the scanner's own subject
# in the control tests below. A plausible one (`1.2.3`) would make this very file an
# offender on the day the repo reached it -- the guard tripping over itself.
CONTROL = "0.0.0-scanner-control"

# path relative to tests/ -> why a literal equal to the CURRENT version is correct
# there. Empty today. An entry that no longer contains the literal is a failure, not
# a shrug: it means the reason expired and nobody removed it.
ALLOWED = {}


def _docstring_nodes(tree):
    """Every string constant that is a docstring, by identity.

    A docstring is the first statement of a module, class or function when that
    statement is a bare string expression. Matching by identity rather than by value
    means a docstring does not accidentally excuse an identical literal used as an
    argument elsewhere in the same file.
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def scan_source(source, version):
    """Line numbers of code string literals in `source` exactly equal to `version`.

    Raises `SyntaxError` when `source` does not parse -- the caller decides what an
    unparseable file means, rather than this returning an empty list and letting
    "could not look" render as "looked and found nothing".
    """
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        if node.value == version:
            hits.append(node.lineno)
    return sorted(hits)


def current_version():
    """The version to scan against, or a loud failure saying nothing was scanned."""
    manifest = REPO_ROOT / ".claude-plugin" / "plugin.json"
    try:
        raw = manifest.read_text(encoding="utf-8")
    except OSError as exc:
        pytest.fail(
            "could not read {} ({}: {}), so NOT ONE test file was scanned for a "
            "hardcoded version. That is the third state, not a pass.".format(
                manifest, exc.__class__.__name__, exc
            )
        )
    try:
        version = json.loads(raw).get("version")
    except (ValueError, AttributeError) as exc:
        pytest.fail(
            "could not read a version out of {} ({}: {}), so NOT ONE test file was "
            "scanned. That is the third state, not a pass.".format(
                manifest, exc.__class__.__name__, exc
            )
        )
    if not isinstance(version, str) or not version:
        pytest.fail(
            "{} declares no usable version ({!r}), so there was nothing to scan the "
            "test files against. That is the third state, not a pass.".format(
                manifest, version
            )
        )
    return version


def test_the_scanner_fires_on_the_shape_that_cost_a_release():
    """Positive control. Without it the sweep below passes on an empty tree, on an
    AST walk that visits nothing, and on a comparison that is never true."""
    source = "def test_x():\n    assert ours_version == \"0.0.0-scanner-control\"\n"
    assert scan_source(source, CONTROL) == [2]


def test_the_scanner_does_not_fire_on_the_two_legitimate_shapes():
    """The must-not-fire half, and the half that decides whether this guard survives
    contact: both shapes below exist in this repository today."""
    # A cache-path fixture pinned at an old release -- #350's own named trap.
    fixture = "def test_x():\n    assert seg(\"/oss/0.1.0/bin/x\") == \"0.1.0\"\n"
    assert scan_source(fixture, CONTROL) == []

    # Narrative prose in a docstring, and in a comment, about a release that
    # happened. Neither can be rewritten and neither is a defect.
    narrative = (
        "\"\"\"What went wrong during the 0.0.0-scanner-control gate.\"\"\"\n"
        "\n"
        "def test_x():\n"
        "    \"\"\"The 0.0.0-scanner-control cycle is why this exists.\"\"\"\n"
        "    # 0.0.0-scanner-control shipped this by accident.\n"
        "    assert True\n"
    )
    assert scan_source(narrative, CONTROL) == []

    # And the same literal in CODE in that same file is still caught, so excluding
    # docstrings excused the sentence rather than the file.
    assert scan_source(narrative + "    x = \"0.0.0-scanner-control\"\n", CONTROL) == [7]


def _python_files(root=None):
    """Every `*.py` under `root` (default `tests/`), plus every directory that could
    not be walked.

    `Path.rglob` swallows `PermissionError` while walking and yields nothing for the
    subtree, so a sweep built on it returns the same empty list for "read the whole
    tree, no offenders" and "could not read the tree" -- this repository's own
    defect class, and the reason `doctor._workflow_scan` returns two lists rather
    than one. `os.walk(onerror=...)` is the only walk that can speak.
    """
    root = TESTS_DIR if root is None else Path(root)
    files = []
    unwalkable = []

    def _onerror(exc):
        unwalkable.append(
            "{}: could not be walked ({})".format(
                getattr(exc, "filename", "<unknown>"), exc.__class__.__name__
            )
        )

    for dirpath, _dirnames, filenames in os.walk(str(root), onerror=_onerror):
        for name in filenames:
            if name.endswith(".py"):
                files.append(Path(dirpath) / name)
    return sorted(files), unwalkable


def test_the_walk_reports_a_subtree_it_could_not_read(tmp_path):
    """The must-fire half of the walk's own third state, measured rather than
    assumed -- and the must-not-fire half in the same fixture."""
    root = tmp_path / "tests"
    (root / "readable").mkdir(parents=True)
    (root / "readable" / "a_test.py").write_text("x = 1\n", encoding="utf-8")
    denied = root / "denied"
    denied.mkdir()
    (denied / "b_test.py").write_text("x = 1\n", encoding="utf-8")

    # Must not fire, before the deny: an ordinary tree reports no unwalkable entry
    # and does find both files. Without this the assertion below passes against a
    # walk that reports every directory as unreadable.
    files, unwalkable = _python_files(root)
    assert unwalkable == [], unwalkable
    assert sorted(p.name for p in files) == ["a_test.py", "b_test.py"], files

    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "could not remove the mode bits ({}); what went untested is whether an "
            "unreadable subtree is reported rather than silently skipped".format(exc)
        )
    try:
        # Confirm the deny actually took -- root ignores the mode bit, some
        # filesystems ignore it, and Windows' chmod on a directory toggles a
        # read-only attribute that does not stop a listing.
        try:
            os.listdir(str(denied))
            took = False
        except OSError:
            took = True
        if not took:
            pytest.skip(
                "this platform still listed a 0o000 directory, so no unreadable "
                "subtree could be produced; what went untested is whether the walk "
                "reports one rather than silently yielding nothing for it"
            )

        files, unwalkable = _python_files(root)
        assert unwalkable, "the walk hit an unreadable subtree and said nothing"
        assert "denied" in " ".join(unwalkable), unwalkable
        assert [p.name for p in files] == ["a_test.py"], files
    finally:
        os.chmod(str(denied), 0o700)


def test_no_test_file_pins_the_current_version():
    version = current_version()
    offenders = []
    files, unscannable = _python_files()
    scanned = 0
    for path in files:
        rel = path.relative_to(TESTS_DIR).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            unscannable.append(
                "{}: unreadable ({})".format(rel, exc.__class__.__name__)
            )
            continue
        try:
            hits = scan_source(source, version)
        except SyntaxError as exc:
            unscannable.append("{}: does not parse ({})".format(rel, exc))
            continue
        scanned += 1
        if hits and rel not in ALLOWED:
            offenders.append("{}:{}".format(rel, ",".join(str(n) for n in hits)))

    assert not unscannable, (
        "these test files could not be scanned, so whether they pin the current "
        "version is unknown rather than clean: {}".format("; ".join(unscannable))
    )
    # A sweep that looked at nothing is not a clean sweep. This file is always one
    # of them, so the floor is not zero.
    assert scanned > 1, "the sweep read {} test file(s); that is not a result".format(
        scanned
    )
    assert not offenders, (
        "these test files spell this repository's current version ({}) as a code "
        "literal, so they will redden on the release commit that bumps it -- after "
        "the fold has emptied changelog.d/. Derive it from "
        ".claude-plugin/plugin.json, or use a version this repository will not reach "
        "(9.9.9 is the convention here): {}".format(version, ", ".join(offenders))
    )


def test_every_exception_is_still_an_exception():
    """An allow-list entry that no longer contains the literal is stale, and a stale
    entry is a licence for the next one."""
    version = current_version()
    checked = 0
    for rel, reason in sorted(ALLOWED.items()):
        assert reason.strip(), "{} is allow-listed with no reason".format(rel)
        path = TESTS_DIR / rel
        assert path.is_file(), "{} is allow-listed and does not exist".format(rel)
        assert scan_source(path.read_text(encoding="utf-8"), version), (
            "{} is allow-listed for spelling the current version and no longer does "
            "-- remove the entry rather than leaving it standing".format(rel)
        )
        checked += 1

    # The loop above is vacuous while ALLOWED is empty, and a vacuous loop is this
    # repository's own defect class. Say which of the two states this run was in,
    # and prove the staleness test itself can fail, on a synthetic entry.
    if checked == 0:
        assert scan_source("def test_x():\n    assert True\n", version) == [], (
            "the staleness check is unexercised (ALLOWED is empty) and its own "
            "control did not behave"
        )
