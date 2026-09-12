"""Every action reference in the scaffolded changelog workflow is pinned to a
commit sha, not a moving tag (#1462).

`.github/workflows/oss-changelog.yml` is written verbatim, by `/oss:scaffold
--apply`, into every repository this plugin scaffolds -- it is not this
repository's own CI, which is `.github/workflows/changelog.yml` and stays on
major-tag pins deliberately (see that file's own header comment). A moving
tag (`actions/checkout@v7`) is repointed by its publisher on any v7.x release,
so the code that runs under the receiving repo's own `GITHUB_TOKEN` can change
between one run and the next with no commit and no pull request anywhere in
that repo. `Digital-Process-Tools/claude-supertool`'s own
`tests/test_ci_action_pinning_925.py` states the same shape for its own
workflows and is the model this file follows.

`.github/dependabot.yml` (scaffolded alongside this workflow, `github-actions`
ecosystem, see `scaffold.DEPENDABOT_YML`) reads as coverage for this and is
not for a bare tag: Dependabot will never bump `v7` to `v7`, so a retag is
live before any pull request exists to review it. Pinning to a sha inverts
that -- the sha cannot move, and Dependabot bumps a sha-pinned action just as
readily, rewriting both the sha and its trailing `# vX.Y.Z` comment -- so the
maintenance cost this buys is a reviewable weekly pull request rather than a
standing, invisible exposure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402

#: `- uses: owner/repo@ref` or `  uses: owner/repo@ref`, with anything after
#: it. A commented-out line cannot match: `#` is neither whitespace nor `-`.
_USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s+(\S+)\s*(.*)$")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: The version the sha is claimed to be, e.g. `# v7.0.1`.
_VERSION_COMMENT_RE = re.compile(r"#\s*v\d+\.\d+\.\d+(?:\s|$)")


def _uses_lines():
    found = []
    for number, line in enumerate(scaffold.CHANGELOG_WORKFLOW.splitlines(), 1):
        match = _USES_RE.match(line)
        if match:
            found.append((number, match.group(1), match.group(2)))
    return found


def test_the_discovery_actually_finds_the_action_references():
    """A parser that finds nothing renders every guard below green while
    checking no action at all -- the failure mode this file exists to
    prevent."""
    found = _uses_lines()
    assert len(found) >= 2, (
        f"only {len(found)} `uses:` references found in "
        "scaffold.CHANGELOG_WORKFLOW -- too few to be the real set, or the "
        "template changed shape and this file is now checking nothing"
    )


def test_every_action_is_pinned_to_a_commit_sha():
    for number, ref, _trailing in _uses_lines():
        _, _, version = ref.partition("@")
        assert version, f"line {number}: `uses: {ref}` declares no ref at all"
        assert _SHA_RE.match(version), (
            f"line {number}: `uses: {ref}` is pinned to the moving ref "
            f"{version!r}, not to a 40-character commit sha. A publisher "
            "repointing that tag runs new code with the receiving "
            "repository's own token on the very next run, and Dependabot "
            "cannot see it happen."
        )


def test_every_sha_pin_says_which_version_it_is():
    for number, ref, trailing in _uses_lines():
        assert _VERSION_COMMENT_RE.search(trailing), (
            f"line {number}: `uses: {ref}` carries no `# vX.Y.Z` comment. A "
            "bare sha is unreadable: nobody can tell a current pin from one "
            "several majors stale by looking, and Dependabot writes this "
            "comment when it bumps, so an absent one goes stale the first "
            "time it does."
        )
