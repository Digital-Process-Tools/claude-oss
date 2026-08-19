"""#285 -- `OK supertool: available` answers PATH, and no brief asks about PATH.

Every developer brief this plugin issues says to call `./supertool`, and this repo's
own rule layer *blocks* Read/Edit/Write/Glob/Grep with a message naming the op that
replaces each. So the entry point is mandatory. It is also gitignored on purpose --
`scripts/scaffold.py` writes `/supertool` into a managed repo's `.gitignore` because
committing it would bake one developer's absolute path into every other clone.

Mandatory, and absent from every fresh clone by design. `check_tool("supertool", ...)`
says nothing about it: it answers *is the binary on PATH*, which a reader takes for
*does this repo have the entry point the brief named*. Two questions, one line, and the
remedies differ.

Observed while writing this, in the worktree the fix was written in: `ls -l ./supertool`
-> `No such file or directory`, while `which supertool` resolved. Both "OK" states of
the old check, in a tree where every op call through `./supertool` would have failed.

**Which component creates it is established here rather than left open**, which is the
half #285 filed as unknown and floated sending upstream. supertool's own
`hooks/session-start.sh` creates it, keyed on the session's cwd, and already handles all
three cases correctly -- it links when nothing is there, leaves a stranger untouched, and
refuses to link at all inside a supertool checkout. Nothing upstream is broken. What is
missing is entirely local: doctor never says which of those happened.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

MARKET = "dpt-plugins"
VERSION = "9.9.9"


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _cache(root, version=VERSION):
    """A plugin cache holding one supertool, plus the install record naming it active.

    Both, because ``active_versions`` reads the record and not the listing -- old
    versions stay unpacked and a glob returns whichever sorts last.
    """
    home = root / "cache"
    # Idempotent: a test that needs both a cache and a state calls this twice.
    (home / MARKET / "supertool" / version).mkdir(parents=True, exist_ok=True)
    entry = home / MARKET / "supertool" / version / "supertool.py"
    entry.write_text("# the plugin's entry point\n", encoding="utf-8")
    record = root / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"supertool@" + MARKET: [{"version": version}]}}),
        encoding="utf-8",
    )
    return home, record, entry


def _link(where, target):
    """Symlink, or the sentence saying why this platform could not make one.

    Windows needs a privilege or Developer Mode for this, so the deny is measured by
    attempting it -- never assumed from ``sys.platform``.
    """
    try:
        os.symlink(str(target), str(where))
    except (OSError, NotImplementedError, AttributeError) as exc:
        return "this platform would not create a symlink ({})".format(exc)
    return None


def _state(project, root, **kw):
    home, record, entry = _cache(root)
    kw.setdefault("cache_root", str(home))
    kw.setdefault("record", str(record))
    return doctor.supertool_entry_point(project, **kw), entry


def test_absent_is_a_finding_and_names_what_creates_it(tmp_path):
    """The state of every fresh clone, and of every worktree an agent cuts mid-session:
    the hook fires on a session's cwd, and nothing fires when an agent cds into a
    directory that did not exist when the session opened."""
    project = tmp_path / "repo"
    project.mkdir()
    (state, detail), _ = _state(project, tmp_path)
    assert state == "absent", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=None, record=None)
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "./supertool" in message, message
    assert "session-start" in message, message


def test_the_plugins_own_link_is_the_passing_state(tmp_path):
    """Positive control. Without it every assertion in this file is satisfied by a
    check that returns a finding unconditionally."""
    project = tmp_path / "repo"
    project.mkdir()
    home, record, entry = _cache(tmp_path)
    refused = _link(project / "supertool", entry)
    if refused:
        pytest.skip(refused + "; what went untested is the matching-target arm")
    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "ok", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    assert doctor.FINDINGS[-1][0] == "OK"


def test_a_link_to_something_else_is_distinct_from_absent(tmp_path):
    """The second failure mode, and the one observed on this very repo -- supertool's
    session-start hook reported `./supertool already exists here and is not the plugin
    symlink -- leaving it untouched`. Its remedy is not the absent case's remedy, so it
    must not render as the absent case."""
    project = tmp_path / "repo"
    project.mkdir()
    stranger = tmp_path / "elsewhere.py"
    stranger.write_text("# not the plugin\n", encoding="utf-8")
    home, record, _ = _cache(tmp_path)
    refused = _link(project / "supertool", stranger)
    if refused:
        pytest.skip(refused + "; what went untested is the other-target arm")
    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "other-target", (state, detail)
    assert "elsewhere.py" in detail, detail

    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "elsewhere.py" in message, message


def test_an_undeterminable_plugin_path_is_not_reported_as_a_wrong_target(tmp_path):
    """The third state, and the reason this is a function rather than an `==`.

    With no readable cache there is no answer to compare against. Reporting
    `other-target` there would accuse a link that may be perfectly correct; reporting
    `ok` would clear one that may not be. Neither is measured, so neither is said.
    """
    project = tmp_path / "repo"
    project.mkdir()
    stranger = tmp_path / "somewhere.py"
    stranger.write_text("x\n", encoding="utf-8")
    refused = _link(project / "supertool", stranger)
    if refused:
        pytest.skip(refused + "; what went untested is the unknown-plugin-path arm")
    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(tmp_path / "no-cache"), record=str(tmp_path / "no-record")
    )
    assert state == "unknown-plugin-path", (state, detail)

    doctor.check_supertool_entry_point(
        project,
        cache_root=str(tmp_path / "no-cache"),
        record=str(tmp_path / "no-record"),
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "unknown" in message or "could not" in message, message
    assert "somewhere.py" in message, message


def test_a_regular_file_at_that_name_is_its_own_state(tmp_path):
    """Not a symlink at all. `readlink` has nothing to say, and calling it absent would
    be wrong in the direction that gets acted on."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "supertool").write_text("#!/bin/sh\n", encoding="utf-8")
    (state, detail), _ = _state(project, tmp_path)
    assert state == "not-a-symlink", (state, detail)


def test_a_dangling_link_is_not_the_same_as_no_link(tmp_path):
    """A symlink pointing at a checkout that has been moved or deleted. Present, wrong,
    and its remedy is re-linking rather than creating."""
    project = tmp_path / "repo"
    project.mkdir()
    refused = _link(project / "supertool", tmp_path / "gone" / "supertool.py")
    if refused:
        pytest.skip(refused + "; what went untested is the dangling arm")
    (state, detail), _ = _state(project, tmp_path)
    assert state == "dangling", (state, detail)


def test_a_supertool_checkout_is_not_told_to_create_a_wrapper(tmp_path):
    """Transcribed from supertool's own session-start hook rather than invented here:
    inside a tree carrying its own `.supertool.json` and `supertool.py`, the hook
    deliberately creates NO wrapper, because one pointing at the plugin install would
    run the plugin core against this tree's presets -- the mix every custom op declines.

    claude-supertool is itself managed by this loop, so without this arm doctor would
    fire a confident wrong warning in the one repository the tool comes from.
    """
    project = tmp_path / "claude-supertool"
    project.mkdir()
    (project / ".supertool.json").write_text("{}\n", encoding="utf-8")
    (project / "supertool.py").write_text("# core\n", encoding="utf-8")
    (state, detail), _ = _state(project, tmp_path)
    assert state == "own-tree", (state, detail)

    home, record, _ = _cache(tmp_path)
    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", message
    assert "supertool.py" in message, message


def test_a_wrapper_inside_a_supertool_checkout_is_its_own_state(tmp_path):
    """The stranger case of the arm above, and not a hypothetical: running this check
    against the maintainer's claude-supertool clone printed it. The hook leaves anything
    already at that name untouched, so a wrapper made before the tree became its own
    supertool checkout stays there -- and through it every custom op answers "comes from
    a different supertool tree" and exits 1. Present, looks right, works for nothing.

    Flagged by the review of this diff as an untested state. It is testable, so it is
    tested rather than argued down.
    """
    project = tmp_path / "claude-supertool"
    project.mkdir()
    (project / ".supertool.json").write_text("{}\n", encoding="utf-8")
    (project / "supertool.py").write_text("# core\n", encoding="utf-8")
    home, record, entry = _cache(tmp_path)
    refused = _link(project / "supertool", entry)
    if refused:
        pytest.skip(refused + "; what went untested is the own-tree-stranger arm")

    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "own-tree-stranger", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "supertool.py" in message, message
    # Distinct from the plain own-tree arm, which is an OK. Without this the two could
    # share a message and the test above would still pass.
    assert len(doctor.FINDINGS) == 1


def test_the_check_prints_exactly_one_line_in_every_state(tmp_path):
    """doctor's contract is one line per check. A state that printed none would be the
    silence this whole file is about, and a state that printed two would scroll."""
    home, record, entry = _cache(tmp_path)
    seen = set()
    for name in ("absent", "not-a-symlink", "own-tree"):
        project = tmp_path / ("case-" + name)
        project.mkdir()
        if name == "not-a-symlink":
            (project / "supertool").write_text("x\n", encoding="utf-8")
        if name == "own-tree":
            (project / ".supertool.json").write_text("{}\n", encoding="utf-8")
            (project / "supertool.py").write_text("x\n", encoding="utf-8")
        doctor.FINDINGS.clear()
        doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
        assert len(doctor.FINDINGS) == 1, (name, doctor.FINDINGS)
        seen.add(name)
    assert seen == {"absent", "not-a-symlink", "own-tree"}
