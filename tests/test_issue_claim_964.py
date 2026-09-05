"""#964: the claim rule's three states, computed rather than remembered.

`scripts/issue_claim.py` replaces a `gh issue edit` incantation written out in
three documents. The assertions below are almost all about the one state the
prose could state and not enforce: `could-not-read`, which must never render as
`unassigned` and must never become a reason to claim.

Every `gh` call is injected. The real binary is never invoked -- a suite that
shelled out to `gh` would either need a network and credentials or would pass
by failing every call, which is the same green as passing by not looking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import issue_claim  # noqa: E402

VIEWER = ["gh", "api", "user", "--jq", ".login"]


def _fake(
    view=None, edit_ok=True, login="maintainer", login_ok=True, edit_detail="boom"
):
    """A `run` stand-in. `view` maps issue number -> the JSON `gh issue view`
    would print, or an exception-ish `(False, detail)` pair for a failed read.

    Records every call so a test can assert what was *not* attempted -- the
    point of several checks below is that no write was issued at all.
    """
    calls = []

    def run(args, timeout=None):
        calls.append(args)
        if args == VIEWER:
            if not login_ok:
                return False, "", "gh: not authenticated"
            return True, login + "\n", None
        if args[:3] == ["gh", "issue", "view"]:
            number = int(args[3])
            answer = view.get(number)
            if isinstance(answer, tuple):
                return False, "", answer[1]
            return True, answer, None
        if args[:3] == ["gh", "issue", "edit"]:
            if not edit_ok:
                return False, "", edit_detail
            return True, "", None
        raise AssertionError("unexpected call: {!r}".format(args))

    run.calls = calls
    return run


def _payload(*logins):
    return json.dumps({"assignees": [{"login": name} for name in logins]})


def _states(rows):
    return [row["state"] for row in rows]


def _edits(run):
    return [c for c in run.calls if c[:3] == ["gh", "issue", "edit"]]


# ------------------------------------------------------------------ the read


def test_read_separates_unassigned_from_assigned_from_unreadable():
    run = _fake(view={1: _payload(), 2: _payload("someone"), 3: (False, "HTTP 404")})
    rows = issue_claim.check([1, 2, 3], "read", run=run)
    assert _states(rows) == ["unassigned", "assigned", "could-not-read"]
    assert rows[2]["detail"] == "HTTP 404"


def test_a_missing_assignees_key_is_could_not_read_not_unassigned():
    """The fold this module exists to refuse. `gh` shapes this field itself, so
    its absence means the read did not answer the question."""
    run = _fake(view={1: json.dumps({"number": 1})})
    rows = issue_claim.check([1], "read", run=run)
    assert _states(rows) == ["could-not-read"]


def test_unparseable_json_is_could_not_read():
    run = _fake(view={1: "not json at all"})
    assert _states(issue_claim.check([1], "read", run=run)) == ["could-not-read"]


def test_an_unrecognised_assignee_entry_is_could_not_read():
    """A shape this does not understand is not an empty field. Guessing here
    would claim an issue on the strength of a payload nobody parsed."""
    run = _fake(view={1: json.dumps({"assignees": [{"name": "no login key"}]})})
    assert _states(issue_claim.check([1], "read", run=run)) == ["could-not-read"]


# ----------------------------------------------------------------- the claim


def test_claim_writes_only_for_an_unassigned_issue():
    run = _fake(view={1: _payload(), 2: _payload("other"), 3: _payload("maintainer")})
    rows = issue_claim.check([1, 2, 3], "claim", run=run)
    assert _states(rows) == ["claimed", "already-claimed", "already-mine"]
    # The must-not-fire half: exactly one write, and it is for the free issue.
    assert _edits(run) == [["gh", "issue", "edit", "1", "--add-assignee", "@me"]]


def test_an_unreadable_issue_is_never_claimed():
    """The whole point. A caller that reads `could-not-read` as `unassigned`
    claims an issue somebody else may be holding."""
    run = _fake(view={1: (False, "gh: connection reset")})
    rows = issue_claim.check([1], "claim", run=run)
    assert _states(rows) == ["could-not-read"]
    assert _edits(run) == []


def test_a_failed_write_is_could_not_claim_and_not_claimed():
    run = _fake(view={1: _payload()}, edit_ok=False, edit_detail="HTTP 403")
    rows = issue_claim.check([1], "claim", run=run)
    assert _states(rows) == ["could-not-claim"]
    assert rows[0]["detail"] == "HTTP 403"


def test_an_unresolvable_viewer_never_claims_over_an_assigned_issue():
    """When we cannot tell whether an assignee is us, it is somebody else.
    An issue assigned to `maintainer` reads `already-claimed`, not
    `already-mine`, and no write is attempted."""
    run = _fake(view={1: _payload("maintainer")}, login_ok=False)
    rows = issue_claim.check([1], "claim", run=run)
    assert _states(rows) == ["already-claimed"]
    assert rows[0]["viewer"] is None
    assert rows[0]["viewer_detail"] == "gh: not authenticated"
    assert _edits(run) == []


def test_an_unresolvable_viewer_still_claims_a_genuinely_free_issue():
    """Positive control for the rule above: it withholds the claim only where
    somebody might be holding the issue. An empty field is empty whoever we
    are, and refusing there would stall the loop on an unrelated failure."""
    run = _fake(view={1: _payload()}, login_ok=False)
    rows = issue_claim.check([1], "claim", run=run)
    assert _states(rows) == ["claimed"]
    assert _edits(run) == [["gh", "issue", "edit", "1", "--add-assignee", "@me"]]


def test_a_refusal_on_one_issue_does_not_stop_the_others():
    """A caller that stopped at the first refusal could not release what it had
    already taken, which is how half a bundle ends up claimed."""
    run = _fake(view={1: _payload("other"), 2: _payload(), 3: _payload()})
    rows = issue_claim.check([1, 2, 3], "claim", run=run)
    assert _states(rows) == ["already-claimed", "claimed", "claimed"]
    assert len(_edits(run)) == 2


def test_an_issue_assigned_to_us_and_somebody_else_is_not_already_mine():
    """Shared assignment is not our lane. `already-mine` would tell a caller it
    holds an issue another loop is also holding."""
    run = _fake(view={1: _payload("maintainer", "other")})
    rows = issue_claim.check([1], "claim", run=run)
    assert _states(rows) == ["already-claimed"]
    assert rows[0]["holders"] == ["other"]


# --------------------------------------------------------------- the release


def test_release_only_removes_our_own_assignment():
    run = _fake(view={1: _payload("maintainer"), 2: _payload("other"), 3: _payload()})
    rows = issue_claim.check([1, 2, 3], "release", run=run)
    assert _states(rows) == ["released", "not-mine", "not-assigned"]
    assert _edits(run) == [["gh", "issue", "edit", "1", "--remove-assignee", "@me"]]


def test_release_of_an_unreadable_issue_is_could_not_read():
    run = _fake(view={1: (False, "HTTP 500")})
    rows = issue_claim.check([1], "release", run=run)
    assert _states(rows) == ["could-not-read"]
    assert _edits(run) == []


def test_a_failed_release_write_is_could_not_release():
    run = _fake(view={1: _payload("maintainer")}, edit_ok=False)
    assert _states(issue_claim.check([1], "release", run=run)) == ["could-not-release"]


# ------------------------------------------------------------- the exit code


@pytest.mark.parametrize(
    "mode,view,expected",
    [
        ("claim", {1: _payload()}, 0),
        ("claim", {1: _payload("other")}, 1),
        ("claim", {1: (False, "boom")}, 1),
        ("release", {1: _payload("maintainer")}, 0),
        ("release", {1: _payload()}, 0),
        ("release", {1: (False, "boom")}, 1),
        ("read", {1: _payload()}, 0),
        ("read", {1: (False, "boom")}, 1),
    ],
)
def test_exit_code_is_zero_only_when_every_row_reached_its_success_state(
    monkeypatch, mode, view, expected
):
    """The rows are the answer, but the code must not say `fine` when one of
    them is a `could-not-*`: a shell caller that ignores the rows still cannot
    proceed as though the claim succeeded."""
    run = _fake(view=view)
    monkeypatch.setattr(issue_claim, "_run", run)
    code = issue_claim.main(["1", "--" + mode])
    assert code == expected


def test_a_non_numeric_issue_argument_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        issue_claim.main(["not-a-number", "--read"])
    assert excinfo.value.code == 2


def test_a_hash_prefixed_issue_number_is_accepted(monkeypatch, capsys):
    """`#964` is how every document in this repository writes an issue number,
    so the one spelling a reader will copy has to work."""
    run = _fake(view={964: _payload()})
    monkeypatch.setattr(issue_claim, "_run", run)
    assert issue_claim.main(["#964", "--read"]) == 0
    assert "#964  unassigned" in capsys.readouterr().out


# ------------------------------------------- the runner's own failure arms


def test_a_missing_gh_binary_is_could_not_read_with_a_reason_naming_it():
    """Three reasons a call fails -- absent binary, timeout, non-zero exit --
    and each keeps its own sentence. A caller told only `it failed` cannot tell
    an unauthenticated session from an absent tool."""
    detail = issue_claim._run(["definitely-not-a-real-binary-964"])[2]
    assert "not on PATH" in detail
