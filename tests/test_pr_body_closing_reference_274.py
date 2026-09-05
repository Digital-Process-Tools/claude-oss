"""A pull request body that closes nothing, in a report that validates clean (#274).

Measured across two sessions: seven agent-written `pr_body` payloads, **four** whose
body bound no closing keyword to the issue the pull request was written for. All four
validated clean here, because `report_schema.validate_pr_body` opens the payload,
checks `title`, `body`, `head` and `base`, and never reads the body's references. Each
was caught at the maintainer's `gh-pr-create` call -- which **reports and does not
refuse**, exit 0 -- and repaired by hand afterwards. On the fourth (#331) the
counterfactual was measured rather than argued: the manual `gh-pr-edit` was separable
from the merge, and without it the merge would have closed nothing while the board read
clean.

Two failure shapes, both observed:

- **an outright omission** -- `(#321)` in prose and no keyword anywhere (PR #331);
- **a keyword rendered inert** -- ``Closes #275, closes #296`` inside a code span, in
  the opening paragraph, which renders as a closing reference that plainly did and
  creates none (PR #332).

The second shape is why this file does not test a mention. A checker asking only
"does #N appear in the body" passes both of them: every one of the four mentioned its
issue number in prose. So the check here is a **binding** check -- a closing keyword
bound to that number, outside code spans and HTML comments.

What this is and is not, because the difference is the whole risk of adding it:

- It is an **absence detector**, conservative in one direction. It reports only that
  it could find no binding; it never claims to decide what a forge will close. Every
  transformation it makes -- stripping fences, stripping inline spans, stripping HTML
  comments, requiring the keyword adjacent to each declared number -- can only make it
  report more often, never less. So a pass is weak and a finding is strong, which is
  the right way round for a gate that runs before anything is published.
- It is **not** a reimplementation of supertool's `_checks.closing_issue_refs`. That
  reader decides which issues a forge would close; every route to it from here makes a
  forge call and two of them publish, so it is not reachable from a stdlib-only
  validator, and a second copy of a resolver is the drifting duplicate the top of
  CLAUDE.md forbids. `gh-pr-create` stays the authority. On the two traps that make a
  substring grep wrong, though, this checker is not merely conservative but correct:
  `Closes #A #B` closes only `#A` and this refuses `#B`; a backticked keyword closes
  nothing and this refuses it.

Three states, and only the third is a defect: the payload closes something, it
deliberately closes nothing (a `Part of #N` pull request is a real decision and
refusing it would be a gate inventing a rule), or nobody said. `closes-nothing` is
sayable the way `gh-pr-edit`'s `unlink` token is sayable, and it carries a reason,
because a deliberate re-scope and a forgotten keyword are one missing line apart.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import report_schema  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "schemas" / "agent-report.schema.json"


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _example():
    return json.loads(json.dumps(_schema()["examples"][0]))


def _written(closes=None, path="body.pr.json"):
    """A report whose pr_body is `written`, with whatever `closes` is under test."""
    report = _example()
    report["pr_body"] = {"state": "written", "path": path}
    if closes is not None:
        report["pr_body"]["closes"] = closes
    return report


def _on_disk(tmp_path, closes, body, head="fix/123"):
    """A report plus a payload the forge would accept, differing only in the body."""
    target = tmp_path / "body.pr.json"
    target.write_text(
        json.dumps({"title": "A title", "body": body, "head": head, "base": "main"}),
        encoding="utf-8",
    )
    report = _example()
    report["pr_body"] = {"state": "written", "path": str(target), "closes": closes}
    return report


def _errors(tmp_path, closes, body, head="fix/123"):
    report = _on_disk(tmp_path, closes, body, head=head)
    shape = report_schema.validate(report)
    assert shape == [], (
        "the fixture is malformed before the body is even read: {}".format(shape)
    )
    return report_schema.validate_pr_body(report, base_dir=tmp_path)


CLOSES_274 = {"state": "closes", "issues": [274]}


# --- the shape half: nobody said is a state, and it is the only defect ----------


def test_a_written_payload_that_says_nothing_about_what_it_closes_is_refused():
    """The third state. Before this, the report said `pr_body: written` -- exactly
    true, and exactly not the question."""
    errors = report_schema.validate(_written())
    assert errors, "a payload saying nothing about what it closes validated clean"
    assert "closes" in " ".join(errors).lower(), errors


def test_saying_what_it_closes_is_accepted():
    """The positive control for the case above. A rule that refused every written
    payload would satisfy that test and fail this one."""
    assert report_schema.validate(_written(CLOSES_274)) == []


def test_deliberately_closing_nothing_is_sayable_and_carries_its_reason():
    said = _written(
        {
            "state": "closes-nothing",
            "reason": "Part of #250; the issue stays open for the second half.",
        }
    )
    assert report_schema.validate(said) == [], report_schema.validate(said)

    silent = _written({"state": "closes-nothing"})
    assert report_schema.validate(silent), (
        "closing nothing with no reason renders identically to forgetting, which is "
        "the state this field exists to make unspellable"
    )


def test_closing_something_has_to_name_the_issues():
    assert report_schema.validate(_written({"state": "closes"})), "no issues at all"
    assert report_schema.validate(_written({"state": "closes", "issues": []})), "empty"
    assert report_schema.validate(_written(CLOSES_274)) == []


def test_a_report_that_wrote_no_payload_owes_nothing_here():
    """`not-written` is a legitimate state and this must not turn it into a defect."""
    report = _example()
    report["pr_body"] = {
        "state": "not-written",
        "path": None,
        "reason": "nothing was committed, so there is no pull request to open",
    }
    assert report_schema.validate(report) == []
    assert report_schema.validate_pr_body(report, base_dir=None) == []


# --- the on-disk half: the body, read for a binding rather than a mention -------


def test_the_omission_shape_is_refused(tmp_path):
    """PR #331, verbatim in shape: the number in prose, no keyword anywhere."""
    errors = _errors(
        tmp_path, CLOSES_274, "This reworks the thing discussed in (#274)."
    )
    assert errors, (
        "a body that closes nothing validated clean against a report saying it closes #274"
    )
    assert "274" in " ".join(errors), errors


def test_the_inert_keyword_shape_is_refused(tmp_path):
    """PR #332, verbatim in shape: the keyword inside a code span.

    This is the case a substring grep for `Closes #` passes, and the reason this
    check strips code spans before it looks.
    """
    errors = _errors(tmp_path, CLOSES_274, "`Closes #274` -- and some prose after it.")
    assert errors, "a backticked keyword closes nothing and was accepted as if it did"


def test_a_body_that_actually_binds_the_keyword_is_accepted(tmp_path):
    """The positive control for both cases above.

    Returning a finding unconditionally satisfies every negative assertion in this
    file. This is the assertion that fails instead.
    """
    assert _errors(tmp_path, CLOSES_274, "Some prose.\n\nCloses #274.") == []


@pytest.mark.parametrize(
    "body",
    [
        "Closes #274",
        "closes #274.",
        "Fixes #274",
        "fixed #274",
        "Resolve #274",
        "Resolved #274",
        "Closes: #274",
        "Closes Digital-Process-Tools/claude-oss#274",
        "Closes https://github.com/Digital-Process-Tools/claude-oss/issues/274",
        "Some prose.\n\nCloses\n#274\n",
    ],
)
def test_the_spellings_a_forge_accepts_are_not_refused(tmp_path, body):
    """A false refusal is cheap to hit and expensive to debug, so the accepted
    grammar is enumerated rather than assumed."""
    assert _errors(tmp_path, CLOSES_274, body) == [], body


@pytest.mark.parametrize(
    "body",
    [
        "A bare #274 mention.",
        "`Closes #274`",
        "```\nCloses #274\n```",
        "<!-- Closes #274 -->",
        "Closes #999 #274",
        "Closes #2740",
        "This foreclosed #274 long ago.",
    ],
)
def test_the_spellings_that_close_nothing_are_refused(tmp_path, body):
    """Each of these renders as a closing reference to a reader and creates none.

    `Closes #999 #274` is the documented trap: a forge links both numbers and closes
    only the first, so the second needs its own keyword and does not have one here.
    """
    assert _errors(tmp_path, CLOSES_274, body), body


def test_every_declared_issue_needs_its_own_binding(tmp_path):
    both = {"state": "closes", "issues": [274, 275]}
    assert _errors(tmp_path, both, "Closes #274.\nCloses #275.") == []
    errors = _errors(tmp_path, both, "Closes #274 #275.")
    assert errors, "the second number of a shared keyword closes nothing"
    assert "275" in " ".join(errors) and "274" not in " ".join(errors), errors


def test_closing_nothing_is_contradicted_by_a_body_that_closes_something(tmp_path):
    """The inverse defect, and it is not symmetric with the one above.

    A report saying `closes-nothing` is read by the maintainer as "merging this leaves
    the issue open". A body binding `Closes #274` under that claim merges and closes
    it, which is the same absence pointing the other way.
    """
    declared = {"state": "closes-nothing", "reason": "Part of #250, deliberately."}
    assert _errors(tmp_path, declared, "Part of #250. More work follows.") == []
    assert _errors(tmp_path, declared, "Part of #250.\n\nCloses #250."), (
        "the report says this closes nothing and the body closes #250"
    )


@pytest.mark.parametrize(
    "name,issues,body",
    [
        (
            "PR #331, the omission",
            [321],
            "Rework of the thing (#321).\r\n\r\nMore prose.",
        ),
        (
            "PR #332, the inert keyword",
            [275, 296],
            "`Closes #275, closes #296`\r\n\r\nThe opening paragraph.",
        ),
    ],
)
def test_the_two_measured_instances_are_refused(tmp_path, name, issues, body):
    """The bodies as they were actually written, CRLF and all.

    Both were created by `gh-pr-create`, which reported the absence and returned 0,
    and both were repaired by hand before the merge. A line ending is not a detail
    here: a forge accepts either, so a checker anchoring on a bare newline would pass
    the one written on a machine that does not use one.
    """
    assert _errors(tmp_path, {"state": "closes", "issues": issues}, body), name


@pytest.mark.parametrize(
    "body",
    [
        "Closes #275.\r\nCloses #296.\r\n",
        "Closes #275.\nCloses #296.\n",
    ],
)
def test_the_repair_that_was_applied_by_hand_is_accepted(tmp_path, body):
    """The positive control for the case above, under both line endings."""
    assert _errors(tmp_path, {"state": "closes", "issues": [275, 296]}, body) == [], (
        body
    )


def test_negated_closing_keyword_still_binds_for_state_closes(tmp_path):
    """#556: PR #554's body disclaimed closing #241 in prose ("It does not close
    #241 and nothing here changes that check") and GitHub closed it anyway on merge,
    because a forge matches a closing keyword by position, not sentence meaning. A
    declared `closes` must not be refused just because the binding sits inside a
    negated sentence -- the forge closes it either way, so refusing it here would be
    a false alarm this checker does not need.
    """
    body = "It does not close #241 and nothing here changes that check."
    errors = _errors(tmp_path, {"state": "closes", "issues": [241]}, body)
    assert errors == [], errors


def test_negated_closing_keyword_is_still_caught_under_closes_nothing(tmp_path):
    """The inverse of the case above, in the same fixture shape (#556). `closes-
    nothing` must still be refused when the body binds a keyword under a negation,
    because the forge closes the issue regardless of the disclaiming prose around
    it -- this is the actual PR #554 shape had it been declared `closes-nothing`. A
    checker that started treating every negated sentence as unbound could not pass
    both this test and the one above.
    """
    body = "It does not close #241 and nothing here changes that check."
    declared = {"state": "closes-nothing", "reason": "Part of #241, deliberately."}
    errors = _errors(tmp_path, declared, body)
    assert errors, "the report says this closes nothing and the body binds #241"


def test_the_matching_rule_is_recorded_beside_the_constant():
    """#556, CLAUDE.md's #180 rule: a transcription is measured against its
    authority in a test, or explained as unmeasurable with a reason -- not just
    asserted in a comment nothing checks. This reads the module's own source for the
    paragraph beside `_CLOSING_KEYWORD` and checks it states the fact that makes the
    negation case harmless: matching is positional, not semantic.
    """
    source = Path(report_schema.__file__).read_text(encoding="utf-8")
    marker = source.index("_CLOSING_KEYWORD = r")
    nearby = source[max(0, marker - 1500) : marker].lower()
    assert "position" in nearby, nearby
    assert "#556" in nearby, nearby


def test_the_finding_names_gh_pr_create_as_the_authority(tmp_path):
    """The check must not imply a guarantee it does not make.

    It detects a definite absence. It does not decide what a forge will close, and
    the sentence a maintainer reads has to say which of those two it is.
    """
    errors = _errors(tmp_path, CLOSES_274, "A bare #274 mention.")
    assert any("gh-pr-create" in error for error in errors), errors


def test_the_schema_declines_to_own_a_closing_reference_reader():
    """The declined half, pinned so it cannot be quietly re-decided.

    A resolver deciding which issues a forge closes lives in supertool and is used by
    gh-pr, gh-pr-create and gh-pr-edit. Every route to it opens the network and two of
    them publish, so it is not reachable from a stdlib-only validator -- and the
    document has to say so, or the weaker check reads as the strong one.
    """
    described = _schema()["$defs"]["pr_body"]["properties"]["closes"]["description"]
    lowered = described.lower()
    assert "gh-pr-create" in lowered, described
    assert "absence" in lowered, described


def test_the_on_disk_narrative_admits_it_is_no_longer_shape_only():
    """Caught in review of this very diff, and pinned rather than just fixed.

    `x-honesty-on-disk` said the on-disk pass "opens the pr_body payload, parses it,
    and checks the shape the forge needs" -- true until this change, and the whole
    point of the change is a check on the body's CONTENT. A narrative describing a
    narrower validator than the one shipped is the same defect as a list describing
    a wider one, and this document's own honesty rests on both being read.
    """
    narrative = _schema()["x-honesty-on-disk"].lower()
    assert "content" in narrative, narrative
    assert "closing keyword" in narrative, narrative


def test_a_payload_whose_body_could_not_be_read_is_not_a_missing_keyword(tmp_path):
    """The third state of the on-disk half.

    A payload that does not exist, or does not parse, has no body to search. Reporting
    "no closing keyword" for one would be this repository's own defect class inside the
    check written against it: nothing looked, and the output says something was found
    wanting.
    """
    report = _example()
    report["pr_body"] = {
        "state": "written",
        "path": str(tmp_path / "never-written.pr.json"),
        "closes": CLOSES_274,
    }
    errors = report_schema.validate_pr_body(report, base_dir=tmp_path)
    assert errors, "a payload that is not there has to be reported"
    joined = " ".join(errors).lower()
    assert "closing keyword" not in joined, errors

    (tmp_path / "broken.pr.json").write_text("# not json", encoding="utf-8")
    report["pr_body"]["path"] = str(tmp_path / "broken.pr.json")
    errors = report_schema.validate_pr_body(report, base_dir=tmp_path)
    assert errors, "a payload that does not parse has to be reported"
    assert "closing keyword" not in " ".join(errors).lower(), errors
