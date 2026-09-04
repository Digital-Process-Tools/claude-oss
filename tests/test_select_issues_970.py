"""#970 -- selection is five scripts and a session doing the joins.

`select_issues.py` composes `dispatch_rank.rank`/`order`, `preflight_check.
search`, `lane_setup.resolve_lane`/`lane_overlap` and `issue_claim.check`
into one call: board in, ranked claimable candidates out, each row carrying
why it survived or did not.

**The three states, and the one that must never render as another.** A tick
that finds no candidate (`none-available`, a real established absence) and a
tick that could not read one of its inputs (`could-not-select`) end
differently now -- `could-not-select` must never render as `none-available`,
which is the whole reason #970 was filed. Every test pairing those two is a
positive/negative control in the same fixture, per this repo's own rule that
a "must not fire" case needs a "must fire" case beside it.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {"filed_by_loop": "filed-by-loop", "priority": ["priority-high", "priority-medium", "priority-low"]}


def _issue(number, labels=None, **extra):
    row = {"number": number, "labels": labels or []}
    row.update(extra)
    return row


def _no_op_checker(numbers, mode, run=None, repo=None):
    """A stand-in for `issue_claim.check` that reads every issue as unassigned."""
    return [{"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"} for n in numbers]


# ---------------------------------------------------------------------------
# could-not-select vs none-available -- the pairing the issue is about
# ---------------------------------------------------------------------------

def test_an_unreadable_board_is_could_not_select_never_none_available():
    result = select_issues.select({"declared": DECLARED, "board_read_ok": False,
                                    "board_read_why": "gh-issues timed out"})
    assert result["state"] == "could-not-select"
    assert "gh-issues timed out" in result["why"]


def test_a_genuinely_empty_board_is_none_available_the_positive_control():
    """The pair to the test above: a board that WAS read, and is truly empty."""
    result = select_issues.select({"declared": DECLARED, "issues": []})
    assert result["state"] == "none-available"


def test_an_unreadable_assignee_field_forces_could_not_select():
    def checker(numbers, mode, run=None, repo=None):
        return [{"issue": n, "state": "could-not-read", "detail": "gh timed out"} for n in numbers]

    payload = {"declared": DECLARED, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=checker)
    assert result["state"] == "could-not-select"
    assert "#1" in result["why"]
    # #970 review round: an unreadable assignee field must still leave a
    # dropped row behind, carrying the disposition the module's own
    # docstring promises -- not silently discarded the way the overall
    # could-not-select return used to hardcode `dropped: []`.
    assert result["dropped"] == [{
        "number": 1,
        "disposition": "assignee-unreadable",
        "why": "assignee read failed: gh timed out",
    }]


def test_an_unmatched_preflight_pattern_still_produces_candidates():
    """The positive control for the could-not-search case below: an ordinary,
    successful preflight read that finds nothing does not block selection."""
    def search(pattern, roots):
        return {"state": "not-matched", "pattern": pattern, "roots": [str(r) for r in roots]}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], preflight_pattern="def fixed_already")],
    }
    result = select_issues.select(payload, checker=_no_op_checker, search=search)
    assert result["state"] == "candidates"
    assert [c["number"] for c in result["candidates"]] == [1]


def test_a_preflight_that_could_not_search_forces_could_not_select():
    def search(pattern, roots):
        return {"state": "could-not-search", "pattern": pattern,
                "roots": [str(r) for r in roots], "problem": "root(s) missing: /nope"}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], preflight_pattern="def fixed_already")],
    }
    result = select_issues.select(payload, checker=_no_op_checker, search=search)
    assert result["state"] == "could-not-select"
    assert "#1" in result["why"]


# ---------------------------------------------------------------------------
# per-issue disposition
# ---------------------------------------------------------------------------

def test_a_stale_issue_is_dropped_with_its_pattern_named():
    def search(pattern, roots):
        return {"state": "matched", "pattern": pattern, "matches": [{"path": "x.py", "line": 1, "text": "..."}]}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], preflight_pattern="already fixed")],
    }
    result = select_issues.select(payload, checker=_no_op_checker, search=search)
    assert result["state"] == "none-available"
    assert result["dropped"] == [{"number": 1, "disposition": "stale",
                                   "why": "preflight pattern matched: already fixed"}]


def test_an_unrankable_issue_is_dropped_and_named():
    payload = {"declared": {}, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "none-available"
    assert result["dropped"][0]["number"] == 1
    assert result["dropped"][0]["disposition"] == "unrankable"


def test_an_assigned_issue_is_dropped_and_named():
    def checker(numbers, mode, run=None, repo=None):
        return [{"issue": n, "state": "assigned", "assignees": ["someone"]} for n in numbers]

    payload = {"declared": DECLARED, "issues": [_issue(1, ["priority-high"])]}
    result = select_issues.select(payload, checker=checker)
    assert result["state"] == "none-available"
    assert result["dropped"][0]["disposition"] == "assigned"


def test_a_lane_collision_is_dropped_and_named():
    def resolve(repo, patterns):
        return {"patterns": [], "files": list(patterns)}

    payload = {
        "declared": DECLARED,
        "issues": [_issue(1, ["priority-high"], lane_patterns=["scripts/held.py"])],
        "held_files": ["scripts/held.py"],
    }
    result = select_issues.select(payload, checker=_no_op_checker, resolve_lane=resolve)
    assert result["state"] == "none-available"
    assert result["dropped"][0]["disposition"] == "lane-collision"
    assert "scripts/held.py" in result["dropped"][0]["why"]


def test_eligible_candidates_are_ranked_best_first():
    payload = {
        "declared": DECLARED,
        "issues": [
            _issue(1, ["priority-low"]),
            _issue(2, ["priority-high"]),
            _issue(3, ["priority-high", "filed-by-loop"]),
        ],
    }
    result = select_issues.select(payload, checker=_no_op_checker)
    assert result["state"] == "candidates"
    numbers = [c["number"] for c in result["candidates"]]
    # human/high (2) outranks loop/high (3) outranks human/low (1) -- ROWS order.
    assert numbers == [2, 3, 1]
    for c in result["candidates"]:
        assert c["disposition"] == "eligible"


# ---------------------------------------------------------------------------
# main() / CLI: closed stdin does not crash (same class as #846)
# ---------------------------------------------------------------------------

def test_main_on_a_closed_stdin_answers_could_not_select_not_a_traceback():
    driver = (
        "import os, runpy, sys\n"
        "os.close(0)\n"
        "sys.stdin = None\n"
        "sys.argv = ['select_issues.py']\n"
        "try:\n"
        "    runpy.run_path({0!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    raise SystemExit(exc.code)\n"
    ).format(str(REPO / "scripts" / "select_issues.py"))
    proc = subprocess.run([sys.executable, "-c", driver], stdin=subprocess.DEVNULL, capture_output=True)
    err = proc.stderr.decode("utf-8", errors="replace")
    out = proc.stdout.decode("utf-8", errors="replace")
    assert "Traceback" not in err, err
    payload = json.loads(out)
    assert payload["state"] == "could-not-select"
    assert proc.returncode == 2


def test_main_on_an_ordinary_piped_board_prints_candidates():
    """The positive control for the closed-stdin test above."""
    board = {"declared": DECLARED, "issues": [{"number": 5, "labels": ["priority-high"]}]}
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "select_issues.py")],
        input=json.dumps(board).encode("utf-8"),
        capture_output=True,
    )
    out = json.loads(proc.stdout.decode("utf-8"))
    assert out["state"] == "candidates"
    assert out["candidates"][0]["number"] == 5
    assert proc.returncode == 0


def test_a_non_ascii_label_does_not_crash_the_print():
    """#970 review round: `select_issues.py` composes `dispatch_rank.rank`,
    whose `why` can carry an issue's own (possibly non-ASCII) label text --
    on a console codepage that cannot encode it, an unreconfigured stdout
    would raise `UnicodeEncodeError` after the selection was already
    computed (#794/#834's own class). Forcing `PYTHONIOENCODING` to ascii
    reproduces a narrow console without needing a real one."""
    import os

    board = {
        "declared": DECLARED,
        "issues": [{"number": 6, "labels": ["priority-hïgh"]}],
    }
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "select_issues.py")],
        input=json.dumps(board).encode("utf-8"),
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
    )
    err = proc.stderr.decode("utf-8", errors="replace")
    assert "UnicodeEncodeError" not in err, err
    assert "Traceback" not in err, err


def test_stdin_that_cannot_decode_as_utf8_is_not_read_as_bad_json():
    """The #834 split: a `UnicodeDecodeError` is a `ValueError` subclass, so
    catching only `ValueError` folds a decode failure into "not valid JSON"
    -- wrong when stdin genuinely was JSON and simply mis-encoded."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "select_issues.py")],
        input=b"\xff\xfe not valid utf-8",
        capture_output=True,
    )
    out = json.loads(proc.stdout.decode("utf-8"))
    assert out["state"] == "could-not-select"
    assert "could not be decoded as UTF-8" in out["why"]
