"""#1746: the owned README says nothing about where a bug in an owned file
goes, and nothing tells a scan, a triage sweep or a fix lane to route a
finding under `.oss/` (or `.github/workflows/oss-changelog.yml`) upstream
instead of "fixing" it locally.

Observed for real: a security scan found a genuine defect in the vendored
`.oss/statusline.py`, a fix lane patched the vendored copy in place and added
a test against it in the consuming repository, and the next
`scaffold.py --apply` resync silently wiped both out -- the README's own
"replaced wholesale" warning was true and did not stop it, because nothing
told the lane where the bug actually belonged.

This test pins the new "Found a bug in one of these files?" section: it
names a real repository (derived, never hardcoded -- `doctor.loop_repository`
is what actually answers "where does a bug in this plugin go"), and it says
plainly not to patch or test the file locally.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402


def _config():
    return {
        "repo": "acme/widget",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }


def test_the_readme_has_a_found_a_bug_section():
    body = scaffold.render_owned(scaffold.OWNED_DIR + "/README.md", _config())
    assert "Found a bug in one of these files?" in body, body


def test_the_section_says_never_to_patch_or_test_it_locally():
    body = scaffold.render_owned(scaffold.OWNED_DIR + "/README.md", _config())
    section_start = body.find("Found a bug in one of these files?")
    assert section_start >= 0
    section = body[section_start:]
    assert "Never patch or test the file in this repository" in section, section


def test_the_section_covers_the_workflow_file_exception_too():
    """The one-exception file (`.github/workflows/oss-changelog.yml`) lives
    outside `.oss/` but is owned the same way -- the routing rule must name it
    too, not just the directory (#1746's own worked example was the vendored
    `statusline.py`, but the workflow file is owned by the identical contract).
    """
    body = scaffold.render_owned(scaffold.OWNED_DIR + "/README.md", _config())
    section_start = body.find("Found a bug in one of these files?")
    section = body[section_start:]
    assert ".github/workflows/oss-changelog.yml" in section, section


def test_the_repository_named_is_derived_from_the_real_plugin_manifest():
    """Must resolve to a real URL when rendered against this plugin's own
    checkout (plugin_root defaults to it) -- never a hardcoded slug, per this
    repository's own governing rule that a fact about one repository never
    lives in shared code."""
    body = scaffold.render_owned(scaffold.OWNED_DIR + "/README.md", _config())
    assert "https://github.com/Digital-Process-Tools/claude-oss" in body, body


def test_loop_repository_line_falls_back_when_the_manifest_cannot_be_read(tmp_path):
    """Must fire: an unreadable plugin_root gets a real sentence, not a crash
    and not a blank line -- the third state (`could not tell`) rendered as
    prose rather than as nothing."""
    line = scaffold._loop_repository_line(tmp_path)
    assert "repository" in line, line


def test_loop_repository_line_resolves_the_real_manifest():
    """Positive control for the fallback test above: the real checkout must
    still resolve to the genuine URL, so the fallback test is not vacuously
    passing because the function never resolves anything."""
    line = scaffold._loop_repository_line(REPO_ROOT)
    assert line == "https://github.com/Digital-Process-Tools/claude-oss", line
