"""batch_hint derives its op classification from supertool, instead of a hardcoded copy (#537).

Found by the v0.13.0 release audit, round 1: `_WRITE_OP_PREFIXES`, `_EXTERNAL_OP_PREFIXES` and
`_READ_OP_PREFIXES` were a hand-copied snapshot of `supertool 'ops:roster'`'s own classification,
dated in a comment beside them -- exactly the second copy `CLAUDE.md`'s governing rule forbids,
because the copy is the one that goes stale in one direction only: an op whose class moves from
read-only to write upstream stays misclassified read-only here forever, since nothing re-derives
or checks the copy.

The fact the module never considered: `supertool 'ops:roster'` measures at well under a tenth of
a second (#537's own measurement, recorded in the commit that fixes this), so calling it once and
caching the answer -- rather than either the rejected "every Bash call" option or the un-considered
"never call it, keep a static copy" option -- is affordable. This module now derives the
classification and deletes the static lists; a `could-not-derive` third state (no `supertool` on
PATH, a non-zero exit, output that does not parse) degrades to "no op is confidently
read-only-or-write", never to a wrong classification in either direction.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import batch_hint  # noqa: E402


SAMPLE_ROSTER_TEXT = """## Ops

Every op loaded here, and nothing else.

- unmarked -- read-only.
- `*` -- writes files in this tree.
- `!` -- changes something outside this tree.

> 10 shipped presets are not loaded here: some/.supertool.json does not list them.

  append* around between edit* gh-issue git-push! read wc
"""


@pytest.fixture(autouse=True)
def _reset_roster_memo(monkeypatch):
    """Every test in this file starts from "nothing derived yet, nothing cached
    on disk" -- the module-level memo and the disk cache are both process-wide
    state that would otherwise leak between tests and between this file and
    test_batch_hint_490.py."""
    monkeypatch.setattr(batch_hint, "_ROSTER_CACHE", batch_hint._UNSET)


# --------------------------------------------------------------- _parse_roster_text


def test_parses_a_realistic_roster_block_into_three_classes():
    parsed = batch_hint._parse_roster_text(SAMPLE_ROSTER_TEXT)
    assert parsed is not None
    assert parsed["write"] == ["append", "edit"]
    assert parsed["external"] == ["git-push"]
    assert parsed["read"] == ["around", "between", "gh-issue", "read", "wc"]


def test_unparseable_text_is_none_not_an_empty_confident_roster():
    """The third state at the parse boundary: text that does not carry a
    recognisable roster block must not become an empty-but-confident roster,
    which would (via `roster()`) silently make every op fall through to
    "unknown" while looking like "derivation succeeded, there is nothing"."""
    assert batch_hint._parse_roster_text("supertool: command not found") is None
    assert batch_hint._parse_roster_text("") is None


SAMPLE_ROSTER_TEXT_NO_DISCLOSURE = """## Ops

Every op loaded here, and nothing else.

- unmarked -- read-only.
- `*` -- writes files in this tree.
- `!` -- changes something outside this tree.

  append* around between edit* gh-issue git-push! read wc
"""


def test_parses_a_roster_block_with_no_preset_disclosure_line():
    """Self-review finding on #537: the first version of this parser located the
    block by anchoring on the `>` preset-disclosure line printed by supertool's
    own `_preset_disclosure` -- which is only emitted when a `.supertool.json`
    fails to list every shipped preset. On a fully-configured repo (the
    well-configured population this fix exists to serve), `ops:roster`'s real
    stdout carries no `>` line at all, and the first version returned `None` for
    a completely successful, fully parseable call -- silently degrading every op
    to "unknown" forever with no visible symptom. The parser must locate the
    block from its own shape (a trailing run of lines that are entirely op
    tokens), not from an optional line that may not be there."""
    parsed = batch_hint._parse_roster_text(SAMPLE_ROSTER_TEXT_NO_DISCLOSURE)
    assert parsed is not None
    assert parsed["write"] == ["append", "edit"]
    assert parsed["external"] == ["git-push"]
    assert parsed["read"] == ["around", "between", "gh-issue", "read", "wc"]


# --------------------------------------------------------------- _derive_roster


def test_derive_roster_returns_none_when_supertool_is_not_on_path(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("no such file: supertool")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert batch_hint._derive_roster() is None


def test_derive_roster_returns_none_on_a_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="boom"),
    )
    assert batch_hint._derive_roster() is None


def test_derive_roster_parses_a_successful_call(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=SAMPLE_ROSTER_TEXT, stderr=""),
    )
    parsed = batch_hint._derive_roster()
    assert parsed == {
        "write": ["append", "edit"],
        "external": ["git-push"],
        "read": ["around", "between", "gh-issue", "read", "wc"],
    }


# --------------------------------------------------------------- roster(): memo + disk cache


def test_roster_is_derived_once_and_memoized_in_process(monkeypatch, tmp_path):
    monkeypatch.setenv("BATCH_HINT_STATE_DIR", str(tmp_path))
    calls = []

    def _fake_derive():
        calls.append(1)
        return {"write": ["edit"], "external": [], "read": ["read"]}

    monkeypatch.setattr(batch_hint, "_derive_roster", _fake_derive)
    first = batch_hint.roster()
    second = batch_hint.roster()
    assert first == second == {"write": ["edit"], "external": [], "read": ["read"]}
    assert len(calls) == 1  # not called twice for two roster() reads in one process


def test_roster_is_cached_to_disk_and_reused_without_a_second_derivation(monkeypatch, tmp_path):
    """The fact the module never checked: a cheap call is still worth caching
    across the many separate `batch_hint.py` subprocess invocations one
    session makes -- this is the read side of that cache, independent of the
    in-process memo above."""
    monkeypatch.setenv("BATCH_HINT_STATE_DIR", str(tmp_path))
    calls = []

    def _fake_derive():
        calls.append(1)
        return {"write": ["edit"], "external": [], "read": ["read"]}

    monkeypatch.setattr(batch_hint, "_derive_roster", _fake_derive)
    batch_hint.roster()
    assert len(calls) == 1

    # A fresh "process" -- reset only the in-process memo, exactly as a new
    # invocation of the hook script would start.
    monkeypatch.setattr(batch_hint, "_ROSTER_CACHE", batch_hint._UNSET)
    second = batch_hint.roster()
    assert second == {"write": ["edit"], "external": [], "read": ["read"]}
    assert len(calls) == 1  # disk cache satisfied it; no second derivation


def test_could_not_derive_is_none_and_is_not_cached_to_disk(monkeypatch, tmp_path):
    """A failed derivation must not be written to the disk cache -- caching
    `None` (or an empty roster) would make a transient failure (network hiccup,
    a PATH not yet set up) into a permanent one for the rest of the machine's
    cache TTL."""
    monkeypatch.setenv("BATCH_HINT_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(batch_hint, "_derive_roster", lambda: None)
    assert batch_hint.roster() is None
    assert not batch_hint._roster_cache_path().exists()


# --------------------------------------------------------------- _op_verdict: the control pair


def test_op_verdict_follows_a_reclassified_op_without_a_code_edit(monkeypatch):
    """The issue's own control pair, half one: an op that moved class upstream
    is reclassified by changing only what `roster()` answers -- nothing in
    this module's source changes."""
    monkeypatch.setattr(
        batch_hint, "_ROSTER_CACHE", {"write": ["grep"], "external": [], "read": []}
    )
    assert batch_hint._op_verdict("grep:pattern:file.py") == "not_offender"


def test_op_verdict_is_unchanged_for_an_op_whose_class_did_not_move(monkeypatch):
    """The issue's own control pair, half two: an op the roster still calls
    read-only classifies identically to before."""
    monkeypatch.setattr(
        batch_hint, "_ROSTER_CACHE", {"write": [], "external": [], "read": ["grep"]}
    )
    assert batch_hint._op_verdict("grep:pattern:file.py") == "single_readonly"


def test_op_verdict_degrades_to_unknown_when_roster_could_not_be_derived(monkeypatch):
    """Third state at the classification boundary: when nothing could be
    derived, a plain op name is `unknown` -- never guessed as read-only or
    as a mutation -- and the `@-` payload-marker fallback still catches what
    it always caught, because that heuristic does not depend on the roster
    at all."""
    monkeypatch.setattr(batch_hint, "_ROSTER_CACHE", None)
    assert batch_hint._op_verdict("read:foo.py") == "unknown"
    assert batch_hint._op_verdict("some-future-op:@-") == "not_offender"
