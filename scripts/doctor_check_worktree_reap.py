"""#1628: is any worktree under `worktree_root` actually reapable right now,
and does this repository offer one runnable command to reap it? Per this
file's own #497/#630 convention -- a new check gets its own module, never
added straight into `scripts/doctor.py`.

Pairs with `doctor_check_worktree_reap_permission.py` (#787): that module
asks whether `git worktree remove --force` and `git branch -D` are even
PERMITTED; this one asks whether anything is actually WAITING to be removed,
and names `scripts/worktree_reap.py --apply` as the remedy -- the same
"remedy has to be runnable, per `doctor-check-contract.md` test 2" shape
every other WARN in this file already follows.

**Report-only, never `--apply` on its own** -- this check calls
`worktree_reap.plan_reap`, which touches nothing; the remedy line names the
command for a human or an agent to run by hand, the same restraint
`doctor_check_stale_branches.check_stale_branches` states for the identical
reason (an administrative removal with no preview is not something a
diagnostic performs on your behalf).

Three states, never two, per this repository's own named defect class:
`ok` (nothing reapable, or nothing configured to check), a finding (one or
more reapable trees), and `could-not-tell` (enumeration itself failed, or a
tree's own state could not be read) -- the third must never collapse into
"nothing to report".

`doctor.py` imports `check_worktree_reap` back out of this module
immediately after this docstring's own code is defined, the same pattern
every sibling module documents.
"""

from pathlib import Path

import doctor
import worktree_reap


def worktree_reap_summary(
    project_dir, config, run=None, gh_bin=None, list_processes=None
):
    """`("ok", detail)` / `("finding", detail)` / `("could-not-tell", detail)`.

    `detail` is a dict: `reapable` (count), `could_not_tell` (count), `kept`
    (count), `remedy` (the runnable command, or `None`), `reason` (only set
    for `could-not-tell`).

    `gh_bin`/`list_processes` are passed straight through to `plan_reap` --
    test-only injection points, never used by `check_worktree_reap` below,
    which always reads the real tracker and the real process table.
    """
    clone = (config or {}).get("clone") if config else None
    if not clone:
        return "could-not-tell", {"reason": "no clone configured"}
    state, plan = worktree_reap.plan_reap(
        clone, config, run=run, gh_bin=gh_bin, list_processes=list_processes
    )
    if state == "could-not-tell":
        return "could-not-tell", {"reason": plan}
    reapable = sum(1 for item in plan if item["decision"] == "reapable")
    could_not_tell = sum(1 for item in plan if item["decision"] == "could-not-tell")
    kept = sum(1 for item in plan if item["decision"] == "kept")
    script = str(Path(doctor.PLUGIN_ROOT) / "scripts" / "worktree_reap.py")
    remedy = "python3 {} --clone {} --apply".format(script, clone)
    if reapable:
        return "finding", {
            "reapable": reapable,
            "could_not_tell": could_not_tell,
            "kept": kept,
            "remedy": remedy,
        }
    if could_not_tell:
        return "could-not-tell", {
            "reason": "{} worktree(s) could not be evaluated (occupancy or merge "
            "state unknown) -- never reaped on an absent answer".format(could_not_tell),
            "reapable": 0,
            "could_not_tell": could_not_tell,
            "kept": kept,
        }
    return "ok", {"reapable": 0, "could_not_tell": 0, "kept": kept}


def check_worktree_reap(
    project_dir, config, run=None, gh_bin=None, list_processes=None
):
    state, detail = worktree_reap_summary(
        project_dir, config, run=run, gh_bin=gh_bin, list_processes=list_processes
    )
    if state == "ok":
        doctor.report(
            "OK",
            "worktree reap: no reapable worktrees ({} kept)".format(detail["kept"]),
        )
        return
    if state == "finding":
        doctor.report_with_remedy(
            "WARN",
            "worktree reap: {} worktree(s) are merged, unoccupied and clean (or "
            "carry only lane scratch output) -- reapable now. {} kept, {} could "
            "not be evaluated.".format(
                detail["reapable"], detail["kept"], detail["could_not_tell"]
            ),
            detail["remedy"],
        )
        return
    doctor.report(
        "WARN",
        "worktree reap: could not be checked -- {}. UNKNOWN, not clean: nothing "
        "here has been shown to be free of a reapable worktree.".format(
            detail["reason"]
        ),
    )
