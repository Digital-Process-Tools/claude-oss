"""Are the declared dependencies actually configured?

Installing them is automatic; configuring them is not, and the difference is invisible.
A memory plugin with no identity still runs and still saves. A rule matcher whose index
was never rebuilt still runs and matches nothing -- and a rule that never fires looks
exactly like a rule that fired and had nothing to say.

So these are checks, not assumptions, and each has three outcomes rather than two.
"""

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


def test_a_memory_store_without_an_identity_is_reported(tmp_path):
    """Saved sessions nobody has told it whose they are still look like a working
    setup, because saving is the part that works.
    """
    (tmp_path / ".remember").mkdir()
    doctor.check_memory(tmp_path)
    assert _states() == ["WARN"]
    assert "identity" in _messages().lower()


def test_a_configured_memory_store_is_ok(tmp_path):
    store = tmp_path / ".remember"
    store.mkdir()
    (store / "identity.md").write_text("who this is\n", encoding="utf-8")
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]


# ---------------------------------------------------------------------------- jit


def test_no_rules_directory_is_reported_as_absent_not_as_fine(tmp_path):
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"]
    assert "no rules" in _messages().lower()


def test_rules_with_no_index_are_a_finding(tmp_path):
    """This is the failure worth catching: the rules exist, the matcher runs, and
    nothing ever fires because the table it reads is not there.
    """
    rules = tmp_path / ".claude" / "jit-context"
    rules.mkdir(parents=True)
    (rules / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]
    assert "index" in _messages().lower()


def test_an_index_older_than_a_rule_is_reported_as_stale(tmp_path):
    """A rule edited after the last rebuild is a rule whose row says something else."""
    rules = tmp_path / ".claude" / "jit-context"
    rules.mkdir(parents=True)
    index = rules / "00-index.tsv"
    index.write_text("stale\n", encoding="utf-8")
    time.sleep(0.01)
    rule = rules / "conventions.md"
    rule.write_text("---\ntitle: x\n---\n", encoding="utf-8")
    newer = index.stat().st_mtime + 60
    import os

    os.utime(rule, (newer, newer))

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"]
    assert "stale" in _messages().lower()


def test_rules_with_a_current_index_are_ok(tmp_path):
    rules = tmp_path / ".claude" / "jit-context"
    rules.mkdir(parents=True)
    (rules / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    time.sleep(0.01)
    (rules / "00-index.tsv").write_text("conventions\tx\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"]


def test_an_empty_index_beside_real_rules_does_not_read_as_current(tmp_path):
    """An index file that exists and holds nothing is the same silence as no index,
    one layer down -- and it is the one that passes an existence check.
    """
    rules = tmp_path / ".claude" / "jit-context"
    rules.mkdir(parents=True)
    (rules / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (rules / "00-index.tsv").write_text("", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]
    assert "empty" in _messages().lower()


def test_the_finding_names_how_to_rebuild(tmp_path):
    rules = tmp_path / ".claude" / "jit-context"
    rules.mkdir(parents=True)
    (rules / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert "rebuild" in _messages().lower()
