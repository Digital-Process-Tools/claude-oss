"""#372: `receipt()` printed values from `.oss.json` raw, so a newline in one forges
receipt lines that a reader cannot tell from the tool's own -- in output the manager
skill and `commands/tick.md` both instruct maintainers to paste verbatim into a
developer brief.

The file's own `_one_line` ("A newline in either forges a receipt line") was applied to
`detail` and to the board lines and skipped everywhere else. The issue names the branch,
worktree-path and sha rows. **Four** fields were measured forging, not three, and the
fourth is the one that decided the shape of the fix:

  branch_pattern      a tracked .oss.json value, the filed case          +2 lines
  worktree_root       an .oss.local.json value                           +2 lines
  repo                the --repo argv, rendered by _row                  +2 lines
  a config *problem*  built by oss_config from a hostile JSON **key**    +2 lines

The last one needs no hostile *value* at all, and `oss_config` cannot close it at its
end: the sentence's whole job is to name the key that is wrong. So the guard belongs at
the point of emission rather than on a list of fields -- a per-field fix closes the three
the auditor reached and leaves the one it did not, and the next field added to the
receipt starts unguarded again.

The assertion is the rendered **line count** against a clean control, per the issue: a
regex that matched would pass against a version that folded the value and then printed
it somewhere else. Every "must not forge" case is paired with a "must still render" one
in the same fixture, because a receipt that rendered nothing at all would have a very
stable line count.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402

# Shaped exactly like the rows `receipt()` prints, so a forged line is
# indistinguishable from a real one by eye. That is the point of the defect.
FORGE = "\nboard     :\n  idle  attacker-branch  /tmp/x"

CONFIG = {
    "repo": "example/example",
    "default_branch": "main",
    "branch_pattern": "fix/{issue}",
    "test_command": "pytest",
    "version_sites": [],
    "changelog_dir": None,
    "docs_targets": [],
    "labels": {"priority": [], "lanes": []},
}

ROW_LABELS = (
    "LANE SETUP #",
    "repo      :",
    "base      :",
    "branch    :",
    "worktree  :",
    "board     :",
)


@pytest.fixture
def stubbed(monkeypatch):
    """No git, no supertool. Neither is what is under test here, and both would make
    the line count depend on the machine the suite runs on.
    """
    monkeypatch.setattr(lane_setup, "_git", lambda repo, *args: (1, "", "nothing ran"))
    monkeypatch.setattr(
        lane_setup,
        "read_board",
        lambda repo: {"state": "could-not-run", "lines": [], "detail": "stubbed"},
    )


def _write(tmp_path, name, **overrides):
    root = tmp_path / name
    root.mkdir()
    config = dict(CONFIG)
    config.update(overrides)
    (root / ".oss.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _lines(repo, issue=317):
    return lane_setup.receipt(lane_setup.compute(repo, issue)).splitlines()


def _payload(tmp_path):
    return lane_setup.compute(_write(tmp_path, "payload"), 317)


# ------------------------------------------------------- the control, stated first


def test_a_clean_receipt_renders_every_row(tmp_path, stubbed):
    """The must-fire half. Every silence assertion below counts lines, and a renderer
    that had stopped emitting rows would satisfy all of them at once.
    """
    text = lane_setup.receipt(lane_setup.compute(_write(tmp_path, "clean"), 317))
    for label in ROW_LABELS:
        assert label in text, (label, text)
    assert "branch    : fix/317" in text, text


# --------------------------------------------------- the filed case: branch_pattern


def test_a_newline_in_branch_pattern_forges_no_line(tmp_path, stubbed):
    """`oss_config.branch_pattern_problem` (#460) now refuses a `branch_pattern`
    carrying a line break outright, so this fixture stopped being silently accepted
    and started producing one legitimate `config warn:` line -- the same shape as
    the hostile-key case below ("one extra line is legitimate and expected -- the
    problem itself. Two would mean the value forged one."). The forging question is
    unchanged: does that one warning line, or anything else, expand into more than
    one line. It must not.
    """
    clean = _lines(_write(tmp_path, "clean"))
    forged = _lines(_write(tmp_path, "forged", branch_pattern="fix/{issue}" + FORGE))
    assert len(forged) == len(clean) + 1, (
        "expected exactly one extra line (the branch_pattern problem sentence); "
        "got {}: {}".format(len(forged) - len(clean), forged)
    )
    warn = [
        ln for ln in forged if ln.startswith("config warn:") and "branch_pattern" in ln
    ]
    assert len(warn) == 1, forged
    # The branch row still renders -- `compute()` reports the problem and continues,
    # it does not stop deriving the branch -- and it is still exactly one line.
    branch_row = [ln for ln in forged if ln.startswith("branch    :")]
    assert len(branch_row) == 1, forged
    assert "attacker-branch" in branch_row[0], branch_row


def test_a_carriage_return_in_branch_pattern_forges_no_line(tmp_path, stubbed):
    """A bare CR is a line terminator to `str.splitlines()` and repaints the current
    line on a terminal, and it is the one a fold written against newlines alone misses.
    `_one_line` splits on whitespace, so it catches both -- pinned rather than assumed.

    Same one-legitimate-line adjustment as the test above, for the same reason:
    `branch_pattern_problem` now refuses this value too.
    """
    clean = _lines(_write(tmp_path, "clean"))
    cr = "fix/{issue}\rboard     :\r  idle  attacker  /tmp/x"
    forged = _lines(_write(tmp_path, "cr", branch_pattern=cr))
    assert len(forged) == len(clean) + 1, forged


# ------------------------- the site the audit did not reach: a hostile config *key*


def test_a_newline_in_a_config_key_forges_no_line(tmp_path, stubbed):
    """`oss_config` reports an unknown key by naming it, so a hostile JSON key reaches
    the receipt through a *problem sentence* rather than through any value. Nothing in
    `oss_config` can close this at its end without refusing to say which key is wrong.

    One extra line is legitimate and expected -- the problem itself. Two would mean the
    key forged one.
    """
    clean = _lines(_write(tmp_path, "clean"))
    hostile = _lines(_write(tmp_path, "key", **{"zz" + FORGE: 1}))
    assert len(hostile) == len(clean) + 1, (
        "expected exactly one extra line (the problem sentence); got {}: {}".format(
            len(hostile) - len(clean), hostile
        )
    )


def test_an_unknown_key_is_still_reported(tmp_path, stubbed):
    """Control for the case above: the guard must fold the sentence, not suppress it."""
    hostile = _lines(_write(tmp_path, "key2", **{"zz" + FORGE: 1}))
    warn = [ln for ln in hostile if ln.startswith("config warn:") and "zz" in ln]
    assert len(warn) == 1, hostile
    assert "unknown key" in warn[0], warn


# ------------------------------------------------ the other three rows, on the payload


def test_a_forged_repo_row_renders_as_one_line(tmp_path, stubbed):
    """`receipt()` is a pure function of its payload, so rows whose values arrive from
    somewhere the fixture cannot portably forge are asserted against it directly.
    `repo` comes from `--repo`; a directory name may legitimately contain a newline on
    POSIX and cannot on Windows, so building one on disk would skip half the CI matrix
    for a property that is not platform-dependent.
    """
    payload = _payload(tmp_path)
    clean = len(lane_setup.receipt(payload).splitlines())
    payload["repo"] = payload["repo"] + FORGE
    assert len(lane_setup.receipt(payload).splitlines()) == clean, lane_setup.receipt(
        payload
    )


def test_a_forged_worktree_path_renders_as_one_line(tmp_path, stubbed):
    payload = _payload(tmp_path)
    clean = len(lane_setup.receipt(payload).splitlines())
    payload["worktree"] = {
        "state": "resolved",
        "root": "/tmp/wt",
        "path": "/tmp/wt/317" + FORGE,
        "detail": "",
        "exists": False,
    }
    assert len(lane_setup.receipt(payload).splitlines()) == clean, lane_setup.receipt(
        payload
    )


def test_a_forged_sha_row_renders_as_one_line(tmp_path, stubbed):
    payload = _payload(tmp_path)
    clean = len(lane_setup.receipt(payload).splitlines())
    payload["base"] = {
        "state": "resolved",
        "remote": "origin",
        "ref": "origin/main",
        "sha": "0" * 40 + FORGE,
        "detail": "",
    }
    assert len(lane_setup.receipt(payload).splitlines()) == clean, lane_setup.receipt(
        payload
    )


def test_the_payload_route_still_renders_those_rows(tmp_path, stubbed):
    """Control for the three cases above: the same mutations with clean values must
    still produce a receipt carrying each row, so a renderer that dropped them could
    not satisfy the counts by omission.
    """
    payload = _payload(tmp_path)
    payload["worktree"] = {
        "state": "resolved",
        "root": "/tmp/wt",
        "path": "/tmp/wt/317",
        "detail": "",
        "exists": False,
    }
    payload["base"] = {
        "state": "resolved",
        "remote": "origin",
        "ref": "origin/main",
        "sha": "0" * 40,
        "detail": "",
    }
    text = lane_setup.receipt(payload)
    assert "/tmp/wt/317 [free]" in text, text
    assert "0" * 40 in text, text


# ------------------------------------------------------------- truncation is spoken


def test_a_line_cut_by_the_fold_says_so(tmp_path, stubbed):
    """A truncated line that renders as a complete one is this repository's own defect
    class pointed at its own receipt, so the fold marks what it cut. Deliberately not a
    change to `_one_line`, whose existing callers pin their own limits and whose silent
    truncation is theirs to keep.
    """
    payload = _payload(tmp_path)
    payload["repo"] = "r" * 9000
    row = [
        ln
        for ln in lane_setup.receipt(payload).splitlines()
        if ln.startswith("repo      :")
    ]
    assert len(row) == 1, row
    assert row[0].endswith("[truncated]"), row[0][-40:]


def test_an_ordinary_line_is_not_marked_truncated(tmp_path, stubbed):
    """Control: the marker must fire on a cut and never on a line that fitted."""
    text = lane_setup.receipt(_payload(tmp_path))
    assert "[truncated]" not in text, text
