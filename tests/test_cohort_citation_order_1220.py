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

Three states, same discipline as `cohort_freeze` and `push_bypass` above it:

  ok               the cited cohort's recorded freeze (`detail.cohort_freeze`, state
                    "measured") happened strictly before the citation's own timestamp.
  finding          the cited cohort's recorded freeze happened at or after the citation's own
                    timestamp -- exactly v0.25.0's own mistake shape, mechanically caught.
  could-not-check  no cohort was found in the marker, no freeze record exists for the cited
                    cohort, or the recorded freeze itself is not `measured` (`unknown` or
                    `could-not-count`, which cannot be trusted as a boundary either). This is
                    the ordinary case for this repository's own tree today: `.max/` is
                    git-ignored, so a fresh checkout (CI included) carries no state file at
                    all, and this must never render as `ok` -- an absent check is not a clean
                    one.
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


def test_extract_cited_cohort_on_this_repos_own_claude_md():
    """The real file, not a fixture -- proves the regex matches production prose."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    cited = cco.extract_cited_cohort(text)
    assert cited is not None
    assert cited["cohort"].startswith("cohort-")
    assert isinstance(cited["count"], int)


def test_extract_cited_cohort_absent_marker_is_none():
    assert cco.extract_cited_cohort("nothing about cohorts here") is None


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


def test_this_repos_own_current_state_is_could_not_check():
    """The real integration point: run against this repo's own tree, with the real
    (absent) `.max/claude-oss-watch.json`. Proves the third state renders honestly on
    the exact tree CI actually checks out, rather than being only a fixture claim."""
    record = cco.check_repo(
        claude_md_path=REPO_ROOT / "CLAUDE.md",
        state_path=REPO_ROOT / ".max" / "claude-oss-watch.json",
        at="2026-09-07T00:00:00Z",
    )
    assert record["state"] == cco.CITATION_COULD_NOT_CHECK
