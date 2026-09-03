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
# correctly today by the literal substring test (when the op text is
# literally present). A broad, command-name-level prefix (`Bash(git:*)`) was
# a distinct, unfiled gap at the time this paragraph was first written -- see
# the #895 paragraph below for why it is no longer unfiled.
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
#
# #895: the scan above deliberately excluded the documented `name:*` PREFIX
# syntax (`PREFIX_SUFFIX not in e`) because that suffix is also used for an
# op-specific grant (`Bash(git worktree remove:*)`, already handled by the
# literal substring test) and a sibling-op grant (`Bash(git branch -D:*)`,
# correctly left `absent` for this op). But the SAME suffix, applied to the
# bare command name with nothing else in front of it (`Bash(git:*)`), is a
# third, distinct shape: the documented command-name-level prefix grant,
# which covers `git worktree remove` exactly as broadly as `Bash(git *)`
# does. #886's exclusion swept that shape out along with the two it meant to
# exclude, and #895 is the filing for it. `_entry_prefix_wildcard_head`
# recognises only that third shape -- a bare command name immediately
# followed by `:*`, no space anywhere in it -- so `Bash(git worktree
# remove:*)` and `Bash(git branch -D:*)` are untouched (both contain a
# space before `:*`, so `head` here would carry the space and never equal a
# bare op_head).
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


def _entry_prefix_wildcard_head(entry):
    """The bare command name inside a `Bash(name:*)` command-name-level
    prefix rule (`Bash(git:*)`), or None if `entry` is not shaped like one.
    Deliberately narrower than `content.endswith(PREFIX_SUFFIX)` alone: an
    op-specific prefix grant such as `Bash(git worktree remove:*)` also ends
    in `:*`, but its content before the suffix contains whitespace, so it is
    excluded here (it is not this shape -- it is the literal, already-handled
    one, or a sibling op's own grant that must stay `absent` for this op)."""
    if not entry.startswith("Bash(") or not entry.endswith(")"):
        return None
    content = entry[len("Bash(") : -1]
    if not content.endswith(PREFIX_SUFFIX):
        return None
    head = content[: -len(PREFIX_SUFFIX)]
    if not head or any(ch.isspace() for ch in head):
        return None
    return head


def _bash_wildcard_allow_detail(project_dir, op, home=None):
    """Count-and-file detail (same convention as `_permission_rule_state`,
    never the entry text) for Bash allow entries whose command head matches
    `op`'s own first word and which contain a bare wildcard, OR whose
    command-name-level prefix (`Bash(git:*)`, #895) matches it -- either
    shape this check's substring test cannot resolve either way. Empty
    string when none exist."""
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
            if (
                WILDCARD_MARKER in e
                and PREFIX_SUFFIX not in e
                and _entry_command_head(e) == op_head
            )
            or _entry_prefix_wildcard_head(e) == op_head
        ]
        if matches:
            found.append(_entry_count(len(matches), "allow", path))
    return "; ".join(found)


def _bash_wildcard_deny_detail(project_dir, op, home=None):
    """#892: the deny-side sibling of `_bash_wildcard_allow_detail` above --
    same bare-wildcard shape (`Bash(git *)`), same op-head scoping, same
    "count and file, never the text" convention, but scanning `deny` entries
    instead of `allow`.

    #892's own issue and test shape named only the bare wildcard, but this
    now also matches the command-name-level `name:*` prefix shape
    (`Bash(git:*)`, #895's own shape) on the deny side too: leaving it out
    reproduced the exact defect #892 was filed to fix, one spelling over --
    `oss:auditor`'s own review of this diff caught it directly (a
    `deny=["Bash(git:*)"]` fixture rendered `absent` rather than
    `cannot-tell-whether-forbidden`), the same "unfiled gap" shape that #895
    itself was born from on the allow side. Fixed in the same diff rather
    than filed separately: same file, same helper, same one-line mechanism
    already proven correct on the allow side by `_entry_prefix_wildcard_head`
    -- reusing it here, not reimplementing it. Empty string when none
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
            for e in _permission_entries(data, "deny")
            if (
                WILDCARD_MARKER in e
                and PREFIX_SUFFIX not in e
                and _entry_command_head(e) == op_head
            )
            or _entry_prefix_wildcard_head(e) == op_head
        ]
        if matches:
            found.append(_entry_count(len(matches), "deny", path))
    return "; ".join(found)


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
            project_dir, WORKTREE_REMOVE_OP, home=home
        )
        if deny_wildcard_detail:
            return "cannot-tell-whether-forbidden", deny_wildcard_detail
        wildcard_detail = _bash_wildcard_allow_detail(
            project_dir, WORKTREE_REMOVE_OP, home=home
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
            project_dir, BRANCH_DELETE_OP, home=home
        )
        if deny_wildcard_detail:
            return "cannot-tell-whether-forbidden", deny_wildcard_detail
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
