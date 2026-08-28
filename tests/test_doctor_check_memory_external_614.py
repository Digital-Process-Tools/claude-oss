"""#614 -- memory_layout resolved the store by joining the repo root onto
`.claude/remember`'s own config.json in every layout, including the marketplace one
where the plugin lives outside the repo entirely. In that layout the file it read is
none of the plugin's own three config layers (bundled, user-global, per-project), so
an external store keyed by `~/.remember/config.json`'s own `data_dir` was invisible:
`/oss:doctor` said "no identity.md" about a file it never looked for, while remember's
own doctor.sh reported it present and read.

Reported by an external maintainer (jbkkz) measuring against their own repo -- see
the issue for the two conflicting doctor outputs. Every fixture below is constructed
here rather than trusted from the report.

Three real fixes and one honest refusal, in the same file so the negative assertions
each carry a positive control:

- `$REMEMBER_DIR`, when the current process already has it, answers directly.
- `~/.remember/config.json`'s `data_dir`, when it names a plain path (no `{slug}`),
  is now read and resolved -- the layer the plugin's own resolution
  (`lib-memory-dir.sh`) checks BEFORE its bundled default, and the one the old code
  never consulted for a marketplace install.
- A `{slug}`-keyed `data_dir` is not resolved (reimplementing `session_dir_slug`
  would be a second copy of another plugin's algorithm going stale on its own
  schedule) -- `memory_layout` says so through its `unresolved` return value, and
  the two checks that call it report WARN "unknown", never a false absence.
- The swallowed `except (OSError, ValueError): pass` is gone: an unreadable or
  malformed config now reports "unknown", not silent defaulting to the repo-local
  store.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_memory  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


@pytest.fixture(autouse=True)
def _no_real_remember_dir(monkeypatch):
    """Without this, a machine that happens to have REMEMBER_DIR exported in its
    ambient environment (the plugin's own hooks set it while they run) would make
    every test below depend on that machine's own live session."""
    monkeypatch.delenv("REMEMBER_DIR", raising=False)


def _only():
    lines = list(doctor.FINDINGS)
    assert len(lines) == 1, "check must print exactly one line, got {!r}".format(lines)
    return lines[0]


def _home(tmp_path):
    """Isolated and empty unless a test populates it -- see the module docstring
    on `tests/test_doctor_memory_guidance_284.py` for why this must never be the
    real ~/.remember."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def _user_config(home, data_dir):
    cfg_dir = home / ".remember"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps({"data_dir": data_dir}), encoding="utf-8")


# ---------------------------------------------------------------------------
# memory_layout itself
# ---------------------------------------------------------------------------


def test_env_var_wins_over_everything_else(tmp_path):
    """$REMEMBER_DIR, when the process already has it, is authoritative -- no
    config is even opened. Positive control for the negative assertion below."""
    external = tmp_path / "elsewhere"
    external.mkdir()
    home = _home(tmp_path)
    # A user-global config that would say something else entirely, to prove the
    # env var is checked first and the config is never opened.
    _user_config(home, str(tmp_path / "unrelated"))

    import os

    os.environ["REMEMBER_DIR"] = str(external)
    try:
        config_dir, data_dir, unresolved = doctor_check_memory.memory_layout(
            tmp_path, home=home
        )
    finally:
        del os.environ["REMEMBER_DIR"]

    assert data_dir == external, data_dir
    assert unresolved is None, unresolved


def test_user_global_data_dir_is_now_read(tmp_path):
    """The whole of #614, reduced: a marketplace install's real config layer,
    previously never opened."""
    external = tmp_path / "elsewhere" / "store"
    external.mkdir(parents=True)
    home = _home(tmp_path)
    _user_config(home, str(external))

    _, data_dir, unresolved = doctor_check_memory.memory_layout(tmp_path, home=home)
    assert data_dir == external, data_dir
    assert unresolved is None, unresolved


def test_no_user_global_config_keeps_the_legacy_default(tmp_path):
    """Negative control for the test above: nothing set, nothing to resolve, the
    repo-local default is unchanged."""
    home = _home(tmp_path)
    _, data_dir, unresolved = doctor_check_memory.memory_layout(tmp_path, home=home)
    assert data_dir == tmp_path / ".remember", data_dir
    assert unresolved is None, unresolved


def test_slug_keyed_data_dir_is_reported_unresolved_not_defaulted(tmp_path):
    """The third state this issue is actually about: an external store keyed by
    {slug}, which memory_layout does not compute. Silently keeping the repo-local
    default here is the exact bug -- the fix must say it does not know, not guess
    "legacy" and be wrong."""
    home = _home(tmp_path)
    _user_config(home, "~/.remember/{slug}")

    config_dir, data_dir, unresolved = doctor_check_memory.memory_layout(
        tmp_path, home=home
    )
    assert unresolved is not None
    assert "{slug}" in unresolved, unresolved
    assert "session_dir_slug" in unresolved or "lib-slug.sh" in unresolved, unresolved


def test_local_install_never_consults_the_home_config(tmp_path):
    """A local install's bundled config is `.claude/remember/config.json` itself
    -- the home directory must not be touched at all. Proven with a home config
    that, if read, would resolve somewhere else entirely."""
    config_dir = tmp_path / ".claude" / "remember"
    (config_dir / "scripts").mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"data_dir": ".remember"}), encoding="utf-8"
    )
    home = _home(tmp_path)
    _user_config(home, str(tmp_path / "would-be-wrong"))

    _, data_dir, unresolved = doctor_check_memory.memory_layout(tmp_path, home=home)
    assert data_dir == tmp_path / ".remember", data_dir
    assert unresolved is None, unresolved


def test_unresolvable_home_is_reported_unknown_not_silently_defaulted(tmp_path, monkeypatch):
    """The auditor's own finding on this fix: `Path.home()` raising RuntimeError (no
    HOME/USERPROFILE) used to fall straight back to the repo-local default with no
    `unresolved` reason at all -- indistinguishable from "checked, and this really is
    the store". There is exactly one other candidate layer here (unlike
    doctor_check_merge_permission.py's settings_candidates, which still has the
    project scope to fall back to), so a home that cannot be resolved must be
    reported as unknown, not silently taken as confirmed."""

    def _boom():
        raise RuntimeError("no home directory")

    monkeypatch.setattr(doctor_check_memory.Path, "home", staticmethod(_boom))

    _, data_dir, unresolved = doctor_check_memory.memory_layout(tmp_path, home=None)
    assert data_dir == tmp_path / ".remember", data_dir
    assert unresolved is not None
    assert "home directory could not be determined" in unresolved, unresolved


def test_malformed_user_global_config_is_unknown_not_silently_defaulted(tmp_path):
    """The swallowed `except (OSError, ValueError): pass` this issue names directly
    (#614 point 4): bad JSON must surface as unknown, not vanish."""
    home = _home(tmp_path)
    cfg_dir = home / ".remember"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{not json", encoding="utf-8")

    _, data_dir, unresolved = doctor_check_memory.memory_layout(tmp_path, home=home)
    assert unresolved is not None
    assert "not valid JSON" in unresolved, unresolved


# ---------------------------------------------------------------------------
# check_memory / check_core_memories consuming the unresolved state
# ---------------------------------------------------------------------------


def test_check_memory_reports_unknown_for_a_slug_keyed_store(tmp_path):
    """The false absence this issue was filed over: check_memory must not say "no
    identity.md" about a store it knows it cannot locate."""
    home = _home(tmp_path)
    _user_config(home, "~/.remember/{slug}")
    # A local .remember that, if consulted, would look like "nothing here" --
    # proving the check does not fall through to it once unresolved.
    (tmp_path / ".remember").mkdir()

    doctor.check_memory(tmp_path, home=home)
    state, message = _only()
    assert state == "WARN"
    assert "unknown" in message, message
    assert "no identity.md" not in message, message


def test_check_memory_still_finds_identity_in_a_resolved_external_store(tmp_path):
    """Positive control for the test above, same layout shape minus the slug:
    resolution succeeds and identity.md is found where the config says it is."""
    external = tmp_path / "elsewhere" / "store"
    external.mkdir(parents=True)
    (external / "identity.md").write_text("x\n", encoding="utf-8")
    home = _home(tmp_path)
    _user_config(home, str(external))

    doctor.check_memory(tmp_path, home=home)
    state, message = _only()
    assert state == "OK", message
    assert "memory store configured" in message, message


def test_check_core_memories_reports_unknown_for_a_slug_keyed_store(tmp_path):
    home = _home(tmp_path)
    _user_config(home, "~/.remember/{slug}")

    doctor.check_core_memories(tmp_path, home=home)
    state, message = _only()
    assert state == "WARN"
    assert "unknown" in message, message


def test_check_core_memories_still_answers_for_a_resolved_external_store(tmp_path):
    """Positive control: with resolution succeeding, check_core_memories answers
    exactly as it does for the repo-local layout."""
    external = tmp_path / "elsewhere" / "store"
    external.mkdir(parents=True)
    home = _home(tmp_path)
    _user_config(home, str(external))

    doctor.check_core_memories(tmp_path, home=home)
    state, message = _only()
    assert state == "OK", message
    assert "does not exist yet" not in message, message
    assert "no core-memories.md" in message or "nothing recorded" in message, message
