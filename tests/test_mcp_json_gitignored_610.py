"""#610: `.mcp.json` in THIS repo, and why it must never be committable.

Measured on this checkout: `.mcp.json` names a `claude-channel` MCP server with an
absolute path into one machine's clone of `claude-supertool` --

    {"mcpServers": {"claude-channel": {"command": "bun",
      "args": ["/Users/.../claude-supertool/notifiers/claude-channel/channel.ts"]}}}

-- and it was excluded only in `.git/info/exclude`, which is per-clone and
invisible to anyone else's checkout. A second maintainer's clone has no
exclusion at all: creating the identical file there for the identical local
convenience would show up as untracked-and-uncommittable-by-luck rather than
by rule, and a `git add -A` would happily stage one machine's absolute path.

`bin/oss-workspace` already solves the problem this file exists for --
portably, at local scope, resolved from the installed supertool plugin rather
than from a checkout -- so this repo does not need a tracked `.mcp.json` of its
own the way `claude-supertool`'s own repo does (`${CLAUDE_PLUGIN_ROOT}` there
resolves to supertool's own root; here it would resolve to THIS plugin's root,
which ships no notifier). The fix is not to track the file -- deleting it
matched the launcher's coverage on this machine at the time #610 was filed --
it is to move the exclusion into the TRACKED `.gitignore`, the way `/supertool`
(another machine-specific path) is already handled a few lines above, so the
rule travels with the repo instead of living on one disk.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_this_repos_own_gitignore_keeps_mcp_json_uncommittable():
    """Pinned so a future `.mcp.json` -- machine-local convenience, one path,
    reintroduced for a good reason -- cannot silently become committable again
    just because it happens to live on a clone whose `.git/info/exclude` was
    never touched.
    """
    rules = [
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    ]
    assert ".mcp.json" in rules, (
        ".mcp.json holds a machine-local MCP server registration -- an absolute "
        "path off one disk on this repo's own history (#610) -- and belongs in "
        "the TRACKED .gitignore, not only in one clone's .git/info/exclude, or a "
        "second maintainer's checkout has no exclusion at all."
    )


def test_the_must_fire_control_the_rule_above_would_otherwise_be_vacuous_against():
    """Without this, a `.gitignore` missing EVERY rule -- an empty file, say --
    would satisfy the assertion above just as happily as a correctly maintained
    one, because a bare `in` check against an empty list never fails on its own.
    This proves the file actually carries unrelated rules too, so the first
    test is checking THIS repo's real `.gitignore` rather than one that
    happens to be trivially satisfiable.
    """
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__" in text
