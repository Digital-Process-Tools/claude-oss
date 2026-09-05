"""#245 step 2 (first slice): two file-keyed traps move out of `CLAUDE.md`'s "Traps
that cost time here" section -- loaded in full by every session that opens this repo --
into `paths` jit-context rules under `.claude/jit-context/paths/00-manual/`, which cost
nothing until the file they are about is actually touched.

Unlike the `01-oss` layer `scripts/oss_rules.py` generates and ships into every
scaffolded repository, `00-manual` is this repository's own, human-maintained layer:
these two traps are about developing `claude-oss` itself (`scripts/doctor.sh`,
`bin/oss-workspace`, `scripts/assemble_changelog.py`), not knowledge to inject into a
repository this plugin manages, so they do not belong in `oss_rules.RULES` at all --
`scripts/oss_rules.py`'s own `install()` only ever touches the `01-oss` subdirectory of
each dimension and never `00-manual` (confirmed by reading `install()`: it removes and
rewrites `root / ".claude/jit-context" / dimension / LAYER` where `LAYER = "01-oss"`).

Per the `claude-jit-context:vocabulary` skill, a rule that ships without a demonstration
that it fires is the inert-layer bug #144 already shipped once. The `paths` dimension is
driven by a separate hook (`pre-path-hook.sh`) that `tests/jit_hook_harness.py` does not
drive -- so, following the precedent already in this repository for a `paths` rule's own
proof of fire (`tests/test_jit_oss_config_anchor_639.py`), the match is exercised
directly against realistic and unrelated paths rather than through the installed hook.

Python 3.9 compatible.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

MANUAL_LAYER = REPO_ROOT / ".claude" / "jit-context" / "paths" / "00-manual"
SHELL_RULE = MANUAL_LAYER / "posix-shell-portability.md"
CHANGELOG_RULE = MANUAL_LAYER / "assemble-changelog-root.md"
INDEX = MANUAL_LAYER / "00-index.tsv"

CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def _frontmatter_match(text):
    for line in text.splitlines():
        if line.startswith("match:"):
            return line[len("match:") :].strip()
    raise AssertionError("no match: line found in frontmatter")


# --- 1. the two rule files exist, with a title, a description and a match -----------


def test_both_rule_files_exist_with_frontmatter():
    for rule in (SHELL_RULE, CHANGELOG_RULE):
        assert rule.is_file(), "{} does not exist".format(rule)
        text = rule.read_text(encoding="utf-8")
        assert text.startswith("---\n"), "{} carries no frontmatter".format(rule)
        assert "title:" in text
        assert "description:" in text
        assert "match:" in text


# --- 2. the shell-portability rule fires on the two files it was found on, on any --
# ---    other shell script in the same two directories, and on nothing else --------


def test_shell_portability_rule_fires_on_doctor_sh_and_oss_workspace():
    pattern = _frontmatter_match(SHELL_RULE.read_text(encoding="utf-8"))
    assert re.search(pattern, "scripts/doctor.sh")
    assert re.search(pattern, "bin/oss-workspace")
    # A worktree-relative form, the shape a real Edit/Read tool_input carries.
    assert re.search(pattern, "/Users/x/claude-oss-wt/245/scripts/doctor.sh")


def test_shell_portability_rule_fires_on_a_future_shell_script_it_was_not_found_on():
    """A reviewer finding on this rule's first draft (#245): scoping the match to only
    the two files the traps were discovered on would leave a THIRD shell script that
    repeats either mistake with no warning at all, even though both traps are general
    POSIX-shell mistakes and not facts about those two files specifically. Widened to
    every file under bin/ and every .sh under scripts/ -- this is the must-fire proof
    for a file that did not exist when the rule was written."""
    pattern = _frontmatter_match(SHELL_RULE.read_text(encoding="utf-8"))
    assert re.search(pattern, "scripts/some_new_helper.sh")
    assert re.search(pattern, "bin/some-new-launcher")


def test_shell_portability_rule_does_not_fire_on_an_unrelated_file():
    """Must-not-fire control, paired with the must-fire cases above so a pattern that
    matches everything cannot pass this rule's proof by accident."""
    pattern = _frontmatter_match(SHELL_RULE.read_text(encoding="utf-8"))
    assert not re.search(pattern, "scripts/oss_config.py")
    assert not re.search(pattern, "scripts/doctor.py")
    assert not re.search(pattern, "notes/doctor.sh.md")
    assert not re.search(pattern, "scripts/sub/doctor.sh")


# --- 3. the assemble_changelog.py rule fires on both known locations, and only them --


def test_changelog_root_rule_fires_on_both_assembler_locations():
    pattern = _frontmatter_match(CHANGELOG_RULE.read_text(encoding="utf-8"))
    assert re.search(pattern, "scripts/assemble_changelog.py")
    assert re.search(pattern, ".oss/assemble_changelog.py")


def test_changelog_root_rule_does_not_fire_on_an_unrelated_file():
    pattern = _frontmatter_match(CHANGELOG_RULE.read_text(encoding="utf-8"))
    assert not re.search(pattern, "scripts/assemble_changelog_test.py")
    assert not re.search(pattern, "scripts/oss_rules.py")
    assert not re.search(pattern, "CHANGELOG.md")


# --- 4. the index carries both rows, and each row's match agrees with its .md -------


def test_index_carries_both_rows_matching_their_md_frontmatter():
    assert INDEX.is_file()
    rows = [
        line.split("\t")
        for line in INDEX.read_text(encoding="utf-8").splitlines()
        if line
    ]
    by_name = {row[1]: row[0] for row in rows if len(row) == 2}
    assert by_name.get("posix-shell-portability.md") == _frontmatter_match(
        SHELL_RULE.read_text(encoding="utf-8")
    )
    assert by_name.get("assemble-changelog-root.md") == _frontmatter_match(
        CHANGELOG_RULE.read_text(encoding="utf-8")
    )


# --- 5. install() never touches 00-manual, so this layer survives a rescaffold ------


def test_oss_rules_install_never_writes_00_manual(tmp_path):
    import oss_rules

    project = tmp_path / "repo"
    (project / ".claude" / "jit-context" / "paths" / "00-manual").mkdir(parents=True)
    sentinel = project / ".claude" / "jit-context" / "paths" / "00-manual" / "keep.md"
    sentinel.write_text("---\ntitle: keep\n---\nstays\n", encoding="utf-8")

    oss_rules.install(project)

    assert sentinel.is_file(), (
        "install() touched the 00-manual layer -- it must only ever replace 01-oss"
    )
    assert sentinel.read_text(encoding="utf-8") == "---\ntitle: keep\n---\nstays\n"


# --- 6. CLAUDE.md's traps section no longer carries the moved bullets, and points ----
# ---    at the rules that replace them ----------------------------------------------


def test_claude_md_no_longer_carries_the_moved_trap_prose():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    start = text.index("## Traps that cost time here")
    end = text.index("\n## ", start + 1)
    section = text[start:end]
    assert "strips nothing under Git Bash" not in section, (
        "the ${0%/*} trap prose is still inline in CLAUDE.md"
    )
    assert "suppresses errexit for that command" not in section, (
        "the trailing || true trap prose is still inline in CLAUDE.md"
    )
    assert "since #590, from the" not in section, (
        "the assemble_changelog.py root-derivation trap prose is still inline in CLAUDE.md"
    )
    assert ".claude/jit-context/paths/00-manual/posix-shell-portability.md" in section
    assert ".claude/jit-context/paths/00-manual/assemble-changelog-root.md" in section


def test_claude_md_shrank():
    """Not a tight bound -- just a receipt that the move actually reduced the
    unconditionally-loaded byte count, not merely relocated a copy."""
    size = len(CLAUDE_MD.read_bytes())
    assert size < 62000, (
        "CLAUDE.md is {} bytes -- expected it to have shrunk below the pre-move size "
        "(63259 B) by roughly the two moved bullets".format(size)
    )
