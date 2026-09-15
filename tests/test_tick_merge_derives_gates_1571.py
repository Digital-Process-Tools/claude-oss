"""#1571: the merge spawn must derive its own gate facts before it merges.

`agents/tick-merge.md` stated `skills/manager/phases/merge.md`'s gates in prose --
feature scope, public API change, external-contributor authored, head branch
matching ``^curate/`` -- and gave the spawn no call that establishes any of them.
It receives a bare pull request number, and its first documented action was
``gh-pr-merge:N:squash|force|cleanup``, where ``|force`` bypasses the confirm gate.

A rule stated without a measurement is this repository's own named defect one level
down: a spawn that never reads ``author_association`` and a spawn that read it and
found a first-time contributor produce the same merge. Found by gate 3's round-one
audit of the v0.36.0 delta, filed unranked, and it stopped the tag.

These pin the two halves that make the difference: the derivation is documented at
all, and it is documented BEFORE the merge call rather than after it. Ordering is
load-bearing here because the file is read top-down by a spawn that acts as it
reads.

Every assertion is paired with a positive control, per this repo's rule that a
check which cannot fail proves nothing.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TICK_MERGE = REPO_ROOT / "agents" / "tick-merge.md"
MERGE_PHASE = REPO_ROOT / "skills" / "manager" / "phases" / "merge.md"

# The two reads that cannot be derived from the pull request number alone, and
# that the gates in merge.md turn on. These are supertool op spellings, not
# GitHub API field names: the first draft of this fix documented
# `gh pr view --json author_association`, which is wrong twice over -- gh spells
# that field `authorAssociation`, and this repo's own guard refuses a raw
# `gh pr view` at command position in favour of the `gh-pr` op. A test pinned to
# field names would have passed on a call no spawn here can run.
REQUIRED_READS = ("gh-pr:", "external")

MERGE_CALL = "gh-pr-merge"


def _text(path):
    return path.read_text(encoding="utf-8")


# --------------------------------------------------- the derivation exists


def test_tick_merge_documents_the_gate_reads():
    """Both reads must be named in the file that has to act on them."""
    text = _text(TICK_MERGE)
    missing = [read for read in REQUIRED_READS if read not in text]
    assert not missing, (
        "agents/tick-merge.md names none of {} -- it states merge.md's gates in "
        "prose but gives the spawn no way to establish them (#1571)".format(missing)
    )


def test_tick_merge_does_not_document_a_raw_gh_pr_view():
    """This repo's supertool guard refuses `gh pr view` at command position, so a
    spawn following such a documented call is refused rather than gated. The first
    draft of this very fix shipped one."""
    text = _text(TICK_MERGE)
    assert "gh pr view" not in text, (
        "agents/tick-merge.md documents a raw `gh pr view`, which this repo's own "
        "guard refuses in favour of the `gh-pr` op -- a documented call the spawn "
        "cannot run is not a gate (#1571)"
    )


def test_the_field_check_is_capable_of_failing():
    """Positive control: a field neither file mentions must not be found, or the
    assertion above would pass on any text at all."""
    text = _text(TICK_MERGE)
    assert "notAFieldAnyGitHubApiReturns" not in text


# --------------------------------------------------- and it comes first


def _first_index(text, needle):
    index = text.find(needle)
    assert index != -1, "{!r} is absent from the file entirely".format(needle)
    return index


def test_the_derivation_is_documented_before_the_merge_call():
    """The file is read top-down by a spawn that acts as it reads, so a gate
    stated after the merge call is a gate stated after the merge."""
    text = _text(TICK_MERGE)
    merge_at = _first_index(text, MERGE_CALL)
    for read in REQUIRED_READS:
        read_at = _first_index(text, read)
        assert read_at < merge_at, (
            "agents/tick-merge.md mentions {!r} at byte {} but first calls {!r} at "
            "byte {} -- the derivation must precede the merge, not follow it "
            "(#1571)".format(read, read_at, MERGE_CALL, merge_at)
        )


def test_the_ordering_check_would_catch_a_reversal():
    """Positive control for the ordering assertion: on a constructed text with the
    fields after the merge call, the same comparison must fail."""
    reversed_text = "{} then later gh-pr: and external".format(MERGE_CALL)
    merge_at = reversed_text.find(MERGE_CALL)
    field_at = reversed_text.find("gh-pr:")
    assert not (field_at < merge_at), (
        "the ordering comparison cannot distinguish before from after -- the test "
        "above would pass on a file that derives nothing until after it merges"
    )


# --------------------------------------------------- the phase file agrees


def test_merge_phase_states_the_same_two_reads():
    """`merge.md` is where the gates live; a derivation documented only in the
    spawn leaves the phase file's own readers deriving nothing."""
    text = _text(MERGE_PHASE)
    missing = [read for read in REQUIRED_READS if read not in text]
    assert not missing, (
        "skills/manager/phases/merge.md names none of {} -- its gates turn on "
        "facts it never says how to read (#1571)".format(missing)
    )


def test_merge_phase_points_at_the_existing_classifier():
    """`inbound_triage.classify_pr` already translates GitHub's association
    vocabulary and already returns a could-not-tell state. A second hand-rolled
    translation beside it is the duplicated fact CLAUDE.md forbids."""
    assert "classify_pr" in _text(MERGE_PHASE)


def test_merge_phase_still_states_the_gates_themselves():
    """Positive control: the fields are being added alongside the existing rules,
    not in place of them."""
    text = _text(MERGE_PHASE)
    for rule in ("external-contributor", "curate/"):
        assert rule in text, (
            "skills/manager/phases/merge.md no longer states the {!r} gate -- the "
            "field additions must not have displaced it".format(rule)
        )


def test_curate_branch_prefix_is_a_real_anchored_pattern():
    """The gate is `^curate/`, anchored. A substring check would hold a pull
    request whose branch merely contains the word somewhere."""
    assert re.match(r"^curate/", "curate/20260915T120000Z")
    assert not re.match(r"^curate/", "fix/not-curate/1571")
