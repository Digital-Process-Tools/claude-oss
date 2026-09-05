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
51-file drive-by. So the count is frozen at BASELINE below and this gate
only fails when it goes UP -- a new violation lands, or an existing one is
touched and made worse -- never when it stays flat. It is expected to shrink
over time as follow-up issues clean up individual files; lower BASELINE by
hand in the same PR that does the cleanup, so the improvement is locked in
rather than silently available to regress back into.

**Three states, not two** (CLAUDE.md's own defect class: an absence produced
by the tool must never render like an absence in the world). `ruff` missing
or crashing is `could-not-run` (exit 2), never a quiet pass -- a CI runner
that lost its `ruff` install must not report a clean lint on a tree nobody
actually checked.

No `--select` is passed here, deliberately, matching validators/ruff/ruff.py
(shipped with supertool) and pyproject.toml's own comment: the ruleset lives
in [tool.ruff.lint], not hardcoded into two places that could drift apart.

Usage: ruff_ratchet.py [--root DIR] [--baseline N]
Exit codes: 0 ok (at or under baseline), 1 over baseline, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

# Measured at #635 -- see the module docstring for what this number is and
# is not. Do not raise it to make a regression go away; lower it whenever a
# real fix reduces the count.
BASELINE = 95


def _count(root: Path) -> Tuple[Optional[int], str]:
    """(count, detail). count is None when ruff could not be run at all."""
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
            cwd=str(root), capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "ruff could not be run: %s" % (exc,)
    # ruff check: 0 clean, 1 findings, 2 ruff itself failed (bad config,
    # unreadable path, unknown rule) -- that third one is a fault, not a
    # verdict about the tree, so it is not a count either.
    if proc.returncode not in (0, 1):
        return None, "ruff exited %d: %s" % (
            proc.returncode, proc.stderr or proc.stdout)
    try:
        items = json.loads(proc.stdout or "[]")
    except ValueError:
        return None, "ruff produced unparseable output: %r" % (proc.stdout,)
    if not isinstance(items, list):
        return None, "expected a JSON array from ruff, got %s" % (
            type(items).__name__,)
    return len(items), proc.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument("--baseline", default=BASELINE, type=int)
    args = parser.parse_args(argv)

    count, detail = _count(args.root)
    if count is None:
        print("COULD NOT RUN: %s" % (detail,))
        return 2
    if count > args.baseline:
        print(
            "FAIL: ruff reports %d findings under the #635 ruleset, the "
            "ratchet baseline is %d (%d over). Fix the new finding(s), or "
            "if the increase is genuinely deliberate, say why in the PR and "
            "raise BASELINE in scripts/ruff_ratchet.py in the same commit."
            % (count, args.baseline, count - args.baseline)
        )
        return 1
    if count < args.baseline:
        print(
            "OK: ruff reports %d findings, %d under the %d ratchet "
            "baseline. Consider lowering BASELINE in "
            "scripts/ruff_ratchet.py to lock the improvement in."
            % (count, args.baseline - count, args.baseline)
        )
        return 0
    print("OK: ruff reports %d findings, at the ratchet baseline." % (count,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
