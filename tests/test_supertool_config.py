"""This repository's own `.supertool.json`, as two invariants (#189).

A config file is not code, and a test that re-reads the JSON it just wrote
asserts nothing. These two assert something the file cannot state about
itself, and both were red on the commit that preceded them:

1. Enabling the `watch` preset without declaring a radar tier leaves `radar`
   refusing. The refusal is correct rather than a bug, so nothing fails until
   somebody runs the op -- the preset is simply one key short of working and
   no test, lint or CI leg says so.
2. A repository name hand-typed into a tracked file travels with that file
   when a contributor copies it into another repository, at which point two
   repos bind one watcher socket with a declaration each. The name belongs to
   a derivation from `.oss.json`, not to this file.

Each pairs with a positive control on a synthetic document, because an
assertion that a key is absent also passes when the reader found nothing at
all -- an unreadable file, a parser looking in the wrong place, a repo root
resolved one directory too high.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".supertool.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _radar_tiers(doc):
    """`ops.radar.radar_tiers` when it is a mapping, else None."""
    ops = doc.get("ops")
    if not isinstance(ops, dict):
        return None
    radar = ops.get("radar")
    if not isinstance(radar, dict):
        return None
    tiers = radar.get("radar_tiers")
    return tiers if isinstance(tiers, dict) else None


def _watch_names(doc):
    """Every `ops.*.watch_name` in the document, by op name."""
    ops = doc.get("ops")
    if not isinstance(ops, dict):
        return {}
    return {
        name: block["watch_name"]
        for name, block in ops.items()
        if isinstance(block, dict) and "watch_name" in block
    }


def test_the_config_is_there_and_declares_presets():
    """The control the two tests below stand on.

    Without it a moved file or a parse failure renders as two clean passes:
    no presets found, therefore no tier required; no ops found, therefore no
    name declared.
    """
    assert CONFIG.is_file(), "{} is missing".format(CONFIG)
    doc = _load(CONFIG)
    assert isinstance(doc, dict)
    assert isinstance(doc.get("presets"), list) and doc["presets"], (
        "no presets declared, so the watch-preset test below would pass vacuously"
    )


def test_the_watch_preset_comes_with_a_radar_tier():
    doc = _load(CONFIG)
    if "watch" not in doc.get("presets", []):
        pytest.skip("the watch preset is not enabled here, so radar is not loaded")
    tiers = _radar_tiers(doc)
    assert tiers, (
        "the watch preset is enabled and ops.radar.radar_tiers is absent or empty, "
        "so radar refuses instead of reconciling a board. This repository is on "
        "GitHub: declare the gh-prs tier."
    )
    assert "gh-prs" in tiers, (
        "this repository is on GitHub, so gh-prs is the tier that reads its "
        "board; declared tiers are {}".format(sorted(tiers))
    )


def test_a_watch_preset_without_a_tier_is_what_that_reader_catches():
    """Positive control: the reader fires on the shape the test above names."""
    assert _radar_tiers({"presets": ["git", "watch"], "ops": {"radar": {}}}) is None
    assert _radar_tiers({"presets": ["watch"]}) is None
    assert _radar_tiers({"ops": {"radar": {"radar_tiers": {}}}}) == {}
    assert _radar_tiers({"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}) == {
        "gh-prs": {}
    }


def test_no_repository_name_is_hand_typed_into_the_tracked_config():
    declared = _watch_names(_load(CONFIG))
    assert declared == {}, (
        "ops.{} declares a watch_name. A tracked file carrying one repository's "
        "name travels into the next repository somebody copies it to, and both "
        "then bind one socket with a declaration each. bin/oss-workspace derives "
        "the name from .oss.json instead.".format(sorted(declared))
    )


def test_a_hand_typed_name_would_be_seen():
    """Positive control: the reader finds a name when one is there."""
    assert _watch_names({"ops": {"radar": {"watch_name": "claude-oss"}}}) == {
        "radar": "claude-oss"
    }
    assert _watch_names({"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}) == {}
    assert _watch_names({}) == {}
