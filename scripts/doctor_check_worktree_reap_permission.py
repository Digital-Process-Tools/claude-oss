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

import json

from doctor_check_merge_permission import (
    _entry_count,
    _permission_entries,
    _permission_rule_state,
    settings_candidates,
)

import doctor

WORKTREE_REMOVE_OP = "git worktree remove"
BRANCH_DELETE_OP = "git branch -D"
REAP_RULE_FILE = ".claude/settings.local.json"

# #886: the substring test `_permission_rule_state` performs is blind to a
# *covering* wildcard rule -- `Bash(git *)` grants `git worktree remove` under
# Claude Code's own permission matcher, but `"git worktree remove" in "Bash(git
# *)"` is False, so the substring test renders `absent`, the state that means
# "nobody granted this". `absent` and "granted by a wildcard the substring test
# cannot read" must not collapse into the same state.
#
# What this deliberately does NOT do: interpret what a wildcard covers. That is
# Claude Code's own permission matcher's job (a dotall regex built from the
# rule, per its own source), and reimplementing it here would be a second copy
# of somebody else's classification -- CLAUDE.md forbids exactly that, for
# reasons this repository has already paid for. This only asks a narrower,
# non-semantic question: does a Bash allow entry contain a bare `*` this
# substring test was never going to be able to read? A rule using the
# documented `name:*` prefix suffix (`Bash(git branch -D:*)`,
# `Bash(git worktree remove:*)`) is left alone -- those are already handled
# correctly today, either by the literal substring test (when the op text is
# literally present) or are a distinct, unfiled gap (a broad prefix like
# `Bash(git:*)`) rather than the one #886 measured and asked for.
#
# The wildcard scan is scoped to the op's own first word (`git`, for both ops
# this module checks), never to "any Bash entry with a `*` anywhere in the
# settings file". An unrelated grant -- `Bash(npm *)`, `Bash(curl *)` -- cannot
# cover a `git` op under any wildcard semantics, and flagging it anyway would
# turn a genuine `absent` into a false "might already be covered", which is
# the opposite direction from the defect #886 was filed for. Comparing the
# entry's own first token to the op's first token is a structural read, not a
# guess about what the wildcard matches -- the same restraint the substring
# test itself already exercises by keying on the full op text.
WILDCARD_MARKER = "*"
PREFIX_SUFFIX = ":*"


def _entry_command_head(entry):
    """The first whitespace-separated token inside a `Bash(...)` rule's
    parentheses, or None if `entry` is not shaped like a Bash rule. Purely
    structural parsing -- no wildcard interpretation."""
    if not entry.startswith("Bash(") or not entry.endswith(")"):
        return None
    content = entry[len("Bash(") : -1]
    parts = content.split(None, 1)
    return parts[0] if parts else None


def _bash_wildcard_allow_detail(project_dir, op, home=None):
    """Count-and-file detail (same convention as `_permission_rule_state`,
    never the entry text) for Bash allow entries whose command head matches
    `op`'s own first word and which contain a bare wildcard -- one this
    check's substring test cannot resolve either way. Empty string when none
    exist."""
    op_head = op.split(None, 1)[0]
    found = []
    for path in settings_candidates(project_dir, home=home):
        try:
            if not path.exists():
                continue
        except OSError:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        matches = [
            e
            for e in _permission_entries(data, "allow")
            if WILDCARD_MARKER in e
            and PREFIX_SUFFIX not in e
            and _entry_command_head(e) == op_head
        ]
        if matches:
            found.append(_entry_count(len(matches), "allow", path))
    return "; ".join(found)


def worktree_remove_permission_state(project_dir, home=None):
    """Is there a settings rule naming `git worktree remove`? See
    `doctor_check_merge_permission._permission_rule_state` for the four answers
    and why an unreadable neighbour never wins over a rule that was actually
    read. A fifth answer, `cannot-tell-whether-covered`, replaces `absent` when
    a Bash allow entry whose command head is `git` also contains a bare
    wildcard this substring test cannot resolve -- see the module docstring
    above `_bash_wildcard_allow_detail`."""
    state, detail = _permission_rule_state(
        project_dir, lambda e: WORKTREE_REMOVE_OP in e, home=home
    )
    if state == "absent":
        wildcard_detail = _bash_wildcard_allow_detail(
            project_dir, WORKTREE_REMOVE_OP, home=home
        )
        if wildcard_detail:
            return "cannot-tell-whether-covered", wildcard_detail
    return state, detail


def branch_delete_permission_state(project_dir, home=None):
    """Is there a settings rule naming `git branch -D`? Same five answers, same
    caveats, as `worktree_remove_permission_state` above -- independent of it,
    per the issue: a rule granting one command says nothing about the other."""
    state, detail = _permission_rule_state(
        project_dir, lambda e: BRANCH_DELETE_OP in e, home=home
    )
    if state == "absent":
        wildcard_detail = _bash_wildcard_allow_detail(
            project_dir, BRANCH_DELETE_OP, home=home
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
    doctor.report(
        "WARN",
        "no settings rule names {}, so the first merge whose worktree reap is "
        "declined will send you to run it by hand and be denied by the auto "
        "mode classifier. Add `Bash({}:*)` to {} (machine scope, untracked) "
        "before the first merge. A rule is not the only thing that can allow "
        "or deny this call, so this is not a prediction that it will be "
        "denied.".format(BRANCH_DELETE_OP, BRANCH_DELETE_OP, REAP_RULE_FILE),
    )
