"""#1391: the manager skill is a library, loaded via `Skill(manager)` by
`commands/tick.md` and `commands/release.md`, never an entry point a human
types. The documented Claude Code skill frontmatter key for this is
`user-invocable`, HYPHENATED -- this file's first draft pinned the
underscored `user_invocable` instead, which the harness silently ignores
as an unrecognised key. That draft's red/green transition was real (the
file's own text genuinely changed) and proved nothing about the picker,
because an unrecognised key changes no observable behaviour either way;
the original `user_invocable: true` had never been read either, so the
skill appeared in the picker by default rather than by request. Caught by
the coordinator, not by self-review -- neither spawned reviewer checked
the key spelling against the harness's own documentation
(https://code.claude.com/docs/en/skills), only against this repo's own
(uniformly wrong) prior usage. See trap.d/1391.skill-frontmatter-
underscore-vs-hyphen.md.

Pins two facts together: the spine's own frontmatter opts out of the
picker using the key the harness actually reads, and both callers still
name it by `Skill(manager)` -- so the fix is a visibility flag only,
never a removal of the library shape itself.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md has no frontmatter block"
    return match.group(1)


def test_manager_skill_is_not_user_invocable():
    text = (ROOT / "skills/manager/SKILL.md").read_text(encoding="utf-8")
    fm = _frontmatter(text)
    assert re.search(r"^user-invocable:\s*false\s*$", fm, re.MULTILINE), (
        "skills/manager/SKILL.md must declare user-invocable: false, "
        "HYPHENATED -- that is the key Claude Code's skill frontmatter "
        "actually documents; the underscored user_invocable is silently "
        "ignored and changes nothing (#1391). It is a library loaded by "
        "commands/tick.md and commands/release.md, never a slash-picker "
        "entry point."
    )
    assert "user_invocable" not in fm, (
        "the underscored user_invocable key should not remain in "
        "skills/manager/SKILL.md's frontmatter -- a key nothing reads is "
        "a fact with no consumer, and someone will eventually edit it "
        "believing it does something (#1391)"
    )


def test_both_callers_still_name_the_skill():
    for path in ("commands/tick.md", "commands/release.md"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "Skill(manager)" in text, (
            f"{path} must still invoke Skill(manager) -- flipping "
            "user-invocable must not sever either caller (#1391)"
        )
