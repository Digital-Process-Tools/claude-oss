#!/usr/bin/env python3
"""Check that a release's cohort citation names an already-frozen cohort -- #1220.

#1122 (PR #1218) rewrote the "What is not proven yet" marker's rule so it only ever
cites a cohort that has already finished freezing -- the previous release's, settled --
never the release-being-cut's own not-yet-frozen one. That closed one live mismatch
(v0.25.0's marker cited cohort-21 at 30; the count actually applied when the freeze ran,
on the far side of the tag, was 32) but left the ordering rule itself as release-process
prose in `skills/manager/phases/accounting.md` and `commands/release.md` -- read and
followed by a release session, not verified by a test. A future release commit that
repeats the mistake would pass every test in the suite today.

Two shapes were on the table for the mechanical check (the issue names both): diff two
release commits' cited cohort numbers against their own tagger dates, or check a cited
cohort against the two-route `cohort_freeze` decision `oss_state.py` already records
(``detail.cohort_freeze``). This module builds the second. The first needs full git
history across release tags; this repository's own CI checkout is `actions/checkout`'s
default depth of 1 (`test_claude_md_currency.py` notes the same constraint for a
different check), so a tag-walking design could not run on the leg that matters most,
and would need a shallow-clone third state layered on top of the ones below anyway. The
state file route needs no git history at all: it reads the current worktree's own
CLAUDE.md and the state file the loop already keeps, and the state file *is* the actual
source of truth for "when did this cohort finish freezing" -- `cohort_freeze.py` derives
the count from a tag's own tagger date, but only the state entry keeps that fact, git
does not.

The cost this pays for that cheapness: `.max/` (the state file's own directory) is
git-ignored, so a freshly-cloned tree -- every CI leg included -- carries no state file
at all, and this check can only ever report `could-not-check` there. That is disclosed,
not hidden: see `check_repo`'s own third state below and the test proving it against
this repo's real, absent state file. This is a tool a release session runs from its own
working tree, where a state file that has actually been written this cycle exists to be
read, not a repo-wide pytest gate that fires on every checkout.

Four states, same discipline as `cohort_freeze` and `push_bypass`:

  ok               the cited cohort's recorded freeze (``detail.cohort_freeze``, state
                    ``measured``) happened strictly before the citation's own timestamp.
  finding          the cited cohort's recorded freeze happened at or after the
                    citation's own timestamp -- v0.25.0's own mistake, mechanically
                    caught.
  declined         the marker explicitly declined to cite a specific cohort-N-at-M
                    figure this release, using the stated decline phrase below, instead
                    of guessing between two counts its own tooling had just shown to
                    disagree (#1264). Nothing was verified, but nothing was forgotten
                    either -- a stated decline is not a finding (there is no false
                    citation to catch) and not a clean `ok` (no ordering was actually
                    checked), so it gets its own state rather than being folded into
                    either.
  could-not-check  no cohort was found in the marker at all (neither a numeric citation
                    nor a stated decline -- the marker was silently forgotten or
                    garbled), no freeze record exists for a cited cohort, or the only
                    recorded freeze for it is not `measured` (`unknown` or
                    `could-not-count` cannot be trusted as a boundary either). Never
                    rendered the same as `ok` -- an absent check is not a clean one --
                    and never the same as `declined`, which is stated on purpose rather
                    than missing.

Timestamps are arguments, never read from the clock in here, the same discipline
`oss_state.py` states for itself: a function that reads the clock cannot be tested for
what it decided, and a release gate built on this module is evidence.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import oss_state  # noqa: E402

CITATION_OK = "ok"
CITATION_FINDING = "finding"
CITATION_DECLINED = "declined"
CITATION_COULD_NOT_CHECK = "could-not-check"

EXIT_OK = 0
EXIT_FINDING = 1
EXIT_COULD_NOT_CHECK = 3
# Not 2 -- argparse.ArgumentParser.error() always exits 2, and every sibling
# state script in this family (`select_issues_preflight.py`,
# `gate3_disposition.py`, `transcript_refusals.py`) reserves that number for
# a usage error only, or skips it entirely. A `declined` verdict is a real,
# substantive answer, not a usage mistake, so it must not share 2 with one
# (#1267) -- a caller branching on exit code alone could not otherwise tell
# an honest decline from a bad invocation.
EXIT_DECLINED = 4

# The live marker's own shape (CLAUDE.md, "What is not proven yet"):
#   **Cohort freeze: cohort-22 at 42 open issues, against cohort-21's 29.**
# Only the newest-cited cohort (the one under question) is extracted -- the
# previous cohort named later in the same sentence is prose recording where the
# comparison came from, not a citation this check judges.
_MARKER_RE = re.compile(r"Cohort freeze:\s*cohort-(\d+)\s+at\s+(\d+)")

# The marker's own greppable way to say "I looked, and I am not going to guess"
# (#1264): a release whose own tooling produced two disagreeing counts for the
# only citable cohort should say so rather than pick one. This is a literal
# substring match on purpose, not a loose "cannot ... cited" pattern -- a marker
# that wants this state has to use these exact words, the same way a real
# citation has to match `_MARKER_RE`'s exact shape.
_DECLINE_TEXT = "Cohort freeze: cannot be cleanly cited this release"


# The section a real release marker lives in (`CLAUDE.md`'s own heading,
# see the module docstring). #1269: this repository's own prose narrates
# *past* releases' cohort counts routinely, in whole-file-searchable text
# well before this heading -- so the search is scoped to this section, not
# the whole file, and a stale historical citation elsewhere can never be
# matched at all. Text with no such heading (a synthetic fixture, or a repo
# whose CLAUDE.md predates the section) falls back to a whole-text search
# rather than finding nothing.
_MARKER_SECTION_HEADING = "## What is not proven yet"


def _marker_section(text):
    """The text of the current marker's own section, or ``text`` unchanged
    if the heading is not present at all (#1269's fallback case)."""
    start = text.find(_MARKER_SECTION_HEADING)
    if start == -1:
        return text
    return text[start:]


def extract_cited_cohort(text):
    """The newest cohort the *current* marker cites.

    Searches only inside the "## What is not proven yet" section (#1269) --
    never the whole file -- so a stale numeric citation this repository's own
    prose narrates about a past release cannot be matched ahead of, or
    instead of, the current marker's own citation or decline.

    Three distinguishable returns:

    * ``{"cohort": "cohort-N", "count": M}`` -- a real numeric citation.
    * ``{"cohort": None, "count": None, "declined": True}`` -- the marker used
      the stated decline phrase instead of naming a cohort. Distinguishable from
      both a real citation (no ``"declined"`` key there) and from ``None`` by
      identity and by shape, so a caller cannot mistake either for the other.
    * ``None`` -- the marker's own sentence is not present at all, in either
      shape. A caller must treat this as "nothing to check", never as a clean
      pass and never as a stated decline.
    """
    section = _marker_section(text or "")
    match = _MARKER_RE.search(section)
    if match:
        number, count = match.groups()
        return {"cohort": "cohort-{}".format(number), "count": int(count)}
    if _DECLINE_TEXT in section:
        return {"cohort": None, "count": None, "declined": True}
    return None


def _measured_freeze_ats(entries, cohort):
    """Every ``at`` timestamp at which ``cohort`` was recorded as `measured`.

    A cohort can only shrink (#407), so more than one `measured` recording for the
    same cohort is a later re-count refining the number, not a second freeze -- the
    *earliest* one is when the ordering question actually settled, and using a later
    one would let a re-count silently move a real `finding` into an `ok`.
    """
    ats = []
    for entry in entries or []:
        detail = entry.get("detail") if isinstance(entry, dict) else None
        freeze = detail.get("cohort_freeze") if isinstance(detail, dict) else None
        if not isinstance(freeze, dict):
            continue
        if freeze.get("cohort") != cohort:
            continue
        if freeze.get("state") != oss_state.COHORT_MEASURED:
            continue
        at = entry.get("at")
        if isinstance(at, str) and at.strip():
            ats.append(at)
    return sorted(ats)


def _parse_timestamp(value):
    """An ISO 8601 timestamp as a tz-aware UTC ``datetime``, or ``None``.

    Self-review (#1220) found two spawned reviewers converging on the same real
    bug: an earlier version of this function compared timestamps as plain
    strings, on the assumption that every one of them shares an identical
    `Z`-suffixed, fraction-free format. Neither half of that assumption holds --
    a `comparison_at` obtained via ``git log --format=%cI`` or ``date
    +%Y-%m-%dT%H:%M:%S%z`` (both named in this diff's own doc pointers) carries
    an explicit ``+HH:MM`` offset rather than `Z`, and a state-file `at` with
    fractional seconds sorts *before* a bare-second one lexically while being
    chronologically *after* it -- both silently flip a real `finding` into a
    false `ok`. So this parses rather than compares strings, and refuses a
    naive (timezone-less) timestamp outright rather than guessing it means UTC:
    guessing a timezone is exactly the class of guess this whole module exists
    to remove.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_dt.timezone.utc)


def check_citation_order(cited, entries, comparison_at):
    """The ordering rule itself, against a list of state-file entries.

    ``cited`` is ``extract_cited_cohort``'s return (or ``None``). ``entries`` is the
    state file's own list shape (``oss_state.read``'s return -- oldest first,
    ``{"at", "decision", "detail"}``). ``comparison_at`` is the citing commit's own
    timestamp, an ISO 8601 string, given by the caller rather than read from the
    clock here. Both this value and every recorded freeze ``at`` are parsed with
    ``_parse_timestamp`` and compared as real instants -- never as strings -- so a
    difference in offset or fractional-second precision between the two sides
    (they come from different sources and are never guaranteed to match byte for
    byte) cannot flip the verdict.

    #1268: ``comparison_at`` is validated on *every* path, declined included,
    before any branch on ``cited`` runs. `--at` is a required argument on
    every invocation of this module, not a value some callers happen to pass
    and others don't -- so a caller that hands this function a malformed
    timestamp has made a real invocation mistake regardless of which shape
    the marker turns out to be, and a declined marker (which never uses the
    timestamp for a comparison) is not a reason to skip telling them. The
    earlier version validated ``comparison_at`` only on the path that goes
    on to actually compare it, so a declined marker paired with a garbled
    `--at` silently reported `declined` with the bad input never even read.
    """
    if not comparison_at or not str(comparison_at).strip():
        return {
            "state": CITATION_COULD_NOT_CHECK,
            "cohort": cited.get("cohort") if isinstance(cited, dict) else None,
            "reason": "no comparison timestamp was given",
        }
    comparison_dt = _parse_timestamp(comparison_at)
    if comparison_dt is None:
        return {
            "state": CITATION_COULD_NOT_CHECK,
            "cohort": cited.get("cohort") if isinstance(cited, dict) else None,
            "reason": (
                "the comparison timestamp {!r} could not be parsed as a "
                "timezone-aware ISO 8601 timestamp -- a bare value with no `Z` "
                "suffix and no explicit UTC offset is refused rather than "
                "assumed to be UTC".format(comparison_at)
            ),
        }
    if isinstance(cited, dict) and cited.get("declined"):
        return {
            "state": CITATION_DECLINED,
            "cohort": None,
            "reason": (
                "the marker explicitly declined to cite a specific cohort this "
                "release, using its stated decline phrase, rather than guess "
                "between two disagreeing counts -- nothing was verified, but "
                "nothing was forgotten either"
            ),
        }
    if not cited:
        return {
            "state": CITATION_COULD_NOT_CHECK,
            "cohort": None,
            "reason": ("no cohort citation found in the marker -- nothing to check"),
        }
    cohort = cited["cohort"]
    freeze_ats = _measured_freeze_ats(entries, cohort)
    if not freeze_ats:
        return {
            "state": CITATION_COULD_NOT_CHECK,
            "cohort": cohort,
            "reason": (
                "no `measured` freeze record exists for {} in the given state-file "
                "entries -- an unmeasured or absent freeze cannot be trusted as a "
                "boundary, so this citation cannot be verified either way".format(
                    cohort
                )
            ),
        }
    parsed_freezes = []
    unparseable = []
    for raw in freeze_ats:
        freeze_dt = _parse_timestamp(raw)
        if freeze_dt is None:
            unparseable.append(raw)
        else:
            parsed_freezes.append((freeze_dt, raw))
    if not parsed_freezes:
        return {
            "state": CITATION_COULD_NOT_CHECK,
            "cohort": cohort,
            "reason": (
                "every recorded freeze timestamp for {} failed to parse as a "
                "timezone-aware ISO 8601 timestamp ({}) -- cannot verify "
                "ordering".format(cohort, ", ".join(unparseable))
            ),
        }
    parsed_freezes.sort(key=lambda pair: pair[0])
    freeze_dt, freeze_at = parsed_freezes[0]
    if freeze_dt < comparison_dt:
        return {"state": CITATION_OK, "cohort": cohort, "reason": None}
    return {
        "state": CITATION_FINDING,
        "cohort": cohort,
        "reason": (
            "cites {} whose recorded freeze ({}) had not yet run when this "
            "citation was written ({}) -- the same shape as v0.25.0's own "
            "marker, guessing a cohort's count ahead of its own freeze".format(
                cohort, freeze_at, comparison_at
            )
        ),
    }


def check_repo(claude_md_path, state_path, at):
    """The live wrapper: read CLAUDE.md and a state file, then apply the rule.

    ``at`` is the citing commit's own timestamp -- an ISO 8601 string the caller
    supplies (the release commit's own timestamp, or "now" for a pre-commit gate).
    Never read from the clock here, for the same reason `oss_state.py` never reads
    it: a function that reads the clock cannot be tested for what it decided.
    """
    claude_md_path = Path(claude_md_path)
    if not claude_md_path.is_file():
        return {
            "state": CITATION_COULD_NOT_CHECK,
            "cohort": None,
            "reason": "{} does not exist".format(claude_md_path),
        }
    text = claude_md_path.read_text(encoding="utf-8", errors="replace")
    cited = extract_cited_cohort(text)

    # A declined citation has nothing to verify against a state file at all
    # (#1264) -- checked before the state file is even opened, so a state
    # file that happens to be corrupt or unreadable can never downgrade an
    # honest, self-contained decline into `could-not-check`. The declined
    # branch inside `check_citation_order` would reach the same answer, but
    # only once past a state-file read this case does not need to survive.
    if isinstance(cited, dict) and cited.get("declined"):
        return check_citation_order(cited, entries=[], comparison_at=at)

    try:
        entries = oss_state.read(state_path)
    except oss_state.StateError as exc:
        return {
            "state": CITATION_COULD_NOT_CHECK,
            "cohort": cited["cohort"] if cited else None,
            "reason": "state file at {} is unreadable: {}".format(state_path, exc),
        }

    return check_citation_order(cited, entries, at)


def citation_order_line(record):
    """One line a release report can print. The state decides the sentence."""
    state = record.get("state")
    cohort = record.get("cohort") or "an unstated cohort"
    if state == CITATION_OK:
        return "cohort citation order: ok -- {} was already frozen".format(cohort)
    if state == CITATION_FINDING:
        return "cohort citation order: FINDING -- {}".format(record.get("reason"))
    if state == CITATION_DECLINED:
        return "cohort citation order: declined -- {}".format(
            record.get("reason") or "no reason recorded"
        )
    if state == CITATION_COULD_NOT_CHECK:
        return "cohort citation order: could-not-check -- {}".format(
            record.get("reason") or "no reason recorded"
        )
    return "cohort citation order: unrecognised state {!r}, nothing claimed".format(
        state
    )


_EXIT_CODES = {
    CITATION_OK: EXIT_OK,
    CITATION_FINDING: EXIT_FINDING,
    CITATION_DECLINED: EXIT_DECLINED,
    CITATION_COULD_NOT_CHECK: EXIT_COULD_NOT_CHECK,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Check that CLAUDE.md's cohort-freeze marker cites only an "
            "already-frozen cohort, against the state file's own cohort_freeze "
            "decisions (#1220)."
        )
    )
    parser.add_argument(
        "--claude-md",
        default=str(Path(__file__).resolve().parent.parent / "CLAUDE.md"),
        help="path to CLAUDE.md (default: this repo's own)",
    )
    parser.add_argument(
        "--state",
        required=True,
        help="path to the tick state file (.oss.local.json's state_file)",
    )
    parser.add_argument(
        "--at",
        required=True,
        help="the citing commit's own ISO 8601 timestamp",
    )
    args = parser.parse_args(argv)

    record = check_repo(args.claude_md, args.state, args.at)
    print(citation_order_line(record))
    return _EXIT_CODES.get(record["state"], EXIT_COULD_NOT_CHECK)


if __name__ == "__main__":
    sys.exit(main())
