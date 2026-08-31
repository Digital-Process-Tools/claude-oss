"""#710: the release commit must never be staged with `git commit --all` (or a bare
`git add .` / `git add -A`), and `commands/release.md` is the only place that says how to stage it.

Recorded from the `0.16.0` release: the release commit was made with `git commit --all` via
supertool's `git-commit:::MESSAGE:::--all`. `.venv/` was untracked at the time and swept in --
1390 files committed where 41 were intended -- reset before it reached the remote. The document's
own "Then" section said *"commit with `commit_subject`"* and never said how to stage, which is the
gap this closes: not by widening `.gitignore` forever (route 2, reactive by construction and
already the mitigation that let this recur once), but by naming route 1 -- stage explicit paths,
never a staging mode that sweeps the whole working tree.

This cannot assert the release is actually run this way -- that is a procedure a human or an
agent follows, not something a test can execute -- so it pins the document's own instruction
instead, with a control proving the check can fail against the document as it read before this
fix.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_MD = REPO_ROOT / "commands" / "release.md"


def _then_section(text):
    start = text.find("## Then")
    if start < 0:
        return ""
    rest = text[start:]
    end = rest.find("\n## ", 1)
    return rest if end < 0 else rest[:end]


def test_release_then_section_forbids_sweeping_staging():
    section = _then_section(RELEASE_MD.read_text(encoding="utf-8"))
    assert section, "commands/release.md must carry a '## Then' section"
    assert "--all" in section or "-a" in section, (
        "the 'Then' section must name the forbidden staging mode explicitly, or a reader has "
        "no way to know `git commit --all` is the thing being ruled out (#710)"
    )
    assert "explicit paths" in section or "explicit path" in section, (
        "the 'Then' section must say what to do instead of sweeping staging -- name the paths "
        "the release touched, not just forbid --all (#710)"
    )


def test_the_must_fire_control_fires_on_the_document_as_it_read_before_this_fix():
    """Reconstructs the pre-fix 'Then' section verbatim and proves the second assertion above
    would have failed against it -- otherwise the first test could be passing for a reason that
    has nothing to do with this fix, the same way an `in` check against an empty haystack would.
    """
    before_fix = (
        "## Then\n\n"
        "Fold the changelog if this repo uses fragments (`/oss:changelog`), commit with "
        "`commit_subject` --\n"
        "or with `chore(release): {version}` when it is null, per the rule above -- and tag. "
        "Then **verify the tag exists on the remote**:\n"
    )
    section = _then_section(before_fix)
    assert section
    has_forbidden_named = "--all" in section or "-a" in section
    has_explicit_paths = "explicit paths" in section or "explicit path" in section
    assert not (has_forbidden_named and has_explicit_paths), (
        "the control text must NOT already satisfy the real check, or the real test above "
        "cannot be trusted to have found anything"
    )
