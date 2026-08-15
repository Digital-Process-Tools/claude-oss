"""Guards on agents/triager.md's board-level duties.

Companion to test_content_invariants.py, which holds the cross-document prose
guards. These are the triager's own: the label-write route, the cluster duty,
the cohort burn-down and the disagreement invitation.

Every anchor is matched against a flattened copy of the document -- lowercased,
every run of whitespace collapsed to one space -- because these documents wrap
at 100 columns and a multi-word anchor lands across a newline the moment a
paragraph is reflowed. A checker whose finding is about its own reading,
dressed as a finding about the file, is the defect this plugin is named after
pointed at the test suite.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAGER = REPO_ROOT / "agents" / "triager.md"
EXECUTABLE_PROSE = sorted(
    list((REPO_ROOT / "skills").rglob("SKILL.md"))
    + list((REPO_ROOT / "agents").glob("*.md"))
    + list((REPO_ROOT / "commands").glob("*.md"))
)


def _flatten(text):
    """Fold case and collapse every run of whitespace to one space."""
    return " ".join(text.lower().split())


def _triager():
    return _flatten(TRIAGER.read_text(encoding="utf-8"))


def _unmet(text, anchors):
    folded = _flatten(text)
    return [anchor for anchor in anchors if anchor not in folded]


# The document as it stood before this change: the negative control the checks
# below are run against, so a check that would pass on anything is visible.
PRIOR = """
Labels are a write, so they go through raw `gh` -- `gh issue edit N --add-label ...`.

## What you surface, beyond labels

- **Merged but still open.**
- **A released milestone still holding open issues.**
- **A stale premise** -- grep for the *concept*, not the issue's spelling of it.
- **Duplicates**, as a comment naming the twin, never as a close.

## Report format

A table, not reassurance. Per issue: number, what you applied, and one line of reason.
"""


def test_the_triager_document_exists_and_is_prose():
    """Positive control. Every check below is an `in` against this file's text,
    so an empty or missing file satisfies none of them for the wrong reason --
    and a suite that could not find the document would report every duty as
    absent, which is a finding about the harness wearing the costume of a
    finding about the file.
    """
    assert TRIAGER.is_file(), "agents/triager.md is missing"
    assert len(_triager()) > 2000, "agents/triager.md is too short to be the brief"


# ------------------------------------------------------------- the label write

LABEL_WRITE_ANCHORS = [
    "replaces the whole label set",
    "every label not named in that call is removed",
    "only when replacing the whole set is the thing you mean",
    "issues/n/labels",
    "count after your last write, not before it",
]


def test_triager_states_that_patch_replaces_the_label_set():
    """`gh api -X PATCH issues/N -f 'labels[]=x'` removes every label it does not
    name. Exit 0, no warning, and the labels most likely to be destroyed are the
    ones an agent never sets and therefore never re-sends.
    """
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), LABEL_WRITE_ANCHORS)


def test_the_label_write_check_fires_on_the_line_as_it_stood_before():
    missing = _unmet(PRIOR, LABEL_WRITE_ANCHORS)
    assert missing == LABEL_WRITE_ANCHORS, (
        "the label-write check passes against a document that only prescribes "
        "--add-label, so it is not anchored on the new rule: {}".format(missing)
    )


# ------------------------------------------------------------- the PATCH sweep

# `gh api` spells the verb two ways -- `-X PATCH` and `--method PATCH` -- and a
# sweep anchored on one of them would wave the other through. That is the same
# defect the sweep exists to catch, one level up: a guard that looked and could
# only see half of what it was pointed at.
PATCH_SPELLINGS = ("-x patch", "--method patch")
LABEL_WORD = "labels[]="
REPLACES = "replaces the whole label set"


def _patch_without_its_warning(text):
    folded = _flatten(text)
    if not any(spelling in folded for spelling in PATCH_SPELLINGS):
        return False
    if LABEL_WORD not in folded:
        return False
    return REPLACES not in folded


def test_the_patch_sweep_fires_on_a_document_that_prescribes_it_bare():
    """The positive control for the sweep below. Without it, the sweep passes on
    a corpus in which the PATCH form simply never appears -- a pattern that
    matched nothing having checked nothing. Both spellings are controlled, or the
    sweep's coverage of the second one is an assumption rather than a check.
    """
    assert _patch_without_its_warning(
        "Set the labels with `gh api -X PATCH repos/O/R/issues/N -f 'labels[]=bug'`."
    )
    assert _patch_without_its_warning(
        "Set them with `gh api --method PATCH repos/O/R/issues/N -f 'labels[]=bug'`."
    )
    assert not _patch_without_its_warning(
        "`gh api -X PATCH ... -f 'labels[]=bug'` replaces the whole label set."
    )
    assert not _patch_without_its_warning(
        "`gh api --method PATCH ... -f 'labels[]=bug'` replaces the whole label set."
    )


def test_no_document_prescribes_the_patch_label_write_without_the_warning():
    assert EXECUTABLE_PROSE, "no executable prose found -- this check would vacuously pass"
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in EXECUTABLE_PROSE
        if _patch_without_its_warning(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "these documents name the PATCH label write without saying it replaces the "
        "whole set, which is the form that silently deletes a cohort label: {}".format(
            offenders
        )
    )


# ------------------------------------------------------------ the cluster duty

CLUSTER_ANCHORS = [
    "cluster on the mechanism, never on the title",
    "propose only",
    "two issues in the same file are not a cluster",
    "different grades of evidence",
    "reported, not proposed",
]


def test_triager_carries_the_cluster_duty():
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), CLUSTER_ANCHORS)


def test_the_cluster_check_fires_on_the_document_that_had_no_cluster_duty():
    missing = _unmet(PRIOR, CLUSTER_ANCHORS)
    assert missing == CLUSTER_ANCHORS, (
        "the cluster check passes against a document with no cluster duty: {}".format(
            missing
        )
    )


CLUSTER_STATE_ANCHORS = [
    "no two issues share a mechanism",
    "could not look",
    "it is not none",
]


def test_the_cluster_row_has_three_states():
    """`none` and `I could not read across the board` are different answers, and
    an omitted row renders as the first one. This plugin is named after that.
    """
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), CLUSTER_STATE_ANCHORS)


def test_the_three_state_check_fires_on_a_row_that_only_says_none():
    """The negative control has to be a document that reports clusters and stops
    at two states -- not one that omits the duty entirely, which would let this
    pass on the strength of the cluster duty's absence rather than on the
    absence of the third state.
    """
    two_states = (
        "Report a `Clusters` row. Say `none` explicitly when you read across the whole "
        "board and no two issues share a mechanism, so a zero reads as 'I looked'. "
        "Cluster on the mechanism, never on the title."
    )
    missing = _unmet(two_states, CLUSTER_STATE_ANCHORS)
    assert missing == ["could not look", "it is not none"], (
        "this control must carry the `none` state and lack only the third one, or it "
        "cannot show that the check discriminates between a two-state row and a "
        "document with no cluster duty at all -- which is what it looked like it was "
        "showing while it asserted a substring of a set that was missing everything. "
        "missing={}".format(missing)
    )


def test_the_cluster_duty_forbids_every_forge_write_it_can_reach():
    """The tool grant withholds Edit and Write, so the filesystem is closed. The
    forge is not: `gh issue close`, `gh issue edit --body` and `gh issue comment`
    are all Bash calls and all reachable from this agent. So propose-only cannot
    be delegated to the frontmatter here -- the prose is the boundary, and it has
    to name the three commands rather than gesture at them.
    """
    folded = _triager()
    for command in ("gh issue close", "gh issue edit --body", "gh issue comment"):
        assert command in folded, (
            "triager.md does not name `{}` as a forge write it must not make; "
            "the Edit/Write denial does not cover it".format(command)
        )


# --------------------------------------------------- cohort and milestone reads

COHORT_ANCHORS = [
    "the cohort burn-down, every run",
    "state the limit you counted under, beside the number",
    "a partial read rendering as a total",
    "filed after the freeze",
    "never remove one either",
]


def test_triager_reports_the_cohort_burn_down_with_the_limit_it_counted_under():
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), COHORT_ANCHORS)


def test_the_cohort_check_fires_on_a_document_that_only_forbids_the_write():
    write_only = "- **Never write a `cohort-*` label.** Freezing a cohort is the maintainer's act."
    missing = _unmet(write_only, COHORT_ANCHORS)
    assert missing == COHORT_ANCHORS, (
        "the cohort check passes on a document carrying only the write "
        "prohibition: {}".format(missing)
    )


def test_a_shipped_milestone_is_stated_as_a_rule_not_only_as_a_finding():
    assert "a shipped milestone ends at zero" in _triager()


# The burn-down got a duty, a counting trap and a limit in #148. What it did not
# get is the thing this plugin is named after: a third state. `Clusters` has one
# spelled out; the cohort row had two -- a number, and the limit beside it -- so
# a run that could not count had nowhere to say so, and the only shape left for
# it was silence. An omitted burn-down and a finished backlog render identically,
# which is the exact failure the duty exists to prevent, one level up.
COHORT_STATE_ANCHORS = [
    "no cohort label exists on this board",
    "could not count",
    "never render as 0 open",
]


def test_the_cohort_burn_down_has_three_states():
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), COHORT_STATE_ANCHORS)


def test_the_cohort_state_check_fires_on_a_burn_down_that_is_only_a_number():
    """The control has to be a document that already carries the duty, the trap
    and the limit -- everything #148 shipped -- and lacks only the third state.
    A control missing the whole bullet would let this pass on the duty's absence
    rather than on the absence of the state, which is a check reporting on a
    sentence nobody wrote.
    """
    two_states = (
        "- **The cohort burn-down, every run** -- how many issues carrying the current "
        "cohort label are still open. **State the limit you counted under, beside the "
        "number** -- `gh-issues:label=cohort-N,state=open,per=100`. The tally was a "
        "partial read rendering as a total, and a cohort that appears to shrink when it "
        "has not is worse than no number at all."
    )
    missing = _unmet(two_states, COHORT_STATE_ANCHORS)
    assert missing == COHORT_STATE_ANCHORS, (
        "this control carries the burn-down duty, the limit and the counting trap and "
        "must lack all three state phrases, or the check is anchored on the duty rather "
        "than on its third state: missing={}".format(missing)
    )


def test_the_cohort_row_is_required_in_the_report_format_section():
    """Under `What you surface` the burn-down is a thing to notice; in `Report
    format` it is a row whose absence is a finding. #148 put it only in the
    first, and a duty nobody has to render is a duty that renders as nothing.
    """
    assert "a **`cohort`** row is required" in _triager(), (
        "agents/triager.md describes the burn-down but never makes it a required row "
        "of the report, so omitting it costs the agent nothing"
    )


STALE_PREMISE_ANCHORS = [
    "grep the issue number with a word boundary after it",
    "only a pull makes the working tree honest",
    "say which commit your grep answered about",
]


def test_the_stale_premise_check_names_its_two_mechanics_and_its_third_state():
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), STALE_PREMISE_ANCHORS)


def test_the_tree_freshness_rule_does_not_send_an_agent_into_an_occupied_tree():
    """A `git pull` is a write to a working tree, and in this loop the clone and
    every worktree are routinely occupied by another agent. Moving HEAD under a
    running suite to answer a triage question is not a trade this brief may make,
    so the freshness instruction has to carry its own exception.
    """
    assert "unless another agent is working in it" in _triager()


# ------------------------------------------------- the disagreement invitation

DISAGREEMENT_ANCHORS = [
    "say so and rank it your way, with the reason",
    "that disagreement is worth more than the label",
]


def test_triager_may_argue_with_the_ranking_table():
    """A model told to apply a table and not told it may argue with the table
    will apply the table. The developer brief has `Push back`; this one had
    nothing equivalent.
    """
    assert not _unmet(TRIAGER.read_text(encoding="utf-8"), DISAGREEMENT_ANCHORS)


def test_the_disagreement_check_fires_on_the_brief_without_it():
    missing = _unmet(PRIOR, DISAGREEMENT_ANCHORS)
    assert missing == DISAGREEMENT_ANCHORS


# --------------------------------------------------------------- anchors bite

@pytest.mark.parametrize(
    "anchors",
    [
        LABEL_WRITE_ANCHORS,
        CLUSTER_ANCHORS,
        CLUSTER_STATE_ANCHORS,
        COHORT_ANCHORS,
        COHORT_STATE_ANCHORS,
        STALE_PREMISE_ANCHORS,
        DISAGREEMENT_ANCHORS,
    ],
)
def test_every_anchor_is_already_flattened(anchors):
    """An anchor carrying a capital letter or a double space can never match the
    flattened document, so the guard it belongs to would be permanently red for
    a reason that has nothing to do with the rule. Either way it stops being a
    statement about the file.
    """
    for anchor in anchors:
        assert anchor == _flatten(anchor), "anchor is not in flattened form: {!r}".format(
            anchor
        )


DOCUMENT_ANCHORS = (
    LABEL_WRITE_ANCHORS
    + CLUSTER_ANCHORS
    + CLUSTER_STATE_ANCHORS
    + COHORT_ANCHORS
    + COHORT_STATE_ANCHORS
    + STALE_PREMISE_ANCHORS
    + DISAGREEMENT_ANCHORS
)


def test_every_anchor_matches_exactly_one_place_in_the_document():
    """The other half, and it is the half that fails quietly.

    An anchor that stops matching -- because the phrase was reworded, or because
    markup the flattener does not strip landed inside its span -- turns its guard
    red, which is loud and self-announcing. An anchor generic enough to match
    something incidental turns its guard permanently green, and a green guard for
    a rule the document no longer states is indistinguishable from a green guard
    for a rule it does. Requiring exactly one occurrence closes that direction:
    the anchor has to be the sentence, not a phrase that happens to be in it.
    """
    folded = _triager()
    wrong = {
        anchor: folded.count(anchor)
        for anchor in DOCUMENT_ANCHORS
        if folded.count(anchor) != 1
    }
    assert not wrong, (
        "each anchor must occur exactly once in agents/triager.md -- 0 means the "
        "guard is red for a reason unrelated to the rule, and more than 1 means it "
        "can survive the rule's deletion: {}".format(wrong)
    )



# ------------------------------------------------ the command doc must not disagree
#
# `agents/triager.md` is what the triager reads; `commands/triage.md` is what the
# maintainer reads about the triager. Two descriptions of one contract, and #83
# established at length that the copy which drifts is the one quoted afterwards.
#
# This lane shipped the cluster duty into the agent file and left the command file
# enumerating three report parts, so the maintainer's own documentation promised a
# report shape the agent no longer produces -- and a `Clusters` row the reader was
# never told to look for reads exactly like a row the agent forgot.

TRIAGE_COMMAND = REPO_ROOT / "commands" / "triage.md"


def test_the_command_doc_tells_the_maintainer_the_clusters_row_exists():
    """The agent produces a Clusters row; the command doc has to say so, or the
    reader has no reason to notice a missing one.
    """
    assert TRIAGE_COMMAND.is_file(), "commands/triage.md is missing"
    folded = _flatten(TRIAGE_COMMAND.read_text(encoding="utf-8"))
    assert "clusters" in folded, (
        "commands/triage.md never mentions Clusters, so the maintainer is told the "
        "report has parts that do not include the one row whose absence is "
        "indistinguishable from an empty one"
    )


def test_the_command_doc_carries_the_clusters_third_state():
    """`none` and `could not look` are different answers. If only the agent file says
    so, the reader has no basis for rejecting a blank row.
    """
    folded = _flatten(TRIAGE_COMMAND.read_text(encoding="utf-8"))
    # Anchored on "row that did not run" rather than on "could not look". The control
    # below caught that one: it is this repo's house vocabulary for a third state and
    # appears in commands/doctor.md, so a guard keyed on it would have been green
    # whatever commands/triage.md said about clusters.
    missing = [phrase for phrase in ("row that did not run",) if phrase not in folded]
    assert not missing, (
        "commands/triage.md describes the Clusters row without its third state {} -- "
        "a row that did not run then reads as a board with no clusters".format(missing)
    )


def test_the_command_doc_states_the_propose_only_boundary():
    """The constraint that makes the duty safe. Stated in the agent file for the agent;
    stated here so the maintainer knows a cluster is a request and not a decision
    already taken.
    """
    # Anchored on "label to express a cluster", not on "never closes". The red run
    # caught that one: commands/triage.md:10 has said "never touches code, never closes
    # an issue" since long before clusters existed, so the guard passed against the
    # unchanged file -- a green tick over a sentence the document did not contain.
    folded = _flatten(TRIAGE_COMMAND.read_text(encoding="utf-8"))
    assert "label to express a cluster" in folded, (
        "commands/triage.md does not tell the maintainer that a cluster is a proposal "
        "the triager never acts on, so a reader could take the parent as already chosen"
    )


def test_the_command_doc_tells_the_maintainer_the_cohort_burn_down_exists():
    """The one number that says whether the backlog terminates, and the command
    doc enumerated the report's parts without it. A maintainer told the report
    has four parts has no reason to notice that the burn-down is not one of them.
    """
    assert TRIAGE_COMMAND.is_file(), "commands/triage.md is missing"
    folded = _flatten(TRIAGE_COMMAND.read_text(encoding="utf-8"))
    assert "cohort burn-down" in folded, (
        "commands/triage.md never mentions the cohort burn-down, so the maintainer is "
        "not told to look for the board's terminating condition"
    )


def test_the_command_doc_carries_the_cohort_third_state():
    """Anchored on `could not count`, which occurs nowhere else in the repo -- not
    on `could not look`, which is house vocabulary for a third state and appears
    in commands/doctor.md, so a guard keyed on it could never fail here.
    """
    folded = _flatten(TRIAGE_COMMAND.read_text(encoding="utf-8"))
    assert "could not count" in folded, (
        "commands/triage.md describes the burn-down without its third state -- a run "
        "that could not count then reaches the maintainer as a zero"
    )


def test_these_command_doc_guards_are_not_vacuous():
    """Positive control, and the first attempt at it was wrong in a way worth keeping.

    It stripped every *line* containing "luster" and then asserted the phrases were
    gone -- but the paragraph spans several lines and only one of them carries that
    word, so "could not look" survived and the control failed. A control that fails
    for a reason unrelated to what it controls is no better than one that passes for
    an unrelated reason.

    So the control is a sibling command document instead: one that legitimately never
    describes this row. If these phrases were generic enough to turn up there, every
    guard above would be permanently green regardless of what `commands/triage.md`
    says, and a deleted section would not turn one red.
    """
    sibling = REPO_ROOT / "commands" / "doctor.md"
    assert sibling.is_file(), "commands/doctor.md is missing -- no control to compare against"
    folded = _flatten(sibling.read_text(encoding="utf-8"))
    ambient = [
        phrase
        for phrase in (
            "clusters",
            "row that did not run",
            "label to express a cluster",
            "cohort burn-down",
            "could not count",
        )
        if phrase in folded
    ]
    assert not ambient, (
        "{} appear in commands/doctor.md, which does not describe the Clusters row -- "
        "so they are ambient phrasing and the guards above cannot fail".format(ambient)
    )
