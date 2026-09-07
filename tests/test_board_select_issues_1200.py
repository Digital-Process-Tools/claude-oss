"""#1200 -- `select_issues.py --board` fetches its own board now, the same
way the default mode does, instead of reading a board-shaped payload on
stdin.

`docs/pick-the-work.md` already stated -- twice, unconditionally -- that
this entry point takes no stdin at all. `--board` was the one leftover that
contradicted it: `_read_stdin_json()` existed for no other caller, and a
tick that fed it nothing (or the wrong shape) got a clean `stdin: not valid
JSON` refusal rather than a rendered receipt, costing a live tick three
exit-2s (#1178). The fix is to make the code match the design rather than
document the exception (#1195's own rejected shape) -- see #1200's own body
for why.

Every "must not render as X" case here is paired with a positive control,
per this repository's own rule (CLAUDE.md, "a negative assertion needs a
positive control"): `test_board_translates_raw_github_author_association`
carries both halves in the same test function, and
`test_a_failed_fetch_reports_could_not_select_not_an_empty_receipt`'s own
positive control is `test_board_fetches_its_own_board_and_needs_no_stdin`
above it -- a genuinely successful fetch through the identical `--board`
code path, not a separate assertion buried in a fixture that never
exercises the failure branch.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "lanes": ["lane-dispatch", "lane-doctor"],
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
    "lane_other": "lane-other",
}


def _write_config(tmp_path):
    config = {
        "repo": "Digital-Process-Tools/claude-oss",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "worktree_root": str(tmp_path / "wt"),
        "labels": DECLARED,
    }
    (tmp_path / ".oss.json").write_text(json.dumps(config), encoding="utf-8")


def _issue(number, association="maintainer", **extra):
    row = {
        "number": number,
        "title": "issue #{0}".format(number),
        "body": "body of #{0}".format(number),
        "labels": ["priority-high"],
        "author_association": association,
    }
    row.update(extra)
    return row


def test_read_stdin_json_is_gone():
    """The function this fix deletes -- a regression guard against it
    quietly coming back the next time `--board` grows a new need."""
    assert not hasattr(select_issues, "_read_stdin_json")


def test_board_fetches_its_own_board_and_needs_no_stdin(tmp_path, monkeypatch, capsys):
    """The positive control: `--board` renders a real receipt from a
    fetched board, with stdin closed the whole time -- proving the mode
    needs no stdin payload at all any more."""
    _write_config(tmp_path)

    def fake_fetch_board(repo_slug, per=100, run=None):
        assert repo_slug == "Digital-Process-Tools/claude-oss"
        return {
            "state": "ok",
            "issues": [_issue(101, association="CONTRIBUTOR")],
            "capped": False,
            "cap_detail": "",
            "detail": "",
        }

    monkeypatch.setattr(select_issues, "_fetch_board", fake_fetch_board)
    monkeypatch.setattr(sys, "stdin", None)

    code = select_issues.main(["--board", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "#101" in out, out


def test_a_failed_fetch_reports_could_not_select_not_an_empty_receipt(
    tmp_path, monkeypatch, capsys
):
    """A board this call could not read must never render as a board with
    no rows -- the same rule #1145 already holds for the default mode,
    extended here to `--board`."""
    _write_config(tmp_path)

    def broken_fetch_board(repo_slug, per=100, run=None):
        return {
            "state": "could-not-fetch",
            "issues": [],
            "capped": False,
            "cap_detail": "",
            "detail": "gh: command not found",
        }

    monkeypatch.setattr(select_issues, "_fetch_board", broken_fetch_board)

    code = select_issues.main(["--board", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 2, out
    payload = json.loads(out)
    assert payload["state"] == "could-not-select", out
    assert "gh: command not found" in payload["why"], out


def test_board_translates_raw_github_author_association(tmp_path, monkeypatch, capsys):
    """`_fetch_board` hands back GitHub's own raw vocabulary
    (`CONTRIBUTOR`, `OWNER`, ...), never `rank()`'s translated
    "external"/"maintainer" axis. Untranslated, a non-loop issue renders
    `could not rank` on this receipt even though the default mode (which
    does translate) ranks the identical issue fine -- the two entry points
    must agree.

    Paired with a positive control in the same fixture, per this
    repository's own rule (CLAUDE.md, "a negative assertion needs a
    positive control"): #203 carries an association GitHub itself uses
    (`FIRST_TIME_CONTRIBUTOR`) that is genuinely outside both of
    `_translate_author_association`'s recognised sets, so it must still
    render `could not rank` -- proving this harness can actually see that
    phrase appear, not only its absence."""
    _write_config(tmp_path)

    def fake_fetch_board(repo_slug, per=100, run=None):
        return {
            "state": "ok",
            "issues": [
                _issue(202, association="CONTRIBUTOR", labels=[]),
                _issue(203, association="FIRST_TIME_CONTRIBUTOR", labels=[]),
            ],
            "capped": False,
            "cap_detail": "",
            "detail": "",
        }

    monkeypatch.setattr(select_issues, "_fetch_board", fake_fetch_board)

    code = select_issues.main(["--board", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "#202" in out, out
    assert "#203  could not rank" in out, out
    line_202 = next(line for line in out.splitlines() if "#202" in line)
    line_203 = next(line for line in out.splitlines() if "#203" in line)
    assert "could not rank" not in line_202, out
    assert "could not rank" in line_203, out
