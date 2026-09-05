"""Guard for #687 and #689: the manager loop's own runbook command cells.

`skills/manager/SKILL.md`'s three-call table (the block under "Three calls
stand in for judgement here") is copy-pasted verbatim by a live session --
nothing in this repository executed any of its cells before the 0.16.0
release gate's round-one audit found two independent defects there:

- **#687**: the "dispatching" row invoked `${CLAUDE_PLUGIN_ROOT}/scripts/
  fleet_label.py` directly. That file is committed mode 100644 with no
  shebang -- `scripts/lane_setup.py`, invoked the same way two rows above,
  is 100755 with a `#!/usr/bin/env python3` line, so the exec bit does
  survive packaging and this file specifically never had one. Run as
  written the row exits 126 (permission denied).
  `skills/manager/phases/dispatch.md` already composes the identical call
  through `python3 "..."` and works.
- **#689**: none of the table's four cells quoted `${CLAUDE_PLUGIN_ROOT}`.
  A plugin root containing a space -- the ordinary shape of a Windows
  home directory built from a two-word account name -- word-splits into
  argv the moment a session pastes the cell into a shell.

Scope, stated because a guard that only pins the two lines just fixed reads
as coverage it does not have: this reaches every `${CLAUDE_PLUGIN_ROOT}`
occurrence inside the three-call table's own command cells, plus the
`fleet_label.py` compose line in `dispatch.md` that the table's row must stay
in parity with, plus -- since #741 -- every `${CLAUDE_PLUGIN_ROOT}/scripts/`
reference anywhere in `dispatch.md` (below). It does **not** sweep every code
fence in the whole loop's prose for quoting or executable-bit correctness --
SKILL.md and the other phase files contain many other script mentions and
paths that are prose about a script rather than a command a session runs
verbatim, and telling those apart well enough to assert on them is a bigger,
separate piece of work #689 already declined once; #741 found a fifth genuine
instance outside this file's reach while this widening was being written
(`skills/manager/phases/handback.md:84`) and it is reported, not fixed here.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import manager_docs  # noqa: E402

SKILL_MD = manager_docs.repo_root() / "skills" / "manager" / "SKILL.md"
DISPATCH_MD = manager_docs.repo_root() / "skills" / "manager" / "phases" / "dispatch.md"

TABLE_ANCHOR = "calls stand in for judgement here"  # #1069: SKILL.md now says "Four"

_UNQUOTED_ROOT = re.compile(r'(?<!")\$\{CLAUDE_PLUGIN_ROOT\}')
_SCRIPT_CALL = re.compile(
    r'(python3\s+)?"?\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([A-Za-z_]+\.py)"?'
)


def _table_rows(text):
    """The three-call table's own row lines, header and separator stripped."""
    idx = text.index(TABLE_ANCHOR)
    lines = text[idx:].splitlines()
    rows = []
    in_table = False
    for line in lines:
        if line.startswith("| Before"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            break
        if line.startswith("| --- "):
            continue
        rows.append(line)
    assert rows, (
        "table anchor found but no data rows followed -- table moved or was renamed"
    )
    return rows


def _git_mode(rel_path):
    """The git blob mode for a tracked file, e.g. '100644' or '100755'.

    Reads the tree rather than the filesystem: a checkout can lose the exec
    bit on some platforms/filesystems, and it is the *committed* mode that
    every fresh clone and every packaged install actually gets.
    """
    out = subprocess.run(
        ["git", "ls-files", "-s", rel_path],
        cwd=str(manager_docs.repo_root()),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out, "git ls-files -s returned nothing for {0} -- not tracked?".format(
        rel_path
    )
    return out.split()[0]


def test_table_rows_quote_every_plugin_root_reference():
    """Must-not-fire: every ${CLAUDE_PLUGIN_ROOT} in a command cell is quoted (#689)."""
    rows = _table_rows(SKILL_MD.read_text(encoding="utf-8"))
    offenders = [row for row in rows if _UNQUOTED_ROOT.search(row)]
    assert not offenders, (
        "unquoted ${{CLAUDE_PLUGIN_ROOT}} in a runbook command cell -- "
        "word-splits on a plugin root containing a space: {0}".format(offenders)
    )


def test_unquoted_plugin_root_is_detected_when_present():
    """Must-fire control for the check above: a deliberately unquoted cell is caught.

    Without this, a regex that matches nothing could be silently broken
    (typo'd metacharacter, wrong anchor) and the test above would pass for
    the wrong reason forever.
    """
    offending_row = (
        "| dispatching | `${CLAUDE_PLUGIN_ROOT}/scripts/fleet_label.py "
        '<primary> <issue1,issue2,...> "<phrase>"` |'
    )
    assert _UNQUOTED_ROOT.search(offending_row), (
        "the unquoted-reference regex failed to catch a known-bad row -- "
        "the guard above would pass vacuously"
    )


def test_quoted_plugin_root_is_not_flagged():
    """Must-not-fire control: a properly quoted cell is not a false positive."""
    fixed_row = (
        '| dispatching | `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_label.py" '
        '<primary> <issue1,issue2,...> "<phrase>"` |'
    )
    assert not _UNQUOTED_ROOT.search(fixed_row)


def test_script_invocations_match_their_own_executable_bit():
    """#687: a table cell invoking a script directly requires that script to
    be executable in git's own tree; a script that is not gets a python3
    prefix instead. Fires on any cell that gets this backwards, for any
    script the table names -- not hardcoded to fleet_label.py alone.
    """
    rows = _table_rows(SKILL_MD.read_text(encoding="utf-8"))
    text = "\n".join(rows)
    calls = _SCRIPT_CALL.findall(text)
    assert calls, "no ${CLAUDE_PLUGIN_ROOT}/scripts/*.py call found in the table at all"
    mismatches = []
    for prefix, script_name in calls:
        rel = "scripts/{0}".format(script_name)
        mode = _git_mode(rel)
        invoked_directly = not prefix
        executable = mode == "100755"
        if invoked_directly and not executable:
            mismatches.append(
                "{0} is invoked directly but is mode {1} (not executable)".format(
                    rel, mode
                )
            )
    assert not mismatches, "; ".join(mismatches)


def test_fleet_label_row_matches_dispatch_md_invocation():
    """The SKILL.md table's dispatching cell and dispatch.md's own compose
    line must invoke the script the same way -- #687 was exactly these two
    documents disagreeing about how to run the identical file. #1069 folded
    fleet_label.py into lane_setup.py --label; the row to compare is the one
    naming --label now, not "fleet_label.py" (gone with the rest of that
    file's own CLI).
    """
    rows = _table_rows(SKILL_MD.read_text(encoding="utf-8"))
    skill_row = next(r for r in rows if "--label" in r)
    skill_call = _SCRIPT_CALL.search(skill_row)
    assert skill_call, "no lane_setup.py --label invocation found in the SKILL.md table row"

    dispatch_text = DISPATCH_MD.read_text(encoding="utf-8")
    dispatch_calls = [
        m
        for m in _SCRIPT_CALL.finditer(dispatch_text)
        if m.group(2) == "lane_setup.py"
        and "--label" in dispatch_text[m.start() : m.start() + 200]
    ]
    assert dispatch_calls, "no lane_setup.py --label invocation found in dispatch.md"
    dispatch_call = dispatch_calls[0]

    skill_prefix, skill_script = skill_call.groups()
    dispatch_prefix, dispatch_script = dispatch_call.groups()
    assert skill_script == dispatch_script == "lane_setup.py"
    assert bool(skill_prefix) == bool(dispatch_prefix), (
        "SKILL.md and dispatch.md disagree on whether lane_setup.py --label needs "
        "a python3 prefix: {0!r} vs {1!r}".format(skill_row, dispatch_call.group(0))
    )


# ------------------------------------- #741: every plugin-root script reference
# in dispatch.md, not only the table and the fleet_label.py line
#
# #741 found dispatch.md's own --claim line unquoted -- added by #705 in the
# same diff that added the fleet_label.py row the parity test above checks,
# so the fourth site sat right beside the third and neither guard above
# reached it. Sweeping the rest of the file for the same class (CLAUDE.md's
# own rule: once one instance turns up, sweep the file it came from) found
# two more the issue never named -- the lane-disjointness check and the
# lane-bundling check, both quoted correctly in SKILL.md's own table cells but
# not here. All three are the #689 word-split, not a new mechanism.

_UNQUOTED_ROOT_SCRIPT_RE = re.compile(r'(?<!")\$\{CLAUDE_PLUGIN_ROOT\}/scripts/')


def _unquoted_plugin_root_script_refs(text):
    """[(line number, line text)] for every unquoted ${CLAUDE_PLUGIN_ROOT}/scripts/
    reference -- #689's word-split, applied to a whole document rather than one
    table's rows.
    """
    return [
        (i, line.strip())
        for i, line in enumerate(text.splitlines(), 1)
        if _UNQUOTED_ROOT_SCRIPT_RE.search(line)
    ]


def test_dispatch_md_quotes_every_plugin_root_script_reference():
    """Must-not-fire: no unquoted ${CLAUDE_PLUGIN_ROOT}/scripts/... left in dispatch.md."""
    offenders = _unquoted_plugin_root_script_refs(
        DISPATCH_MD.read_text(encoding="utf-8")
    )
    assert not offenders, (
        "unquoted ${{CLAUDE_PLUGIN_ROOT}}/scripts/... in dispatch.md -- word-splits "
        "on a plugin root containing a space: {0}".format(offenders)
    )


def test_unquoted_plugin_root_script_reference_is_detected_when_present():
    """Must-fire control: the #741 line as it stood before its fix is caught."""
    bad = (
        "**Run `${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py <issue> --claim` from "
        "the clone before writing"
    )
    assert _unquoted_plugin_root_script_refs(bad) == [(1, bad.strip())]


def test_quoted_plugin_root_script_reference_is_not_flagged():
    """Must-not-fire control: the fixed form is not a false positive."""
    good = (
        '**Run `"${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue> --claim` from '
        "the clone before writing"
    )
    assert _unquoted_plugin_root_script_refs(good) == []
