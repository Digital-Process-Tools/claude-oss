"""``check_vanished_worktrees`` -- one check, in its own module per the #497/#630
convention.

#845: two independently reported instances of a lane's own worktree directory
disappearing mid-run, caused by no command the lane itself ran -- once twice
in the same run, once as a sub-manager's own `git worktree remove` deleting a
*different*, still-live lane's tree and branch. #845's own investigation
found no `git worktree remove` / `rmtree` call anywhere in `scripts/` or
`skills/` that touches a git worktree directory, so the mechanism was not
identified in this plugin's own code. This is the loud detector #845 asks
for instead of a fabricated fix: `lane_setup.detect_vanished_worktrees`
flags a live registry record whose own worktree directory is confirmed
absent, and this check is what makes that reach a maintainer unprompted,
the same way `check_trap_queue` is the forcing function for its own queue.

Reported, never blocking -- the same choice #905 made for the trap queue,
for the same reason: a live lane record whose worktree vanished is a fact
to react to, not a fact that should refuse every other diagnostic line.

Every shared name is reached through `doctor` imported as a module, so a
test's `monkeypatch.setattr(doctor, ...)` still reaches this code after a
future move, the same convention `doctor_check_trap_queue.py` documents.
"""

import doctor

try:
    import lane_setup
except ImportError:  # pragma: no cover - the module sits beside this file
    lane_setup = None


def check_vanished_worktrees(project_dir, config):
    """#845: any live lane record whose own worktree directory is already gone.

    `unknown` is a real, common state -- no registry, or nothing live -- and
    is reported as `OK`, the same way `check_trap_queue` reports its own
    `none` as `OK` rather than as a silence. `could-not-run` is kept apart
    from both: a registry that could not be read is not a confirmed absence
    of vanished worktrees, so it is reported as `WARN`, never folded into the
    clean state.
    """
    if lane_setup is None:
        doctor.report(
            "WARN",
            "vanished worktrees: not checked (scripts/lane_setup.py could not be imported)",
        )
        return
    worktree_root = config.get("worktree_root") if config else None
    if not worktree_root:
        # Found by this lane's own auditor round (#845): this is a genuine skip --
        # `detect_vanished_worktrees` is never called below -- and this repository's
        # own convention (`doctor.unmeasured`'s docstring, and the sibling
        # `worktree_root` check `main()` runs two lines earlier) is that a skip is
        # WARN, never OK. OK is reserved for a check that actually ran and came back
        # clean; this line used to render the two identically.
        doctor.report(
            "WARN",
            "vanished worktrees: not checked -- worktree_root is not known in this tree "
            "(expected inside a worktree this loop cut rather than the main clone).",
        )
        return
    result = lane_setup.detect_vanished_worktrees(worktree_root)
    if result["state"] == "could-not-run":
        doctor.report(
            "WARN",
            "vanished worktrees: could not be checked -- {}. UNKNOWN, not clean: nothing "
            "here has been shown to be free of a vanished worktree.".format(
                result["detail"]
            ),
        )
        return
    if result["state"] == "unknown":
        doctor.report(
            "OK",
            "vanished worktrees: none to check -- {}".format(
                result["detail"] or "no live lane records."
            ),
        )
        return
    vanished = result["vanished"]
    if not vanished:
        doctor.report(
            "OK",
            "vanished worktrees: none -- every live lane record's own directory is present.",
        )
        return
    doctor.report(
        "WARN",
        "vanished worktrees: {} live lane record(s) whose own worktree directory is "
        "confirmed absent ({}) -- see #845: the mechanism is not identified in this "
        "plugin's own code. Do not assume the branch is lost -- its commits are usually "
        "still reachable via `git reflog` / `git cat-file` on the shared clone.".format(
            len(vanished),
            ", ".join("#{0}".format(v["issue"]) for v in vanished),
        ),
    )
