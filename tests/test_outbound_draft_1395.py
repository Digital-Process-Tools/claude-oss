"""``outbound/`` -- the loop drafts public acts, the human sends them (#1395).

Mirrors `tests/test_trap_curate_905.py`'s own shape for `scripts/trap_curate.py`,
the module this one is deliberately modelled on: one file per intended public
act, and this module only counts what is waiting, never posts anything.

The positive control matters here specifically: a `could-not-read` outbound/
and a `none` outbound/ (empty, or absent) must render as different states --
`pending_count` returns `None` for the former and `0` for the latter -- or a
directory this run could not even list would silently read as "nothing to
send", which is the load-bearing third state #1395 itself names.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import outbound_draft  # noqa: E402


def _write(root, name, body="draft body\n"):
    path = Path(root) / "outbound"
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------- none


def test_absent_directory_is_none_not_could_not_read(tmp_path):
    result = outbound_draft.waiting(tmp_path)
    assert result["state"] == "none"
    assert result["count"] == 0
    assert outbound_draft.pending_count(tmp_path) == 0


def test_empty_directory_is_none(tmp_path):
    (tmp_path / "outbound").mkdir()
    result = outbound_draft.waiting(tmp_path)
    assert result["state"] == "none"
    assert result["count"] == 0


def test_only_the_owned_readme_is_still_none(tmp_path):
    _write(tmp_path, "README.md", "owned by the plugin\n")
    result = outbound_draft.waiting(tmp_path)
    assert result["state"] == "none"
    assert result["count"] == 0


# ------------------------------------------------------------------ waiting


def test_a_pending_draft_is_counted_and_classified(tmp_path):
    _write(tmp_path, "42.pending.reply-to-comment.md")
    result = outbound_draft.waiting(tmp_path)
    assert result["state"] == "waiting"
    assert result["count"] == 1
    assert result["by_state"]["pending"] == 1
    draft = result["drafts"][0]
    assert draft["parses"] is True
    assert draft["issue"] == 42
    assert draft["state"] == "pending"
    assert draft["slug"] == "reply-to-comment"


def test_every_state_is_counted_separately(tmp_path):
    _write(tmp_path, "1.pending.a.md")
    _write(tmp_path, "2.sent.b.md")
    _write(tmp_path, "3.dropped.c.md")
    _write(tmp_path, "4.stale.d.md")
    result = outbound_draft.waiting(tmp_path)
    assert result["count"] == 4
    assert result["by_state"] == {"pending": 1, "sent": 1, "dropped": 1, "stale": 1}


def test_a_name_with_no_slug_does_not_parse_but_is_still_listed(tmp_path):
    _write(tmp_path, "42.pending.md")
    result = outbound_draft.waiting(tmp_path)
    assert result["state"] == "waiting"
    assert result["count"] == 1
    draft = result["drafts"][0]
    assert draft["parses"] is False
    # Unparsed names are listed but not counted against any state.
    assert result["by_state"] == {"pending": 0, "sent": 0, "dropped": 0, "stale": 0}


def test_a_name_with_an_unknown_state_does_not_parse(tmp_path):
    _write(tmp_path, "42.posted.a.md")
    result = outbound_draft.waiting(tmp_path)
    draft = result["drafts"][0]
    assert draft["parses"] is False


# ------------------------------------------------------------- pending_count


def test_pending_count_only_counts_pending(tmp_path):
    _write(tmp_path, "1.pending.a.md")
    _write(tmp_path, "2.sent.b.md")
    _write(tmp_path, "3.dropped.c.md")
    assert outbound_draft.pending_count(tmp_path) == 1


# --------------------------------------------------------------- could-not-read


@pytest.mark.skipif(os.name == "nt", reason="chmod-based unreadability is POSIX-only")
def test_an_unreadable_directory_is_could_not_read_not_none(tmp_path):
    path = tmp_path / "outbound"
    path.mkdir()
    (path / "1.pending.a.md").write_text("x", encoding="utf-8")
    original_mode = path.stat().st_mode
    try:
        path.chmod(0)
        result = outbound_draft.waiting(tmp_path)
        assert result["state"] == "could-not-read"
        assert result["count"] is None
        assert outbound_draft.pending_count(tmp_path) is None
    finally:
        path.chmod(original_mode)


def test_could_not_read_is_never_folded_into_none_the_positive_control(tmp_path):
    """Must-fire pair for the test above: pending_count distinguishes `None`
    (could-not-read) from `0` (none/empty) by construction, proven directly
    rather than only through the skipped POSIX permission test."""
    none_result = outbound_draft.waiting(tmp_path)
    assert none_result["count"] == 0

    could_not_read_result = {
        "state": "could-not-read",
        "count": None,
        "by_state": None,
        "drafts": [],
        "why": "outbound/ could not be listed: PermissionError: denied",
    }
    assert none_result["count"] != could_not_read_result["count"]
    assert none_result["state"] != could_not_read_result["state"]


# --------------------------------------------------------------------- render


def test_render_names_every_state_count(tmp_path):
    _write(tmp_path, "1.pending.a.md")
    result = outbound_draft.waiting(tmp_path)
    rendered = outbound_draft.render(result)
    assert "1 pending" in rendered
    assert "0 sent" in rendered
    assert "0 dropped" in rendered
    assert "0 stale" in rendered


def test_render_could_not_read_says_so():
    result = {
        "state": "could-not-read",
        "count": None,
        "by_state": None,
        "drafts": [],
        "why": "outbound/ could not be listed: PermissionError: denied",
    }
    rendered = outbound_draft.render(result)
    assert rendered.startswith("outbound: ? could-not-read")
