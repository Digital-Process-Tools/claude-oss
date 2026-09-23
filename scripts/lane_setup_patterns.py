"""Cross-cutting guard lookup for a set of files (#566), and the disjointness report a lane brief reads (#267, #558).

Split out of `lane_setup.py` for #1069: which cross-cutting guard tests a
set of files touches (`known_guards`/`guards_for_files`, #566), and the
disjointness report a lane brief actually reads (`lane_report`, #267/#558).
Needs `resolve_lane`/`lane_overlap`/`_lane_resolved_to_nothing` from
`select_issues_overlap.py` -- lane_setup's own registration and reporting
still has to resolve and compare patterns, the same functions
`select_issues.py` uses for the identical question one layer up.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import stat as _stat
from pathlib import Path

import lane_setup_worktree
import oss_config
import select_issues_overlap

CROSS_CUTTING_GUARDS = (
    (
        "skills/",
        "tests/test_content_invariants.py",
        "hardcoded repo facts in skill/agent/command prose",
    ),
    (
        "agents/",
        "tests/test_content_invariants.py",
        "hardcoded repo facts in skill/agent/command prose",
    ),
    (
        "commands/",
        "tests/test_content_invariants.py",
        "hardcoded repo facts in skill/agent/command prose",
    ),
    (
        "scripts/",
        "tests/test_unwired_scripts_253.py",
        "a script added, removed, or dropped from its last live reference",
    ),
    (
        "bin/",
        "tests/test_unwired_scripts_253.py",
        "a script added, removed, or dropped from its last live reference",
    ),
    # test_gate_state_consumers_328.py scans *every* tracked file under commands/ and
    # scripts/ for a bare occurrence of the gate producer's identifier, not only the
    # files that already call it -- an auditor caught the first version of this
    # mapping naming only the four current consumers, which reported nothing for a
    # brand-new file that started calling it, exactly the PR #431 shape this issue is
    # about. So the trigger here is the same two directories the real guard scans,
    # not an enumeration of who currently calls it.
    (
        "scripts/",
        "tests/test_gate_state_consumers_328.py",
        "may add or lose a consumer of the changelog scaffolding gate's state",
    ),
    (
        "commands/",
        "tests/test_gate_state_consumers_328.py",
        "may add or lose a consumer of the changelog scaffolding gate's state",
    ),
    # #1222: `tests/test_bare_gh_git_spawn_sweep_1165.py`'s own docstring says it
    # "scans every `scripts/*.py` file" for a bare, unrouted `gh`/`git` subprocess
    # spawn -- the same repo-wide-scan shape `test_gate_state_consumers_328.py`
    # already justifies a directory-prefix trigger for, immediately above. This
    # repo has paid for the missing instance of this guard five times over
    # (#1157, #1163, #1168, #1172, #1173) and it was never declared here, so a
    # brand-new file under `scripts/` reported zero guards for the one class of
    # defect this repository keeps re-finding by hand.
    (
        "scripts/",
        "tests/test_bare_gh_git_spawn_sweep_1165.py",
        "a new or touched scripts/*.py file may add a bare, unrouted gh/git "
        "subprocess spawn -- route it through gh_which.safe_which instead",
    ),
    (
        "CLAUDE.md",
        "tests/test_claude_md_currency.py",
        "the 'What is not proven yet' release marker paragraph",
    ),
    (
        "changelog.d/",
        "tests/test_claude_md_currency.py",
        "fragment presence gates whether the release marker must be current",
    ),
    (
        "pyproject.toml",
        "tests/test_python_floor_410.py",
        "the declared Python floor and its four derived sites",
    ),
    (
        "README.md",
        "tests/test_python_floor_410.py",
        "the Python floor's README support badge",
    ),
    (
        "scripts/doctor.sh",
        "tests/test_python_floor_410.py",
        "the Python floor's oldest python3.N candidate in the interpreter walk",
    ),
    (
        ".github/workflows/tests.yml",
        "tests/test_python_floor_410.py",
        "the Python floor's CI matrix lowest entry",
    ),
    # #1094: `tests/test_command_references.py`'s own `_enumerates_both_sides_of_
    # the_boundary` check reads the *concatenated* text of `SKILL.md` plus every
    # `skills/manager/phases/*.md` file, never one of them alone -- so `SKILL.md`
    # can be byte-identical between two branches while a phases file alone trips
    # it (observed live: PR #1091 added a phrase to `phases/merge.md` and opened
    # 7 of 18 CI legs red on this exact check, with none of the files a narrowed
    # local run would have named). A guard keyed to *what the check reads*, the
    # same #432 argument this whole table already makes, rather than to which
    # single file a diff happened to touch.
    (
        "skills/manager/SKILL.md",
        "tests/test_command_references.py",
        "SKILL.md + every phases/*.md file, concatenated, is what the "
        "boundary-enumeration check actually reads",
    ),
    (
        "skills/manager/phases/",
        "tests/test_command_references.py",
        "SKILL.md + every phases/*.md file, concatenated, is what the "
        "boundary-enumeration check actually reads",
    ),
)


def _guard_test_existence(repo, test_path):
    """Whether `test_path` (one of `CROSS_CUTTING_GUARDS`'s own entries) exists as a
    regular file under `repo`. Three states, not two -- #566:

      exists          the guard test is present in this repository. Run it.
      absent          confirmed not present -- this class of guard does not exist
                       here, and a lane must be told that rather than handed a
                       path that collects nothing.
      could-not-tell  the repository could not be examined at this path -- an
                       ancestor this process cannot traverse, an unreadable
                       parent. Never folded into `absent`: an unlookable name
                       and a genuine miss render identically as
                       `FileNotFoundError` on a platform that folds Win32 codes
                       onto `ENOENT` (CLAUDE.md), so `_absence_confirmed` --
                       already used by `worktree_occupancy` for the identical
                       swallow -- decides which of the two this is
                       rather than trusting the exception type alone.

    `CROSS_CUTTING_GUARDS` is a fact about *this* repository (claude-oss) living
    in shared code that runs against every managed repository (#566) -- a
    managed repo carries none of these test files by construction. This
    function is what turns "the table names a guard" into "the guard applies
    here", the same way `resolve_lane`'s `glob-no-match` turns "the pattern is
    well-formed" into "the pattern matched something": a fact asserted and a
    fact confirmed are not the same claim, and only a check can tell them apart.
    """
    p = Path(repo) / test_path
    try:
        st = p.stat()
    except (FileNotFoundError, NotADirectoryError):
        return (
            "absent"
            if lane_setup_worktree._absence_confirmed(p) is True
            else "could-not-tell"
        )
    except (OSError, ValueError):
        return "could-not-tell"
    return "exists" if _stat.S_ISREG(st.st_mode) else "absent"


def _repo_declared_guards(repo):
    """Extra `(prefix, test_path, why)` triples this managed repository declares
    for itself via `.oss.json`'s `lane_guards` key (#1722).

    `CROSS_CUTTING_GUARDS` above is a fact about claude-oss's own tree -- every
    built-in entry names a claude-oss path -- so a repo this loop merely
    operates on (e.g. claude-supertool) had no way to register a guard test of
    its own that a lane's file-set search should have anticipated before
    dispatch. This is that extension point: read the same way `_guard_test_
    existence` already reads a repo-relative path, merged into the built-in
    table wherever a caller passes `repo`.

    Tolerant by construction: a missing `.oss.json`, one that fails to parse or
    validate, or one that carries no `lane_guards` key at all, all return `()`
    rather than raising -- `oss_config.load` already reports a malformed
    config's own problems to whoever builds this lane's payload; this merge
    exists only to add guards, never to duplicate that reporting. A
    malformed *entry* inside an otherwise-valid `lane_guards` list is skipped
    individually rather than discarding the whole declared list, the same
    "still exercised, not lost to one bad sibling" shape `guards_for_files`
    itself already gives a partially-covered file set.
    """
    if repo is None:
        return ()
    config, _problems = oss_config.load(Path(repo) / oss_config.CONFIG_NAME)
    if not config:
        return ()
    declared = config.get("lane_guards")
    if not isinstance(declared, list):
        return ()
    triples = []
    for entry in declared:
        if not isinstance(entry, dict):
            continue
        prefix = entry.get("prefix")
        test_path = entry.get("test")
        why = entry.get("why")
        if (
            isinstance(prefix, str)
            and prefix.strip()
            and isinstance(test_path, str)
            and test_path.strip()
            and isinstance(why, str)
            and why.strip()
        ):
            triples.append((prefix, test_path, why))
    return tuple(triples)


def known_guards(repo=None):
    """The full enumeration, grouped by guard test with every trigger reason that
    maps to it. Answers #432's own sizing question -- how many of these exist --
    as a derived count rather than a pasted one, so a sixth guard added later
    changes this return value instead of needing a second list updated by hand.

    `repo` is optional and, when given, adds each entry's `status`
    (`_guard_test_existence`) against that repository -- #566/#567: the sizing
    answer this exists to give is about the repository a lane is dispatched
    into, not about claude-oss's own tree, so a caller counting "how many
    guards apply" in a managed repo must count entries whose `status` is
    `exists`, not the declared length of `CROSS_CUTTING_GUARDS`. Omitted
    (`repo=None`) keeps the declared enumeration only -- the shape this
    function has always had, and what `claude-oss`'s own sizing test still
    checks against its own tree.

    `repo`, when given, also folds in whatever that repository declares
    for itself via `.oss.json`'s `lane_guards` key (`_repo_declared_guards`,
    #1722) -- `CROSS_CUTTING_GUARDS` alone is a fact about claude-oss's own
    tree, and this is the one place a managed repo's own guards join it.
    """
    guards = CROSS_CUTTING_GUARDS + _repo_declared_guards(repo)
    grouped = {}
    for prefix, test_path, why in guards:
        grouped.setdefault(test_path, []).append({"prefix": prefix, "why": why})
    result = []
    for test_path in sorted(grouped):
        entry = {"test": test_path, "triggers": grouped[test_path]}
        if repo is not None:
            entry["status"] = _guard_test_existence(repo, test_path)
        result.append(entry)
    return result


def guards_for_files(files, repo=None):
    """Which guard tests a lane's resolved files (`resolve_lane`'s `files` list --
    repo-relative POSIX paths, never a module-name guess) trip, deduplicated to one
    entry per guard even when several files or several reasons point at it.

    Matches by prefix on the canonical path form the rest of this module already
    produces, not by trusting a caller's own idea of which area a change belongs
    to -- the seam #432 exists to close was exactly a human's idea of "these three
    files are about doctor" being wrong about a fourth, unrelated-by-name file.

    `repo` is optional and, when given, adds each entry's `status`
    (`_guard_test_existence`) against that repository -- #566: `CROSS_CUTTING_GUARDS`
    is a fact about claude-oss, and a lane dispatched into a managed repository
    that does not carry a named guard test must be told so rather than handed a
    path that collects nothing when it runs the guard. The entry is never
    dropped for `absent` or `could-not-tell` -- the class still applies to the
    files touched, and dropping it would silently undo the trigger this
    function exists to report; only the disposition changes, from "run this"
    to "this class applies and cannot be run here".

    `repo`, when given, also folds in whatever that repository declares for
    itself via `.oss.json`'s `lane_guards` key (`_repo_declared_guards`,
    #1722) -- the same merge `known_guards` above performs, so a lane's own
    file-set search anticipates a managed repo's own guard exactly as it
    already anticipates claude-oss's built-in ones.
    """
    guards = CROSS_CUTTING_GUARDS + _repo_declared_guards(repo)
    hits = {}
    for f in files or []:
        for prefix, test_path, why in guards:
            if f == prefix or f.startswith(prefix):
                reasons = hits.setdefault(test_path, [])
                if why not in reasons:
                    reasons.append(why)
    result = []
    for test_path in sorted(hits):
        entry = {"test": test_path, "why": hits[test_path]}
        if repo is not None:
            entry["status"] = _guard_test_existence(repo, test_path)
        result.append(entry)
    return result


def _refused_patterns(resolved):
    """Every pattern in a `resolve_lane` result (`resolved["patterns"]`) that was
    refused outright, rather than checked against the tree at all -- #774. A
    `glob-no-match` pattern is a well-formed, verified fact (the pattern really
    does match nothing on disk) and correctly contributes an empty `files` list;
    a `refused` pattern was never read as a pattern in the first place, so the
    comparison `lane_overlap` performs never happened for it at all. Conflating
    the two -- both leave the pattern's own files out of `files` -- is exactly
    how a disjointness check that never ran for one side ends up printing the
    identical `overlap : none` a real, checked, disjoint result would also print
    (the issue's own measurement). `None` in, `[]` out: nothing to ask about a
    side that was never given.
    """
    if resolved is None:
        return []
    return [
        entry["pattern"]
        for entry in resolved["patterns"]
        if entry["state"] == "refused"
    ]


def lane_report(repo, lane_patterns):
    """The `lane` section of a lane-setup payload, or None when no `--lane`
    was given at all -- an absent ask must never read as a checked, empty
    lane.

    `guards` (#432) is computed from the resolved files -- the files a
    developer brief is actually about to touch -- so a brief names the
    cross-cutting guard tests its own diff triggers, which a narrowed test
    run selected by filename would not include.

    **#1532 removed the against side.** This function used to take
    `against_patterns` (a hand-typed set) or `derived_held`
    (`derive_held_set`'s own return value, built from every open pull request
    plus every live lane record) and report the overlap between the two, plus
    a per-candidate `availability` verdict -- available / blocked /
    could-not-check / resolved-to-nothing / could-not-derive-the-held-set.
    All of it answered one question, which files are already spoken for, and
    #1528 stopped that answer dropping a candidate: what was left was a
    computation whose only remaining consumer was a receipt line. git reports
    a real collision at merge, like everywhere else, and `git-worktrees`
    reports which lanes are live from the filesystem, with no second copy to
    go stale.
    """
    if not lane_patterns:
        return None
    a = select_issues_overlap.resolve_lane(repo, lane_patterns)
    # #566: `repo` is threaded through so each guard's `status` is answered against
    # the repository the lane is actually dispatched into, never against claude-oss's
    # own tree by default -- the whole defect this issue is about.
    return {
        "lane": a,
        "guards": guards_for_files(a["files"], repo) if a else [],
    }


#: `linked_worktree_state`'s own return values -- a repository's ordinary
#: working tree, a linked worktree `git worktree add` cut, or "git did not
#: answer either call" (never folded into `WORKTREE_MAIN`, which would let
#: #865 back in through the one case this function exists to catch).
WORKTREE_MAIN = "main"
WORKTREE_LINKED = "linked"
WORKTREE_COULD_NOT_TELL = "could-not-tell"
