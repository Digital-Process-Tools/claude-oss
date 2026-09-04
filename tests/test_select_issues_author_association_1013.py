"""#1013 -- `select_issues.select` fed a real `gh api` payload never ranked a
single non-loop issue: `dispatch_rank.rank`'s own contract expects an
already-translated `"external"`/`"maintainer"` axis (see its module
docstring), but nothing translated GitHub's own `author_association` field
(`OWNER`/`MEMBER`/`COLLABORATOR`/`CONTRIBUTOR`/`NONE`/...) before handing it
in -- so every real board built from `gh api` marked every non-loop issue
`unrankable`, silently making #993's external/maintainer split inert outside
a test fixture that happened to pre-translate the value by hand.

Must-fire / must-not-fire pair, per this repo's own rule: a real GitHub
value from each of the two recognised sets must rank; a value neither set
recognises must still refuse to rank, exactly as it did before this fix --
translating no association silently into a guess would be the identical
defect moved one call earlier.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402

DECLARED = {
    "filed_by_loop": "filed-by-loop",
    "priority": ["priority-high", "priority-medium", "priority-low"],
}


def _no_op_checker(numbers, mode, run=None, repo=None):
    return [{"issue": n, "state": "unassigned", "assignees": [], "viewer": "bot"} for n in numbers]


def _issue(number, association, labels=None):
    return {"number": number, "labels": labels or [], "author_association": association}


def test_github_owner_association_ranks_as_maintainer():
    result = select_issues.select(
        {"declared": DECLARED, "issues": [_issue(1, "OWNER", ["priority-high"])]},
        checker=_no_op_checker,
    )
    assert result["state"] == "candidates", result
    assert result["candidates"][0]["author"] == "maintainer"


def test_github_member_and_collaborator_also_rank_as_maintainer():
    result = select_issues.select(
        {
            "declared": DECLARED,
            "issues": [
                _issue(1, "MEMBER", ["priority-high"]),
                _issue(2, "COLLABORATOR", ["priority-high"]),
            ],
        },
        checker=_no_op_checker,
    )
    assert result["state"] == "candidates", result
    authors = {c["number"]: c["author"] for c in result["candidates"]}
    assert authors == {1: "maintainer", 2: "maintainer"}


def test_github_contributor_and_none_rank_as_external():
    result = select_issues.select(
        {
            "declared": DECLARED,
            "issues": [
                _issue(1, "CONTRIBUTOR", ["priority-high"]),
                _issue(2, "NONE", ["priority-high"]),
            ],
        },
        checker=_no_op_checker,
    )
    assert result["state"] == "candidates", result
    authors = {c["number"]: c["author"] for c in result["candidates"]}
    assert authors == {1: "external", 2: "external"}


def test_an_unrecognised_github_association_still_refuses_to_rank():
    """Negative control: a value in neither GitHub set (a typo, a value this
    module does not yet know, e.g. `FIRST_TIME_CONTRIBUTOR`) must still land
    in `dropped` as `unrankable`, never guessed into `external` or
    `maintainer`."""
    result = select_issues.select(
        {"declared": DECLARED, "issues": [_issue(1, "FIRST_TIME_CONTRIBUTOR", ["priority-high"])]},
        checker=_no_op_checker,
    )
    assert result["state"] == "none-available", result
    assert result["dropped"][0]["disposition"] == "unrankable"


def test_a_missing_association_still_refuses_to_rank_the_positive_control():
    """Pair to the test above with a different dark input: no field at all."""
    result = select_issues.select(
        {"declared": DECLARED, "issues": [{"number": 1, "labels": ["priority-high"]}]},
        checker=_no_op_checker,
    )
    assert result["state"] == "none-available", result
    assert result["dropped"][0]["disposition"] == "unrankable"
