"""Does the installed dependency actually read this plugin's rule layer? (#119)

Every observable signal said the `01-oss` layer was healthy -- files on disk, index
rows current, `doctor` listing them, the generator's own tests green. Nothing anywhere
asked *does anything read this directory?*, and the answer was no: `claude-jit-context`
enumerates layers from a fixed list in three hooks (`pre-path-hook.sh:308`,
`pre-tool-hook.sh:721`, `pre-prompt-hook.sh:173`, measured against 0.3.5) and `01-oss`
is not in it.

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

#: The shape the three real hooks carry today, verbatim apart from indentation.
OMITS = 'split("00-manual 10-auto 20-grouped 30-crosscutting", layers, " ")\n'
#: The same line if upstream simply added our layer to the list.
NAMES = 'split("00-manual 01-oss 10-auto 20-grouped 30-crosscutting", layers, " ")\n'
#: What the upstream fix is expected to look like: no fixed list anywhere.
ENUMERATED = 'for d in "$JIT_BASE/$dim"/*/; do echo "$d"; done\n'


def _cache(tmp_path, hooks, version=VERSION, name=PLUGIN, install_path=True, stray=False):
    """A fabricated plugin cache plus the install record that points at it.

    ``stray`` unpacks the plugin somewhere the cache layout would never find it, so the
    test below distinguishes "installPath was used" from "the glob happened to work".
    """
    root = tmp_path / "cache"
    root.mkdir(parents=True, exist_ok=True)
    plugin = (tmp_path / "elsewhere" / version) if stray else (root / "dpt-plugins" / name / version)
    (plugin / "scripts").mkdir(parents=True)
    for filename, body in hooks.items():
        target = plugin / "scripts" / filename
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(body, encoding="utf-8")
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


def test_hooks_that_enumerate_at_runtime_are_unknown_not_unread(tmp_path):
    """The durability case: the upstream fix must not read as a permanent failure."""
    cache, record = _cache(tmp_path, {"pre-tool-hook.sh": ENUMERATED})
    finding = _one(_project(tmp_path), cache, record)
    assert finding["state"] == "could-not-determine"
    # Discriminating, not decorative: the `unread` arm says "a fixed list that does not
    # include", so this phrase cannot be reached from the state this test must not see.
    assert "none carries a fixed layer list" in finding["detail"]


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
