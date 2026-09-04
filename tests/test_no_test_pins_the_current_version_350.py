"""#350 -- no test may assert against a literal equal to this repo's current version.

`tests/test_oss_workspace_launcher_289.py` carried `assert ours_version == "0.6.0"`.
It passed for the whole of the 0.6.0 cycle, for the wrong reason: the value under
test came from a global that read this repository's own manifest, so the assertion
was `<the current version> == <a literal spelling of the current version>`. The
first thing a release does is bump that manifest, so the assertion reddened on the
release commit itself -- after the fold had already emptied `changelog.d/`, which is
the most expensive moment in the cycle to discover anything.

**The guard is worth more than the fix**, because the fix is one call site and the
class is every test file. So: no test file under `tests/` may **pin** the version
`.claude-plugin/plugin.json` currently declares.

**Pin, not merely spell** -- and that distinction is #399's, not #350's. Until
then the rule was the literal one, any code literal equal to the current version,
and it reported the opposite defect at the worst possible moment: cutting `v0.9.0`
it named `test_freshness.py:59,60,169`, three version-comparison fixtures that
read no manifest and cannot redden when one is bumped. A literal that pins and a
literal that merely collides must be handled in opposite ways, so the guard has to
tell them apart. It does that with `version_routes`, and the reasoning, the two
bounds measured and rejected first, and what the chosen one gives up are argued at
length beside that function rather than repeated here.

Four deliberate narrowings, each of which is the difference between a guard and a
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
* **A route to this repository's own version**, added by #399. A file that never
  reaches the version the manifest declares cannot redden when it is bumped,
  whatever its literals happen to spell, so only a file that does reach it is
  weighed. `VERSION_ROUTES` over-approximates that on purpose.

Three outcomes, not two, because a hit this guard declines to fail on is still a
hit and an absence it produced would be this repository's own defect class: a
**pin** fails; a **collision** is announced by name as a `UserWarning` saying it is
not an offender, for the length of the cycle in which the repository happens to
spell it; and a file that could not be walked, read or parsed is `unscannable`,
which is neither.

What this cannot catch, said out loud rather than implied: a test that reads the
current version at runtime and asserts something wrong about it; a literal spelled
in pieces or built by concatenation; and, since #399, a test that reaches this
repository's own version by a route `VERSION_ROUTES` does not name. The first two
are out of reach of a literal scan. The third is a list, and a list cannot report
what it does not contain -- it is the price of the bound, and the argument for
paying it is beside `version_routes`.
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


def _scan_tree(tree, version):
    """The literal scan over an already-parsed tree -- see `scan_source`."""
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


def scan_source(source, version):
    """Line numbers of code string literals in `source` exactly equal to `version`.

    Raises `SyntaxError` when `source` does not parse -- the caller decides what an
    unparseable file means, rather than this returning an empty list and letting
    "could not look" render as "looked and found nothing".
    """
    return _scan_tree(ast.parse(source), version)


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


def _routes_tree(tree):
    """The route scan over an already-parsed tree -- see `version_routes`."""
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
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            # A rename hides the route from every use site: after
            # `from doctor import PLUGIN_ROOT as here`, `here` spells nothing and
            # the import is the only place left to read it. The import node is
            # inspected rather than the `ast.alias` under it because `alias`
            # carries no `lineno` before 3.10 and CI runs 3.9.
            names = [getattr(node, "module", None) or ""]
            for alias in node.names:
                names.append(alias.name or "")
                names.append(alias.asname or "")
            if any(route in name for name in names for route in VERSION_ROUTES):
                hits.append(node.lineno)
    return sorted(hits)


def version_routes(source):
    """Line numbers where `source` shows a route to this repo's own version.

    Code only, on the same argument the literal scan uses: prose describing the
    manifest is not a read of it, and narrative about a past release is
    permanent and legitimate.
    """
    return _routes_tree(ast.parse(source))


def classify_source(source, version):
    """`(pins, collisions)` -- the literals from `scan_source`, split in two.

    Every hit lands in exactly one bucket and none is dropped, so the split can
    never quietly lose a literal; `test_the_split_loses_nothing` holds that.

    Parses `source` once and shares the tree between the literal scan and the
    route scan -- `sweep()` calls this once per file, and each used to
    `ast.parse` the same source independently (#933).
    """
    tree = ast.parse(source)
    hits = _scan_tree(tree, version)
    if _routes_tree(tree):
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


def test_a_route_renamed_on_import_is_still_a_route(tmp_path):
    """`from doctor import PLUGIN_ROOT as here` binds the route to a name that no
    longer spells it, and every use site is then an ordinary local. The import
    statement is the only place the route is still visible, so it has to be read
    -- otherwise a genuine pin is waved through as a collision by an ordinary
    rename, which is #350's original cost arriving through #399's fix.

    The import node is inspected rather than the `ast.alias` under it: `alias`
    carries no `lineno` before Python 3.10, and CI runs 3.9.
    """
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_aliased.py").write_text(
        'from doctor import PLUGIN_ROOT as here\n'
        'def test_x():\n'
        '    assert str(here) == "0.0.0-scanner-control"\n',
        encoding="utf-8",
    )
    # Must-not-fire half, same shape: importing something that is not a route,
    # under the same alias. Without it this passes on a scan that calls every
    # `from ... import ... as ...` a route.
    (root / "test_unrelated.py").write_text(
        'from doctor import compare_versions as here\n'
        'def test_x():\n'
        '    assert str(here) == "0.0.0-scanner-control"\n',
        encoding="utf-8",
    )

    pins, collisions, unscannable, scanned = sweep(CONTROL, root=root)

    assert unscannable == [], unscannable
    assert scanned == 2, scanned
    assert pins == ["test_aliased.py:3"], pins
    assert collisions == ["test_unrelated.py:3"], collisions


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
    pinned = 0
    collided = 0
    for path in sorted(root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        pins, collisions = classify_source(source, CONTROL)
        assert sorted(pins + collisions) == scan_source(source, CONTROL), path
        assert not (pins and collisions), path
        pinned += len(pins)
        collided += len(collisions)
        seen += 1
    assert seen == 2, seen
    # The partition holds trivially for a classifier that sends everything one
    # way, so the invariant alone is not a result: both buckets have to have been
    # reached in this run for it to be a statement about a split at all.
    assert pinned == 1, pinned
    assert collided == 1, collided


def _minor_after(version, steps):
    """`_minor_after("0.8.0", 1)` -> `"0.9.0"`, `_minor_after("0.8.0", 2)` ->
    `"0.10.0"`, or None when `version` is not three integers.

    Spelled by arithmetic rather than as a literal on purpose: a file naming the
    version this repository is about to reach becomes an offender the day it
    reaches it, and this file carries a route. `steps` is how many minors ahead
    to look -- `_next_minor` below is `steps=1`, and #901 adds a `steps=2`
    WARNING-only horizon beside it (see `warn_on_far_horizon_pins`).
    """
    parts = version.split(".")
    if len(parts) != 3:
        return None
    try:
        major, minor, _patch = (int(part) for part in parts)
    except ValueError:
        return None
    return "{}.{}.0".format(major, minor + steps)


def _next_minor(version):
    """`0.8.0` -> `0.9.0`, or None when the version is not three integers.

    `_minor_after(version, 1)`, kept as its own name because it feeds the
    FAILING sweep below and every caller of that sweep names `_next_minor`.
    """
    return _minor_after(version, 1)


def warn_on_far_horizon_pins(pins, horizon):
    """#901: a literal beyond the one-minor horizon is a third state the
    pass/fail sweep cannot express -- not wrong today, not right either. This
    reports it as a `UserWarning` naming the pins and the horizon, the same
    "announce, never fail" mechanism `test_no_test_file_pins_the_current_
    version` already uses for a collision, so a pull request introducing one
    is told and nothing reddens. Widening the FAILING sweep itself was tried
    and reverted for majors -- see the docstring on
    `test_the_sweep_is_clean_for_the_version_this_repository_reaches_next` --
    and a horizon of two minors would hit the identical failure mode one step
    further out, which is why this stays a warning rather than a second
    assertion.
    """
    if not pins:
        return
    warnings.warn(
        "{} test file(s) pin {}, two minors beyond the current version -- not "
        "an offender yet, but it will redden the release commit that bumps "
        "this repository into range unless fixed first: {}".format(
            len(pins), horizon, ", ".join(pins)
        ),
        UserWarning,
        stacklevel=1,
    )


def test_the_sweep_is_clean_for_the_version_this_repository_reaches_next():
    """#399's real cost is that the release commit is the worst moment to learn
    this. The next minor is knowable now, so it is asked now.

    `scanned` and `unscannable` are this test's own controls: without them a walk
    that read nothing, or a tree that would not parse, passes as clean.

    It FAILS about the next MINOR and nothing else, and that gap is deliberate
    rather than an oversight. Measured when this landed: the next major would
    report `test_doctor_inprocess.py`, `test_release_publish.py` and
    `test_release_config.py`, which spell `1.0.0`, `1.1.0` and `1.2.0` in files
    that carry a route -- so a forward sweep over majors would go red today, on
    a question nobody has examined and this diff was not briefed to answer.
    Asserting it here would redden every pull request until somebody edited a
    fixture to make CI green, which is the reflex this repository refuses to
    train. What goes untested is therefore a major bump.

    #901: the one-minor horizon has its own gap one step short of a major --
    v0.20.0's release commit went red on a literal TWO minors out
    (`test_plugin_update_dependencies_605.py` landed `0.21.0` while the current
    version was `0.19.0`), invisible to this assertion until the bump moved it
    into range. Widening the FAILING horizon to two minors was considered and
    declined: it has the identical failure mode as the major case above, one
    step further out, just not measured to the same degree yet -- so instead
    this function also runs a WARNING-only sweep two minors out, below, using
    the same "announce, never fail" mechanism `test_no_test_file_pins_the_
    current_version` already has for a collision. Moving the question into
    `/oss:release`'s own version-sites sweep (`commands/release.md` gate 4,
    `git grep -n "<the new version>"`) was also considered and declined: that
    sweep is scoped to `version_sites` -- the specific files a release bump
    writes into -- not to `tests/` in general, where this defect actually
    lives, so folding it in would need its own separate release-time check
    rather than an extension of an existing one. A warning inside the suite
    that already asks this question, at the moment #399 says to ask it, costs
    less than either alternative.
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

    # #901: the one-minor horizon above is a hard floor, not the whole answer --
    # v0.20.0's release commit went red on a literal TWO minors out, invisible
    # to the assertion above until the bump moved it into range. Reported here
    # as a WARNING, never a failure, at exactly the point #399's own docstring
    # says is knowable now: see `warn_on_far_horizon_pins`.
    far_horizon = _minor_after(current_version(), 2)
    if far_horizon is not None:
        far_pins, _far_collisions, far_unscannable, far_scanned = sweep(far_horizon)
        assert far_unscannable == [], far_unscannable
        assert far_scanned > 1, far_scanned
        warn_on_far_horizon_pins(far_pins, far_horizon)


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
        clean = "def test_x():\n    assert True\n"
        assert scan_source(clean, version) == [], (
            "the staleness check is unexercised (ALLOWED is empty) and its own "
            "control did not behave"
        )
        # The loop above is the only caller of `classify_source` in this test, so
        # while ALLOWED is empty the #399 rewiring is never reached. Exercise it
        # on a synthetic entry of each shape, or an allow-list entry excused by a
        # broken classifier the day somebody adds one would go unnoticed.
        routed = 'M = ".claude-plugin/plugin.json"\ndef test_x():\n    assert v == "{}"\n'
        assert classify_source(routed.format(version), version) == ([3], []), (
            "a routed literal is a pin, and the staleness check reads pins"
        )
        assert classify_source(clean, version) == ([], []), (
            "a file with no literal at all must produce neither bucket"
        )


def test_minor_after_generalizes_next_minor():
    """`_minor_after(v, 1)` must be `_next_minor(v)` -- the new helper is a
    generalization, not a parallel implementation that can drift from it."""
    assert _minor_after("0.8.0", 1) == _next_minor("0.8.0")
    assert _minor_after("0.8.0", 2) == "0.10.0"
    assert _minor_after("bad", 2) is None


def test_a_literal_two_minors_out_warns_rather_than_fails(tmp_path):
    """#901: v0.20.0's own release commit went red on a literal TWO minors
    out (`0.21.0`, landed by #605 while the current version was `0.19.0`) --
    invisible to the one-minor sweep, which fires only once the version bump
    moves it into range. Widening the FAILING horizon was already tried and
    reverted for majors (see the docstring on
    `test_the_sweep_is_clean_for_the_version_this_repository_reaches_next`),
    so this widens a WARNING-only horizon instead: a pull request that lands
    such a literal is told about it, and nothing reddens.

    Must-fire and must-not-fire in the same fixture, synthetic and isolated
    from this repository's real tests/ tree so the assertion does not depend
    on what tests/ happens to spell today.
    """
    horizon = _minor_after("1.2.3", 2)
    assert horizon == "1.4.0"

    offender = tmp_path / "offender"
    offender.mkdir()
    (offender / "test_x.py").write_text(
        'M = ".claude-plugin/plugin.json"\n'
        'def test_x():\n    assert v == "{}"\n'.format(horizon),
        encoding="utf-8",
    )
    pins, _collisions, unscannable, scanned = sweep(horizon, root=offender)
    assert unscannable == []
    assert scanned == 1
    assert pins, "the synthetic fixture must actually pin the horizon literal"

    with pytest.warns(UserWarning, match=horizon):
        warn_on_far_horizon_pins(pins, horizon)

    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "test_y.py").write_text("def test_y():\n    assert True\n", encoding="utf-8")
    pins2, _c2, _u2, _s2 = sweep(horizon, root=clean)
    assert pins2 == [], "the must-not-fire control pins the horizon literal too"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_on_far_horizon_pins(pins2, horizon)
        assert caught == [], "no pins beyond the horizon; nothing should warn"


def test_the_real_sweep_two_minors_out_is_reported_as_a_warning_not_a_failure():
    """The integration half: run the same warning-only sweep against this
    repository's real tests/ tree, at the actual two-minors-out horizon.
    Never asserts `not pins` -- that would be exactly the failing horizon
    #901 says not to widen -- it only proves the call does not raise and
    reports via `UserWarning` when there is something to report.
    """
    horizon = _minor_after(current_version(), 2)
    if horizon is None:
        pytest.skip(
            "the current version ({!r}) is not three integers, so the "
            "two-minors-out horizon could not be derived".format(current_version())
        )
    pins, _collisions, unscannable, scanned = sweep(horizon)
    assert unscannable == [], unscannable
    assert scanned > 1, scanned
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_on_far_horizon_pins(pins, horizon)
    if pins:
        assert any(horizon in str(w.message) for w in caught), caught
    else:
        assert caught == []
