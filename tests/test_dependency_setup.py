"""Are the declared dependencies actually configured?

Installing them is automatic; configuring them is not, and the difference is invisible.
A memory plugin with no identity still runs and still saves. A rule matcher whose index
was never rebuilt still runs and matches nothing -- and a rule that never fires looks
exactly like a rule that fired and had nothing to say.

So these are checks, not assumptions, and each has three outcomes rather than two.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _states():
    return [state for state, _ in doctor.FINDINGS]


def _messages():
    return " ".join(message for _, message in doctor.FINDINGS)


# ------------------------------------------------------------------------- memory


def test_a_project_with_no_memory_store_warns_with_the_fix(tmp_path):
    doctor.check_memory(tmp_path)
    assert _states() == ["WARN"]
    assert "remember" in _messages()


def _memory(root, identity=True, data_dir=".remember"):
    """The real layout: config and identity in `.claude/remember/`, sessions in the
    `data_dir` that config names.

    Conflating the two was a live bug. This checker looked for identity inside the DATA
    directory, so it reported "no identity" for every correctly configured repo -- and
    I relayed that about two of our own before somebody said they were surprised.
    """
    config_dir = root / ".claude" / "remember"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({"data_dir": data_dir}), encoding="utf-8"
    )
    if identity:
        (config_dir / "identity.md").write_text("who the agent is\n", encoding="utf-8")
    (root / data_dir).mkdir(parents=True, exist_ok=True)
    return config_dir


def test_a_memory_store_without_an_identity_is_reported(tmp_path):
    """Sessions save fine without one, which is what makes the gap invisible."""
    _memory(tmp_path, identity=False)
    doctor.check_memory(tmp_path)
    assert _states() == ["WARN"]
    assert "identity" in _messages().lower()


def test_a_configured_memory_store_is_ok(tmp_path):
    _memory(tmp_path)
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]


def test_identity_is_looked_for_beside_the_config_not_in_the_data_dir(tmp_path):
    """The bug this fixes, from both sides: identity in the data dir must NOT satisfy
    the check, and identity beside config.json must.
    """
    _memory(tmp_path, identity=False)
    (tmp_path / ".remember" / "identity.md").write_text("wrong place\n", encoding="utf-8")
    doctor.check_memory(tmp_path)
    assert _states() == ["WARN"]


def test_a_custom_data_dir_from_the_config_is_honoured(tmp_path):
    """`data_dir` is configurable, so a hardcoded `.remember` reports a missing store
    for a repo that has one.
    """
    _memory(tmp_path, data_dir="memory-store")
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]


# ---------------------------------------------------------------------------- jit


def _layer(root, dimension="vocabulary", layer="00-manual"):
    """The real layout: rules live per dimension, per layer, and each layer carries
    its OWN index. An earlier version of this check looked for one index at the root
    of the rules directory, which does not exist -- so a correctly configured repo
    would have been told, permanently and confidently, that none of its rules run.
    """
    path = root / ".claude" / "jit-context" / dimension / layer
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_no_rules_directory_is_reported_as_absent_not_as_fine(tmp_path):
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"]
    assert "no rules" in _messages().lower()


def test_rules_with_no_index_are_a_finding(tmp_path):
    """This is the failure worth catching: the rules exist, the matcher runs, and
    nothing ever fires because the table it reads is not there.
    """
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]
    assert "index" in _messages().lower()


def test_the_index_is_looked_for_inside_the_layer_not_at_the_root(tmp_path):
    """An index at the rules root does not satisfy a layer that has none of its own."""
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (tmp_path / ".claude" / "jit-context" / "00-index.tsv").write_text("x\ty\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]


def test_each_dimension_is_checked_separately(tmp_path):
    """One indexed dimension does not vouch for another. Reporting OK because the
    first layer checked out is how a whole dimension goes quiet unnoticed.
    """
    indexed = _layer(tmp_path, "vocabulary")
    (indexed / "billing.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (indexed / "00-index.tsv").write_text("billing\tx\n", encoding="utf-8")
    unindexed = _layer(tmp_path, "paths")
    (unindexed / "commands.md").write_text("---\ntitle: y\n---\n", encoding="utf-8")

    doctor.check_jit_rules(tmp_path)
    assert "FAIL" in _states()
    assert "paths" in _messages()


def test_an_index_older_than_a_rule_is_reported_as_stale(tmp_path):
    """A rule edited after the last rebuild is a rule whose row says something else."""
    layer = _layer(tmp_path)
    index = layer / "00-index.tsv"
    index.write_text("stale\n", encoding="utf-8")
    time.sleep(0.01)
    rule = layer / "conventions.md"
    rule.write_text("---\ntitle: x\n---\n", encoding="utf-8")
    newer = index.stat().st_mtime + 60
    os.utime(rule, (newer, newer))

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"]
    assert "stale" in _messages().lower()


def test_rules_with_a_current_index_are_ok(tmp_path):
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    time.sleep(0.01)
    (layer / "00-index.tsv").write_text("conventions\tx\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"]


def test_an_empty_index_beside_real_rules_does_not_read_as_current(tmp_path):
    """An index file that exists and holds nothing is the same silence as no index,
    one layer down -- and it is the one that passes an existence check.
    """
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (layer / "00-index.tsv").write_text("", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]
    assert "empty" in _messages().lower()


def test_the_finding_names_how_to_rebuild(tmp_path):
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert "rebuild" in _messages().lower()
