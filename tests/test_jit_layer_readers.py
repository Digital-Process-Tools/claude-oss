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

Four states, and the third and fourth are the point:

  reads                 a hook's layer enumeration names our layer
  unread                every enumeration found omits it -- a real gap, WARN
  could-not-determine   nothing was measured: the dependency is not installed, its
                        tree was not found, a hook would not read, or no hook carries
                        a fixed enumeration at all
  no-layer              this repo has no such layer, so there is nothing to read

`could-not-determine` covers the case that matters most for durability. The upstream
fix (`claude-jit-context#176`) removes the fixed list, so a check keyed on today's
spelling would report `unread` forever after it is fixed -- the same defect inverted.
When no fixed enumeration is found the answer is *unknown*, never *unread*.

Every hook set below is fabricated. A test that only passes when a particular
dependency version happens to be installed on the runner is a test CI cannot run
honestly, and it would measure the machine rather than the code.
"""

import json
import sys
from pathlib import Path

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
    plugin = (tmp_path / "elsewhere" / version) if stray else (root / "dpt-plugins" / name / version)
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


def test_hooks_that_enumerate_at_runtime_are_unknown_not_unread(tmp_path):
    """The durability case: the upstream fix must not read as a permanent failure."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": ENUMERATED})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine"
    # Discriminating, not decorative: the `unread` arm says "a fixed list that does not
    # include", so this phrase cannot be reached from the state this test must not see.
    assert "none carries a fixed layer list" in finding["detail"]


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
        {"pre-tool-hook.sh": ENUMERATED},
        extra={"tests/test-layer-enumeration.sh": FIXTURE},
    )
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine", finding
    assert "test-layer-enumeration.sh" in finding["detail"], finding["detail"]
    assert "outside the hook set" in finding["detail"], finding["detail"]

    # Must-fire half: the identical string, in a file the manifest declares.
    cache, record = _cache(
        tmp_path / "control", {"pre-tool-hook.sh": ENUMERATED, "pre-path-hook.sh": FIXTURE}
    )
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


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
        {"pre-tool-hook.sh": ENUMERATED, "common.sh": OMITS},
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


def test_a_hook_manifest_that_will_not_parse_is_could_not_determine(tmp_path):
    """Present and unreadable is not the same as present and empty.

    Paired with a parseable manifest over the identical tree, so this cannot pass against
    a reader that fails on every manifest.
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

    cache, record = _cache(tmp_path / "control", {"pre-tool-hook.sh": NAMES})
    assert _one(_project(tmp_path), cache, record)["state"] == "reads"


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
    for path in sorted((cache / "dpt-plugins" / PLUGIN / VERSION / "scripts").iterdir()):
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
    """Vacuity guard: the four states are asserted to have been *seen*, not assumed.

    A level table checked against an empty set of observed states is trivially
    complete, which is the failure this whole file is about.
    """
    seen = set()
    cases = [
        ({"pre-tool-hook.sh": NAMES}, LAYER),
        ({"pre-tool-hook.sh": OMITS}, LAYER),
        ({"pre-tool-hook.sh": ENUMERATED}, LAYER),
        ({"pre-tool-hook.sh": OMITS}, "00-manual"),
    ]
    for index, (hooks, layer) in enumerate(cases):
        cache, record = _cache(tmp_path / str(index), hooks)
        project = _project(tmp_path / str(index), layer=layer)
        seen.add(
            doctor.jit_layer_readers(project, record=record, cache_root=cache)[0]["state"]
        )

    assert seen == {"reads", "unread", "could-not-determine", "no-layer"}
    assert seen <= set(doctor.JIT_LAYER_LEVELS)
    assert set(doctor.JIT_LAYER_LEVELS.values()) <= {"OK", "WARN", "FAIL"}
    assert doctor.JIT_LAYER_LEVELS["unread"] == "WARN"
    assert doctor.JIT_LAYER_LEVELS["could-not-determine"] == "WARN"
    assert doctor.JIT_LAYER_LEVELS["reads"] == "OK"
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
        tmp_path, {"pre-tool-hook.sh": 'split("00-manual {}", layers, " ")\n'.format(renamed)}
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
    doctor.main([])
    messages = [message for _, message in doctor.FINDINGS]
    assert any(message.startswith("jit rule layer:") for message in messages), messages
