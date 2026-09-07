"""A mechanical check for cohort-citation ordering -- #1220.

#1122 (PR #1218) changed CLAUDE.md's release-currency marker so it only ever cites an
already-frozen cohort (the previous release's, settled), never the release-being-cut's own
not-yet-frozen one. That closed one live mismatch (v0.25.0 cited cohort-21 at 30; the count
actually applied when the freeze ran, minutes later on the far side of the tag, was 32) but
left the ordering rule itself as release-process prose -- a release session reads and follows
it, nothing mechanically enforces it. A future release commit could repeat the mistake and
every test in the suite would still pass.

Two shapes were on the table (the issue names both): diff two release commits' cited cohort
numbers against their own tagger dates, or check a cited cohort against the two-route
`cohort_freeze` decision recorded in the state file (`oss_state.py`'s own
`detail.cohort_freeze`). The first needs full git history across tags; this repository's own
CI checkout is `actions/checkout`'s default depth of 1 (see `test_claude_md_currency.py`'s own
note), so a check built on walking tags would be unable to run on the one place it matters
most, and would need its own third state for "shallow clone, cannot compare" layered on top of
the states below. The second needs only the current worktree's own CLAUDE.md and the state
file already keeps: no tags, no history walk, and it is the actual source of truth for "when
did this cohort finish freezing" (`cohort_freeze.py` derives it from a tag's own tagger date,
but that number lives in the state entry, not in git). This module builds the second shape.

Four states, same discipline as `cohort_freeze` and `push_bypass` above it:

  ok               the cited cohort's recorded freeze (`detail.cohort_freeze`, state
                    "measured") happened strictly before the citation's own timestamp.
  finding          the cited cohort's recorded freeze happened at or after the citation's own
                    timestamp -- exactly v0.25.0's own mistake shape, mechanically caught.
  declined         the marker used its stated decline phrase instead of naming a cohort
                    (#1264) -- a release whose own tooling produced two disagreeing counts
                    said so honestly rather than guessing between them. Not `ok` (nothing was
                    verified) and not a `finding` (there is no false citation to catch), so it
                    gets its own state rather than colliding with either.
  could-not-check  no cohort was found in the marker in either shape (no numeric citation and
                    no stated decline -- the marker was silently forgotten or garbled), no
                    freeze record exists for the cited cohort, or the recorded freeze itself is
                    not `measured` (`unknown` or `could-not-count`, which cannot be trusted as a
                    boundary either). This is the ordinary case for this repository's own tree
                    today: `.max/` is git-ignored, so a fresh checkout (CI included) carries no
                    state file at all, and this must never render as `ok` -- an absent check is
                    not a clean one -- and never as `declined`, which is stated on purpose.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import cohort_citation_order as cco  # noqa: E402
import oss_state  # noqa: E402

MARKER_TEXT = "**Cohort freeze: cohort-22 at 42 open issues, against cohort-21's 29.**"


def _freeze_entry(cohort, at, state=oss_state.COHORT_MEASURED, count=1):
    return {
        "at": at,
        "decision": "froze {} at {}".format(cohort, count),
        "detail": {
            "cohort_freeze": {
                "cohort": cohort,
                "counts": {"a": count, "b": count},
                "count": count if state == oss_state.COHORT_MEASURED else None,
                "state": state,
                "why": None,
            }
        },
    }


# ---------------------------------------------------------------------------
# extract_cited_cohort: pure text parsing, no git and no state file involved.
# ---------------------------------------------------------------------------


def test_extract_cited_cohort_reads_the_live_marker_shape():
    cited = cco.extract_cited_cohort(MARKER_TEXT)
    assert cited == {"cohort": "cohort-22", "count": 42}


# ---------------------------------------------------------------------------
# Self-review (#1220): both spawned reviewers found the same real bug --
# comparing timestamps as plain strings breaks the moment the two sides do not
# share an identical format. A `comparison_at` with an explicit UTC offset
# (the natural shape of `git log --format=%cI` or `date +%Y-%m-%dT%H:%M:%S%z`,
# both named as ways to obtain it in this diff's own doc pointers) or a
# `freeze_at` carrying fractional seconds must still compare correctly.
# ---------------------------------------------------------------------------


def test_finding_survives_a_non_utc_offset_on_the_comparison_timestamp():
    """`comparison_at` with an explicit +02:00 offset, naming the same instant
    as a bare UTC time one hour later, must still be read as *before* a freeze
    recorded in UTC an hour after that -- not compared lexically, where the
    '+02:00' string sorts before 'Z' and would falsely read as earlier."""
    entries = [_freeze_entry("cohort-21", at="2026-08-10T12:00:00Z")]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-21", "count": 30},
        entries=entries,
        # 2026-08-10T09:00:00+02:00 == 2026-08-10T07:00:00Z, well before the freeze.
        comparison_at="2026-08-10T09:00:00+02:00",
    )
    assert record["state"] == cco.CITATION_FINDING


def test_fractional_seconds_do_not_flip_a_finding_into_an_ok():
    """'.5Z' sorts lexically *before* the bare-second 'Z' string it is actually
    chronologically after -- a purely lexical comparison reads this backwards."""
    entries = [_freeze_entry("cohort-21", at="2026-08-10T12:00:00.500000Z")]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-21", "count": 30},
        entries=entries,
        comparison_at="2026-08-10T12:00:00Z",
    )
    assert record["state"] == cco.CITATION_FINDING


def test_could_not_check_on_an_unparseable_comparison_timestamp():
    entries = [_freeze_entry("cohort-21", at="2026-08-10T12:00:00Z")]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-21", "count": 30},
        entries=entries,
        comparison_at="not-a-timestamp",
    )
    assert record["state"] == cco.CITATION_COULD_NOT_CHECK


def test_could_not_check_on_a_bare_timestamp_with_no_timezone():
    """A naive timestamp (no `Z`, no offset) is refused rather than silently
    assumed to be UTC -- guessing a timezone is exactly the class of guess
    this module exists to remove."""
    entries = [_freeze_entry("cohort-21", at="2026-08-10T12:00:00Z")]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-21", "count": 30},
        entries=entries,
        comparison_at="2026-08-10T09:00:00",
    )
    assert record["state"] == cco.CITATION_COULD_NOT_CHECK


def test_extract_cited_cohort_on_this_repos_own_claude_md_cross_checked():
    """Strengthens the weak version a reviewer spawn flagged: independently
    derive the cited cohort and count by a different mechanism (plain string
    slicing, not `_MARKER_RE`) and assert the two agree -- this is what would
    actually catch a regex change that picked up the *previous* cohort named
    later in the same sentence instead of the newest one.

    #1264: this repository's own live marker can legitimately be either shape
    -- a real `cohort-N at M` citation, or a stated decline when the release's
    own tooling could not produce a trustworthy number. Cross-check whichever
    shape is actually present rather than assuming the numeric one, and prove
    the two are still told apart (a declined marker must never silently read
    as a numeric citation, and vice versa)."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    cited = cco.extract_cited_cohort(text)
    assert cited is not None

    marker = "Cohort freeze: "
    start = text.index(marker)
    sentence_end = text.index(".", start)
    sentence = text[start + len(marker) : sentence_end]

    if sentence.startswith("cannot be cleanly cited this release"):
        assert cited == {"cohort": None, "count": None, "declined": True}
    else:
        number_str, rest = sentence[len("cohort-") :].split(" at ", 1)
        count_str = rest.split(" ", 1)[0]
        assert cited == {"cohort": "cohort-" + number_str, "count": int(count_str)}


def test_extract_cited_cohort_recognises_the_declined_form():
    """Positive control for the declined shape itself, independent of whatever
    this repository's own live CLAUDE.md happens to say at any given moment."""
    text = (
        "**Cohort freeze: cannot be cleanly cited this release, and that is "
        "stated rather than guessed past.** Some further prose."
    )
    cited = cco.extract_cited_cohort(text)
    assert cited == {"cohort": None, "count": None, "declined": True}


def test_extract_cited_cohort_absent_marker_is_none():
    """Negative control: a section that names neither shape (silently
    forgotten, or garbled past recognising) must still return `None`, not be
    swept up by the new declined pattern's broader net."""
    assert cco.extract_cited_cohort("nothing about cohorts here") is None


def test_extract_cited_cohort_garbled_marker_is_still_none():
    """A near-miss on the decline wording (paraphrased rather than the exact
    stated phrase) must not match either pattern -- the decline form is a
    literal substring on purpose, not a loose paraphrase-tolerant match."""
    text = "Cohort freeze: we are not going to guess a number this time."
    assert cco.extract_cited_cohort(text) is None


# ---------------------------------------------------------------------------
# check_citation_order: the ordering rule itself, against synthetic freeze records.
# This is the red/fix/green core -- reproduce v0.25.0's own mistake shape, and a
# positive control that must pass.
# ---------------------------------------------------------------------------


def test_finding_reproduces_v0_25_0s_own_mistake_shape():
    """The release commit is written, then the tag, then the freeze. Citing the
    cohort that freezes *after* this same commit is exactly what went wrong."""
    entries = [_freeze_entry("cohort-21", at="2026-08-10T12:00:00Z")]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-21", "count": 30},
        entries=entries,
        comparison_at="2026-08-10T09:00:00Z",  # the release commit, written *before* the freeze
    )
    assert record["state"] == cco.CITATION_FINDING
    assert "cohort-21" in record["reason"]


def test_ok_when_the_cited_cohort_already_finished_freezing():
    """Positive control: citing the *previous* cohort, whose freeze is already
    settled well before this citation, must pass."""
    entries = [_freeze_entry("cohort-20", at="2026-07-01T12:00:00Z")]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-20", "count": 18},
        entries=entries,
        comparison_at="2026-08-10T09:00:00Z",
    )
    assert record["state"] == cco.CITATION_OK


def test_could_not_check_when_no_cohort_was_cited():
    record = cco.check_citation_order(
        cited=None, entries=[], comparison_at="2026-08-10T09:00:00Z"
    )
    assert record["state"] == cco.CITATION_COULD_NOT_CHECK


def test_declined_citation_is_its_own_state_not_could_not_check_not_ok():
    """#1264: a marker that explicitly declined to cite a cohort must render
    as its own state -- not folded into `could-not-check` (which already means
    "no record to verify against", a different thing from "nothing to
    verify"), and not `ok` either, since nothing was actually checked."""
    record = cco.check_citation_order(
        cited={"cohort": None, "count": None, "declined": True},
        entries=[],
        comparison_at="2026-08-10T09:00:00Z",
    )
    assert record["state"] == cco.CITATION_DECLINED
    assert record["state"] != cco.CITATION_COULD_NOT_CHECK
    assert record["state"] != cco.CITATION_OK


def test_could_not_check_when_the_cited_cohort_has_no_freeze_record():
    entries = [_freeze_entry("cohort-19", at="2026-06-01T00:00:00Z")]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-20", "count": 18},
        entries=entries,
        comparison_at="2026-08-10T09:00:00Z",
    )
    assert record["state"] == cco.CITATION_COULD_NOT_CHECK
    assert "cohort-20" in record["reason"]


def test_could_not_check_when_the_only_record_for_the_cohort_is_not_measured():
    """An `unknown` or `could-not-count` freeze cannot be trusted as a boundary
    either -- treating it as a clean freeze would let a disagreeing-routes cohort
    silently pass the ordering check."""
    entries = [
        _freeze_entry(
            "cohort-20", at="2026-07-01T00:00:00Z", state=oss_state.COHORT_UNKNOWN
        )
    ]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-20", "count": 18},
        entries=entries,
        comparison_at="2026-08-10T09:00:00Z",
    )
    assert record["state"] == cco.CITATION_COULD_NOT_CHECK


def test_earliest_measured_freeze_wins_when_a_cohort_was_recorded_more_than_once():
    """A cohort can only shrink, so the first `measured` recording is the one that
    actually settled the ordering question -- a later re-count refining the number
    must not push the freeze time later and turn a real `finding` into an `ok`."""
    entries = [
        _freeze_entry("cohort-21", at="2026-08-10T12:00:00Z", count=30),
        _freeze_entry("cohort-21", at="2026-08-15T12:00:00Z", count=32),
    ]
    record = cco.check_citation_order(
        cited={"cohort": "cohort-21", "count": 30},
        entries=entries,
        comparison_at="2026-08-10T09:00:00Z",
    )
    assert record["state"] == cco.CITATION_FINDING


# ---------------------------------------------------------------------------
# check_repo: the live wrapper -- reads CLAUDE.md and a state file, never the clock.
# ---------------------------------------------------------------------------


def test_check_repo_reports_could_not_check_with_no_state_file(tmp_path):
    """This repository's own state file lives under `.max/`, which is git-ignored --
    a fresh checkout (every CI leg included) has none. That must render as
    could-not-check, never as a silent ok."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(MARKER_TEXT, encoding="utf-8")
    missing_state = tmp_path / "does-not-exist.json"
    record = cco.check_repo(
        claude_md_path=claude_md,
        state_path=missing_state,
        at="2026-08-10T09:00:00Z",
    )
    assert record["state"] == cco.CITATION_COULD_NOT_CHECK


def test_check_repo_end_to_end_finding(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(MARKER_TEXT, encoding="utf-8")
    state_path = tmp_path / "watch.json"
    oss_state.append(
        state_path,
        at="2026-09-06T10:00:00Z",
        decision="froze cohort-22 at 42",
        detail={
            "cohort_freeze": {
                "cohort": "cohort-22",
                "counts": {"a": 42, "b": 42},
                "count": 42,
                "state": oss_state.COHORT_MEASURED,
                "why": None,
            }
        },
    )
    record = cco.check_repo(
        claude_md_path=claude_md,
        state_path=state_path,
        at="2026-09-06T08:00:00Z",  # the release commit, written before that freeze
    )
    assert record["state"] == cco.CITATION_FINDING


def test_check_repo_end_to_end_ok(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(MARKER_TEXT, encoding="utf-8")
    state_path = tmp_path / "watch.json"
    oss_state.append(
        state_path,
        at="2026-08-06T10:00:00Z",
        decision="froze cohort-22 at 42",
        detail={
            "cohort_freeze": {
                "cohort": "cohort-22",
                "counts": {"a": 42, "b": 42},
                "count": 42,
                "state": oss_state.COHORT_MEASURED,
                "why": None,
            }
        },
    )
    record = cco.check_repo(
        claude_md_path=claude_md,
        state_path=state_path,
        at="2026-09-06T08:00:00Z",  # well after the recorded freeze
    )
    assert record["state"] == cco.CITATION_OK


def test_check_repo_end_to_end_declined(tmp_path):
    """#1264: a declined marker with no state file at all -- the ordinary case
    for a fresh checkout -- still reports `declined`, not `could-not-check`."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "**Cohort freeze: cannot be cleanly cited this release, and that is "
        "stated rather than guessed past.** More prose follows.",
        encoding="utf-8",
    )
    missing_state = tmp_path / "does-not-exist.json"
    record = cco.check_repo(
        claude_md_path=claude_md,
        state_path=missing_state,
        at="2026-09-06T08:00:00Z",
    )
    assert record["state"] == cco.CITATION_DECLINED


def test_this_repos_own_current_state_is_could_not_check_or_declined():
    """The real integration point: run against this repo's own tree, with the real
    (absent) `.max/claude-oss-watch.json`. Proves the honest third (or fourth)
    state renders on the exact tree CI actually checks out, rather than being
    only a fixture claim.

    #1264: this repository's own live marker is not always the same shape --
    a real `cohort-N at M` citation renders `could-not-check` here (no state
    file exists to verify it against), while a stated decline renders
    `declined` regardless of the state file, since a decline has nothing to
    verify in the first place. Either is honest; a silent `ok` never is."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    cited = cco.extract_cited_cohort(text)
    expected = (
        cco.CITATION_DECLINED
        if isinstance(cited, dict) and cited.get("declined")
        else cco.CITATION_COULD_NOT_CHECK
    )
    record = cco.check_repo(
        claude_md_path=REPO_ROOT / "CLAUDE.md",
        state_path=REPO_ROOT / ".max" / "claude-oss-watch.json",
        at="2026-09-07T00:00:00Z",
    )
    assert record["state"] == expected
    assert record["state"] != cco.CITATION_OK
