"""Where the external-issue count comes from and how it is cached (#595).

The number that changes what a maintainer does next -- an issue filed by someone
outside the repository -- is read off GitHub's own `authorAssociation` rather than
`-author:@me`: the latter is a fact about whoever is authenticated on this machine, and
this repository's own governing rule is that a fact about one machine does not stand in
for a fact about the repository (CLAUDE.md).

`_board_field` used to render this count a second time, as `/ Neis`, beside the
identical number `_inbound_field`'s `is` group already carries (#1406) -- #1463 removed
that duplicate render, so this file now covers only the reading and the cache, not the
`_board_field` output. The three-way `?`/`0`/measured distinction this issue's own
"must-fire control" reasoning established still matters; it is exercised on the
surviving renderer in `tests/test_statusline_inbound_1406.py` and on the raw reading
below (`_gh_external_issue_count`), not here.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _symbols(ascii_only=True):
    return statusline._symbols(ascii_only)


# ------------------------------------------------------------------------- the cache
#
# `_board_field`'s own rendering of this field (the `?`/`0`/measured
# distinction #595 established) moved to `tests/test_statusline_eis_dedup_
# 1463.py` and `tests/test_statusline_inbound_1406.py` -- #1463 removed the
# render from `_board_field` itself, so there is nothing left of it to
# assert here. This file keeps covering the cache round trip and the raw
# `_gh_external_issue_count` reading below.


def test_a_cache_with_issues_but_no_external_count_leaves_it_none():
    """No `state` field to distinguish this any more (#597) -- `issues_external`
    being `None` while `prs`/`issues` are ints is the whole answer."""
    board = statusline.board_from_cache({"prs": 2, "issues": 14, "fetched_at": 0})
    assert board["issues"] == 14
    assert board["issues_external"] is None


def test_a_cache_with_both_counts_is_fully_read():
    board = statusline.board_from_cache(
        {"prs": 2, "issues": 14, "issues_external": 2, "fetched_at": 0}
    )
    assert board["issues_external"] == 2


def test_a_cache_with_a_genuine_zero_external_count_is_not_none():
    """The must-fire control for the test above: zero is a real reading."""
    board = statusline.board_from_cache(
        {"prs": 2, "issues": 14, "issues_external": 0, "fetched_at": 0}
    )
    assert board["issues_external"] == 0
    assert board["issues_external"] is not None


# ---------------------------------------------------------------- _gh_external_issue_count


def test_membership_rows_are_not_counted_as_external(monkeypatch):
    """`_run` is mocked to return the shape the fixed call actually produces: one
    `author_association` value per line, raw text -- `gh api --jq` output, not a
    JSON array (#620). PR rows never reach here at all: the jq `select` that keeps
    them out runs server-side, before this function ever sees output."""
    lines = "OWNER\nMEMBER\nCOLLABORATOR\nNONE\nCONTRIBUTOR"
    monkeypatch.setattr(statusline, "_run", lambda command, timeout=25: lines)
    assert statusline._gh_external_issue_count("owner/repo", 5) == 2


def test_a_null_association_makes_the_whole_count_unreliable(monkeypatch):
    """None is not a floor -- one unreadable row and the whole count is untaken, per
    the module's own convention that a partial read is not a measurement. `null` is
    the literal jq prints for a missing/`None` field in raw mode."""
    lines = "OWNER\nnull"
    monkeypatch.setattr(statusline, "_run", lambda command, timeout=25: lines)
    assert statusline._gh_external_issue_count("owner/repo", 2) is None


def test_fewer_rows_than_the_known_total_is_unreliable_not_undercounted():
    """The paging hazard this guards against: a listing call that came back short of the
    total `_gh_count` already measured must not silently report a smaller number."""

    def _short(command, timeout=25):
        return "NONE"

    import statusline as sl

    orig = sl._run
    sl._run = _short
    try:
        assert sl._gh_external_issue_count("owner/repo", 5) is None
    finally:
        sl._run = orig


def test_no_total_to_check_against_is_unreliable():
    assert statusline._gh_external_issue_count("owner/repo", None) is None


def test_gh_failing_outright_is_unreliable():
    import statusline as sl

    orig = sl._run
    sl._run = lambda command, timeout=25: None
    try:
        assert sl._gh_external_issue_count("owner/repo", 3) is None
    finally:
        sl._run = orig


def test_zero_open_issues_is_a_genuine_zero_not_unreliable():
    """The must-fire control beside the failure tests above: an empty result and a
    total of zero agree, and that agreement is a real measurement, not a call that
    could not run. `_run` returns `""` (its own success-with-no-output convention),
    never `None`, for a repo with no open issues."""
    import statusline as sl

    orig = sl._run
    sl._run = lambda command, timeout=25: ""
    try:
        assert sl._gh_external_issue_count("owner/repo", 0) == 0
    finally:
        sl._run = orig


def test_the_argument_vector_never_asks_for_the_field_gh_issue_list_does_not_have(
    monkeypatch,
):
    """#620's whole finding: `gh issue list --json authorAssociation` requests a field
    that command has never had -- `Unknown JSON field: "authorAssociation"`, exit 1,
    every invocation. Every fixture above monkeypatches `_run`'s return value and none
    of the six directions in the original #595 suite ever looked at what `_run` was
    *called with*, so the one broken part of this function had no fixture describing
    it. Assert on the command directly: this is the test that would have failed the
    day #595 landed, and it is the one this suite was missing."""
    captured = {}

    def _capture(command, timeout=25):
        captured["command"] = command
        return "OWNER"

    monkeypatch.setattr(statusline, "_run", _capture)
    statusline._gh_external_issue_count("owner/repo", 1)
    command = captured["command"]
    assert "authorAssociation" not in command, command
    assert command[0] == "gh" and "api" in command
    assert any("owner/repo/issues" in str(part) for part in command), command
    assert any("author_association" in str(part) for part in command), command
    assert any("pull_request" in str(part) for part in command), command
