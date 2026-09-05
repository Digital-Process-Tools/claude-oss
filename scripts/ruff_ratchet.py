#!/usr/bin/env python3
"""Ratchet gate over the narrow ruff ruleset adopted in #635.

This is the CI-leg half of #635's two-part answer (see .supertool.json for
the write-time half): a check over the whole tree, run once per push/PR,
that cannot be skipped the way a per-file write-time validator can.

**Why a ratchet and not "fix the selected classes first".** Measured at #635
against this repo's own [tool.ruff.lint] selection (F401, F841, E722, B006,
A001; see pyproject.toml for why those five and why not ruff's defaults):
95 findings across 51 files, none of them inside #635's own claimed files
(pyproject.toml, .github/workflows/tests.yml, .supertool.json,
changelog.d/635.*.md). Fixing 51 unrelated files in one issue's lane would
have blown past that lane's own scope and turned a lint-adoption PR into a
51-file drive-by. It is expected to shrink over time as follow-up issues
clean up individual files; regenerate `ruff_ratchet_baseline.txt` (with
`--write-baseline`) in the same PR that does the cleanup, so the improvement
is locked in rather than silently available to regress back into.

**#1061: a bare count is not a ratchet against composition, only against
size.** The original gate compared `len(findings) > BASELINE` -- a single
integer, 99, frozen in this module. A pull request that fixes one
pre-existing finding while introducing a different, unrelated one leaves the
count unchanged (99 stays 99) and the leg stays green, which is exactly the
case a ratchet exists to catch. The fix is a set diff, not a bigger count:
`ruff_ratchet_baseline.txt` (sibling of this file) is a checked-in snapshot
of every finding ruff reports on this tree today, one per line, each line a
fingerprint -- relative path, rule code, and ruff's own message text, tab
separated. A run's own findings are fingerprinted the same way and compared
against that snapshot as multisets (a `collections.Counter`, not a bare
`set`): a fingerprint absent from the baseline, or present but appearing
*more* times than the baseline shows, is new and fails the gate -- even when
the total count is identical to before, because a fix and a regression
elsewhere cancelled each other out in the sum. Fixing something no longer
requires anyone to lower a number by hand; it happens automatically, because
that fingerprint simply stops showing up. Only a genuinely new fingerprint
(or an increased count of an existing one) needs `--write-baseline` at all,
and only when the increase is a deliberate, argued exception -- not to
launder a regression, the same rule the old BASELINE comment stated for
raising that integer.

**Message text, not line number, is the granularity, and that is a
measured choice, not the only one available.** A location-anchored
fingerprint (file + code + line) would treat an unrelated edit earlier in
the same file -- one that merely shifts every following line down -- as a
whole new set of findings, which is exactly the kind of tool-produced
absence-that-looks-like-presence this repository's whole `CLAUDE.md` is
about, one direction over. ruff's own `message` field usually names the
concrete symbol involved (`` `pathlib.Path` imported but unused ``), so two
distinct violations of the same rule in the same file are still two distinct
fingerprints in the ordinary case; a `Counter` rather than a bare `set`
covers the residual case of two genuinely identical messages in the same
file (measured on this tree at the time this was written: zero such
collisions across all 99 baseline entries, so this is a safety margin, not
something observed to matter yet).

**Three states, not two** (CLAUDE.md's own defect class: an absence produced
by the tool must never render like an absence in the world). `ruff` missing
or crashing, or the baseline file itself unreadable, is `could-not-run`
(exit 2), never a quiet pass -- a CI runner that lost its `ruff` install, or
whose checkout dropped the baseline file, must not report a clean lint on a
tree nobody actually checked.

No `--select` is passed here, deliberately, matching validators/ruff/ruff.py
(shipped with supertool) and pyproject.toml's own comment: the ruleset lives
in [tool.ruff.lint], not hardcoded into two places that could drift apart.

Usage:
  ruff_ratchet.py [--root DIR] [--baseline-file PATH]
  ruff_ratchet.py --write-baseline [--root DIR] [--baseline-file PATH]
Exit codes: 0 ok (no new/increased finding), 1 new/increased finding(s)
present, 2 could not run (ruff missing or broken, or the baseline file
could not be read).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Sibling of this file, tracked in git -- the checked-in snapshot #1061
#: replaces the bare `BASELINE` integer with. See the module docstring for
#: the format and why it is message-keyed rather than line-keyed.
DEFAULT_BASELINE_FILE = Path(__file__).resolve().parent / "ruff_ratchet_baseline.txt"

#: One line of the baseline file: three tab-separated fields, no field
#: containing a literal tab -- ruff never emits one in a `code` or a
#: `filename`, and an embedded tab in a `message` would need escaping this
#: format does not attempt, on the same "measured, not proven" footing the
#: module docstring already states for message-collision risk generally.
_SEP = "\t"


def _run_ruff(root: Path) -> Tuple[Optional[List[dict]], str]:
    """(items, detail). items is None when ruff could not be run at all or
    its output could not be parsed as a JSON array."""
    if not shutil.which("ruff"):
        return None, "ruff not found on PATH -- pip install ruff"
    try:
        # encoding + errors="replace", explicit rather than bare text=True: ruff always
        # writes UTF-8 JSON, but bare text=True decodes with
        # locale.getpreferredencoding(False) -- typically a Windows codepage such as
        # cp1252 -- which has undefined byte values that can appear as UTF-8
        # continuation bytes. A UnicodeDecodeError there is not an OSError or a
        # SubprocessError, so it would not be caught below: it would propagate as an
        # unhandled traceback exiting 1, the same exit code this script uses for a real
        # "FAIL: over baseline", misreporting an encoding crash as a lint regression.
        # validators/ruff/ruff.py, shipped with supertool, already passes both flags on
        # the identical subprocess.run call; this is the same fix at the second call
        # site.
        proc = subprocess.run(
            ["ruff", "check", "--output-format", "json", "--no-cache", "--", "."],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "ruff could not be run: %s" % (exc,)
    # ruff check: 0 clean, 1 findings, 2 ruff itself failed (bad config,
    # unreadable path, unknown rule) -- that third one is a fault, not a
    # verdict about the tree, so it is not a count either.
    if proc.returncode not in (0, 1):
        return None, "ruff exited %d: %s" % (
            proc.returncode,
            proc.stderr or proc.stdout,
        )
    try:
        items = json.loads(proc.stdout or "[]")
    except ValueError:
        return None, "ruff produced unparseable output: %r" % (proc.stdout,)
    if not isinstance(items, list):
        return None, "expected a JSON array from ruff, got %s" % (type(items).__name__,)
    return items, proc.stdout


def _fingerprint(item: dict, root: Path) -> Optional[str]:
    """One baseline-file line for one ruff finding, or `None` when the item
    is missing a field this needs -- a malformed item is dropped from the
    fingerprinted set rather than raising, so a future ruff release adding
    fields does not crash this gate; it can only make that one finding
    silently unfingerprinted, which the caller counts and reports rather
    than swallows.
    """
    try:
        filename = item["filename"]
        code = item["code"]
        message = item["message"]
    except (KeyError, TypeError):
        return None
    try:
        rel = Path(filename).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        rel = str(filename)
    if code is None:
        code = ""
    if _SEP in rel or _SEP in code or _SEP in message:
        # Not observed from ruff in practice -- see the module docstring's
        # "measured, not proven" note -- but a literal tab in any field
        # would silently misalign the three columns on read-back, which is
        # worse than refusing to fingerprint the one finding that has it.
        return None
    return _SEP.join((rel, code, message))


def _fingerprint_counts(items: List[dict], root: Path) -> Tuple[Counter, int]:
    """(counts, dropped). `dropped` is how many items could not be
    fingerprinted at all -- reported by the caller rather than silently
    shrinking the set that gets compared."""
    counts: Counter = Counter()
    dropped = 0
    for item in items:
        fp = _fingerprint(item, root)
        if fp is None:
            dropped += 1
            continue
        counts[fp] += 1
    return counts, dropped


def _load_baseline(path: Path) -> Tuple[Optional[Counter], str]:
    """(counts, detail). counts is None when the baseline file does not
    exist, cannot be read, or contains a line that is not exactly three
    tab-separated fields -- a malformed snapshot must never be read as an
    empty one, which would fail every real finding as \"new\"."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "no baseline file at %s -- run with --write-baseline first" % (
            path,
        )
    except OSError as exc:
        return None, "%s could not be read: %s" % (path, exc)
    counts: Counter = Counter()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        fields = line.split(_SEP)
        if len(fields) != 3:
            return None, "%s:%d: expected 3 tab-separated fields, found %d" % (
                path,
                lineno,
                len(fields),
            )
        counts[line] += 1
    return counts, ""


def _write_baseline(path: Path, counts: Counter) -> int:
    """Writes one line per occurrence, sorted -- a diff-friendly text file a
    maintainer can open directly, per #1061's own brief: a plain list of
    (path, code, message) triples, one finding per line, is readable without
    tooling and diffs one line per finding gained or lost rather than one
    opaque integer. Returns the number of lines written."""
    lines: List[str] = []
    for fingerprint, count in counts.items():
        lines.extend([fingerprint] * count)
    lines.sort()
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return len(lines)


def _new_or_increased(current: Counter, baseline: Counter) -> Dict[str, int]:
    """{fingerprint: how many more than the baseline} for every fingerprint
    whose count in `current` exceeds its count in `baseline` (0 if absent) --
    the set-diff #1061 asks for, expressed as a multiset comparison so an
    increased count of an already-known finding is caught too, not only a
    brand new fingerprint."""
    over: Dict[str, int] = {}
    for fingerprint, count in current.items():
        delta = count - baseline.get(fingerprint, 0)
        if delta > 0:
            over[fingerprint] = delta
    return over


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument("--baseline-file", default=None, type=Path)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="regenerate the baseline file from the current tree and exit 0",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    baseline_file = (
        args.baseline_file if args.baseline_file is not None else DEFAULT_BASELINE_FILE
    )

    items, detail = _run_ruff(root)
    if items is None:
        print("COULD NOT RUN: %s" % (detail,))
        return 2
    current, dropped = _fingerprint_counts(items, root)

    if args.write_baseline:
        written = _write_baseline(baseline_file, current)
        extra = (
            ""
            if not dropped
            else " (%d finding(s) could not be fingerprinted and were dropped)"
            % (dropped,)
        )
        print("WROTE: %d finding(s) to %s%s" % (written, baseline_file, extra))
        return 0

    baseline, baseline_detail = _load_baseline(baseline_file)
    if baseline is None:
        print("COULD NOT RUN: %s" % (baseline_detail,))
        return 2

    over = _new_or_increased(current, baseline)
    if over:
        total_new = sum(over.values())
        print(
            "FAIL: %d new/increased finding(s) not in the baseline snapshot "
            "(%s):" % (total_new, baseline_file)
        )
        for fingerprint in sorted(over):
            path, code, message = fingerprint.split(_SEP, 2)
            times = over[fingerprint]
            print(
                "  %s [%s] %s%s"
                % (path, code, message, "" if times == 1 else " (x%d)" % times)
            )
        print(
            "Fix the new finding(s), or if the increase is genuinely "
            "deliberate, say why in the PR and run --write-baseline to "
            "record it in the same commit."
        )
        return 1

    dropped_note = (
        ""
        if not dropped
        else " (%d finding(s) could not be fingerprinted)" % (dropped,)
    )
    fewer = sum(baseline.values()) - sum(current.values())
    if fewer > 0:
        print(
            "OK: %d finding(s), %d fewer than the %d in the baseline "
            "snapshot%s. Consider running --write-baseline to lock the "
            "improvement in."
            % (sum(current.values()), fewer, sum(baseline.values()), dropped_note)
        )
    else:
        print(
            "OK: %d finding(s), none new against the baseline snapshot%s."
            % (sum(current.values()), dropped_note)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
