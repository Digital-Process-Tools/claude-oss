"""#1160 -- `_attach_bodies` used to do
`issues_by_number.get(member.get("number")) or {}`, so a group member whose
number has no matching row in `issues_by_number` fell through to
`_fenced_body(None)` -- `{"body_length": 0, "body_truncated": False}`, a fence
around nothing, indistinguishable in the payload from an issue whose body
genuinely is empty (row present, `body == ""`).

Filed as latent rather than live: every current call path builds
`issues_by_number` from the SAME board fetch that produced the group's own
members, so a join miss cannot happen today. The field below is a guard
against a future change that fetches the two lists separately, not a fix for
an observed bad payload -- see the report for why building it anyway was
still judged worth doing.

Both cases share `body_length == 0` and `body_truncated == False`; only the
new `body_state` field tells them apart, and the two tests below are the
must-fire / positive-control pair proving it does.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402


# --------------------------------------------------------------- must-fire


def test_a_join_miss_is_marked_no_matching_row_not_silently_empty():
    """The bug: a member number absent from `issues_by_number` used to come
    back with a fenced empty body and no way to tell it apart from a real
    empty body. Red on main (`body_state` does not exist there at all);
    green once `_attach_bodies` sets it."""
    groups_result = {"groups": [{"members": [{"number": 99}]}]}
    issues_by_number = {}  # #99 has no matching row -- the join miss
    select_issues._attach_bodies(groups_result, issues_by_number)
    member = groups_result["groups"][0]["members"][0]
    assert member["body_state"] == "no-matching-row"
    assert member["body_length"] == 0
    assert member["body_truncated"] is False


# ------------------------------------------------------------ positive control


def test_a_genuinely_empty_real_body_is_marked_fetched():
    """The positive control: a row that IS present, whose real body just
    happens to be empty, must read differently from the join-miss case
    above even though both share `body_length == 0`."""
    groups_result = {"groups": [{"members": [{"number": 5}]}]}
    issues_by_number = {5: {"number": 5, "body": ""}}
    select_issues._attach_bodies(groups_result, issues_by_number)
    member = groups_result["groups"][0]["members"][0]
    assert member["body_state"] == "fetched"
    assert member["body_length"] == 0
    assert member["body_truncated"] is False


def test_a_normal_non_empty_fetched_body_is_also_marked_fetched():
    groups_result = {"groups": [{"members": [{"number": 6}]}]}
    issues_by_number = {6: {"number": 6, "body": "hello"}}
    select_issues._attach_bodies(groups_result, issues_by_number)
    member = groups_result["groups"][0]["members"][0]
    assert member["body_state"] == "fetched"
    assert member["body_length"] == len("hello")
