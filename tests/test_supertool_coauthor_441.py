"""Guards on the project's own supertool commit-identity, issue #441.

Every commit made through supertool's `git-commit` op appends a `Co-Authored-By`
trailer, and this repo had never set `ops.git-commit.coauthor` in `.supertool.json`
-- so every agent commit carried supertool's own default, `Max <noreply>`, which is
not a valid email address and not an identity anyone on this project chose.

This is not an upstream defect: the trailer, the default and the override key are
all documented in claude-supertool. The fix is entirely local -- declare the value
this repository actually wants, on record in the tracked config, once.

Fixing forward: the commits that already carry the old default are squash-merge
subjects in main's history, and rewriting shared history to correct a trailer on
them is not a trade this project makes. See changelog.d for the fragment recording
that decision so nobody reopens it.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The identity this project's own commits already carry: 247+117 of the commits in
# this repo's history use exactly this string as their Co-Authored-By trailer (via
# Claude Code's own commit convention), against 171 carrying supertool's unchosen
# default and 36 carrying a different assistant identity. Picking the dominant,
# already-real identity over inventing a new one, and over supertool's placeholder.
EXPECTED_COAUTHOR = "Claude Opus 5 (1M context) <noreply@anthropic.com>"


def _declared_coauthor(config):
    """What ops.git-commit.coauthor resolves to for a given parsed .supertool.json.

    Returns None (never the expected string) when the key -- or any parent of it --
    is absent, so a check comparing this to EXPECTED_COAUTHOR cannot pass merely
    because the file exists.
    """
    if not isinstance(config, dict):
        return None
    ops = config.get("ops")
    if not isinstance(ops, dict):
        return None
    git_commit = ops.get("git-commit")
    if not isinstance(git_commit, dict):
        return None
    return git_commit.get("coauthor")


def test_supertool_json_declares_the_project_coauthor():
    """.supertool.json is tracked, so this is the same answer for every maintainer."""
    config = json.loads((REPO_ROOT / ".supertool.json").read_text(encoding="utf-8"))
    assert _declared_coauthor(config) == EXPECTED_COAUTHOR, (
        "ops.git-commit.coauthor in .supertool.json must be set to this project's own "
        "commit identity ({!r}), not left to supertool's own 'Max <noreply>' default "
        "-- see issue #441".format(EXPECTED_COAUTHOR)
    )


def test_the_coauthor_check_fires_when_the_key_is_absent():
    """Positive control: a config that never sets the key must not read as satisfying
    the assertion above -- otherwise the check above could pass on file existence
    alone, which is exactly the defect this file exists to rule out.
    """
    assert _declared_coauthor({}) != EXPECTED_COAUTHOR
    assert _declared_coauthor({"ops": {}}) != EXPECTED_COAUTHOR
    assert _declared_coauthor({"ops": {"git-commit": {}}}) != EXPECTED_COAUTHOR
    assert _declared_coauthor(
        {"ops": {"git-commit": {"coauthor": "Max <noreply>"}}}
    ) != (EXPECTED_COAUTHOR)
