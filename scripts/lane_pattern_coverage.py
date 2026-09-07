"""Does `.oss.json`'s `labels.lane_patterns` actually hold the disjointness
property `docs/pick-the-work.md` describes, for THIS repo's own tree (#1229)?

`oss_config.py` validates only the shape of `lane_patterns` -- an object
mapping a lane label to a list of globs, or null. It never resolves a
pattern against the filesystem, so a pattern that matches nothing (a rename
left a glob behind) and two lanes claiming the same file both pass that
validation cleanly. This module is the derivation `scripts/doctor_check_
lane_patterns.py` reports through -- built as its own module, per the
issue's own requirement, so it stays runnable by hand while editing
`.oss.json`, the exact moment somebody wants the answer (the same shape
`ranking_table.py`, `release_delta.py` and `gate3_disposition.py` already
use for the identical reason).

**Overlap is a refactoring signal, not a dispatch gate.** The maintainer's
own ruling on #1229: a disjointness gate has to be complete to be worth
anything, and this one cannot be -- `select_issues.py`'s own held-lane
collision check and ordinary git conflict detection already catch the
failure file-set overlap targets, and both are loud and cheap when they
fire. What overlap here means is narrower and still real: a file resolved
into two lanes is doing two lanes' jobs, and the useful response is to
split the file, not to route dispatch around it. Nothing in this module or
its caller may be read as a merge or dispatch precondition.

Resolution goes through `select_issues_overlap.resolve_lane` -- the
identical function `select_issues.py`'s own held-lane collision check uses
-- never a hand-rolled prefix match that could disagree with it.

Three states, and the third is load-bearing (the defect class this whole
plugin is named after, one layer up): a repo that has never declared
`lane_patterns` and a repo whose patterns are all clean must never render
the same as each other, and neither may render as a repo that HAS a
problem.

    ok               lane_patterns declared; every pattern resolves to at
                      least one file (or is a bare literal, asserted rather
                      than checked -- see `resolve_lane`'s own docstring for
                      why a file that does not exist yet is not a defect);
                      no two lanes claim the same path
    finding          a pattern matches nothing on disk (`dead_patterns`), a
                      pattern is malformed (`refused`), or two lanes claim
                      the same file (`overlaps`) -- all three are reported
                      together, none takes priority over another
    not-configured   labels.lane_patterns is null, absent, or an empty
                      object -- the ordinary state for a repo that has not
                      adopted the convention. Never "ok": a check that never
                      ran must not look like one that found nothing.

`uncovered_count` is a fourth, separate signal, reported only inside a
`finding`/`ok` result (never gates the state on its own): the maintainer's
own two-part ruling on #1229 is (1) universal coverage must never become a
failing invariant -- `lane-other` exists precisely for "no lane owns this
file", a designed state, not a defect -- and (2) a freshly scaffolded repo
where NOTHING is covered must not dump the whole tree as noise, which
teaches a maintainer to skip the diagnostic. Both are satisfied by scoping
the walk to top-level directories some lane already touches, and reporting
a bare count rather than a path list. `None` (not `0`) means no lane
resolved to a single file, so no scope could be established at all -- that
is a different state from "scope established, nothing left uncovered in
it", and the two must not collapse to the same number.

Python 3.9 compatible.
"""

import os
from pathlib import Path

import select_issues_overlap

#: Directories this walk never descends into: version control internals,
#: never a source of a file a lane could plausibly claim, and large enough
#: on some checkouts to make the walk itself expensive for no purpose.
_SKIP_DIRS = frozenset((".git",))


def _walk_all_files(repo):
    """``(files, problem)`` -- every regular file under `repo`, repo-relative
    POSIX paths, skipping `_SKIP_DIRS`. ``problem`` is ``None`` on a clean
    walk, or a string naming what went wrong -- never a bare ``[]`` a caller
    could mistake for "this repo has no files" (the same shape
    `select_issues_overlap._expand_directory`'s own `onerror` callback
    exists to preserve, reused here as the same walk over the whole tree
    rather than one declared directory).

    This is a filesystem walk, not `git ls-files` -- deliberately: the
    maintainer's own requirement on #1229 is that this check is cheap
    enough to run on every `/oss:doctor` invocation, no subprocess. An
    untracked file (a build artefact, a local scratch file) is therefore
    indistinguishable from a tracked one here, which can only ever make the
    uncovered count an overestimate, never hide a real gap.
    """
    files = []

    def _onerror(exc):
        raise exc

    try:
        for dirpath, dirnames, filenames in os.walk(str(repo), onerror=_onerror):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    if not p.is_symlink() and p.is_file():
                        files.append(p.relative_to(repo).as_posix())
                except OSError:
                    continue
    except OSError as exc:
        return [], "{}: {}".format(type(exc).__name__, exc)
    return sorted(files), None


def _dead_patterns(lane, resolved):
    return [
        (lane, entry["pattern"])
        for entry in resolved["patterns"]
        if entry["state"] == "glob-no-match"
    ]


def _refused_patterns(lane, resolved):
    return [
        (lane, entry["pattern"], entry["detail"])
        for entry in resolved["patterns"]
        if entry["state"] == "refused"
    ]


def _overlaps(lane_files):
    """``[(file, [lanes...])]`` sorted by file -- every file two or more
    lanes both resolved to. `lane_files` maps a lane label to its resolved
    file list.
    """
    owners = {}
    for lane, files in lane_files.items():
        for f in files:
            owners.setdefault(f, []).append(lane)
    return sorted((f, sorted(lanes)) for f, lanes in owners.items() if len(lanes) >= 2)


def _uncovered_count(repo, lane_files):
    """``None`` when no lane resolved a single file (no scope established);
    otherwise the count of files under a top-level directory some lane
    already touches, that no lane covers.
    """
    covered = set()
    scopes = set()
    for files in lane_files.values():
        for f in files:
            covered.add(f)
            scopes.add(f.split("/", 1)[0])
    if not scopes:
        return None
    all_files, problem = _walk_all_files(repo)
    if problem is not None:
        return None
    in_scope = (f for f in all_files if f.split("/", 1)[0] in scopes)
    return sum(1 for f in in_scope if f not in covered)


def lane_pattern_report(repo, lane_patterns):
    """``dict`` -- see this module's own docstring for the three states and
    the `overlaps`/`dead_patterns`/`refused`/`uncovered_count` fields.
    """
    repo = Path(repo)
    if not lane_patterns:
        return {
            "state": "not-configured",
            "overlaps": [],
            "dead_patterns": [],
            "refused": [],
            "uncovered_count": None,
        }
    lane_files = {}
    dead_patterns = []
    refused = []
    for lane, patterns in lane_patterns.items():
        resolved = select_issues_overlap.resolve_lane(repo, patterns or [])
        lane_files[lane] = resolved["files"]
        dead_patterns.extend(_dead_patterns(lane, resolved))
        refused.extend(_refused_patterns(lane, resolved))
    overlaps = _overlaps(lane_files)
    uncovered_count = _uncovered_count(repo, lane_files)
    state = "finding" if (overlaps or dead_patterns or refused) else "ok"
    return {
        "state": state,
        "overlaps": overlaps,
        "dead_patterns": dead_patterns,
        "refused": refused,
        "uncovered_count": uncovered_count,
    }
