"""#787: mirrors `doctor_check_merge_permission.py`, one op over -- for the two
hand commands `gh-pr-merge`'s own `|cleanup` falls back to when it declines a
reap (a worktree it cannot confirm `idle`, a branch a worktree still holds):
`git worktree remove --force <path>` and `git branch -D <branch>`. Both are
commonly denied by the Claude Code auto-mode classifier by default, and nothing
told a maintainer that before their first merge sent them into it.

Two checks, not one, per the issue's own author: the two commands are permitted
or denied independently by the classifier, so a rule granting one says nothing
about the other, and folding them into a single check would either under- or
over-report whichever half it carried no state for.

Reuses `doctor_check_merge_permission`'s `_permission_rule_state` and
`settings_candidates` rather than re-implementing the settings-file scan a
third time -- same four states (`present` / `denied` / `absent` / `unknown`),
same two-scope read (project then user), same "count and file, never the
entry text" convention that check already established for exactly this reason
(a tracked, contributor-writable settings file must never gain the ability to
write this script's own output lines).

`doctor.py` imports the four public names below back out of this module
immediately after this docstring's own code is defined, the same pattern
`doctor_check_merge_permission.py` documents for its own two checks -- so
`doctor.check_worktree_remove_permission` etc. answer exactly as they do here,
and a test's `monkeypatch.setattr(doctor, ...)` reaches this module's code.
"""

from doctor_check_merge_permission import _permission_rule_state

import doctor

WORKTREE_REMOVE_OP = "git worktree remove"
BRANCH_DELETE_OP = "git branch -D"
REAP_RULE_FILE = ".claude/settings.local.json"


def worktree_remove_permission_state(project_dir, home=None):
    """Is there a settings rule naming `git worktree remove`? See
    `doctor_check_merge_permission._permission_rule_state` for the four answers
    and why an unreadable neighbour never wins over a rule that was actually
    read."""
    return _permission_rule_state(
        project_dir, lambda e: WORKTREE_REMOVE_OP in e, home=home
    )


def branch_delete_permission_state(project_dir, home=None):
    """Is there a settings rule naming `git branch -D`? Same four answers, same
    caveats, as `worktree_remove_permission_state` above -- independent of it,
    per the issue: a rule granting one command says nothing about the other."""
    return _permission_rule_state(
        project_dir, lambda e: BRANCH_DELETE_OP in e, home=home
    )


def check_worktree_remove_permission(project_dir, home=None):
    """Report the rule, and never more than the rule -- same caveat as
    `check_merge_permission`, carried over verbatim (#787): this is a file
    read, not a probe of the harness, and it must never claim more than that
    a rule exists or does not.
    """
    state, detail = worktree_remove_permission_state(project_dir, home=home)
    if state == "present":
        doctor.report(
            "OK",
            "a settings rule names {} ({}). This is a file read, not a probe of "
            "the harness: it says the rule exists, not that the reap call will "
            "be permitted.".format(WORKTREE_REMOVE_OP, detail),
        )
        return
    if state == "denied":
        doctor.report(
            "WARN",
            "the only settings rule naming {} is a deny rule ({}). gh-pr-merge's "
            "own cleanup falls back to this command by hand on a refused reap, "
            "and it will stop there too.".format(WORKTREE_REMOVE_OP, detail),
        )
        return
    if state == "unknown":
        doctor.report(
            "WARN",
            "could not read {}, so whether a {} rule exists is unknown -- not "
            "answered as absent, because that would send you to add a rule you "
            "may already have.".format(detail, WORKTREE_REMOVE_OP),
        )
        return
    doctor.report(
        "WARN",
        "no settings rule names {}, so the first merge whose worktree reap is "
        "declined will send you to run it by hand and be denied by the auto "
        "mode classifier. Add `Bash({}:*)` to {} (machine scope, untracked) "
        "before the first merge. A rule is not the only thing that can allow "
        "or deny this call, so this is not a prediction that it will be "
        "denied.".format(WORKTREE_REMOVE_OP, WORKTREE_REMOVE_OP, REAP_RULE_FILE),
    )


def check_branch_delete_permission(project_dir, home=None):
    """Sibling to `check_worktree_remove_permission` above -- same wording
    pattern, same caveats, for `git branch -D` instead."""
    state, detail = branch_delete_permission_state(project_dir, home=home)
    if state == "present":
        doctor.report(
            "OK",
            "a settings rule names {} ({}). This is a file read, not a probe of "
            "the harness: it says the rule exists, not that the reap call will "
            "be permitted.".format(BRANCH_DELETE_OP, detail),
        )
        return
    if state == "denied":
        doctor.report(
            "WARN",
            "the only settings rule naming {} is a deny rule ({}). gh-pr-merge's "
            "own cleanup falls back to this command by hand on a refused reap, "
            "and it will stop there too.".format(BRANCH_DELETE_OP, detail),
        )
        return
    if state == "unknown":
        doctor.report(
            "WARN",
            "could not read {}, so whether a {} rule exists is unknown -- not "
            "answered as absent, because that would send you to add a rule you "
            "may already have.".format(detail, BRANCH_DELETE_OP),
        )
        return
    doctor.report(
        "WARN",
        "no settings rule names {}, so the first merge whose worktree reap is "
        "declined will send you to run it by hand and be denied by the auto "
        "mode classifier. Add `Bash({}:*)` to {} (machine scope, untracked) "
        "before the first merge. A rule is not the only thing that can allow "
        "or deny this call, so this is not a prediction that it will be "
        "denied.".format(BRANCH_DELETE_OP, BRANCH_DELETE_OP, REAP_RULE_FILE),
    )
