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
                       already used by `worktree_occupancy` and `lane_count` for
                       the identical swallow -- decides which of the two this is
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
    """
    grouped = {}
    for prefix, test_path, why in CROSS_CUTTING_GUARDS:
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
    """
    hits = {}
    for f in files or []:
        for prefix, test_path, why in CROSS_CUTTING_GUARDS:
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


def _unresolved_overlap_detail(a, a_refused, b, b_refused):
    """One line naming which side(s) carried a refused pattern and how many --
    #774's own suggested shape, `1 of 1 lane pattern(s) refused`, so the reason
    a comparison could not run is said in as many words rather than standing in
    silently for the bare word `none`.
    """
    parts = []
    if a_refused:
        parts.append(
            "{0} of {1} lane pattern(s) refused: {2}".format(
                len(a_refused), len(a["patterns"]), ", ".join(a_refused)
            )
        )
    if b_refused:
        parts.append(
            "{0} of {1} against pattern(s) refused: {2}".format(
                len(b_refused), len(b["patterns"]), ", ".join(b_refused)
            )
        )
    return "; ".join(parts)


def lane_report(repo, lane_patterns, against_patterns, derived_held=None):
    """The `lane` section of a lane-setup payload, or None when nothing at all
    was asked for. Two lanes given: also the overlap between them, so a
    developer brief's setup call can carry the collision check the maintainer
    would otherwise have to run by eye.

    `guards` (#432) is computed only from the `lane` side's resolved files --
    the files a developer brief is actually about to touch -- never from
    `against`, which names a sibling lane's off-limits files. Reporting a
    guard triggered by the sibling's files would tell a developer to run a
    test for a change it must not make.

    `derived_held` (#558) is `derive_held_set`'s own return value, or None. When
    given, it replaces `against_patterns` as the source of the "against" side --
    combining `--against` with it is refused earlier, in `main`, because a hand-typed
    exclusion beside a derived one is exactly the ambiguity #558 exists to close (was
    this file excluded because the derivation found it, or because someone typed it?).
    Its `held` files become literal patterns through the same `resolve_lane` every
    other side of this call already goes through, so the rendering and the overlap
    check are the one mechanism, not two. When `derived_held["state"]` is
    `could-not-derive`, no "against" side is resolved at all and `availability`
    carries `could-not-derive-the-held-set` -- #558's own words, never `available`
    and never `blocked`.

    `availability` (#558) is a *per-candidate* verdict -- available / blocked /
    could-not-check / resolved-to-nothing / could-not-derive-the-held-set (#843:
    this enumeration itself used to stop at the pre-#809 four, the exact defect
    #837 fixed one function away in dispatch.md's own prose) -- computed only
    when `derived_held` was given, and only for the `lane` side against the
    derived set: a mechanical question this function can answer on its own. The
    tick-level *fill* verdict (filled / under-filled / could-not-tell) that #558
    also names is deliberately NOT computed here: it needs the full list of
    candidate issues under consideration this tick, which is a judgement about
    which issues are even being weighed, not a fact this script can derive from
    one `--lane` argument. That verdict stays prose in the tick, per the issue's
    own framing of the two halves as separable.

    `overlap_state` (#774) is a third answer sitting beside `overlap` itself --
    `resolved` (both sides were actually compared), `could-not-check` (at least
    one side carried a pattern `_lane_pattern_problem` refused, so the
    comparison never ran for it), or `n/a` (fewer than both sides were given at
    all, the pre-existing case). `overlap` alone cannot carry this on its own:
    `[]` is the correct, meaningful answer for two sides that were both
    genuinely resolved and share nothing, and #774's own measurement is that a
    refused pattern produces the identical `[]` -- one word, `none`, for two
    different claims, and in `--against` mode there is no sibling `verdict:`
    line to disambiguate it. `overlap` itself is left `None` whenever
    `overlap_state` is `could-not-check`, the same "nothing to report as a file
    list" shape the pre-existing `n/a` case already uses, so a caller reading
    `overlap` alone (the pre-#774 contract) never mistakes an unresolved
    comparison for a computed empty one; `overlap_detail` carries the reason.
    A refused pattern on the derived-held `lane` side also stops `availability`
    from reading `available` -- the dangerous direction, since a real collision
    hiding behind an unchecked pattern would otherwise render as clear to
    dispatch on.
    """
    if not lane_patterns and not against_patterns and derived_held is None:
        return None
    a = (
        select_issues_overlap.resolve_lane(repo, lane_patterns)
        if lane_patterns
        else None
    )
    a_refused = _refused_patterns(a)
    availability = None
    overlap_state = "n/a"
    overlap_detail = ""
    if derived_held is not None:
        if derived_held["state"] != "resolved":
            b = None
            overlap = None
            if a is not None:
                availability = {
                    "state": "could-not-derive-the-held-set",
                    "files": [],
                    "holders": [],
                    "detail": derived_held["detail"],
                }
        else:
            held_files = sorted(derived_held["held"])
            b = (
                select_issues_overlap.resolve_lane(repo, held_files)
                if held_files
                else {"patterns": [], "files": []}
            )
            # #774, audit round: a held FILE can trip `_lane_pattern_problem`
            # exactly the way a hand-typed pattern can -- a real git-tracked path
            # containing '|' is legal on the filesystems this loop runs on, and
            # `resolve_lane` gives it the identical `refused` state either way.
            # Checking only `a_refused` left a refused held file silently
            # dropping out of `b["files"]`, so a lane whose own pattern resolved
            # cleanly could still read `available` while one of the files it was
            # meant to be checked against was never actually compared -- the
            # same dangerous direction the `a_refused` branch below exists to
            # close, just on the other side of the comparison.
            b_refused = _refused_patterns(b)
            if a is None:
                overlap = None
            elif a_refused or b_refused:
                # #774: a refused pattern on either side means this comparison
                # never ran for it -- rendering `available` here would be the
                # dangerous direction (a real collision hiding behind an
                # unchecked pattern reads as clear to dispatch on), so this is
                # its own state rather than folding into either `available` or
                # `blocked`.
                overlap = None
                overlap_state = "could-not-check"
                overlap_detail = _unresolved_overlap_detail(a, a_refused, b, b_refused)
                availability = {
                    "state": "could-not-check",
                    "files": [],
                    "holders": [],
                    "detail": overlap_detail,
                }
            else:
                overlap = select_issues_overlap.lane_overlap(a["files"], b["files"])
                overlap_state = "resolved"
                if overlap:
                    holders = []
                    for f in overlap:
                        for h in derived_held["held"].get(f, []):
                            if h not in holders:
                                holders.append(h)
                    availability = {
                        "state": "blocked",
                        "files": overlap,
                        "holders": holders,
                        "detail": "",
                    }
                elif select_issues_overlap._lane_resolved_to_nothing(a):
                    # #809: every member of the lane side was well-formed and
                    # checked, and the union still names zero files (an empty
                    # glob, an empty directory, or a mix of the two). `overlap`
                    # is `[]` here for the same reason it would be for a real,
                    # disjoint, non-empty lane -- an empty set intersects
                    # nothing -- so `overlap` alone cannot tell the two apart.
                    # This must not read `available`: a lane nobody managed to
                    # name is not a lane confirmed free.
                    overlap_state = "resolved-to-nothing"
                    availability = {
                        "state": "resolved-to-nothing",
                        "files": [],
                        "holders": [],
                        "detail": "this lane names no file on disk, so nothing "
                        "was compared against the held set (#809)",
                    }
                else:
                    availability = {
                        "state": "available",
                        "files": [],
                        "holders": [],
                        "detail": "",
                    }
    else:
        b = (
            select_issues_overlap.resolve_lane(repo, against_patterns)
            if against_patterns
            else None
        )
        b_refused = _refused_patterns(b)
        if a is None or b is None:
            overlap = None
        elif a_refused or b_refused:
            # #774: the wider half of #766 -- a refused pattern on either side
            # means the comparison never ran, and must never render as the
            # same `none` a real, checked, disjoint pair also prints.
            overlap = None
            overlap_state = "could-not-check"
            overlap_detail = _unresolved_overlap_detail(a, a_refused, b, b_refused)
        else:
            overlap = select_issues_overlap.lane_overlap(a["files"], b["files"])
            overlap_state = "resolved"
            if select_issues_overlap._lane_resolved_to_nothing(
                a
            ) or select_issues_overlap._lane_resolved_to_nothing(b):
                # #809: same reading as the `--derive-held` branch above -- an
                # empty `overlap` from a side that named no file on disk is not
                # the same claim as an empty `overlap` from two real, checked,
                # disjoint sets, so the receipt's `overlap :` line must not
                # print `none` for both. Checked on *both* sides here, unlike
                # the `--derive-held` branch: `--against PATTERN` is itself a
                # maintainer-typed pattern (dispatch.md's own documented
                # fallback), not a derived held set, so it can resolve to
                # nothing exactly the way `--lane` can -- an empty `overlap`
                # from a typo'd or `**`-broken `--against` glob must not read
                # as "checked, disjoint" either. Plain `--against` mode has no
                # `availability` verdict to correct (that field only exists
                # under `--derive-held`), so this is the only render this
                # branch can carry the distinction on.
                overlap_state = "resolved-to-nothing"
    # #566: `repo` is threaded through so each guard's `status` is answered against
    # the repository the lane is actually dispatched into, never against claude-oss's
    # own tree by default -- the whole defect this issue is about.
    guards = guards_for_files(a["files"], repo) if a else []
    result = {
        "lane": a,
        "against": b,
        "overlap": overlap,
        "overlap_state": overlap_state,
        "overlap_detail": overlap_detail,
        "guards": guards,
    }
    if derived_held is not None:
        # #734, review round: `derived_held["lanes"]["stale_pruned"]` names every
        # registry record this call's own `derive_held_set` deleted as a side
        # effect (a branch it corroborated as locally gone) -- surfaced here so a
        # caller can see what was pruned rather than the deletion happening with
        # no trace anywhere in this payload. Absent on the two shapes that carry
        # no `lanes` sub-dict at all (no config loaded; a hand-built `derived_held`
        # in an older test fixture), which is exactly "nothing pruned", not a
        # different claim. `prune_failed` (#792) is the sibling of that same
        # side effect gone wrong -- a record the deletion attempt could not
        # actually remove -- and is surfaced the same way, never folded into
        # `stale_pruned`.
        result["held_source"] = {
            "state": derived_held["state"],
            "detail": derived_held["detail"],
            "stale_pruned": derived_held.get("lanes", {}).get("stale_pruned", []),
            "prune_failed": derived_held.get("lanes", {}).get("prune_failed", []),
        }
        result["availability"] = availability
    return result


#: `linked_worktree_state`'s own return values -- a repository's ordinary
#: working tree, a linked worktree `git worktree add` cut, or "git did not
#: answer either call" (never folded into `WORKTREE_MAIN`, which would let
#: #865 back in through the one case this function exists to catch).
WORKTREE_MAIN = "main"
WORKTREE_LINKED = "linked"
WORKTREE_COULD_NOT_TELL = "could-not-tell"
