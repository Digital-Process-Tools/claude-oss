"""#1000: claim_one() and release_one() call run(...) without resolving
run=None first, unlike every other entry point in issue_claim.py (viewer_login,
read_assignees, check all do `run = _run if run is None else run`). Reached
only on the branch that performs the write -- claim_one when the issue is
free, release_one when it is ours -- so a direct importer calling either with
run=None (the documented default) raises TypeError: 'NoneType' object is not
callable instead of one of the module's own states.

check() and the CLI are both safe already (they resolve run first), so this
is exercised by calling claim_one/release_one directly, bypassing check().
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import select_issues_claim_read as issue_claim  # noqa: E402


def _payload(*logins):
    return json.dumps({"assignees": [{"login": name} for name in logins]})


def _fake(view=None, edit_ok=True):
    view = view or {}
    calls = []

    def run(args, timeout=None):
        calls.append(args)
        if args[:3] == ["gh", "issue", "view"]:
            number = int(args[3])
            answer = view.get(number)
            if isinstance(answer, tuple):
                return False, "", answer[1]
            return True, answer, None
        if args[:3] == ["gh", "issue", "edit"]:
            if not edit_ok:
                return False, "", "boom"
            return True, "", None
        raise AssertionError("unexpected call: {!r}".format(args))

    run.calls = calls
    return run


def test_claim_one_resolves_run_none_instead_of_raising(monkeypatch):
    """Must-fire: the module's own `_run` default resolves, not a TypeError."""

    def fake_run(args, timeout=None):
        if args[:3] == ["gh", "issue", "view"]:
            return True, _payload(), None
        if args[:3] == ["gh", "issue", "edit"]:
            return True, "", None
        raise AssertionError("unexpected call: {!r}".format(args))

    monkeypatch.setattr(issue_claim, "_run", fake_run)
    row = issue_claim.claim_one(1, "maintainer", run=None)
    assert row["state"] == "claimed"


def test_release_one_resolves_run_none_instead_of_raising(monkeypatch):
    """Must-fire: same defect, the release side."""

    def fake_run(args, timeout=None):
        if args[:3] == ["gh", "issue", "view"]:
            return True, _payload("maintainer"), None
        if args[:3] == ["gh", "issue", "edit"]:
            return True, "", None
        raise AssertionError("unexpected call: {!r}".format(args))

    monkeypatch.setattr(issue_claim, "_run", fake_run)
    row = issue_claim.release_one(1, "maintainer", run=None)
    assert row["state"] == "released"


def test_claim_one_still_resolves_an_explicit_run():
    """Must-not-regress: passing a real/fake `run` explicitly still works."""
    run = _fake(view={1: _payload()})
    row = issue_claim.claim_one(1, "maintainer", run=run)
    assert row["state"] == "claimed"
    assert run.calls[-1] == ["gh", "issue", "edit", "1", "--add-assignee", "@me"]


def test_release_one_still_resolves_an_explicit_run():
    """Must-not-regress: passing a real/fake `run` explicitly still works."""
    run = _fake(view={1: _payload("maintainer")})
    row = issue_claim.release_one(1, "maintainer", run=run)
    assert row["state"] == "released"
    assert run.calls[-1] == ["gh", "issue", "edit", "1", "--remove-assignee", "@me"]
