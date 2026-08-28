"""#623: `check_watch_channel` reported `OK` whether a `watch_name` reached every
watch op supertool spawns from, or only one of the five op blocks in
`.supertool.json`. `_declared_watch_names` (the pre-existing local read) answers
"is a name declared anywhere at all", which the moment ONE op block carries
`watch_name` -- so a repo that declared it on `radar` alone, leaving
`channel`/`unwatch`/`watch`/`watches` silent, read as fully configured. Only those
four ops ever spawn or reach a poller; a name reaching `radar` alone reads a
private board over a fleet the other four still resolve to the shared default,
which renders identically to a healthy empty board.

`_watch_declaration_split` answers the finer question off the installed
supertool's own `presets/watch/naming.py:declared_names()` -- read, never
re-derived, per `CLAUDE.md`'s rule against a second copy of a dependency's
published classification. This file fabricates a minimal `naming.py`, the same
technique `test_consumer_watch_name_verdict_reads_the_installed_naming_rule`
already uses for the sibling check, to test doctor's own wiring (registry scan,
import, forwarding the four fields) without depending on supertool's internal
implementation.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

from test_doctor_inprocess import (  # noqa: E402
    _REAL_WATCH_DECLARATION_SPLIT,
    _supertool_config,
)

FAKE_NAMING = """
import json
import os

WATCH_OPS = ("channel", "radar", "unwatch", "watch", "watches")


class Declared:
    def __init__(self, state, declaring_ops, silent_ops, why):
        self.state = state
        self.declaring_ops = declaring_ops
        self.silent_ops = silent_ops
        self.why = why


def declared_names(start_dir=None):
    path = os.path.join(start_dir, ".supertool.json")
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        return Declared("no-config", (), tuple(WATCH_OPS), "")
    except (OSError, ValueError) as err:
        return Declared("unreadable", (), (), type(err).__name__)
    ops = doc.get("ops") if isinstance(doc, dict) else {}
    blocks = ops if isinstance(ops, dict) else {}
    declaring = {
        op: block["watch_name"]
        for op, block in blocks.items()
        if isinstance(block, dict)
        and isinstance(block.get("watch_name"), str)
        and block["watch_name"]
    }
    silent = tuple(sorted(set(WATCH_OPS) - set(declaring)))
    if not declaring:
        return Declared("silent", (), silent, "")
    return Declared("found", tuple(sorted(declaring)), silent, "")
"""


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _fake_install(tmp_path, name="supertool-9.9.9"):
    install_dir = tmp_path / name
    naming_dir = install_dir / "presets" / "watch"
    naming_dir.mkdir(parents=True)
    (naming_dir / "naming.py").write_text(FAKE_NAMING, encoding="utf-8")
    registry = tmp_path / "installed_plugins.json"
    registry.write_text(
        json.dumps(
            {"plugins": {"supertool@marketplace": [{"installPath": str(install_dir)}]}}
        ),
        encoding="utf-8",
    )
    return registry


def _point_expanduser_at(monkeypatch, registry):
    monkeypatch.setattr(
        doctor.os.path,
        "expanduser",
        lambda p: str(registry) if p.endswith("installed_plugins.json") else p,
    )


def test_split_reports_the_silent_ops_for_a_partial_declaration(tmp_path, monkeypatch):
    """Must-fire half: `watch_name` on two of five ops."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _supertool_config(
        repo, {"ops": {"radar": {"watch_name": "oss"}, "channel": {"watch_name": "oss"}}}
    )
    registry = _fake_install(tmp_path)
    _point_expanduser_at(monkeypatch, registry)

    state, declaring_ops, silent_ops, why = _REAL_WATCH_DECLARATION_SPLIT(repo)
    assert state == "found", (state, why)
    assert set(declaring_ops) == {"channel", "radar"}
    assert set(silent_ops) == {"unwatch", "watch", "watches"}


def test_split_reports_no_silent_ops_for_a_full_declaration(tmp_path, monkeypatch):
    """Must-not-fire control, same fixture shape: all five ops declared."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _supertool_config(
        repo,
        {
            "ops": {
                op: {"watch_name": "oss"}
                for op in ("channel", "radar", "unwatch", "watch", "watches")
            }
        },
    )
    registry = _fake_install(tmp_path)
    _point_expanduser_at(monkeypatch, registry)

    state, declaring_ops, silent_ops, why = _REAL_WATCH_DECLARATION_SPLIT(repo)
    assert state == "found", (state, why)
    assert silent_ops == ()


def test_split_is_unknown_when_the_registry_is_absent(tmp_path, monkeypatch):
    """Mirrors `_consumer_watch_name_verdict`'s own absent-registry test: silence
    here must not be indistinguishable from a clean full declaration."""
    monkeypatch.setattr(
        doctor.os.path,
        "expanduser",
        lambda p: str(tmp_path / "nope.json") if p.endswith("installed_plugins.json") else p,
    )
    state, declaring_ops, silent_ops, why = _REAL_WATCH_DECLARATION_SPLIT(tmp_path)
    assert state == "unknown"
    assert why


def test_check_watch_channel_reports_partial_for_a_half_declared_repo(
    tmp_path, monkeypatch, capsys
):
    """End to end: `watch_name` on one op block must not read as `OK`."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    monkeypatch.setattr(
        doctor,
        "_watch_declaration_split",
        lambda project_dir: ("found", ("radar",), ("channel", "unwatch", "watch", "watches"), ""),
    )
    doctor.check_watch_channel(tmp_path, env={})
    capsys.readouterr()
    findings = list(doctor.FINDINGS)
    assert [state for state, _ in findings] == ["WARN"]
    assert "channel" in findings[0][1] and "unwatch" in findings[0][1]


def test_check_watch_channel_reports_split_unknown_rather_than_ok(
    tmp_path, monkeypatch, capsys
):
    """Must-fire pair for the state above: the split could not be determined at
    all, and that must not clear as OK either -- #533's own lesson, one field
    over."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    monkeypatch.setattr(
        doctor,
        "_watch_declaration_split",
        lambda project_dir: ("unknown", (), (), "no supertool install"),
    )
    doctor.check_watch_channel(tmp_path, env={})
    capsys.readouterr()
    findings = list(doctor.FINDINGS)
    assert [state for state, _ in findings] == ["WARN"]
    assert "OK" not in [state for state, _ in findings]


def test_check_watch_channel_stays_ok_when_fully_declared(tmp_path, monkeypatch, capsys):
    """Must-not-fire control for both states above: nothing silent clears
    normally, through the ordinary `declared-only` -> OK path."""
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    monkeypatch.setattr(
        doctor, "_watch_declaration_split", lambda project_dir: ("found", ("radar",), (), "")
    )
    monkeypatch.setattr(doctor, "_consumer_watch_name_verdict", lambda name: ("accepted", ""))
    doctor.check_watch_channel(tmp_path, env={})
    capsys.readouterr()
    findings = list(doctor.FINDINGS)
    assert [state for state, _ in findings] == ["OK"]
