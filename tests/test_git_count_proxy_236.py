"""Guard against #236: a piped `git log` count is corrupted through the maintainer's

rtk proxy -- `printf '' | wc -l` is 0, but the same empty range through the proxy
prints a single trailing newline, so `rtk git log <range> --oneline | wc -l` reads
an empty range as 1. Zero is the load-bearing value here: nothing merged since the
tag, reach did not move, no fragments pending -- every one of those reads as one
under the broken proxy.

The fix this repo adopted is typed, not stylistic: never derive a commit count or a
commit identity by parsing piped `git log` text. `git rev-list --count <range>` and
`git rev-parse` answer the same questions with one value computed by git, with no
row rendering -- and no proxy -- in between.

This is a content test, over the governing prose and the scripts that actually
compute a release delta. It fails loudly when the anti-pattern regex matches
nothing at all, because a pattern that cannot fire has not checked anything --
that is the positive control below.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from manager_docs import ManagerLoop  # noqa: E402

#: The manager loop's whole prose -- SKILL.md plus every phase file it defers
#: to. This check asks "does the loop say X", never "does one file say X".
MANAGER_LOOP = ManagerLoop(REPO_ROOT)

# A shell pipe from `git log` into `wc -l` (or `wc -c`) used to count rows/bytes --
# the exact shape that reads a bare trailing newline as one row. Requires a literal
# pipe character, so prose that merely *describes* the trap in words, without a
# runnable piped snippet, does not trip it.
ANTI_PATTERN = re.compile(r"git log\b[^\n`]*\|\s*wc\s+-[lc]\b")

# Narrative history is allowed to quote the broken form when describing a past fix
# -- CHANGELOG.md and the changelog fragments that fold into it are append-only
# records, not instructions the loop re-reads and re-runs. This test's own file is
# excluded because its positive control below constructs the offending string on
# purpose.
NARRATIVE_EXCLUDES = {"CHANGELOG.md"}


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line.strip()]


def _governing_files():
    """The prose and scripts the loop actually reads and runs, not its own history."""
    files = []
    for path in _tracked_files():
        rel = path.relative_to(REPO_ROOT)
        parts = rel.parts
        if str(rel) in NARRATIVE_EXCLUDES:
            continue
        if parts[0] == "changelog.d":
            continue
        if parts[0] == "tests" and rel.name == "test_git_count_proxy_236.py":
            continue
        if parts[0] in ("skills", "agents", "commands", "scripts") or str(rel) == "CLAUDE.md":
            files.append(path)
    return files


def test_governing_files_exist():
    """A suite that silently found no files would pass the check below vacuously."""
    files = _governing_files()
    assert files, "no governing prose/scripts found -- the sweep below would check nothing"


def test_anti_pattern_detector_fires_on_the_broken_form():
    """Positive control: the regex must actually be able to catch the class it guards."""
    offending = "commits = len(subprocess.check_output(['git', 'log', '--oneline']).splitlines())"
    also_offending = "rtk git log v0.5.0..main --oneline | wc -l"
    not_offending = "piping `git log` through `wc -l` corrupts an empty range through the proxy"
    assert not ANTI_PATTERN.search(offending)  # this shape needs its own guard; not this one
    assert ANTI_PATTERN.search(also_offending), (
        "the detector must fire on a piped git log | wc -l count -- if it does not, "
        "the sweep below is checking nothing"
    )
    assert not ANTI_PATTERN.search(not_offending), (
        "the detector must not fire on prose that merely describes the trap in words"
    )


def test_no_piped_git_log_count_in_governing_prose_or_scripts():
    offenders = []
    for path in _governing_files():
        text = path.read_text(encoding="utf-8")
        for match in ANTI_PATTERN.finditer(text):
            line = text[: match.start()].count("\n") + 1
            rel = path.relative_to(REPO_ROOT)
            offenders.append("{}:{}: {!r}".format(rel, line, match.group(0)))
    assert not offenders, (
        "A piped `git log | wc -l` count is corrupted through the maintainer's rtk proxy "
        "(#236): an empty range reads as 1, not 0, and zero is the load-bearing value. "
        "Use `git rev-list --count <range>` instead:\n  " + "\n  ".join(offenders)
    )


def test_release_delta_uses_rev_list_count():
    """The one place this repo actually computes a release delta must use the typed form."""
    text = (REPO_ROOT / "scripts" / "release_delta.py").read_text(encoding="utf-8")
    assert "rev-list" in text and "--count" in text, (
        "scripts/release_delta.py must derive commit counts with `git rev-list --count`, "
        "never by parsing piped `git log` output (#236)"
    )


def test_manager_skill_states_the_rule():
    """The written rule this class needs: never derive a count or identity from piped git log."""
    text = MANAGER_LOOP.read_text(encoding="utf-8")
    assert "rev-list" in text, (
        "skills/manager/SKILL.md must name `git rev-list --count` as the way to count a "
        "commit range, so the rule travels with the loop rather than living only in "
        "CLAUDE.md's own re-derivation (#236)"
    )
    assert re.search(r"rtk|proxy", text, re.IGNORECASE), (
        "skills/manager/SKILL.md must name the rtk proxy as the mechanism that corrupts "
        "a piped git log count, per the measurement in #236"
    )
