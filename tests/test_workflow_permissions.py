"""What token every workflow runs with -- ours, and the one we write into other repos.

A workflow with no `permissions:` block inherits the repository default, which in a repo
that has never flipped the org setting is read/write. Both changelog workflows run on
`pull_request` and execute the assembler from the pull request's own checkout, so a
branch pull request in the same repository runs contributor Python with that token. Fork
pull requests are safe by GitHub's own rule, which is the only reason this was hardening
rather than an incident (#32).

The generated workflow is the one that matters most: it lands in repositories nobody here
watches, and nobody there will think to add the block we forgot.

Two things in these files are already right and are pinned here so a later edit cannot
quietly undo them: they use `pull_request` and not `pull_request_target`, and the base ref
reaches the shell through `env:` rather than a `${{ }}` expansion in the script body.

Deliberately not a YAML parse: the assertion is about what a maintainer reads in the
file.

Python 3.9 compatible.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402

OUR_WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

GENERATED_WORKFLOW = ".github/workflows/oss-changelog.yml"


def _config(**overrides):
    config = {
        "repo": "owner/name",
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
    config.update(overrides)
    return config


def _generated():
    return scaffold.render_owned(GENERATED_WORKFLOW, _config())


def _permission_grants(text):
    """The lines under a top-level `permissions:` key, stripped.

    Returns None when the key is absent, which is the failure this file exists for --
    an empty list would read as "declared, and grants nothing", which is the opposite.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() != "permissions:":
            continue
        grants = []
        for following in lines[index + 1:]:
            if not following.strip():
                continue
            if not following.startswith(" "):
                break
            grants.append(following.strip())
        return grants
    return None


def _named_workflows():
    """Every workflow whose permissions this repo is responsible for, ours first."""
    pairs = [(str(path.relative_to(REPO_ROOT)), path.read_text(encoding="utf-8")) for path in OUR_WORKFLOWS]
    pairs.append(("generated " + GENERATED_WORKFLOW, _generated()))
    return pairs


def test_there_are_workflows_to_check():
    """A glob that found nothing would make every check below pass having read no file."""
    assert OUR_WORKFLOWS, "no .github/workflows/*.yml found -- the checks below are vacuous"


@pytest.mark.parametrize("name,text", _named_workflows(), ids=lambda value: value if isinstance(value, str) and len(value) < 60 else "")
def test_every_workflow_declares_a_permissions_block(name, text):
    grants = _permission_grants(text)
    assert grants is not None, (
        "{}: no top-level `permissions:` -- the job inherits the repository default, "
        "which is read/write in a repo that has not changed it".format(name)
    )
    assert grants, "{}: `permissions:` declared with nothing under it".format(name)


#: The one deliberate exception (#777), and the argument for it: the generated
#: workflow's fragment gate reads the `no-changelog` label LIVE via `gh api
#: repos/{repo}/pulls/{n}` -- the `pulls` endpoint, not `issues/{n}/labels`, because a
#: pull request is also an issue but the scope covering `/issues/*` is `issues: read`
#: rather than `pull-requests: read`. Without this the live read 403s on every run,
#: forever, and degrades silently to the frozen event payload -- exactly the bug #777
#: fixes reappearing behind a scope mismatch nobody would see fail. Named here, once,
#: rather than left to whoever next tightens this test to relearn why it is wider.
_DELIBERATELY_WIDER = {
    "generated " + GENERATED_WORKFLOW: ["contents: read", "pull-requests: read"],
}


@pytest.mark.parametrize("name,text", _named_workflows(), ids=lambda value: value if isinstance(value, str) and len(value) < 60 else "")
def test_no_workflow_grants_more_than_reading_the_contents(name, text):
    grants = _permission_grants(text)
    expected = _DELIBERATELY_WIDER.get(name, ["contents: read"])
    assert grants == expected, (
        "{}: expected exactly {!r}, got {!r}. Anything wider than `contents: read` "
        "needs its own argument in the pull request that added it -- see "
        "`_DELIBERATELY_WIDER` above for the one that exists today.".format(
            name, expected, grants
        )
    )


# ------------------------------------------- what the audit found correct, pinned here


@pytest.mark.parametrize("name,text", _named_workflows(), ids=lambda value: value if isinstance(value, str) and len(value) < 60 else "")
def test_no_workflow_triggers_on_pull_request_target(name, text):
    assert "pull_request_target" not in text, (
        "{}: `pull_request_target` runs the base repository's workflow with a write "
        "token and the fork's code in scope. `pull_request` is the safe trigger and "
        "was chosen deliberately.".format(name)
    )


@pytest.mark.parametrize("name,text", _named_workflows(), ids=lambda value: value if isinstance(value, str) and len(value) < 60 else "")
def test_the_base_ref_reaches_the_shell_through_env_and_not_an_expansion(name, text):
    expansion = "${{ github.event.pull_request.base.ref }}"
    carriers = [line.strip() for line in text.splitlines() if expansion in line]
    if not carriers:
        pytest.skip("{} does not read the base ref".format(name))
    for line in carriers:
        assert line.startswith("BASE_REF:"), (
            "{}: the base ref is interpolated into {!r}. A `${{{{ }}}}` expansion is "
            "textual substitution, so whatever the ref carries becomes shell source; it "
            "goes through `env:` instead.".format(name, line)
        )
