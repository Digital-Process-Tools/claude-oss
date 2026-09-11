"""#1383: `schemas/agent-report.schema.json` carries a `review.spawn_error`
field (`type: ["string", "null"]`) that no document told a lane to fill in.
A lane whose `Agent`/`Task` tool is refused at runtime (observed 2026-09-09,
a `claude-supertool` tick) has, since #1333, a correct place to land that
fact in the schema (`review.mechanism` plus the `not-checked` state), but
nothing ever told it `spawn_error` exists or what belongs there -- so the
one field shaped to carry the verbatim refusal text sat unused, and the
diagnostic detail that would settle #1383's own open question (harness gate,
manifest issue, something else) was lost even when a lane correctly reported
`not-checked`.

This is the narrowest testable claim available for a doc-only fix: the
developer brief (spine + phases, via `scripts/developer_docs.py`, the same
set every other content check over this brief reads) must actually name
`spawn_error` and tell a lane what to put there.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import developer_docs  # noqa: E402


def _flat(text):
    return " ".join(text.lower().split())


def test_developer_brief_documents_spawn_error():
    flat = _flat(developer_docs.text())
    assert "spawn_error" in flat, (
        "the developer brief never names review.spawn_error -- the schema "
        "field exists but nothing tells a lane to use it (#1383)"
    )


def test_developer_brief_tells_lane_what_to_put_in_spawn_error():
    flat = _flat(developer_docs.text())
    # Not just naming the field -- telling the lane to record the verbatim
    # refusal/error text there when a spawn tool is unreachable, the same
    # "quote it verbatim" instruction dispatch.md already gives for
    # agent-unreachable (#978's own precedent).
    assert "spawn_error" in flat
    idx = flat.index("spawn_error")
    window = flat[max(0, idx - 400) : idx + 400]
    assert "verbatim" in window or "quote" in window, (
        "spawn_error is named but the brief does not say to record the "
        "actual refusal text there (#1383)"
    )
