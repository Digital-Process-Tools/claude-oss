"""#780 -- `own-tree-stranger` never resolves the link, so a `./supertool`
pointing at the tree's OWN `supertool.py` was warned about identically to one
pointing at a stranger.

`supertool_entry_point` returned `own-tree-stranger` on `os.lstat` succeeding
alone, inside a supertool checkout, without ever comparing the link's target
against the `core` it already had in hand. The `_same_file` machinery every
other branch of this function uses to keep "different" apart from "could not
tell" was simply never reached here. This file pins the three-way split that
replaces it: the alias earns `own-tree-ok`, a real stranger keeps the WARN as
`own-tree-stranger`, and a comparison the filesystem would not answer is its
own `own-tree-unknown` state rather than folding into either.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _link(where, target):
    """Symlink, or the sentence saying why this platform could not make one."""
    try:
        os.symlink(str(target), str(where))
    except (OSError, NotImplementedError, AttributeError) as exc:
        return "this platform would not create a symlink ({})".format(exc)
    return None


def _own_tree(tmp_path, name="claude-supertool"):
    project = tmp_path / name
    project.mkdir()
    (project / ".supertool.json").write_text("{}\n", encoding="utf-8")
    (project / "supertool.py").write_text("# core\n", encoding="utf-8")
    return project


def test_a_wrapper_aliasing_the_trees_own_core_is_ok(tmp_path):
    """The convenience form the issue is about: `./supertool -> supertool.py`,
    both inside the same checkout. Before #780 this rendered as
    `own-tree-stranger` -- the identical WARN a genuine stranger earns."""
    project = _own_tree(tmp_path)
    refused = _link(project / "supertool", project / "supertool.py")
    if refused:
        pytest.skip(refused + "; what went untested is the own-tree-ok arm")

    state, detail = doctor.supertool_entry_point(project, cache_root=str(tmp_path / "no-cache"))
    assert state == "own-tree-ok", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=str(tmp_path / "no-cache"))
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", message
    assert "supertool.py" in message, message
    assert len(doctor.FINDINGS) == 1


def test_a_wrapper_pointing_elsewhere_still_warns(tmp_path):
    """Positive control for the arm above: a genuinely different target inside the
    same own-tree checkout must still WARN as `own-tree-stranger` -- proving the
    split does not just default everything in an own-tree checkout to OK."""
    project = _own_tree(tmp_path)
    home = tmp_path / "cache"
    market_dir = home / "dpt-plugins" / "supertool" / "9.9.9"
    market_dir.mkdir(parents=True)
    stranger_entry = market_dir / "supertool.py"
    stranger_entry.write_text("# plugin core\n", encoding="utf-8")
    record = tmp_path / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"supertool@dpt-plugins": [{"version": "9.9.9"}]}}),
        encoding="utf-8",
    )
    refused = _link(project / "supertool", stranger_entry)
    if refused:
        pytest.skip(refused + "; what went untested is the own-tree-stranger arm")

    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "own-tree-stranger", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert len(doctor.FINDINGS) == 1


def test_a_readlink_failure_reads_as_could_not_tell_not_a_stranger(tmp_path, monkeypatch):
    """`_same_file` returning `None` -- the filesystem refusing to answer -- must
    render as its own `own-tree-unknown` WARN, not silently fold into the
    `own-tree-stranger` accusation. Stubbed at `_same_file` rather than by
    constructing a real unreadable path, which is unreliable cross-platform."""
    project = _own_tree(tmp_path)
    refused = _link(project / "supertool", project / "supertool.py")
    if refused:
        pytest.skip(refused + "; what went untested is the own-tree-unknown arm")

    monkeypatch.setattr(doctor, "_same_file", lambda left, right: None)

    state, detail = doctor.supertool_entry_point(project, cache_root=str(tmp_path / "no-cache"))
    assert state == "own-tree-unknown", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=str(tmp_path / "no-cache"))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "unknown" in message, message
    assert len(doctor.FINDINGS) == 1
