"""#426: the maintainer half of #335. A fragment renamed when a pull request opens
(`git mv changelog.d/N.section.md changelog.d/M.section.md`) leaves the body still
naming the old number, and the fold consumes the filename -- so the same
`fragment` leg that refuses a lane's #274-shaped fragment refuses the
maintainer's rename too. Measured on PR #338, recorded in #335's comment.

#335 argued the rename should not stay a manual step: the number a fragment is
keyed to (the pull request's own number) does not exist until the pull request
is open, so the rename and the body rewrite are coupled and neither half is
correct alone. `scripts/rename_changelog_fragment.py` performs both in one
operation and refuses rather than leaving a fragment `--check` would reject.

This file drives it against a real git repo with a real fragment: the rename
must move the number in the body along with the filename, paired with a
control on an already-correct fragment (must be left alone, not rewritten) and
a control on a fragment that never named itself even before the rename (must
refuse rather than silently produce another broken fragment).
"""

import ast
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
RENAMER = SCRIPTS_DIR / "rename_changelog_fragment.py"

# The vendored root: the one script this test actually invokes as a
# subprocess. #1148's own PR review is why this is no longer a hand-kept
# list of everything the renamer's import chain happens to reach today --
# `lane_setup.py` grew a new `import select_issues_rank` for an unrelated
# reason (a lane-size constant), and the old hardcoded LANE_SETUP_SUBMODULES
# list here had no way to know: it went stale on a CI-only failure (a local
# run has the whole of scripts/ on the path, so this class of gap is
# invisible until a runner actually isolates the vendored copy). Deriving
# the set by following imports, transitively, closes the whole class rather
# than adding one more name to a list the next new import will make stale
# again.
VENDOR_ROOTS = ("rename_changelog_fragment",)

OK, REFUSED = 0, 3


def _local_import_names(path, known):
    """Every name `path` imports directly that is itself one of `known` (a
    module name with a same-named file under scripts/), found by parsing
    the file's own `import X` / `from X import ...` statements with `ast`
    rather than executing anything."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in known:
                    found.add(alias.name)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module in known
        ):
            found.add(node.module)
    return found


def _vendor_closure(roots):
    """Every scripts/*.py module reachable from `roots` by following local
    imports, transitively -- the set `_vendor` below actually copies. A
    module reachable only through a THIRD module's own import (not directly
    from `roots`) is exactly the shape #1148's PR review found missing here,
    so this keeps widening the frontier until nothing new turns up rather
    than walking `roots`'s own imports once."""
    known = {p.stem for p in SCRIPTS_DIR.glob("*.py")}
    closure = set(roots)
    frontier = set(roots)
    while frontier:
        discovered = set()
        for name in frontier:
            for dep in _local_import_names(SCRIPTS_DIR / (name + ".py"), known):
                if dep not in closure:
                    discovered.add(dep)
        closure |= discovered
        frontier = discovered
    return closure


def _vendor(tmp_path):
    """A synthetic repo with its own .git and changelog.d/, carrying copies of
    the renamer and everything its own import chain reaches -- the renamer
    imports the assembler and lane_setup as sibling modules in scripts/, and
    each of those pulls in more of its own family, so the whole closure has
    to be copied together for `import rename_changelog_fragment` to resolve
    here."""
    root = tmp_path / "vendor"
    script_dir = root / "scripts"
    script_dir.mkdir(parents=True)
    for name in _vendor_closure(VENDOR_ROOTS):
        shutil.copy(SCRIPTS_DIR / (name + ".py"), script_dir / (name + ".py"))
    (root / "changelog.d").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    return root, script_dir / "rename_changelog_fragment.py"


def _commit_fragment(root, name, body):
    frag = root / "changelog.d" / name
    frag.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add fragment"], cwd=str(root), check=True
    )
    return frag


def _check(root):
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "assemble_changelog.py"), "--check"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def _rename(script_path, root, fragment_rel, new_issue):
    return subprocess.run(
        [sys.executable, str(script_path), fragment_rel, str(new_issue)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def test_vendor_closure_includes_every_transitive_local_import(tmp_path):
    """The exact regression this fix closes (#1148's own PR review):
    `lane_setup.py` gained `import select_issues_rank`, three imports deep
    from the renamer's own root (rename_changelog_fragment -> lane_setup ->
    select_issues_rank), and the old hardcoded LANE_SETUP_SUBMODULES list
    did not know. Assert the derived closure reaches it -- and, as a
    positive control, that it reaches the modules that were already known
    to be needed, so a closure that discovered nothing at all would not
    pass this test by accident."""
    closure = _vendor_closure(VENDOR_ROOTS)
    assert "select_issues_rank" in closure
    for already_known in (
        "assemble_changelog",
        "lane_setup",
        "oss_config",
        "lane_setup_worktree",
        "select_issues_claim_read",
    ):
        assert already_known in closure


def test_vendored_tree_can_actually_import_the_renamer(tmp_path):
    """The end-to-end shape of the bug: run the vendored copy standalone (no
    scripts/ on the path beyond what _vendor copied) and confirm it does not
    fail to import at all -- paired with the tests below, which exercise it
    for real, this is the narrowest possible reproduction of a
    ModuleNotFoundError in the vendored tree."""
    root, script_path = _vendor(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", "import rename_changelog_fragment"],
        cwd=str(script_path.parent),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_rename_moves_the_self_reference_with_the_filename(tmp_path):
    root, script_path = _vendor(tmp_path)
    _commit_fragment(root, "338.fixed.md", "- Fixed the thing (#338).\n")

    before = _check(root)
    assert before.returncode == OK, (before.stdout, before.stderr)

    result = _rename(script_path, root, "changelog.d/338.fixed.md", 425)
    assert result.returncode == OK, (result.stdout, result.stderr)

    old = root / "changelog.d" / "338.fixed.md"
    new = root / "changelog.d" / "425.fixed.md"
    assert not old.exists(), "the old filename must be gone once the rename ran"
    assert new.exists(), "the renamed fragment must exist under the new number"
    text = new.read_text(encoding="utf-8")
    assert "#425" in text, "the body must be rewritten to name the new number"
    assert "#338" not in text, "the old self-reference must not survive the rename"

    after = _check(root)
    assert after.returncode == OK, (
        "renamed fragment still fails --check -- the rewrite did not follow the rename",
        after.stdout,
        after.stderr,
    )

    # `git mv` alone stages the pre-rewrite bytes; the rewrite happens on disk
    # afterwards, so it must also be staged, or `git commit --amend` (no `-a`,
    # the instruction skills/manager/SKILL.md gives) would commit the OLD body
    # under the NEW filename -- the exact defect this tool exists to close,
    # one layer later.
    unstaged = subprocess.run(
        ["git", "diff", "--", "changelog.d/425.fixed.md"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert unstaged.stdout == "", (
        "the rewritten body was not staged -- an amend without an explicit "
        "`git add` would commit the pre-rewrite text",
        unstaged.stdout,
    )


def test_rename_refuses_when_the_body_never_named_the_old_issue(tmp_path):
    """Control on the failure path: a fragment that never named its own issue
    even before the rename has nothing for the tool to move -- it must refuse
    rather than silently produce a renamed fragment `--check` would still
    reject, which is the exact failure #335 and #426 are about."""
    root, script_path = _vendor(tmp_path)
    _commit_fragment(root, "338.fixed.md", "- Fixed the thing.\n")

    result = _rename(script_path, root, "changelog.d/338.fixed.md", 425)
    assert result.returncode == REFUSED, (result.stdout, result.stderr)
    assert "#425" in result.stdout or "#425" in result.stderr


def test_rename_leaves_an_already_correct_fragment_alone(tmp_path):
    """Positive control: renaming to the number a fragment already carries
    must be a no-op rather than a refusal or a rewrite that could corrupt a
    fragment that was already fine."""
    root, script_path = _vendor(tmp_path)
    _commit_fragment(root, "425.fixed.md", "- Fixed the thing (#425).\n")

    before_text = (root / "changelog.d" / "425.fixed.md").read_text(encoding="utf-8")
    result = _rename(script_path, root, "changelog.d/425.fixed.md", 425)
    assert result.returncode == OK, (result.stdout, result.stderr)
    after_text = (root / "changelog.d" / "425.fixed.md").read_text(encoding="utf-8")
    assert after_text == before_text, (
        "an already-correct fragment must not be rewritten"
    )
