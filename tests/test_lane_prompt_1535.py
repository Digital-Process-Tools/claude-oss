"""#1535: the spawn payload is the issue numbers and the worktree, nothing else.

`agents/developer.md` is injected whole on every turn of every lane and already
carries supertool, TDD, the publishing clause, pushback and untrusted input. A
brief restating them per lane pays for them twice, and
`lane_setup_brief_schema` refused to render the `Agent(...)` call unless the
restatement was there -- a substring match over the brief's own text, satisfied
by the words appearing, which is compliance with itself.

So the schema now checks the *prompt about to be dispatched* against the two
facts a lane cannot read anywhere else, plus the one check that was always about
the prompt string rather than the brief's content:

    issues       the issue numbers -- nothing else tells the lane what to work on
    worktree     derived at claim time by the dispatcher
    placeholder  a literal `{{...}}` marker, unfixable after dispatch (#1022)

Every "must not fire" below is paired with a "must fire" in the same fixture.

Python 3.9 compatible.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402
import lane_setup_brief_schema as brief_schema  # noqa: E402
import lane_setup_claim  # noqa: E402
import select_issues_claim_read as claim_read  # noqa: E402

#: The target shape #1535 names, verbatim in structure.
TARGET = "Issues 1526 and 1528. Your worktree is /tmp/wt/1526."


def _row(payload, element):
    for row in payload["elements"]:
        if row["element"] == element:
            return row
    raise AssertionError(
        "no {0!r} row in {1}".format(
            element, [r["element"] for r in payload["elements"]]
        )
    )


# ------------------------------------------------- the element set is the two facts plus the placeholder


def test_the_schema_checks_three_elements_and_names_them():
    payload = brief_schema.check_text(
        TARGET, issues=[1526, 1528], worktree="/tmp/wt/1526"
    )
    assert [row["element"] for row in payload["elements"]] == [
        "issues",
        "worktree",
        "placeholder",
    ]


def test_the_target_prompt_passes_with_nothing_else_in_it():
    """The whole point: a two-sentence prompt is a complete spawn payload."""
    payload = brief_schema.check_text(
        TARGET, issues=[1526, 1528], worktree="/tmp/wt/1526"
    )
    assert payload["state"] == brief_schema.STATE_OK, payload["missing"]


def test_the_retired_restatement_checks_are_gone():
    """Must-not-fire, paired with the must-fire above: a prompt naming no
    supertool op, no TDD order and no publishing clause is `ok` now. Each
    retired check is also asserted absent as a callable, so a rename cannot
    leave one running under another name."""
    for name in (
        "check_supertool",
        "check_judgment_call",
        "check_pushback",
        "check_tdd",
        "check_docs",
        "check_worktrees",
        "check_recon",
        "check_publishing",
    ):
        assert not hasattr(brief_schema, name), (
            "{0} survived -- the brief still enforces a restatement of "
            "agents/developer.md (#1535)".format(name)
        )


# ------------------------------------------------- issues: verified against what the claim holds


def test_a_prompt_missing_a_claimed_issue_is_a_structural_finding():
    payload = brief_schema.check_text(
        "Issue 1526. Your worktree is /tmp/wt/1526.",
        issues=[1526, 1528],
        worktree="/tmp/wt/1526",
    )
    row = _row(payload, "issues")
    assert row["state"] == "missing"
    assert row["checked"] == brief_schema.STRUCTURAL
    assert "1528" in row["why"]
    assert payload["state"] == brief_schema.STATE_FINDINGS


def test_a_number_that_merely_looks_like_an_issue_does_not_satisfy_the_check():
    """The self-confirmation this replaces: presence of *a* number is not
    presence of *the* numbers this lane holds.

    The worktree here deliberately carries no digits. A real worktree path is
    named after the primary issue, so the primary's own number is satisfied by
    the worktree sentence alone -- a genuine narrowing of this check, and the
    reason the fixture below would otherwise pass for the wrong reason. The
    companion numbers, which is where a dropped issue actually costs
    something, are checked with nothing else to satisfy them.
    """
    payload = brief_schema.check_text(
        "Issues 42 and 43. Your worktree is /tmp/wt/lane-a.",
        issues=[1526],
        worktree="/tmp/wt/lane-a",
    )
    assert _row(payload, "issues")["state"] == "missing"


def test_with_no_claimed_set_given_the_row_says_what_it_could_not_verify():
    """Third state: the check still runs, but it can only say that some issue
    number appears. It must never render as the verified case."""
    payload = brief_schema.check_text(TARGET)
    row = _row(payload, "issues")
    assert row["state"] == "found"
    assert "not verified" in row["note"]

    # Must-fire in the same fixture: no issue number at all is still a finding.
    assert (
        _row(brief_schema.check_text("no numbers here"), "issues")["state"] == "missing"
    )


# ------------------------------------------------- worktree


def test_a_prompt_missing_the_worktree_is_a_structural_finding():
    payload = brief_schema.check_text(
        "Issues 1526 and 1528.", issues=[1526, 1528], worktree="/tmp/wt/1526"
    )
    row = _row(payload, "worktree")
    assert row["state"] == "missing"
    assert row["checked"] == brief_schema.STRUCTURAL
    assert "/tmp/wt/1526" in row["why"]


def test_with_no_worktree_given_the_row_says_what_it_could_not_verify():
    payload = brief_schema.check_text(TARGET)
    row = _row(payload, "worktree")
    assert row["state"] == "found"
    assert "not verified" in row["note"]

    assert (
        _row(brief_schema.check_text("Issue 1526, nothing else."), "worktree")["state"]
        == "missing"
    )


# ------------------------------------------------- the placeholder check survives unchanged (#1022)


def test_a_literal_placeholder_marker_still_refuses():
    payload = brief_schema.check_text(
        "Issues 1526 and 1528. Your worktree is {{WORKTREE PATH HERE}}.",
        issues=[1526, 1528],
    )
    assert _row(payload, "placeholder")["state"] == "missing"
    assert payload["state"] == brief_schema.STATE_FINDINGS


# ------------------------------------------------- could-not-read is its own answer
#
# Carried over from the deleted test_brief_schema_967.py, whose other coverage
# was about the eight restatement elements #1535 retired. This third state is
# not about them: "this prompt is missing the worktree" and "nobody read that
# file" are different facts, and the second must never be reported in the
# vocabulary of the first.


def test_an_unreadable_file_is_neither_ok_nor_a_findings_row(tmp_path):
    payload = brief_schema.check_path(tmp_path / "no-such-file.md")
    assert payload["state"] == brief_schema.STATE_COULD_NOT_READ
    assert payload["missing"] == []
    assert payload["elements"] == []
    assert "nobody looked" in brief_schema.receipt(payload)


def test_check_path_reads_a_real_file_and_reports_on_it(tmp_path):
    """Positive control for the assertion above: check_path is not simply
    always could-not-read."""
    good = tmp_path / "prompt.md"
    good.write_text(TARGET, encoding="utf-8")
    assert brief_schema.check_path(good)["state"] == brief_schema.STATE_OK

    bad = tmp_path / "bad.md"
    bad.write_text("no issue and no path", encoding="utf-8")
    assert brief_schema.check_path(bad)["state"] == brief_schema.STATE_FINDINGS


def test_every_element_declares_how_it_was_checked():
    payload = brief_schema.check_text(TARGET)
    for row in payload["elements"]:
        assert row["checked"] == brief_schema.STRUCTURAL, row


def test_the_receipt_names_where_the_rest_of_a_lane_brief_lives():
    text = brief_schema.receipt(brief_schema.check_text(TARGET))
    assert "agents/developer.md" in text


# ------------------------------------------------- lane_prompt: the dispatcher composes it


def test_lane_prompt_composes_the_two_facts_and_nothing_else():
    assert (
        lane_setup.lane_prompt([1526, 1528], "/tmp/wt/1526")
        == "Issues 1526 and 1528. Your worktree is /tmp/wt/1526."
    )
    assert (
        lane_setup.lane_prompt([1526], "/tmp/wt/1526")
        == "Issue 1526. Your worktree is /tmp/wt/1526."
    )


def test_lane_prompt_says_the_worktree_is_unknown_rather_than_omitting_it():
    """An absent worktree must not render as a prompt that simply does not
    mention one -- the lane would cut its own and nobody would know which."""
    text = lane_setup.lane_prompt([1526], None)
    assert "1526" in text
    assert "could not be derived" in text


def test_agent_call_carries_the_prompt_when_one_is_given():
    call = lane_setup.agent_call(
        1526, [1526, 1528], "phrase", "oss:developer", prompt=TARGET
    )
    assert 'prompt: "{0}"'.format(TARGET) in call

    # Must-fire in the same fixture: without one, the placeholder is still there.
    bare = lane_setup.agent_call(1526, [1526, 1528], "phrase", "oss:developer")
    assert 'prompt: "<brief>"' in bare


# ------------------------------------------------- compose_claim_label needs no brief file


def _claim(tmp_path, primary, also):
    def checker(numbers, mode, repo=None):
        if mode == "claim":
            return [{"issue": n, "state": claim_read.STATE_CLAIMED} for n in numbers]
        return [{"issue": n, "state": claim_read.STATE_RELEASED} for n in numbers]

    return lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"),
        primary,
        "fix/{0}".format(primary),
        str(tmp_path / "wt"),
        also_claim=also,
        checker=checker,
    )


def test_a_claim_renders_the_whole_call_with_no_brief_file_at_all(tmp_path):
    result = _claim(tmp_path, 1526, [1528])
    label = lane_setup.compose_claim_label(
        {"issue": 1526, "claim_result": result},
        "phrase",
        subagent_type="oss:developer",
        worktree="/tmp/wt/1526",
    )
    assert label["state"] == "rendered", label
    assert "Issues 1526 and 1528. Your worktree is /tmp/wt/1526." in label["text"]
    assert label["brief"]["state"] == brief_schema.STATE_OK


def test_an_appended_brief_carrying_a_placeholder_still_refuses(tmp_path):
    """Must-fire control for the pass above: the schema is not decorative just
    because the dispatcher composes most of the prompt itself."""
    path = tmp_path / "extra.md"
    path.write_text("{{PASTE THE RECON SUMMARY HERE}}", encoding="utf-8")
    result = _claim(tmp_path, 1526, [1528])
    label = lane_setup.compose_claim_label(
        {"issue": 1526, "claim_result": result},
        "phrase",
        subagent_type="oss:developer",
        worktree="/tmp/wt/1526",
        brief_path=str(path),
    )
    assert label["state"] == "brief-structural-finding"
    assert label["text"] is None


def test_an_underivable_worktree_refuses_the_call(tmp_path):
    result = _claim(tmp_path, 1526, [1528])
    label = lane_setup.compose_claim_label(
        {"issue": 1526, "claim_result": result},
        "phrase",
        subagent_type="oss:developer",
        worktree=None,
    )
    assert label["state"] == "brief-structural-finding"


# ------------------------------------------------- the CLI no longer demands a brief file


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "lane_setup.py")] + list(args),
        capture_output=True,
        text=True,
    )


def test_subagent_type_no_longer_requires_brief():
    """Must-not-fire. Paired below with the direction that is still enforced."""
    result = _cli(
        "1",
        "--claim",
        "--lane",
        "x.py",
        "--phrase",
        "p",
        "--subagent-type",
        "oss:developer",
    )
    assert "--subagent-type requires --brief" not in (result.stdout + result.stderr)


def test_brief_still_requires_subagent_type():
    """Must-fire in the same pair: --brief alone was silently ignored (#1143)."""
    result = _cli("1", "--claim", "--lane", "x.py", "--brief", "b.md")
    assert "--brief requires --subagent-type" in (result.stdout + result.stderr)
