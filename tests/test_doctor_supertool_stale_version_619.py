"""#619: `supertool_entry_point` computes that `./supertool` resolves into a cached
version the install record no longer calls active, and reports it `ok` anyway --
the disagreement lands only in a parenthetical inside a line whose state says there
is nothing to look at. This is the reporting half of claude-supertool#2071: the
symlink resolves perfectly, to the wrong version, so nothing that checks for a
dangling link -- here or in supertool's own doctor -- can see it.

`stale-version` gets a state of its own, kept apart from `other-target` on purpose:
this link is unambiguously the plugin's own artifact, only an old one, and the
remedy (relink to the active entry) differs from "this points somewhere unrelated".
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


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _link(where, target):
    try:
        os.symlink(str(target), str(where))
    except (OSError, NotImplementedError, AttributeError) as exc:
        return "this platform would not create a symlink ({})".format(exc)
    return None


def _cache_two_versions(root, linked_version, active_version):
    """A plugin cache holding two supertool versions, with the install record
    naming `active_version` active -- so a link resolved into `linked_version`
    disagrees with what is actually running."""
    home = root / "cache"
    entries = {}
    for version in (linked_version, active_version):
        version_dir = home / MARKET / "supertool" / version
        version_dir.mkdir(parents=True, exist_ok=True)
        entry = version_dir / "supertool.py"
        entry.write_text("# supertool {}\n".format(version), encoding="utf-8")
        entries[version] = entry
    record = root / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"supertool@" + MARKET: [{"version": active_version}]}}),
        encoding="utf-8",
    )
    return home, record, entries


def test_a_link_into_a_superseded_cached_version_is_not_reported_ok(tmp_path):
    """The must-fire half: `./supertool` resolves to a real supertool.py in the
    plugin cache, but the install record says a DIFFERENT version is active --
    same shape as this repo's own #619, where 0.47.0 stayed linked for eleven
    days after 0.49.0 and 0.51.0 shipped."""
    project = tmp_path / "repo"
    project.mkdir()
    home, record, entries = _cache_two_versions(tmp_path, "0.47.0", "0.51.0")
    refused = _link(project / "supertool", entries["0.47.0"])
    if refused:
        pytest.skip(refused + "; what went untested is the stale-version arm")

    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "stale-version", (state, detail)
    assert "0.47.0" in detail and "0.51.0" in detail, detail

    doctor.check_supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "0.47.0" in message and "0.51.0" in message, message
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS


def test_a_link_into_the_active_version_is_still_ok(tmp_path):
    """The must-not-fire control, in the same fixture as the must-fire case above:
    a link resolving into the version the record actually calls active must stay
    `ok`, not `stale-version` -- the new state fires on disagreement, never on
    agreement."""
    project = tmp_path / "repo"
    project.mkdir()
    home, record, entries = _cache_two_versions(tmp_path, "0.47.0", "0.51.0")
    refused = _link(project / "supertool", entries["0.51.0"])
    if refused:
        pytest.skip(refused + "; what went untested is the still-ok control")

    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "ok", (state, detail)

    doctor.check_supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", (level, message)
