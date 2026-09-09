"""#1391: the manager skill is a library, loaded via `Skill(manager)` by
`commands/tick.md` and `commands/release.md`, never an entry point a human
types. `user_invocable: true` published it into the slash picker as
`/oss:manager` anyway -- a one-click way to defeat the per-tick context
discard the sub-manager exists for, since invoking it loads the whole
spine into the invoking session and that session holds it forever after.

Pins two facts together: the spine's own frontmatter opts out of the
picker, and both callers still name it by `Skill(manager)` -- so the fix
is a visibility flag only, never a removal of the library shape itself.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md has no frontmatter block"
    return match.group(1)


def test_manager_skill_is_not_user_invocable():
    text = (ROOT / "skills/manager/SKILL.md").read_text(encoding="utf-8")
    fm = _frontmatter(text)
    assert re.search(r"^user_invocable:\s*false\s*$", fm, re.MULTILINE), (
        "skills/manager/SKILL.md must declare user_invocable: false -- it "
        "is a library loaded by commands/tick.md and commands/release.md, "
        "never a slash-picker entry point (#1391)"
    )


def test_both_callers_still_name_the_skill():
    for path in ("commands/tick.md", "commands/release.md"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "Skill(manager)" in text, (
            f"{path} must still invoke Skill(manager) -- flipping "
            "user_invocable must not sever either caller (#1391)"
        )
