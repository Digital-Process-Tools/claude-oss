"""#1162: the releaser could not read whether a pull request had gone green,
though a sub-manager already had a script and a named trap for exactly that.

`scripts/pr_green.py` used to be named in exactly one prose file
(`agents/sub-manager.md`), so a releaser landing gate 3's own blocking fix
had no instruction and no trap -- the same failure mode #1086 already paid
for once: a hand-written wait loop reading `NOT ALL GREEN` as containing
`ALL GREEN` and exiting green with checks still pending.

The fix is a shared phase file, `skills/manager/phases/ci-green.md`, both
`agents/sub-manager.md` and `agents/releaser.md` point at rather than
restate. This module pins:

- the new file exists, is registered in `skill_phases.DOCUMENTS`, and the
  spine (`SKILL.md`) references it -- otherwise `skill_phases.check()`
  reports it `unreferenced`, which is this plugin's own defect class
  (an absence produced by the tool, read as an absence in the world)
  pointed at its own documentation;
- the `NOT ALL GREEN` / `ALL GREEN` substring trap is pinned in the new
  file's own text -- per `loop-prose-parity.md`'s rule, pin the measured
  tool output rather than just agreement between two prose copies;
- `pr_green.py` is named in the new file plus both agent definitions
  (the issue's own acceptance grep), and `agents/sub-manager.md` no longer
  restates the trap or the state table inline -- a second copy is exactly
  what `CLAUDE.md`'s standing rule against duplicated facts forbids.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import skill_phases  # noqa: E402

CI_GREEN = "skills/manager/phases/ci-green.md"


def _grep_rl(pattern, dirs):
    """Pure-Python equivalent of `grep -rl PATTERN DIRS...` -- no external
    binary, so this cannot fail with an unspawnable-tool error on a runner
    that lacks (or PATH-hides) a `grep` executable (#1162 self-review)."""
    named = set()
    for d in dirs:
        base = ROOT / d
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pattern in text:
                named.add(str(path.relative_to(ROOT).as_posix()))
    return named


def test_ci_green_phase_file_exists_and_is_registered():
    rows = {r["path"]: r for r in skill_phases.check()}
    assert CI_GREEN in rows, "not declared in skill_phases.DOCUMENTS: " + CI_GREEN
    row = rows[CI_GREEN]
    assert row["state"] == "ok", row
    assert row["referenced"] is True, "spine does not name " + CI_GREEN


def test_ci_green_pins_the_not_all_green_substring_trap():
    """Positive control: this is the trap #1086 paid for. A file that dropped
    it during the move would still look fine to every other check here."""
    text = (ROOT / CI_GREEN).read_text(encoding="utf-8")
    assert "NOT ALL GREEN" in text
    assert "ALL GREEN" in text
    assert "#1086" in text


def test_pr_green_named_in_the_shared_file_and_both_agents():
    named = _grep_rl("pr_green", ["agents", "skills", "commands"])
    assert CI_GREEN in named, named
    assert "agents/sub-manager.md" in named, named
    assert "agents/releaser.md" in named, named


def test_sub_manager_no_longer_restates_the_trap_inline():
    """The nine-line inline block moves out; sub-manager.md keeps a pointer,
    never a second copy of the state table or the trap text."""
    text = (ROOT / "agents/sub-manager.md").read_text(encoding="utf-8")
    assert "ci-green.md" in text
    assert "NOT ALL GREEN" not in text, "sub-manager.md still restates the trap inline"


def test_releaser_points_at_the_shared_file():
    text = (ROOT / "agents/releaser.md").read_text(encoding="utf-8")
    assert "ci-green.md" in text


def test_merge_phase_cites_rather_than_restates():
    text = (ROOT / "skills/manager/phases/merge.md").read_text(encoding="utf-8")
    assert "ci-green.md" in text
