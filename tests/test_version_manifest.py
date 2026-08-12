"""Guard: the plugin manifest version must track the released CHANGELOG version.

Claude Code's plugin updater compares ``.claude-plugin/plugin.json`` *versions*, not
source SHAs. A release that ships without bumping the manifest is invisible to every
marketplace install, which keeps reporting it is already up to date. A stale manifest
is a shipping bug, not cosmetics.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
README = REPO_ROOT / "README.md"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
RELEASE_HEADING_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]")
README_BADGE_RE = re.compile(
    r"!\[Version\]\(https://img\.shields\.io/badge/version-(\d+\.\d+\.\d+)-orange\)"
)


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _changelog_versions():
    """Released versions, newest first. ``## [Unreleased]`` is skipped by the regex."""
    versions = []
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        match = RELEASE_HEADING_RE.match(line)
        if match:
            versions.append(match.group(1))
    return versions


def test_manifest_version_is_semver():
    version = _manifest()["version"]
    assert SEMVER_RE.match(version), "plugin.json version is not semver: {!r}".format(version)


def test_changelog_has_released_versions():
    assert _changelog_versions(), "CHANGELOG.md has no '## [x.y.z]' release heading"


def test_manifest_matches_newest_changelog_release():
    manifest_version = _manifest()["version"]
    newest = _changelog_versions()[0]
    assert manifest_version == newest, (
        ".claude-plugin/plugin.json declares {} but the newest CHANGELOG.md release "
        "is {}. Marketplace updaters compare manifest versions, so shipping this way "
        "makes the release invisible.".format(manifest_version, newest)
    )


def test_changelog_releases_are_strictly_descending():
    """Newest-first ordering is what makes 'the newest release' well defined."""
    versions = [tuple(int(p) for p in v.split(".")) for v in _changelog_versions()]
    assert versions == sorted(versions, reverse=True), (
        "CHANGELOG.md release headings are not in descending order: {}".format(
            _changelog_versions()
        )
    )


def test_readme_version_badge_matches_manifest():
    """A release sweep keyed on the outgoing version can never find a badge that
    stopped being bumped: it is not mid-transition, so it never matches the pattern
    the sweep greps for. Pin the badge to the manifest directly, and fail loud when
    the regex finds nothing -- a regex that matched nothing has checked nothing.
    """
    match = README_BADGE_RE.search(README.read_text(encoding="utf-8"))
    assert match is not None, (
        "README.md has no version badge matching the expected shields.io pattern. "
        "Update README_BADGE_RE rather than letting this pass silently."
    )
    assert match.group(1) == _manifest()["version"], (
        "README.md's version badge reads {} but the manifest declares {}.".format(
            match.group(1), _manifest()["version"]
        )
    )


def test_manifest_declares_its_plugin_dependencies():
    """The three sibling plugins are what make the loop work; losing one silently
    turns a documented capability into a missing tool at runtime.
    """
    dependencies = _manifest()["dependencies"]
    assert dependencies == ["supertool", "remember", "claude-jit-context"], dependencies
