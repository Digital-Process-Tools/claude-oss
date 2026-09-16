"""#1571: the merge spawn must derive its own gate facts before it merges.

`agents/tick-merge.md` stated `skills/manager/phases/merge.md`'s gates in prose --
feature scope, public API change, external-contributor authored -- and gave the
spawn no call that establishes any of them. It receives a bare pull request
number, and its first documented action was
``gh-pr-merge:N:squash|force|cleanup``, where ``|force`` bypasses the confirm gate.

#1602 later dropped the `^curate/` head-branch gate these tests originally also
covered: `author_association` is the one remaining fact this file pins, not two.

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

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TICK_MERGE = REPO_ROOT / "agents" / "tick-merge.md"
MERGE_PHASE = REPO_ROOT / "skills" / "manager" / "phases" / "merge.md"

# The one read that cannot be derived from the pull request number alone, and
# that the remaining gate in merge.md turns on. This is a supertool op spelling,
# not a GitHub API field name: the first draft of this fix documented
# `gh pr view --json author_association`, which is wrong twice over -- gh spells
# that field `authorAssociation`, and this repo's own guard refuses a raw
# `gh pr view` at command position in favour of the `gh-pr` op. A test pinned to
# field names would have passed on a call no spawn here can run.
#
# #1573: the second draft's own `gh-prs:state=open,external,iids` was wrong a
# third way -- `external` is not a filter or a flag `gh-prs` recognises at all
# (`supertool 'help:gh-prs'` lists exactly `assignee, author, label,
# merged-since, per, reviewer, state` plus `anyauthor, failed, iids, nopipe`),
# and the live call is refused on sight. `test_tick_merge_documents_the_gate_reads`
# below still only pins substring presence, and prose *explaining* why
# `external` is not a real filter still contains the substring "external" --
# so REQUIRED_READS pins the token that actually carries the read
# (`author_association`, fed to `inbound_triage.classify_pr`) rather than the
# board-filter spelling that was never valid, and BROKEN_FILTER_CALL below
# pins the exact refused string as a standing regression check.
#
# #1602 dropped the `^curate/` head-branch gate and, with it, the
# `gh-pr:N:status` call that fed it -- REQUIRED_READS pinned both tokens before
# this, and now pins the one fact that is still read rather than recalled.
REQUIRED_READS = ("author_association",)

# The exact call #1573 found refused. Its presence anywhere in either file,
# even inside an explanation of why it does not work, is the shape that
# fooled REQUIRED_READS the first time -- so this is checked by itself,
# never folded into REQUIRED_READS.
BROKEN_FILTER_CALL = "gh-prs:state=open,external,iids"

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


def test_neither_file_documents_the_refused_gh_prs_filter():
    """#1573: `gh-prs:state=open,external,iids` is refused outright --
    `external` is neither a filter nor a flag `gh-prs` recognises. A prose
    line built to *explain* why it does not work still contains the same
    substring `REQUIRED_READS` used to pin on, which is exactly how the
    first fix passed this file's own tests while shipping a call nothing
    can run. Checked as an exact standing string, never folded into
    REQUIRED_READS above."""
    for path in (TICK_MERGE, MERGE_PHASE):
        text = _text(path)
        assert BROKEN_FILTER_CALL not in text, (
            "{} still documents the refused call {!r} -- #1573 found this "
            "exact string refused by supertool's own gh-prs op".format(
                path.name, BROKEN_FILTER_CALL
            )
        )


def test_the_broken_filter_check_is_capable_of_failing():
    """Positive control: a constructed text carrying the broken call must be
    caught by the same substring check, or the assertion above proves
    nothing."""
    poisoned = "some prose\n{}\nmore prose".format(BROKEN_FILTER_CALL)
    assert BROKEN_FILTER_CALL in poisoned


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


def test_merge_phase_states_the_same_read():
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
    """Positive control: the field is being added alongside the existing rule,
    not in place of it."""
    text = _text(MERGE_PHASE)
    for rule in ("external-contributor",):
        assert rule in text, (
            "skills/manager/phases/merge.md no longer states the {!r} gate -- the "
            "field additions must not have displaced it".format(rule)
        )
