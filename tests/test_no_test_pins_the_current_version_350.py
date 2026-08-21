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
import warnings
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


# ------------------------------------------------------------------------ #399
#
# A literal equal to the current version and a literal that PINS the current
# version are opposite defects, and the scan above cannot tell them apart. It
# reported `test_freshness.py:59,60,169` on the v0.9.0 release commit -- the
# lexical-versus-numeric fixture (`0.9.0` against `0.10.0`, the minimal
# one-digit/two-digit pair) and a fixture record. None of the three reads this
# repository's manifest; none can redden when it is bumped.
#
# The bound the scan lacks is provenance: does the value this literal is weighed
# against come from THIS repository's declared version? That is not decidable
# statically, so `version_routes` over-approximates it at file granularity -- a
# file with no route to the repository's own version cannot redden on a bump,
# whatever its literals happen to spell.
#
# Two other bounds were measured first, and the second is recorded because it is
# the tempting one:
#
# * **Syntactic position** -- flag a literal only when it is an operand of a
#   comparison whose other side is computed, the exact shape of #350's
#   `assert ours_version == "0.6.0"`. Unreliable:
#   `assert doctor.active_versions(...) == {"supertool": "0.40.0"}`
#   (test_freshness.py:173) is that shape precisely and is fixture data, so the
#   bound would go on reporting collisions as pins.
# * **A route anchored at REPO_ROOT** -- narrower, and it would have MISSED #350
#   itself. That test built its plugin root under `tmp_path`; the defect was
#   that the product read a global instead. So the route is deliberately coarse:
#   any mention at all, fixture manifests included.
#
# What this gives up, said out loud: a test that reaches the repository's own
# version by a route not named in `VERSION_ROUTES` is now exempt, and would
# redden on the release commit -- #350's original cost. Both errors cost the
# same event, and only one of them is armed: when this landed, `0.9.0`, `0.10.0`
# and `0.11.0` were all already spelled as code literals in `tests/`, so the
# over-report was due at each of the next three minor releases, while the
# under-report has never been observed once.

# Spellings by which a test file can reach THIS repository's own declared
# version. An over-approximation on purpose -- it errs toward flagging, and a
# file that merely builds a fixture manifest is included because #350's own
# offender was exactly that shape. It is a list and a list cannot report a route
# it does not contain, which is the residual named above rather than hidden.
VERSION_ROUTES = ("plugin.json", ".claude-plugin", "PLUGIN_ROOT", "plugin_version")


def version_routes(source):
    """Line numbers where `source` shows a route to this repo's own version.

    Code only, on the same argument the literal scan uses: prose describing the
    manifest is not a read of it, and narrative about a past release is
    permanent and legitimate.
    """
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip:
                continue
            if any(route in node.value for route in VERSION_ROUTES):
                hits.append(node.lineno)
        elif isinstance(node, ast.Name):
            if any(route in node.id for route in VERSION_ROUTES):
                hits.append(node.lineno)
        elif isinstance(node, ast.Attribute):
            if any(route in node.attr for route in VERSION_ROUTES):
                hits.append(node.lineno)
    return sorted(hits)


def classify_source(source, version):
    """`(pins, collisions)` -- the literals from `scan_source`, split in two.

    Every hit lands in exactly one bucket and none is dropped, so the split can
    never quietly lose a literal; `test_the_split_loses_nothing` holds that.
    """
    hits = scan_source(source, version)
    if version_routes(source):
        return hits, []
    return [], hits


def sweep(version, root=None):
    """`(pins, collisions, unscannable, scanned)` over every `*.py` under `root`.

    `pins` and `collisions` are `rel:l1,l2` strings, one per file. `unscannable`
    and `scanned` are the third state: a walk that read nothing, or a tree it
    could not parse, must never render as a clean sweep.
    """
    root = TESTS_DIR if root is None else Path(root)
    pins = []
    collisions = []
    files, unscannable = _python_files(root)
    scanned = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            unscannable.append(
                "{}: unreadable ({})".format(rel, exc.__class__.__name__)
            )
            continue
        try:
            file_pins, file_collisions = classify_source(source, version)
        except SyntaxError as exc:
            unscannable.append("{}: does not parse ({})".format(rel, exc))
            continue
        scanned += 1
        for bucket, lines in ((pins, file_pins), (collisions, file_collisions)):
            if lines:
                bucket.append(
                    "{}:{}".format(rel, ",".join(str(n) for n in lines))
                )
    return pins, collisions, unscannable, scanned


def test_a_pin_and_a_colliding_literal_are_told_apart_in_one_sweep(tmp_path):
    """#399's requirement, in one fixture: both shapes present, opposite verdicts.

    A guard that flags both passes a test supplying only the pin, which is how
    this reached a release commit.
    """
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_pin.py").write_text(
        'import doctor\n'
        'def test_x():\n'
        '    assert doctor.plugin_version(doctor.PLUGIN_ROOT) == '
        '"0.0.0-scanner-control"\n',
        encoding="utf-8",
    )
    (root / "test_collision.py").write_text(
        'import doctor\n'
        'def test_y():\n'
        '    assert doctor.compare_versions("0.0.0-scanner-control", '
        '"0.0.0-later") == "behind"\n',
        encoding="utf-8",
    )

    pins, collisions, unscannable, scanned = sweep(CONTROL, root=root)

    assert unscannable == [], unscannable
    assert scanned == 2, scanned
    assert pins == ["test_pin.py:3"], pins
    assert collisions == ["test_collision.py:3"], collisions


def test_the_route_decides_and_not_the_syntax(tmp_path):
    """The sharper control: byte-identical assertions, differing only in whether
    the file carries a route.

    Without it, the pair above also passes on a scan that discriminates by
    syntactic position -- which was measured unreliable and is not what this
    guard does.
    """
    body = 'def test_x():\n    assert value == "0.0.0-scanner-control"\n'
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_routed.py").write_text(
        'MANIFEST = ".claude-plugin/plugin.json"\n' + body, encoding="utf-8"
    )
    (root / "test_unrouted.py").write_text(
        'MANIFEST = "somewhere/else.json"\n' + body, encoding="utf-8"
    )

    pins, collisions, unscannable, scanned = sweep(CONTROL, root=root)

    assert unscannable == [], unscannable
    assert scanned == 2, scanned
    assert pins == ["test_routed.py:3"], pins
    assert collisions == ["test_unrouted.py:3"], collisions


def test_a_route_named_only_in_a_docstring_is_not_a_route(tmp_path):
    """Narrative about the manifest is not a read of it -- the literal scan
    already excludes docstrings for that reason, and so must the route."""
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_prose.py").write_text(
        '"""Describes .claude-plugin/plugin.json and never opens it."""\n'
        'def test_x():\n'
        '    assert value == "0.0.0-scanner-control"\n',
        encoding="utf-8",
    )
    # Must-fire half, same fixture: identical prose, plus the path in CODE.
    (root / "test_code.py").write_text(
        '"""Describes .claude-plugin/plugin.json and then opens it."""\n'
        'MANIFEST = ".claude-plugin/plugin.json"\n'
        'def test_x():\n'
        '    assert value == "0.0.0-scanner-control"\n',
        encoding="utf-8",
    )

    pins, collisions, unscannable, scanned = sweep(CONTROL, root=root)

    assert unscannable == [], unscannable
    assert scanned == 2, scanned
    assert pins == ["test_code.py:4"], pins
    assert collisions == ["test_prose.py:3"], collisions


def test_the_split_loses_nothing(tmp_path):
    """`pins` and `collisions` must partition `scan_source`, not sample it.

    Both buckets are exercised in one run -- a routed file and an unrouted one --
    so the invariant is not checked against a tree where one bucket is always
    empty, and `seen` refuses a vacuous pass.
    """
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_routed.py").write_text(
        'MANIFEST = ".claude-plugin/plugin.json"\n'
        'def test_x():\n'
        '    assert value == "0.0.0-scanner-control"\n',
        encoding="utf-8",
    )
    (root / "test_unrouted.py").write_text(
        'def test_x():\n'
        '    assert value == "0.0.0-scanner-control"\n',
        encoding="utf-8",
    )
    seen = 0
    for path in sorted(root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        pins, collisions = classify_source(source, CONTROL)
        assert sorted(pins + collisions) == scan_source(source, CONTROL), path
        assert not (pins and collisions), path
        seen += 1
    assert seen == 2, seen


def _next_minor(version):
    """`0.8.0` -> `0.9.0`, or None when the version is not three integers.

    Spelled by arithmetic rather than as a literal on purpose: a file naming the
    version this repository is about to reach becomes an offender the day it
    reaches it, and this file carries a route.
    """
    parts = version.split(".")
    if len(parts) != 3:
        return None
    try:
        major, minor, _patch = (int(part) for part in parts)
    except ValueError:
        return None
    return "{}.{}.0".format(major, minor + 1)


def test_the_sweep_is_clean_for_the_version_this_repository_reaches_next():
    """#399's real cost is that the release commit is the worst moment to learn
    this. The next minor is knowable now, so it is asked now.

    `scanned` and `unscannable` are this test's own controls: without them a walk
    that read nothing, or a tree that would not parse, passes as clean.

    It asks about the next MINOR and nothing else, and that gap is deliberate
    rather than an oversight. Measured when this landed: the next major would
    report `test_doctor_inprocess.py`, `test_release_publish.py` and
    `test_release_config.py`, which spell `1.0.0`, `1.1.0` and `1.2.0` in files
    that carry a route -- so a forward sweep over majors would go red today, on
    a question nobody has examined and this diff was not briefed to answer.
    Asserting it here would redden every pull request until somebody edited a
    fixture to make CI green, which is the reflex this repository refuses to
    train. What goes untested is therefore a major bump.
    """
    version = _next_minor(current_version())
    if version is None:
        pytest.skip(
            "the current version ({!r}) is not three integers, so the next minor "
            "could not be derived and whether tests/ pins it went "
            "untested".format(current_version())
        )
    pins, collisions, unscannable, scanned = sweep(version)
    assert unscannable == [], unscannable
    assert scanned > 1, scanned
    assert not pins, (
        "these test files pin {}, the next minor release, so they would redden "
        "the release commit that bumps to it -- and {} colliding literal(s) were "
        "seen alongside them, which are not a defect: {}".format(
            version, len(collisions), ", ".join(pins)
        )
    )


def test_no_test_file_pins_the_current_version():
    version = current_version()
    pins, collisions, unscannable, scanned = sweep(version)
    offenders = [
        entry for entry in pins if entry.rsplit(":", 1)[0] not in ALLOWED
    ]

    assert not unscannable, (
        "these test files could not be scanned, so whether they pin the current "
        "version is unknown rather than clean: {}".format("; ".join(unscannable))
    )
    # A sweep that looked at nothing is not a clean sweep. This file is always one
    # of them, so the floor is not zero.
    assert scanned > 1, "the sweep read {} test file(s); that is not a result".format(
        scanned
    )
    # #399's third state, and it has to be audible or it is an absence this tool
    # produced. A collision is a literal equal to the current version in a file
    # with no route to it: not a defect, and not something this guard can prove
    # harmless either. It is announced for the length of the cycle in which the
    # repository happens to spell it, and stops on its own at the next bump.
    if collisions:
        warnings.warn(
            "{} test file(s) spell the current version ({}) as a code literal "
            "without any route to this repository's own version, so they cannot "
            "redden the release commit and are NOT offenders: {}".format(
                len(collisions), version, ", ".join(collisions)
            ),
            UserWarning,
            stacklevel=1,
        )
    assert not offenders, (
        "these test files spell this repository's current version ({}) as a code "
        "literal AND carry a route to that version ({}), so they will redden on "
        "the release commit that bumps it -- after the fold has emptied "
        "changelog.d/. Derive it from .claude-plugin/plugin.json, or use a version "
        "this repository will not reach (9.9.9 is the convention here): {}".format(
            version, ", ".join(VERSION_ROUTES), ", ".join(offenders)
        )
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
        # A PIN, not merely a hit: after #399 an entry whose literal lost its
        # route is excused by the classifier and no longer needs excusing here.
        pins, _collisions = classify_source(path.read_text(encoding="utf-8"), version)
        assert pins, (
            "{} is allow-listed for pinning the current version and no longer does "
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
