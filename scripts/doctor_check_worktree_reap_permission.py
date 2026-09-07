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

from doctor_check_merge_permission import (
    _bash_wildcard_allow_detail,
    _bash_wildcard_deny_detail,
    _permission_rule_state,
)

import doctor

WORKTREE_REMOVE_OP = "git worktree remove"
BRANCH_DELETE_OP = "git branch -D"
REAP_RULE_FILE = ".claude/settings.local.json"

#: Both ops this module checks are invoked as a bare `git ...` command, so
#: the one command head a covering wildcard has to match is `git` --
#: `_bash_wildcard_allow_detail`/`_bash_wildcard_deny_detail` now take a SET
#: of candidate heads (#1242, generalised for `doctor_check_merge_permission
#: .py`'s own `supertool`/`./supertool` pair), and this module keeps its
#: original single-head behaviour by always passing this one.
_GIT_COMMAND_HEADS = frozenset({"git"})

# #886/#895/#892: the wildcard-scan helpers (`_bash_wildcard_allow_detail`,
# `_bash_wildcard_deny_detail`) used to be defined here, keyed on a single op
# head (`git`, both ops in this module invoke a bare `git ...` command).
# #1242 moved them to `doctor_check_merge_permission.py`, generalised to
# accept a SET of candidate command heads, because that module's own two
# checks need a different head (`supertool`/`./supertool`) to recognise the
# same covering-wildcard shape for `gh-pr-merge` and the supertool call
# itself. Imported back here (see the import block above) so this module
# keeps its existing `git`-only behaviour with no duplicate copy.


def worktree_remove_permission_state(project_dir, home=None):
    """Is there a settings rule naming `git worktree remove`? See
    `doctor_check_merge_permission._permission_rule_state` for the four answers
    and why an unreadable neighbour never wins over a rule that was actually
    read. A fifth answer, `cannot-tell-whether-covered`, replaces `absent` when
    a Bash allow entry whose command head is `git` also contains a bare
    wildcard, or is a command-name-level `name:*` prefix (#895), that this
    substring test cannot resolve -- see the module docstring above
    `_bash_wildcard_allow_detail`. A sixth, `cannot-tell-whether-forbidden`
    (#892), replaces `absent` the same way when the ambiguous bare wildcard is
    on the `deny` side instead -- see `_bash_wildcard_deny_detail`. The two
    are kept as separate state names rather than folded into one, deliberately:
    an allow-side ambiguity means "might already be covered" and a deny-side
    one means "might already be forbidden", and collapsing them loses exactly
    the direction that makes the deny-side case the more dangerous of the two
    (#892's own argument for why it is worse than the gap #886 fixed). Deny is
    checked before allow here, mirroring `_permission_rule_state`'s own "deny
    wins" precedent for the case (nothing in the fixtures currently produces
    it) where both an ambiguous allow and an ambiguous deny wildcard exist for
    the same op head."""
    state, detail = _permission_rule_state(
        project_dir, lambda e: WORKTREE_REMOVE_OP in e, home=home
    )
    if state == "absent":
        deny_wildcard_detail = _bash_wildcard_deny_detail(
            project_dir, _GIT_COMMAND_HEADS, home=home
        )
        if deny_wildcard_detail:
            return "cannot-tell-whether-forbidden", deny_wildcard_detail
        wildcard_detail = _bash_wildcard_allow_detail(
            project_dir, _GIT_COMMAND_HEADS, home=home
        )
        if wildcard_detail:
            return "cannot-tell-whether-covered", wildcard_detail
    return state, detail


def branch_delete_permission_state(project_dir, home=None):
    """Is there a settings rule naming `git branch -D`? Same six answers, same
    caveats, as `worktree_remove_permission_state` above -- independent of it,
    per the issue: a rule granting one command says nothing about the other."""
    state, detail = _permission_rule_state(
        project_dir, lambda e: BRANCH_DELETE_OP in e, home=home
    )
    if state == "absent":
        deny_wildcard_detail = _bash_wildcard_deny_detail(
            project_dir, _GIT_COMMAND_HEADS, home=home
        )
        if deny_wildcard_detail:
            return "cannot-tell-whether-forbidden", deny_wildcard_detail
        wildcard_detail = _bash_wildcard_allow_detail(
            project_dir, _GIT_COMMAND_HEADS, home=home
        )
        if wildcard_detail:
            return "cannot-tell-whether-covered", wildcard_detail
    return state, detail


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
    if state == "cannot-tell-whether-covered":
        doctor.report(
            "WARN",
            "no settings rule literally names {}, but a Bash allow entry with a "
            "wildcard exists ({}) that this check's substring test cannot read -- "
            "it may already cover this op, or may not. Interpreting a wildcard is "
            "Claude Code's own permission matcher's job, not this check's, so this "
            "is not a suggestion to add `Bash({}:*)`: that may already be "
            "redundant. Confirm by attempting the reap once.".format(
                WORKTREE_REMOVE_OP, detail, WORKTREE_REMOVE_OP
            ),
        )
        return
    if state == "cannot-tell-whether-forbidden":
        doctor.report(
            "WARN",
            "no settings rule literally names {}, but a Bash deny entry with a "
            "wildcard exists ({}) that this check's substring test cannot read -- "
            "it may already forbid this op, or may not. This is NOT a suggestion "
            "to add `Bash({}:*)` to an allow list: doing so on a repository that "
            "already denies it via this wildcard would be adding a rule against "
            "the owner's own explicit prohibition. Confirm what the wildcard "
            "covers before adding anything.".format(
                WORKTREE_REMOVE_OP, detail, WORKTREE_REMOVE_OP
            ),
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
    if state == "cannot-tell-whether-covered":
        doctor.report(
            "WARN",
            "no settings rule literally names {}, but a Bash allow entry with a "
            "wildcard exists ({}) that this check's substring test cannot read -- "
            "it may already cover this op, or may not. Interpreting a wildcard is "
            "Claude Code's own permission matcher's job, not this check's, so this "
            "is not a suggestion to add `Bash({}:*)`: that may already be "
            "redundant. Confirm by attempting the reap once.".format(
                BRANCH_DELETE_OP, detail, BRANCH_DELETE_OP
            ),
        )
        return
    if state == "cannot-tell-whether-forbidden":
        doctor.report(
            "WARN",
            "no settings rule literally names {}, but a Bash deny entry with a "
            "wildcard exists ({}) that this check's substring test cannot read -- "
            "it may already forbid this op, or may not. This is NOT a suggestion "
            "to add `Bash({}:*)` to an allow list: doing so on a repository that "
            "already denies it via this wildcard would be adding a rule against "
            "the owner's own explicit prohibition. Confirm what the wildcard "
            "covers before adding anything.".format(
                BRANCH_DELETE_OP, detail, BRANCH_DELETE_OP
            ),
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
