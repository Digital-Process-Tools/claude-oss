"""Does the installed dependency actually read this plugin's rule layer? (#119)

Every observable signal said the `01-oss` layer was healthy -- files on disk, index
rows current, `doctor` listing them, the generator's own tests green. Nothing anywhere
asked *does anything read this directory?*, and the answer was no: up to and including
0.3.5, `claude-jit-context` enumerated layers from a fixed list in three hooks and
`01-oss` was not in it.

**That has since been fixed upstream: 0.4.0 enumerates the layers off disk and no hook
carries a fixed list.** The check is written against the *shape* rather than against a
spelling precisely so that this sentence changing does not make it wrong -- a hook set
with no fixed enumeration answers `could-not-determine`, never `unread`. Line numbers are
deliberately not cited here any more: the three this docstring used to name moved with the
fix, which is the failure mode `agents/developer.md` warns about in general terms and this
file demonstrated in particular.

**What counts as a hook is itself a measurement, and getting that wrong is #241.** The
scan used to read every `*.sh` under the install root, and in 0.4.0 the only match in the
whole tree is line 494 of the dependency's own `tests/test-layer-enumeration.sh` -- a
fixture asserting that its enumerator works, which contains the layer list whether or not
anything enumerates anything. The check therefore printed `reads` for a reason that would
have held equally with the broken fixed list still in the hooks, which is what the first
test below fabricates. Since #241 a hook is what the runtime executes: a script named by a
`command` in the dependency's `hooks/hooks.json`, plus the closure of what those scripts
`source`. Neither half alone is enough and neither is a path convention -- 0.4.0 declares
four entry points under `scripts/` and puts its enumerator in `scripts/common.sh`, which it
declares nowhere and every hook sources, beside four more scripts nothing wires to an event.

Five states, and the third and fourth are the point:

  reads                 a hook's layer enumeration names our layer
  reads-by-glob         a hook enumerates the dimension base by directory glob, so every
                        layer under it is visited -- the shape the upstream fix took, and
                        `OK` since #743 rather than the permanent `unknown` it had become
  unread                every enumeration found in the hook set omits it -- a real gap, WARN
  could-not-determine   nothing was measured: the dependency is not installed, its
                        tree was not found, it carries no hook manifest so nothing
                        separates a hook from a fixture, its manifest resolved to no
                        file, a hook would not read, or no hook carries a fixed
                        enumeration at all -- including the case where the only layer
                        list in the tree sits outside the hook set, which is reported
                        as the reason rather than dropped
  no-layer              this repo has no such layer, so there is nothing to read

`could-not-determine` covers the case that matters most for durability. The upstream
fix (`claude-jit-context#176`) removes the fixed list, so a check keyed on today's
spelling would report `unread` forever after it is fixed -- the same defect inverted.
When no fixed enumeration is found the answer is *unknown*, never *unread* -- and when a
directory glob is found in the hook set, it is `reads-by-glob` rather than either (#743):
holding out for a fixed list after upstream deleted the fixed list made `unknown` terminal,
which costs the verdict line its discrimination the same way a permanent WARN does.

Every hook set below is fabricated. A test that only passes when a particular
dependency version happens to be installed on the runner is a test CI cannot run
honestly, and it would measure the machine rather than the code.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

PLUGIN = "claude-jit-context"
VERSION = "9.9.9"
LAYER = "01-oss"

#: The shape the three real hooks carried up to 0.3.5, verbatim apart from indentation.
#: Fabricated either way -- see the last paragraph of the module docstring for why none of
#: these fixtures is read off the installed dependency.
OMITS = 'split("00-manual 10-auto 20-grouped 30-crosscutting", layers, " ")\n'
#: The same line if upstream simply added our layer to the list.
NAMES = 'split("00-manual 01-oss 10-auto 20-grouped 30-crosscutting", layers, " ")\n'
#: What the upstream fix is expected to look like: no fixed list anywhere.
ENUMERATED = 'for d in "$JIT_BASE/$dim"/*/; do echo "$d"; done\n'
#: The shape of the *fixture* that answered this check for a whole release (#241): a
#: quoted layer list naming our layer, inside a file that enumerates nothing at run time.
#: Deliberately identical in shape to a real enumeration -- the scan must separate the two
#: by what the dependency runs, not by how the line is written.
FIXTURE = 'assert_layers "00-manual 01-oss" "$out"\n'
#: A hook entry point whose own text carries no layer list, reaching one by sourcing.
SOURCES_COMMON = 'SCRIPT_DIR="$(dirname "$0")"\nsource "$SCRIPT_DIR/common.sh"\n'
#: Neither a fixed list nor a directory-glob enumeration -- the genuinely uninformative
#: hook body, used as the negative control for #616's glob-shape detection below.
NEITHER = 'echo "hello"\n'


def _write(target, body):
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, bytes):
        target.write_bytes(body)
    else:
        target.write_text(body, encoding="utf-8")


def _cache(
    tmp_path,
    hooks,
    version=VERSION,
    name=PLUGIN,
    install_path=True,
    stray=False,
    extra=None,
    manifest=True,
    declare=None,
):
    """A fabricated plugin cache plus the install record that points at it.

    ``stray`` unpacks the plugin somewhere the cache layout would never find it, so the
    test below distinguishes "installPath was used" from "the glob happened to work".

    ``hooks`` are written under ``scripts/`` and declared in a fabricated
    ``hooks/hooks.json`` -- which is what makes them hooks (#241). ``extra`` writes
    arbitrary relative paths that are never declared: test fixtures, helpers nothing
    sources, anything the runtime would not execute. ``declare`` narrows the manifest to
    a subset of ``hooks``; ``manifest=False`` omits the manifest entirely.
    """
    root = tmp_path / "cache"
    root.mkdir(parents=True, exist_ok=True)
    plugin = (
        (tmp_path / "elsewhere" / version)
        if stray
        else (root / "dpt-plugins" / name / version)
    )
    (plugin / "scripts").mkdir(parents=True)
    for filename, body in hooks.items():
        _write(plugin / "scripts" / filename, body)
    for relative, body in (extra or {}).items():
        _write(plugin.joinpath(*str(relative).split("/")), body)
    if manifest:
        declared = list(hooks) if declare is None else list(declare)
        _write(
            plugin / "hooks" / "hooks.json",
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "bash ${{CLAUDE_PLUGIN_ROOT}}/scripts/{}".format(
                                            filename
                                        ),
                                    }
                                    for filename in declared
                                ]
                            }
                        ]
                    }
                }
            ),
        )
    entry = {"scope": "user", "version": version}
    if install_path:
        entry["installPath"] = str(plugin)
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"{}@dpt-plugins".format(name): [entry]}}),
        encoding="utf-8",
    )
    return root, record


def _project(tmp_path, layer=LAYER, dimensions=("paths", "tools")):
    root = tmp_path / "repo"
    for dimension in dimensions:
        directory = root / ".claude" / "jit-context" / dimension / layer
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "rule.md").write_text("---\n---\n", encoding="utf-8")
    return root


def _one(project, cache_root, record):
    findings = doctor.jit_layer_readers(project, record=record, cache_root=cache_root)
    assert len(findings) == 1, findings
    return findings[0]


def test_a_hook_set_that_omits_our_layer_is_unread(tmp_path):
    """The state of the world as #119 measured it."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": OMITS})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "unread"
    assert LAYER in finding["detail"]
    assert "pre-tool-hook.sh" in finding["detail"]


def test_a_hook_set_that_names_our_layer_reads_it(tmp_path):
    """The positive control for the assertion above.

    Same fixture, same scanner, one token different. Without it, `unread` is equally
    consistent with a scanner that never matches anything.
    """
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": NAMES})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "reads"


def test_the_positive_answer_counts_what_it_says_it_counts(tmp_path):
    """`len(dimensions)` was rendered as "N rule(s)".

    The two counts are equal in every other fixture here, because `_project` writes exactly
    one entry per dimension -- so this one puts a second entry in a dimension, which is the
    only arrangement that can tell them apart. A diagnostic that names the wrong noun is
    read as a rule count and quoted as one.
    """
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": NAMES})
    project = _project(tmp_path)
    extra = project / ".claude" / "jit-context" / "tools" / LAYER / "second.md"
    extra.write_text("---\n---\n", encoding="utf-8")

    rules = len(list((project / ".claude" / "jit-context").rglob("*.md")))
    dimensions = 2
    assert rules != dimensions, "the fixture cannot tell the two counts apart"

    detail = _one(project, cache, record)["detail"]
    assert "{} rule(s)".format(dimensions) not in detail, detail
    assert "{} dimension(s)".format(dimensions) in detail, detail


def test_hooks_that_enumerate_at_runtime_are_not_unread(tmp_path):
    """The durability case: the upstream fix must not read as a permanent failure.

    This asserted `could-not-determine` until #743, which is the state the upstream fix
    made terminal rather than transitional. The assertion that carries the durability
    argument is the one below -- `unread` is what a hook set enumerating off disk must
    never produce -- and it holds unchanged across that promotion.
    """
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": ENUMERATED})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] != "unread", finding
    assert finding["state"] == "reads-by-glob", finding
    # Discriminating, not decorative: the `unread` arm says "a fixed list that does not
    # include", so this phrase cannot be reached from the state this test must not see.
    assert "fixed list" in finding["detail"]


def test_a_directory_glob_in_the_hook_set_is_named_not_only_the_absence_of_a_list(
    tmp_path,
):
    """#616: a stale `unknown` and a genuinely open one must not read identically.

    `ENUMERATED` is a hook that enumerates its dimension directory with a shell glob
    (`for d in "..."/*/; do`) rather than naming a fixed list -- the shape the upstream
    fix (`claude-jit-context#176`) is expected to take, and the shape a real report
    (#616) showed shipping in 0.6.0's `common.sh`. The state stays `could-not-determine`
    -- this file does not prove the loop's body actually reads what it visits -- but the
    detail must say the glob was seen, which is the one thing that tells a maintainer
    this `unknown` is not the same as one with no evidence in it at all.

    Paired with the negative control in the same fixture shape: a hook carrying neither
    a fixed list nor a glob must not claim to have seen one.
    """
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": ENUMERATED})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "reads-by-glob", finding
    assert "glob" in finding["detail"], finding["detail"]
    assert "pre-tool-hook.sh" in finding["detail"], finding["detail"]

    # Must-not-fire half: a hook with no enumeration of any shape names no glob.
    cache, record = _cache(tmp_path / "control", {"pre-tool-hook.sh": NEITHER})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "glob" not in finding["detail"], finding["detail"]


def test_the_glob_shape_does_not_require_a_same_line_semicolon(tmp_path):
    """Review caught this before #616 shipped: `do` on its own line is ordinary shell.

    The first cut of `JIT_LAYER_DIR_GLOB` anchored on a same-line `;`, so a hook
    written with `do` on the following line -- as common as the semicolon form --
    matched nothing, and the ambiguity #616 asked to be resolved would have silently
    reappeared for this equally ordinary formatting.
    """
    cache, record = _cache(
        tmp_path, {"pre-tool-hook.sh": 'for d in "$base"/*/\ndo\n  echo "$d"\ndone\n'}
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "reads-by-glob", finding
    assert "glob" in finding["detail"], finding["detail"]


def test_a_test_fixture_naming_the_layer_is_not_a_hook_reading_it(tmp_path):
    """#241, and it is the measurement this whole file exists to make honestly.

    The installed 0.4.0 tree answered `reads` off `tests/test-layer-enumeration.sh:494` --
    the dependency's own positive control for its enumerator, a file that could never
    enumerate anything at run time. The string in it is invariant under the upstream fix,
    so the same `reads` would have printed with the broken fixed list still in the hooks.
    That is exactly the tree fabricated here.

    Paired in one fixture: the same layer list inside the *declared* hook must still say
    `reads`, so this cannot pass against a scanner that stopped matching anything.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": OMITS},
        extra={"tests/test-layer-enumeration.sh": FIXTURE},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "unread", finding
    assert "pre-tool-hook.sh" in finding["detail"]
    assert "test-layer-enumeration.sh" not in finding["detail"], finding["detail"]

    cache, record = _cache(
        tmp_path / "control",
        {"pre-tool-hook.sh": NAMES},
        extra={"tests/test-layer-enumeration.sh": FIXTURE},
    )
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


def test_a_layer_list_only_outside_the_hook_set_is_the_reason_it_is_unknown(tmp_path):
    """The judgement call in #241: ignore the fixture, or report it as the non-answer.

    Reported. A run whose only evidence is a fixture is not a run that found nothing --
    it is a run that found the wrong kind of evidence, and the file that supplied it is
    the single most useful thing to print.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": NEITHER},
        extra={"tests/test-layer-enumeration.sh": FIXTURE},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "test-layer-enumeration.sh" in finding["detail"], finding["detail"]
    assert "outside the hook set" in finding["detail"], finding["detail"]

    # Must-fire half: the identical string, in a file the manifest declares.
    cache, record = _cache(
        tmp_path / "control", {"pre-tool-hook.sh": NEITHER, "pre-path-hook.sh": FIXTURE}
    )
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


def test_a_glob_in_the_hook_set_outranks_a_fixed_list_outside_it(tmp_path):
    """#616's tree, re-asserted under #743's answer rather than under its old ambiguity.

    This is the tree #616 reported and the tree the installed 0.6.0 actually is: the
    only fixed layer list left anywhere is the dependency's own test fixture, outside
    the hook set per #241, while the hook set itself enumerates by directory glob.
    #616 could only make the two `unknown`s distinguishable in prose. #743 answers it:
    the glob is evidence from inside the hook set and the fixture is evidence from
    outside it, so the fixture does not withhold what the glob establishes.

    Paired with the must-not-fire half in the same fixture shape: with the glob moved
    out of the hook set, the same fixture leaves the question open again.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": ENUMERATED},
        extra={"tests/test-layer-enumeration.sh": FIXTURE},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "reads-by-glob", finding
    assert "glob" in finding["detail"], finding["detail"]
    assert "pre-tool-hook.sh" in finding["detail"], finding["detail"]

    cache, record = _cache(
        tmp_path / "control",
        {"pre-tool-hook.sh": NEITHER},
        extra={
            "tests/test-layer-enumeration.sh": FIXTURE,
            "vendor/helper.sh": ENUMERATED,
        },
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding


def test_a_helper_the_hooks_source_is_part_of_the_hook_set(tmp_path):
    """A hook's enumeration may live in a file it sources rather than in the entry point.

    Both halves live in `scripts/`, so nothing about the *directory* separates them: what
    does is whether the declared hook reaches the file. A scope keyed on a path prefix
    would pass the first half and fail the second.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": SOURCES_COMMON, "common.sh": OMITS},
        declare=["pre-tool-hook.sh"],
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "unread", finding
    assert "common.sh" in finding["detail"]

    # Same two files, same directory, same manifest -- the hook no longer sources it.
    cache, record = _cache(
        tmp_path / "control",
        {"pre-tool-hook.sh": NEITHER, "common.sh": OMITS},
        declare=["pre-tool-hook.sh"],
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "common.sh" in finding["detail"], finding["detail"]


def test_without_a_hook_manifest_nothing_is_a_hook(tmp_path):
    """No manifest means no way to tell a hook from a fixture, which is a non-answer.

    Must-not-fire and must-fire on one tree: the only difference between the two halves
    is `hooks/hooks.json`.
    """
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": NAMES}, manifest=False)
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "hook manifest" in finding["detail"], finding["detail"]

    cache, record = _cache(tmp_path / "control", {"pre-tool-hook.sh": NAMES})
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


def test_a_manifest_naming_a_script_that_is_not_there_is_could_not_determine(tmp_path):
    """Declared and absent is not the same as declared and clean."""
    cache, record = _cache(
        tmp_path, {"pre-tool-hook.sh": NAMES}, declare=["gone-hook.sh"]
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "gone-hook.sh" in finding["detail"], finding["detail"]


def test_a_manifest_the_plugin_json_names_is_the_one_looked_for(tmp_path):
    """`.claude-plugin/plugin.json` may name the manifest, and the message must say which.

    Must-not-fire half first: the named manifest is absent, and the detail has to name
    *that* path rather than the convention -- a diagnostic reporting `hooks/hooks.json`
    missing while the plugin declared `custom/hooks.json` answers a question nobody asked.
    Must-fire half: the same declaration with the file present resolves the hook, which is
    also the only assertion that the named path is honoured at all.
    """
    declaration = json.dumps({"name": PLUGIN, "hooks": "custom/hooks.json"})
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": NAMES},
        manifest=False,
        extra={".claude-plugin/plugin.json": declaration},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "custom/hooks.json" in finding["detail"], finding["detail"]
    assert "(hooks/hooks.json)" not in finding["detail"], finding["detail"]

    cache, record = _cache(
        tmp_path / "control",
        {"pre-tool-hook.sh": NAMES},
        manifest=False,
        extra={
            ".claude-plugin/plugin.json": declaration,
            "custom/hooks.json": json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/pre-tool-hook.sh",
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
        },
    )
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


def test_a_manifest_path_the_plugin_declared_and_this_cannot_resolve_is_not_a_fallback(
    tmp_path,
):
    """A declaration this cannot resolve is a non-answer, not a licence to guess.

    Falling back to the convention measures a file the plugin did not name, which is the
    #241 substitution one field over -- and in the second half below it is worse than a
    wrong path in a message: a conventional manifest happening to sit there would have
    produced a confident `reads` with nothing anywhere saying the declared key was
    ignored. Both halves must name what was declared.

    The positive control is `test_a_manifest_the_plugin_json_names_is_the_one_looked_for`,
    which asserts `reads` on a declaration that *does* resolve -- so this cannot pass
    against a reader that refuses every declaration.
    """
    declaration = json.dumps({"name": PLUGIN, "hooks": "../../etc/hooks.json"})
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": NAMES},
        manifest=False,
        extra={".claude-plugin/plugin.json": declaration},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "../../etc/hooks.json" in finding["detail"], finding["detail"]
    assert "hooks/hooks.json" not in finding["detail"], finding["detail"]

    # The half that would otherwise answer `reads` off a file nobody named: a perfectly
    # good manifest at the conventional location, and a declaration pointing elsewhere.
    cache, record = _cache(
        tmp_path / "second",
        {"pre-tool-hook.sh": NAMES},
        extra={".claude-plugin/plugin.json": declaration},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "../../etc/hooks.json" in finding["detail"], finding["detail"]


def test_a_hook_manifest_that_will_not_parse_says_so_rather_than_that_it_named_nothing(
    tmp_path,
):
    """Unreadable and empty are two states and used to share one sentence.

    Both halves are must-fire, on the same fixture shape: a manifest that will not parse,
    and one that parses to `{}`. Each has to say its own thing and must not say the
    other's, which is what makes this a discrimination rather than two spellings of
    `could-not-determine`.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": NAMES},
        manifest=False,
        extra={"hooks/hooks.json": "{ not json"},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "hooks.json" in finding["detail"], finding["detail"]
    assert "would not be read" in finding["detail"], finding["detail"]
    assert "named nothing" not in finding["detail"], finding["detail"]

    cache, record = _cache(
        tmp_path / "empty",
        {"pre-tool-hook.sh": NAMES},
        manifest=False,
        extra={"hooks/hooks.json": "{}"},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "named nothing" in finding["detail"], finding["detail"]
    assert "would not be read" not in finding["detail"], finding["detail"]

    cache, record = _cache(tmp_path / "control", {"pre-tool-hook.sh": NAMES})
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


def test_a_subtree_that_cannot_be_walked_is_reported_not_swallowed(tmp_path, request):
    """`Path.rglob` swallows `PermissionError` while walking and yields nothing.

    So the `except OSError` this scan used to carry could never fire for the case it was
    written for, and "the whole tree holds no layer list" came back identical to "this
    could not read the tree" -- with the second one then quoted as the reason the check
    could not determine. `CLAUDE.md` records that trap against `scaffold.py`; this is the
    same walk, in code added by #241.

    The deny is *measured*, never assumed: root ignores the mode bit, some filesystems
    ignore it, and Windows' `os.chmod` on a directory toggles a read-only attribute that
    does not stop a listing. The exact operation `os.walk` performs is attempted, and the
    test skips with what went untested when it did not take.
    """
    hooks = {"pre-tool-hook.sh": NEITHER}
    fixture = {"vendor/test-layer-enumeration.sh": FIXTURE}

    # Must-fire half, readable: the site is found and named.
    cache, record = _cache(tmp_path / "readable", hooks, extra=fixture)
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "test-layer-enumeration.sh" in finding["detail"], finding["detail"]

    cache, record = _cache(tmp_path / "denied", hooks, extra=fixture)
    closed = cache / "dpt-plugins" / PLUGIN / VERSION / "vendor"
    original = closed.stat().st_mode
    closed.chmod(0o000)
    request.addfinalizer(lambda: closed.chmod(original))
    try:
        os.listdir(str(closed))
    except OSError:
        pass
    else:
        pytest.skip(
            "chmod 000 did not deny os.listdir on this platform/user, so the "
            "unwalkable-subtree arm went untested here: {}".format(closed)
        )

    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "did not see the whole tree" in finding["detail"], finding["detail"]
    assert "vendor" in finding["detail"], finding["detail"]
    # The failure this replaces: the subtree vanished and the sentence read as complete.
    assert "test-layer-enumeration.sh" not in finding["detail"], finding["detail"]


def test_a_declared_hook_that_is_missing_cannot_leave_the_rest_saying_unread(tmp_path):
    """An incomplete hook set cannot report a gap, for the same reason an unreadable one
    cannot: the hook that did not resolve is exactly where the enumeration might have
    been.

    Must-fire half on the identical tree: with both declared hooks present and both
    omitting the layer, the gap is real and `unread` is the answer.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": OMITS},
        declare=["pre-tool-hook.sh", "gone-hook.sh"],
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "gone-hook.sh" in finding["detail"], finding["detail"]

    cache, record = _cache(
        tmp_path / "control",
        {"pre-tool-hook.sh": OMITS, "gone-hook.sh": OMITS},
    )
    assert _one(_project(tmp_path), cache, record)["state"] == "unread"


def test_a_manifest_component_that_would_leave_the_install_root_resolves_to_nothing():
    """`_jit_path_parts` is the chokepoint, and it is asserted on every platform.

    The drive-letter case is Windows-only in effect -- `PureWindowsPath("C:/a").joinpath(
    "D:", "x.sh")` is `D:x.sh`, outside the root the join was anchored on -- but the guard
    is unconditional, so the assertion is not vacuous on the legs that cannot exhibit it.
    Paired with the ordinary paths it must keep accepting, so a `_jit_path_parts` that
    refused everything would fail here rather than pass.
    """
    assert doctor._jit_path_parts("scripts/pre-tool-hook.sh")[0] == [
        "scripts",
        "pre-tool-hook.sh",
    ]
    assert doctor._jit_path_parts("/scripts/pre-tool-hook.sh")[0] == [
        "scripts",
        "pre-tool-hook.sh",
    ]
    for refused in ("../../etc/evil.sh", "D:/evil/x.sh", "C:evil.sh", ""):
        parts, reason = doctor._jit_path_parts(refused)
        assert parts is None, (refused, parts)
        # A refusal with no reason is the state without the sentence that makes it
        # actionable, and the caller prints this verbatim (#258).
        assert reason, refused


@pytest.mark.parametrize("running_sep", ["/", "\\"])
def test_a_declared_manifest_path_resolves_the_same_way_on_every_platform(
    monkeypatch, running_sep
):
    """The components a declaration resolves to must not depend on who is running the check.

    #258. `_jit_path_parts` used to split on `os.sep`, so `custom\\hooks.json` was two
    components on Windows and one literal filename on the eight POSIX legs -- the same
    declaration answering two different questions depending on the runner. The injection is
    measured rather than assumed: `os.sep` is the only separator constant this function
    reads (nothing else in `doctor.py` reads one), and rebinding the `os` attribute does not
    touch `posixpath.sep`, so `pathlib` and the fixtures underneath are unaffected. That is
    what makes this a simulation of the Windows leg for this one function, and not a claim
    about Windows generally.

    The accepting half runs under the same injection, so a `_jit_path_parts` that refused
    everything would fail here rather than pass.
    """
    monkeypatch.setattr(os, "sep", running_sep)
    assert os.sep == running_sep, "the separator injection did not take"

    assert doctor._jit_path_parts("scripts/pre-tool-hook.sh")[0] == [
        "scripts",
        "pre-tool-hook.sh",
    ]
    parts, reason = doctor._jit_path_parts("custom\\hooks.json")
    assert parts is None, parts
    assert "backslash" in reason, reason


@pytest.mark.parametrize("running_sep", ["/", "\\"])
def test_a_backslash_in_a_declared_manifest_path_is_refused_rather_than_guessed(
    tmp_path, monkeypatch, running_sep
):
    """A declaration this cannot read is a non-answer with its own reason, on every leg.

    #258, end to end and in both directions. The fixture puts a real, readable manifest at
    `custom/hooks.json` and declares it as `custom\\hooks.json`. Before the fix that tree
    answered `reads` when `os.sep` was a backslash and `could-not-determine` when it was a
    slash -- and the `could-not-determine` blamed a missing file, which is a wrong reason
    inside an honest state.

    The choice being asserted is the conservative one: a backslash is never treated as a
    separator, because on POSIX it legally is a filename character and nothing here can tell
    which the author meant. Guessing would resolve to a file the manifest did not name,
    which is #241's substitution one field over. So the value is refused with a named reason
    and nothing is measured -- never a confident answer this has not earned.

    Must-fire control in the same injected environment: the same tree with a
    forward-slashed declaration resolves and answers `reads`.
    """
    monkeypatch.setattr(os, "sep", running_sep)
    assert os.sep == running_sep, "the separator injection did not take"

    manifest = json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/pre-tool-hook.sh",
                            }
                        ]
                    }
                ]
            }
        }
    )

    cache, record = _cache(
        tmp_path / "control",
        {"pre-tool-hook.sh": NAMES},
        manifest=False,
        extra={
            ".claude-plugin/plugin.json": json.dumps(
                {"name": PLUGIN, "hooks": "custom/hooks.json"}
            ),
            "custom/hooks.json": manifest,
        },
    )
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"

    cache, record = _cache(
        tmp_path / "subject",
        {"pre-tool-hook.sh": NAMES},
        manifest=False,
        extra={
            ".claude-plugin/plugin.json": json.dumps(
                {"name": PLUGIN, "hooks": "custom\\hooks.json"}
            ),
            "custom/hooks.json": manifest,
        },
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "custom\\hooks.json" in finding["detail"], finding["detail"]
    assert "backslash" in finding["detail"], finding["detail"]
    # Not "the file is missing": it is there, under the name the plugin did not write.
    assert "carries no hook manifest" not in finding["detail"], finding["detail"]


def test_an_enumeration_inside_a_comment_is_not_a_measurement(tmp_path):
    """Prose about the layer list is not the layer list.

    Paired in one fixture with a live enumeration in a second file, so a scanner that
    saw nothing at all would fail the second half rather than pass the first.
    """
    commented = '# layers are "00-manual 10-auto 20-grouped 30-crosscutting" today\n'
    cache, record = _cache(tmp_path, {"doc-hook.sh": commented})
    assert _one(_project(tmp_path), cache, record)["state"] == "could-not-determine"

    cache, record = _cache(
        tmp_path / "second", {"doc-hook.sh": commented, "pre-path-hook.sh": OMITS}
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "unread"
    assert "pre-path-hook.sh" in finding["detail"]


def test_an_unreadable_hook_never_settles_the_question(tmp_path):
    """A scan that could not read every hook cannot say the layer is unread.

    The undecodable file is the only difference from
    `test_a_hook_set_that_omits_our_layer_is_unread`, which asserts `unread` on the
    identical enumeration -- so this is the incomplete-scan arm, not a scanner that
    fails on everything.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": OMITS, "broken-hook.sh": b"\xff\xfe not utf-8\n"},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine"
    assert "broken-hook.sh" in finding["detail"]


def test_an_unreadable_hook_does_not_veto_a_positive_answer(tmp_path):
    """One hook naming the layer settles it; nothing unread elsewhere can unsay it."""
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": NAMES, "broken-hook.sh": b"\xff\xfe not utf-8\n"},
    )
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


def test_the_dependency_not_installed_is_could_not_determine(tmp_path):
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    finding = _one(_project(tmp_path), tmp_path / "cache", record)
    assert finding["state"] == "could-not-determine"
    assert PLUGIN in finding["detail"]


def test_an_unreadable_install_record_is_could_not_determine(tmp_path):
    finding = _one(_project(tmp_path), tmp_path / "cache", tmp_path / "absent.json")
    assert finding["state"] == "could-not-determine"


def test_an_installed_version_whose_tree_is_gone_is_could_not_determine(tmp_path):
    """The record says a version runs and nothing is on disk under it."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": OMITS})
    for path in sorted(
        (cache / "dpt-plugins" / PLUGIN / VERSION / "scripts").iterdir()
    ):
        path.unlink()
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine"
    assert "no hook script" in finding["detail"]


def test_the_install_record_path_wins_over_the_cache_layout(tmp_path):
    """A plugin unpacked outside the cache layout is still found, via `installPath`."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": OMITS}, stray=True)
    # The control for the sentence above: nothing the glob could possibly reach.
    assert not list(cache.rglob("*.sh"))
    assert _one(_project(tmp_path), cache, record)["state"] == "unread"


def test_the_cache_glob_answers_when_the_record_carries_no_install_path(tmp_path):
    """Older records omit `installPath`; the cache layout is the documented fallback."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": OMITS}, install_path=False)
    assert _one(_project(tmp_path), cache, record)["state"] == "unread"


def test_a_repo_without_the_layer_has_nothing_to_read(tmp_path):
    """Not a gap, and not a pass about the dependency either."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": OMITS})
    project = _project(tmp_path, layer="00-manual")
    finding = doctor.jit_layer_readers(project, record=record, cache_root=cache)[0]
    assert finding["state"] == "no-layer"


def test_every_state_this_check_emits_has_a_level(tmp_path):
    """Vacuity guard: the five states are asserted to have been *seen*, not assumed.

    A level table checked against an empty set of observed states is trivially
    complete, which is the failure this whole file is about.
    """
    seen = set()
    cases = [
        ({"pre-tool-hook.sh": NAMES}, LAYER),
        ({"pre-tool-hook.sh": OMITS}, LAYER),
        ({"pre-tool-hook.sh": ENUMERATED}, LAYER),
        ({"pre-tool-hook.sh": NEITHER}, LAYER),
        ({"pre-tool-hook.sh": OMITS}, "00-manual"),
    ]
    for index, (hooks, layer) in enumerate(cases):
        cache, record = _cache(tmp_path / str(index), hooks)
        project = _project(tmp_path / str(index), layer=layer)
        seen.add(
            doctor.jit_layer_readers(project, record=record, cache_root=cache)[0][
                "state"
            ]
        )

    assert seen == {
        "reads",
        "reads-by-glob",
        "unread",
        "could-not-determine",
        "no-layer",
    }
    assert seen <= set(doctor.JIT_LAYER_LEVELS)
    assert set(doctor.JIT_LAYER_LEVELS.values()) <= {"OK", "WARN", "FAIL"}
    assert doctor.JIT_LAYER_LEVELS["unread"] == "WARN"
    assert doctor.JIT_LAYER_LEVELS["could-not-determine"] == "WARN"
    assert doctor.JIT_LAYER_LEVELS["reads"] == "OK"
    assert doctor.JIT_LAYER_LEVELS["reads-by-glob"] == "OK"
    assert doctor.JIT_LAYER_LEVELS["no-layer"] == "OK"


def test_the_layer_name_is_not_a_second_copy_of_it(tmp_path, monkeypatch):
    """The name comes from `oss_rules.LAYER`, the module that creates the directory.

    Discriminating on purpose: passing today's `oss_rules.LAYER` in would pass equally
    against a `doctor.py` that hardcoded the same string, since the two agree. So the
    constant is moved out from under it. A second copy of the name in `doctor.py` sends
    this to `no-layer` -- it would go looking for a layer the fixture does not have.
    """
    import oss_rules

    renamed = "42-elsewhere"
    assert oss_rules.LAYER != renamed
    monkeypatch.setattr(oss_rules, "LAYER", renamed)

    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": 'split("00-manual {}", layers, " ")\n'.format(renamed)},
    )
    project = _project(tmp_path, layer=renamed)
    assert _one(project, cache, record)["state"] == "reads"


def test_the_check_prints_one_line_through_the_report_contract(tmp_path):
    """Wired into the run, not merely importable."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": OMITS})
    before = len(doctor.FINDINGS)
    doctor.check_jit_layer_readers(_project(tmp_path), record=record, cache_root=cache)
    added = doctor.FINDINGS[before:]
    assert len(added) == 1
    level, message = added[0]
    assert level == "WARN"
    assert message.startswith("jit rule layer:")


def test_the_doctor_run_reports_the_layer(tmp_path, monkeypatch):
    """The main() wiring, so a check nobody calls cannot pass this file."""
    monkeypatch.setattr(doctor, "FINDINGS", [])
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(REPO_ROOT))
    # #621 self-review: a real `claude mcp get` call answers about this machine,
    # not this fixture -- and this test runs main() against REPO_ROOT itself.
    monkeypatch.setattr(doctor, "check_mcp_channel_registration", lambda **k: None)
    # #582: a real `supertool ops:roster` call, same reason, same fixture.
    monkeypatch.setattr(doctor, "check_supertool_ops", lambda **k: None)
    doctor.main([])
    messages = [message for _, message in doctor.FINDINGS]
    assert any(message.startswith("jit rule layer:") for message in messages), messages


#: #743's subject: the hook globs, and then narrows what it visits to a fixed set of
#: names. A glob alone would say "every directory under the base is enumerated"; this
#: line is what makes that false, and it is the one shape that must not reach `OK`.
GLOB_THEN_FILTERS_US_OUT = (
    'for d in "$JIT_BASE/$dim"/*/; do\n'
    '  name="${d##*/}"\n'
    '  [ "$name" = "00-manual" ] || continue\n'
    '  echo "$name"\n'
    "done\n"
)
#: The positive control for it: the same filter, naming our layer instead of excluding it.
GLOB_THEN_FILTERS_US_IN = GLOB_THEN_FILTERS_US_OUT.replace('"00-manual"', '"01-oss"')
#: A glob beside an ordinary filename that merely *looks* layer-shaped. Measured against
#: the installed 0.6.0's `common.sh`, which is the tree this check has to answer about:
#: the only two-digit-prefixed tokens in it outside comments are `00-index.tsv` and
#: `01-paths.tsv`, index filenames rather than layer names. A filter detector that
#: matched those would send every up-to-date install straight back to `unknown` -- the
#: state #743 exists to leave -- so this is the must-not-fire half of the filter check.
GLOB_BESIDE_AN_INDEX_FILENAME = (
    'for d in "$JIT_BASE/$dim"/*/; do\n'
    '  for tsv in "$d/00-index.tsv" "$d/01-paths.tsv"; do\n'
    '    tsv="$base/$layer/00-index.tsv"\n'
    "  done\n"
    "done\n"
)


def test_a_hook_that_enumerates_layers_by_glob_reads_ours_743(tmp_path):
    """#743: the check's only OK condition was a fixed list, and the upstream fix
    (claude-jit-context#176) deleted the fixed list. The two were mutually exclusive,
    so `unknown` had become the terminal state for every up-to-date install -- which
    is not a third state at all once it is the only reachable one.

    A glob over the dimension base enumerates every directory under it, ours included,
    by construction. What #241 bought was *reject a fixture*, not *refuse to read a
    glob*, and the hook-set membership test that enforces #241 is untouched here.
    """
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": ENUMERATED})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "reads-by-glob", finding
    assert doctor.JIT_LAYER_LEVELS["reads-by-glob"] == "OK"
    # It must say the conclusion came from a glob rather than from a named layer --
    # the two are different evidence and a reader is entitled to know which they have.
    assert "glob" in finding["detail"], finding["detail"]
    assert "pre-tool-hook.sh" in finding["detail"], finding["detail"]
    # Must-not-fire: the `reads` arm's own phrase cannot be reached from here.
    assert "in its layer list" not in finding["detail"], finding["detail"]


def test_a_glob_outside_the_hook_set_is_still_not_an_answer_743(tmp_path):
    """#241 must not regress through the new arm. A glob in a file the runtime never
    executes is the same class of evidence as a layer list in one: a fixture.

    Paired with the positive control in the same fixture shape, so this cannot pass
    against a scanner that stopped matching globs entirely.
    """
    cache, record = _cache(
        tmp_path,
        {"pre-tool-hook.sh": NEITHER},
        extra={"tests/test-layer-enumeration.sh": ENUMERATED},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding

    cache, record = _cache(tmp_path / "control", {"pre-tool-hook.sh": ENUMERATED})
    assert _one(_project(tmp_path), cache, record)["state"] == "reads-by-glob"


def test_a_glob_narrowed_by_a_name_filter_that_excludes_us_is_not_ok_743(tmp_path):
    """The third acceptance criterion, and the one that keeps the new arm honest.

    A hook that globs the base and then keeps only names on a list is enumerating a
    fixed set with extra steps. Answered `could-not-determine` rather than `unread`:
    a filter this cannot see the whole of -- one branch of several, a variable rather
    than a literal -- is a reason not to claim an answer, not evidence of a gap.
    """
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": GLOB_THEN_FILTERS_US_OUT})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "then filter what is visited" in finding["detail"], finding["detail"]

    # Positive control, same shape one token different: a filter that names our layer
    # is not a reason to withhold the answer.
    cache, record = _cache(
        tmp_path / "in", {"pre-tool-hook.sh": GLOB_THEN_FILTERS_US_IN}
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "reads-by-glob", finding


def test_an_index_filename_is_not_a_layer_filter_743(tmp_path):
    """The must-not-fire half of the filter check, measured against the real tree.

    `00-index.tsv` and `01-paths.tsv` are the only two-digit-prefixed tokens outside
    comments in the installed 0.6.0's `common.sh`. A filter detector keyed on "a
    layer-shaped token appears somewhere in the file" matches both, and would answer
    `could-not-determine` for exactly the dependency version #743 was filed about --
    the fix reporting the defect it fixes.
    """
    cache, record = _cache(
        tmp_path, {"pre-tool-hook.sh": GLOB_BESIDE_AN_INDEX_FILENAME}
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "reads-by-glob", finding
    assert "then filter what is visited" not in finding["detail"], finding["detail"]
