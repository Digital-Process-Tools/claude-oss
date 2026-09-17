"""``check_claude_md_size`` -- has this repo's own `CLAUDE.md` outgrown itself
(#1631)?

`CLAUDE.md` is loaded whole into every session of every agent that reads a
repository, so a byte added to it is paid on every turn of every agent
forever. This plugin's own `CLAUDE.md` knows that about itself --
`scripts/claude_md_budget.py` and `tests/test_claude_md_own_budget_1556.py`
hold this repository's own copy to a ceiling -- but a repository the plugin
merely SCAFFOLDS gets no such signal: nothing in `doctor.py` ever looked at
the size of the `CLAUDE.md` it hands out, and nothing tells a maintainer when
theirs has grown past the point where every session pays for it.

A new check, so it lives in its own module from the start rather than going
inline in `doctor.py` -- the convention block at the top of that file. Does
NOT `import doctor` at module scope -- see `.claude/jit-context/paths/
00-manual/doctor-check-module-scope-import.md`: `doctor.py` imports every
`doctor_check_*` submodule, so importing it back at module scope is a
circular `ImportError` the moment this module (or its own test) loads first.

## The threshold is a per-repo fact

Per `CLAUDE.md`'s own governing rule ("a fact about one repository never
lives in shared code"), the size ceiling this check compares against is read
from `.oss.json`'s own `claude_md_size_threshold` key -- joining the
`triage_route_threshold` / `curate_route_threshold` family `scripts/
oss_config.py` already carries (#1155). That family used to also carry
`release_route_threshold` and `outbound_route_threshold`; #1652/#1653
removed both rather than wiring them (see `oss_config.py`'s own `OPTIONAL_
KEYS` comment for why), so this threshold now joins a family of two, not
four. Per the trap recorded against that exact family
(`.claude/jit-context/paths/00-manual/config-value-validation.md` --
`outbound_route_threshold` shipped validated-but-unread), the reader for
THIS key lives right here, not just a set-membership declaration in
`OPTIONAL_KEYS`.

Absent config must not silently mean "fine": an oversized `CLAUDE.md` on a
repo with no threshold configured renders `NOTICE`, naming the size found and
that no threshold exists to compare it against, never a silent `OK` -- that
would be the exact defect class this plugin is named after (an absence
produced by the check read as an absence in the world).

## Third state, mandatory

An unreadable or absent `CLAUDE.md` reports `could-not-tell` (rendered as
`NOTICE`), never `ok` and never a size of zero: `Path.stat()` on a missing
file and a genuinely tiny file both end up small if the exception is
swallowed, which is exactly the trap `.claude/jit-context/paths/00-manual/
filesystem-probe-states.md` and `counter-scripts-silent-gaps.md` both name.

## The remedy is runnable, not just a description

Per `doctor-check-contract.md` test 2 ("the remedy has to be runnable"), the
WARN names the three jit-context dimensions and their directory paths
(`.claude/jit-context/paths/`, `tools/`, `vocabulary/`) plus the
`claude-jit-context:vocabulary` skill, which already covers picking a
dimension, keywording a rule and proving it fires -- "rewrite entries into
jit-context" is judgment work a script cannot do FOR a maintainer, so the
remedy hands over the tool that does the judging, rather than attempting to
automate the judgement itself (left as a harder, explicitly-optional design
in #1631's own issue).

## It clears

Move prose out of `CLAUDE.md` into a jit-context rule, or raise (or set) the
configured threshold deliberately, and the size check passes -- a legitimate
WARN per `doctor-check-contract.md` test 1, unlike the two unclearable WARNs
#1625 and #1623 are about.

## This repository's own loop-prose ban is out of scope here

`CLAUDE.md` states that loop prose (`skills/manager/**`, `agents/*.md`) may
not move to `.claude/jit-context/` in THIS repository, because jit's
shown-set dedup is keyed on `session_id` and a spawned agent inherits its
parent's. That ban is about this repository's own loop files; it says
nothing about an ordinary scaffolded repository's project knowledge, and
this check does not encode or repeat it -- the remedy text below names the
jit route unconditionally, which is correct for the managed repositories
this check is written for. Whether this check should also fire on THIS
repository's own `CLAUDE.md`, and if so how the remedy text should read
given the ban, is left to `.oss.json` (an unconfigured threshold here is
`could-not-tell`/`NOTICE`, never a WARN pointing at a route this repo
declines), not decided in this module.

Python 3.9 compatible.
"""

from pathlib import Path

CLAUDE_MD_NAME = "CLAUDE.md"
CLAUDE_MD_SIZE_THRESHOLD_KEY = "claude_md_size_threshold"

#: The three jit-context dimensions this remedy names, verbatim from
#: CLAUDE.md's own governing rule: "a jit-context rule under
#: .claude/jit-context/<paths|tools|vocabulary>/".
JIT_CONTEXT_DIRS = (
    ".claude/jit-context/paths/",
    ".claude/jit-context/tools/",
    ".claude/jit-context/vocabulary/",
)


def claude_md_size_state(project_dir, threshold):
    """``(state, size, detail)`` -- ``over`` / ``under`` / ``unconfigured`` /
    ``could-not-tell``, the same four-state shape `scripts/workspace_routes.py`
    already uses for its own threshold routes (`over`/`under`/
    ``could-not-count``), plus the absent-file third state this check adds.

    ``threshold`` is whatever `.oss.json`'s own `claude_md_size_threshold` key
    holds -- ``None`` when the key is absent, an ``int`` when a maintainer set
    one. Anything else (a string, a float, a negative number) is treated as
    not configured: a value that does not parse as a real size in bytes is
    not a threshold this check can compare against, and reporting `ok`
    against a value nobody actually set would be the same silent absence
    this module exists to stop.

    ``size`` is the byte count read, or ``None`` when it could not be taken.
    """
    path = Path(project_dir) / CLAUDE_MD_NAME
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return "could-not-tell", None, "no {} in this repository".format(CLAUDE_MD_NAME)
    except OSError as exc:
        return (
            "could-not-tell",
            None,
            "{} could not be read ({})".format(CLAUDE_MD_NAME, exc),
        )
    valid_threshold = (
        isinstance(threshold, int) and not isinstance(threshold, bool) and threshold > 0
    )
    if not valid_threshold:
        return (
            "unconfigured",
            size,
            "{} is {} bytes; no {} configured in .oss.json to compare it "
            "against".format(CLAUDE_MD_NAME, size, CLAUDE_MD_SIZE_THRESHOLD_KEY),
        )
    if size > threshold:
        return (
            "over",
            size,
            "{} is {} bytes, over the configured {} of {}".format(
                CLAUDE_MD_NAME, size, CLAUDE_MD_SIZE_THRESHOLD_KEY, threshold
            ),
        )
    return (
        "under",
        size,
        "{} is {} bytes, at or under the configured {} of {}".format(
            CLAUDE_MD_NAME, size, CLAUDE_MD_SIZE_THRESHOLD_KEY, threshold
        ),
    )


_REMEDY = (
    "Move the knowledge that fires on touching a file, using a tool or "
    "meeting a term into a jit-context rule instead of leaving it always-on: "
    "{} for path-triggered knowledge, {} for a tool's own call shape, {} for "
    "a term. The claude-jit-context:vocabulary skill covers picking the "
    "right dimension, keywording a rule so it fires without noise, and "
    "proving that it does -- use it rather than guessing at the shape by "
    "hand.".format(*JIT_CONTEXT_DIRS)
)


def check_claude_md_size(project_dir, config):
    """One line, in every state -- see `claude_md_size_state`."""
    import doctor

    threshold = None
    if isinstance(config, dict):
        threshold = config.get(CLAUDE_MD_SIZE_THRESHOLD_KEY)
    state, size, detail = claude_md_size_state(project_dir, threshold)
    if state == "could-not-tell":
        doctor.report(
            "NOTICE",
            "CLAUDE.md size: {} -- not answered as fine, and not a size of "
            "zero: this is the third state, a check that could not "
            "look.".format(detail),
        )
        return
    if state == "unconfigured":
        doctor.report(
            "NOTICE",
            'CLAUDE.md size: {}. Add "{}": <bytes> to .oss.json if this '
            "repository wants this check to gate on a real ceiling; until "
            "then this is informational only, never folded into a silent "
            "OK.".format(detail, CLAUDE_MD_SIZE_THRESHOLD_KEY),
        )
        return
    if state == "over":
        doctor.report(
            "WARN",
            "CLAUDE.md size: {}. This file is loaded whole into every session "
            "of every agent that reads this repository, so every byte in it "
            "is paid on every turn forever. {}".format(detail, _REMEDY),
        )
        return
    doctor.report("OK", "CLAUDE.md size: {}.".format(detail))
