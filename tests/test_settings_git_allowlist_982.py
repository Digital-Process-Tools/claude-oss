"""#982: `.claude/settings.json` used to grant the blanket `Bash(git *)`, flagged
during #899's own review as wider than it needed to be but left tracked (#609's own
reasoning, reaffirmed by #899, recorded in the comment above `scaffold.SETTINGS_PATH`).
#899 asked for the narrowing to enumerate every git subcommand the loop's own briefs
actually invoke, rather than a guess at what "looks safe" -- so this module IS that
enumeration, not a re-derivation of it at test time: the set below is hand-verified
against `agents/*.md`, `agents/developer/*.md`, `commands/*.md` and
`skills/manager/**/*.md` (grep for `` `?git [a-z-]+ `` plus manual reading of every hit
to separate an actual invocation from prose *mentioning* git's own behaviour --
`` `git describe` returns the newest tag of any namespace `` is prose, `` git fetch -q
origin `` in a code fence is an invocation). Re-deriving that judgment call
automatically inside this test would just be a second, less careful copy of the same
reading; a mechanical grep over the repo cannot itself tell a mention from a call.

What the enumeration found, and why some entries are op-level rather than
subcommand-level:

- `git commit` is deliberately EXCLUDED. `agents/developer.md` and
  `skills/manager/phases/dispatch.md` both say "never a raw `git commit -m`" --
  every commit goes through `supertool 'git-commit:@-'`, which is a `Bash(supertool:*)`
  call already granted and does not need `Bash(git commit:*)` at all. Granting it back
  would reopen exactly the raw-commit path those two files tell every lane not to use.
- `git worktree` and `git branch` are granted at the OP level
  (`git worktree add`, `git worktree remove`, `git branch -D`, `git branch -r`)
  rather than the bare subcommand. Two reasons: (1) `skills/manager/SKILL.md:187` says
  the raw `git worktree` *listing* is refused in favour of supertool's own
  `git-worktrees` op, so a bare `Bash(git worktree:*)` grant would hand back a path the
  loop's own brief says not to use; (2) `scripts/doctor_check_worktree_reap_permission.py`
  (#787/#895) tests literally for the strings `"git worktree remove"` and
  `"git branch -D"` inside a settings allow entry -- a bare `Bash(git worktree:*)` or
  `Bash(git branch:*)` would NOT contain those substrings, silently flipping doctor's own
  reap-permission check from `present`/`cannot-tell-whether-covered` to a plain `absent`
  that undersells a grant that (via Claude Code's real prefix matcher) is actually there.
  Keeping the exact op-level spelling this repo's own doctor check already expects avoids
  introducing that regression in the same change that narrows the grant.
- `git show` appears in the issue's OWN preflight pattern
  (`git (status|log|diff|worktree|branch|fetch|pull|push|commit|checkout|rev-parse|show)`)
  but no actual `git show` invocation was found anywhere in the briefs -- that pattern was
  the preflight's own illustrative regex, not a spec of the exact subcommand set. Left out
  on the same "enumerate what is actually invoked" rule the issue itself states; add it
  back in a follow-up the day something legitimately needs it.

**The known, load-bearing limitation, stated rather than hidden:** Claude Code's
`Bash(<prefix>:*)` allow syntax matches a literal STRING PREFIX of the whole command, not
"this subcommand with a restricted argument set". A subcommand-level (or even op-level)
grant excludes entirely different, more destructive subcommands the loop never calls at
all (`reset`, `clean`, `rebase`, `filter-branch`, `gc`, `reflog expire`, `stash drop`,
`update-ref`, ...) -- that IS real, structural safety this change buys. It does NOT let a
grant for `git push` or `git checkout` exclude a dangerous flag on an otherwise-legitimate
call (`git push --force`, `git checkout .`): those stay exactly as reachable under the
narrowed grant as they were under the blanket one, restrained only by the same brief-level
"never `git push --delete`" prose that restrained them before (`skills/manager/phases/
merge.md`). This module's negative control below only proves the excluded-subcommand half;
it cannot and does not claim the flag-level half, because the permission syntax cannot
express it.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"

# Subcommand -> the file:line an actual (non-prose) invocation was found at, kept here
# so a future reader can re-verify a single row without repeating the whole sweep.
REQUIRED_SUBCOMMAND_GRANTS = {
    "git status": "agents/developer/review.md (self-review status check)",
    "git log": "skills/manager/SKILL.md:629, phases/release.md:47",
    "git diff": "agents/developer/review.md:54",
    "git fetch": "agents/developer.md:58, commands/tick.md:145",
    "git pull": "commands/tick.md:145 (git fetch && git pull --ff-only)",
    "git push": "agents/sub-manager.md:62, commands/release.md:436 (git push origin <tag>)",
    "git add": "commands/release.md:425 (stage explicit release paths)",
    "git mv": "skills/manager/phases/handback.md:89 (renaming a changelog fragment)",
    "git checkout": "agents/developer/review.md:66 (git checkout -- <path> recovery)",
    "git rev-parse": "agents/developer.md:51, skills/manager/phases/release.md:43",
    "git rev-list": "skills/manager/phases/accounting.md:234 (git rev-list --count)",
    "git ls-remote": "agents/releaser.md:90, commands/release.md:433",
    "git ls-files": "commands/install-audit.md:40, commands/setup.md:66",
    "git symbolic-ref": "agents/developer.md:51",
    "git remote": "agents/developer.md:51 (git remote -v)",
    "git describe": "agents/release-auditor.md:64",
    "git grep": "commands/release.md:330 (git grep for the new version string)",
    "git tag": "agents/sub-manager.md:62, commands/release.md:488",
}

# Op-level (not bare-subcommand) grants -- see the module docstring for why worktree and
# branch stay narrower than the rest of the table above.
REQUIRED_OP_GRANTS = {
    "git worktree add": "agents/developer.md:59, commands/tick.md:512",
    "git worktree remove": "skills/manager/phases/merge.md:114; doctor's own WORKTREE_REMOVE_OP",
    "git branch -D": "commands/doctor.md:486; doctor's own BRANCH_DELETE_OP",
    "git branch -r": "skills/manager/phases/merge.md:125 (git branch -r --merged)",
}

# Never invoked by the loop's own briefs anywhere, and each one materially more
# destructive than anything in the two tables above -- the negative control half of the
# "must fire" / "must not fire" pair CLAUDE.md asks for.
MUST_NOT_BE_GRANTED = [
    "git reset",
    "git clean",
    "git rebase",
    "git filter-branch",
    "git gc",
    "git reflog",
    "git stash drop",
    "git update-ref",
    "git commit",
]


def _load_settings():
    text = SETTINGS_PATH.read_text(encoding="utf-8")
    return json.loads(text)


def _allow_entries():
    document = _load_settings()
    return document.get("permissions", {}).get("allow", [])


def test_settings_file_is_valid_json_with_an_allow_list():
    entries = _allow_entries()
    assert isinstance(entries, list)
    assert entries, "permissions.allow must not be empty"


def test_the_blanket_git_wildcard_is_gone():
    """The defect #982 was filed against: `Bash(git *)` (and the equivalent
    command-name-level prefix spelling `Bash(git:*)`, #895's own documented shape)
    both cover every git subcommand there is, which is exactly what this issue asks
    to narrow away."""
    entries = _allow_entries()
    assert "Bash(git *)" not in entries
    assert "Bash(git:*)" not in entries
    for entry in entries:
        if not entry.startswith("Bash(git"):
            continue
        content = entry[len("Bash(") : -1] if entry.endswith(")") else entry
        # No entry may be a bare `git *` / `git*` shape -- every git grant must name
        # a specific subcommand (or op) before its `:*` suffix.
        assert content not in ("git *", "git*"), entry


@pytest.mark.parametrize("subcommand,source", sorted(REQUIRED_SUBCOMMAND_GRANTS.items()))
def test_every_real_subcommand_invocation_stays_covered(subcommand, source):
    """Must-fire half: every subcommand the loop's own briefs actually invoke keeps a
    working grant after the narrowing, or the next lane to run that call gets stopped
    for a permission it used to have. `source` is not asserted on; it is carried so a
    failure message points a reader straight at the citation that earned this row a
    place in the table."""
    entries = _allow_entries()
    expected = "Bash({}:*)".format(subcommand)
    assert expected in entries, (
        "{} is invoked at {} but no {} grant is present".format(
            subcommand, source, expected
        )
    )


@pytest.mark.parametrize("op,source", sorted(REQUIRED_OP_GRANTS.items()))
def test_every_real_op_level_invocation_stays_covered(op, source):
    entries = _allow_entries()
    expected = "Bash({}:*)".format(op)
    assert expected in entries, (
        "{} is invoked at {} but no {} grant is present".format(op, source, expected)
    )


@pytest.mark.parametrize("dangerous", MUST_NOT_BE_GRANTED)
def test_subcommands_never_invoked_by_the_loop_stay_ungranted(dangerous):
    """Must-not-fire half, paired with the two tests above: a subcommand nothing in
    the loop's own briefs ever calls must not gain a grant just because the narrowing
    touched this file -- `git commit` most of all, since granting it back would reopen
    the raw-commit path `agents/developer.md` and `skills/manager/phases/dispatch.md`
    both tell every lane never to use."""
    entries = _allow_entries()
    assert "Bash({}:*)".format(dangerous) not in entries
    # A bare wildcard would also cover it -- already asserted absent above, repeated
    # here so this test alone still catches a regression that reintroduces one.
    assert "Bash(git *)" not in entries


def test_doctor_worktree_and_branch_permission_checks_still_see_present():
    """Regression guard for the exact gap the module docstring names: doctor's own
    `worktree_remove_permission_state` / `branch_delete_permission_state` (#787/#895)
    read this file with a literal substring test over `"git worktree remove"` /
    `"git branch -D"`. If the narrowing had used a bare `Bash(git worktree:*)` or
    `Bash(git branch:*)` grant instead of the op-level spelling, these would have
    silently regressed from `present` to `absent` -- the exact "absence produced by
    the tool, read as an absence in the world" defect CLAUDE.md names at the top."""
    import sys

    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    # `doctor` must be imported before its check submodules: `doctor_check_
    # merge_permission` does `import doctor` at module level, and importing a
    # check submodule first (with `doctor` not yet in `sys.modules`) triggers a
    # circular ImportError when `doctor.py` itself later does `from doctor_check_
    # merge_permission import MERGE_OP, ...` while that module is still mid-load.
    # Every other test in this suite that reaches these checks imports `doctor`
    # first for the same reason (see tests/test_doctor_inprocess.py).
    import doctor  # noqa: F401
    from doctor_check_worktree_reap_permission import (
        branch_delete_permission_state,
        worktree_remove_permission_state,
    )

    w_state, _ = worktree_remove_permission_state(str(REPO_ROOT))
    b_state, _ = branch_delete_permission_state(str(REPO_ROOT))
    assert w_state == "present", w_state
    assert b_state == "present", b_state
