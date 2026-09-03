"""#962: both CI workflows declare a concurrency group, and the one that also
runs on pushes to the default branch must not cancel those.

Without a group, every push to an open pull request starts a fresh run of all
14 legs and leaves the superseded ones running. The minutes are the smaller
cost: `gh-pr:N:status` sums checks across runs, so a pull request's tally mixes
legs from a superseded commit with legs from the head commit, and `not all
green` can mean an old run that will never finish rather than a new one that
failed.

The asymmetry between the two files is the part worth guarding. `changelog.yml`
is `pull_request`-only and cancels unconditionally. `tests.yml` also runs on
pushes to the default branch, and those runs are what `scripts/statusline.py`
and the release gates read as a commit's verdict -- a cancelled one reports
neither pass nor fail, which is this repository's own defect class produced by
its own configuration. So a bare `cancel-in-progress: true` in `tests.yml` is a
regression even though it would look tidier, and this file fails on it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


def test_the_parser_this_file_needs_is_present_on_ci():
    """A skipped file and a clean file are the same tick, so CI must not skip this
    one. `pytest.importorskip` at module scope would have made every assertion below
    vanish on a runner whose install step lost pyyaml, reported as `skipped` where
    nobody reads it -- the house shape is `tests/test_shell_leg_budget_303.py`'s and
    this file uses it rather than inventing a second answer."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the concurrency assertions in "
            "this file did not run on a runner. The pytest job installs it; if that "
            "line changed, this file went quiet rather than red."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
TESTS_YML = WORKFLOWS / "tests.yml"
CHANGELOG_YML = WORKFLOWS / "changelog.yml"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _push_branches(doc):
    """The branches a workflow runs on for `push`, or `[]` when it has no push
    trigger. `on` parses as the boolean True under YAML 1.1, which is why this
    reads both keys rather than assuming one -- a lookup that silently returned
    nothing would make every check below vacuous."""
    triggers = doc.get("on", doc.get(True))
    assert triggers is not None, "workflow declares no triggers at all"
    if not isinstance(triggers, dict):
        return []
    push = triggers.get("push")
    if not isinstance(push, dict):
        return []
    return push.get("branches") or []


@needs_yaml
def test_both_workflows_declare_a_concurrency_group():
    for path in (TESTS_YML, CHANGELOG_YML):
        doc = _load(path)
        block = doc.get("concurrency")
        assert block, "{} declares no concurrency block".format(path.name)
        group = block.get("group")
        assert group, "{}: concurrency block with no group".format(path.name)
        assert "github.ref" in group, (
            "{}: the group must vary by ref, or one pull request's push cancels "
            "another's run: {!r}".format(path.name, group)
        )


@needs_yaml
def test_the_workflow_that_runs_on_the_default_branch_does_not_cancel_those_runs():
    """The real assertion. A push run on the default branch is a commit's
    verdict; cancelling it leaves neither pass nor fail behind."""
    doc = _load(TESTS_YML)
    assert _push_branches(doc), (
        "tests.yml no longer runs on any push branch -- this check's whole "
        "premise is gone, and it would otherwise pass by not applying"
    )
    flag = doc["concurrency"]["cancel-in-progress"]
    assert flag is not True, (
        "tests.yml cancels in progress unconditionally, so a push run on the "
        "default branch can be cancelled by the next commit and that commit is "
        "left reporting neither pass nor fail"
    )
    assert isinstance(flag, str) and "pull_request" in flag, (
        "tests.yml's cancel-in-progress must be an expression naming the "
        "pull_request event, not {!r}".format(flag)
    )


@needs_yaml
def test_the_pull_request_only_workflow_cancels_unconditionally():
    """The other half, so the pair is not satisfiable by making both files
    timid. `changelog.yml` has no push run to protect; if a `push:` trigger is
    ever added, this fails and sends the author to the expression instead."""
    doc = _load(CHANGELOG_YML)
    assert not _push_branches(doc), (
        "changelog.yml gained a push trigger, so its unconditional "
        "cancel-in-progress can now cancel a default-branch run: give it the "
        "same expression tests.yml uses"
    )
    assert doc["concurrency"]["cancel-in-progress"] is True


@needs_yaml
def test_the_flag_check_fires_on_an_unconditional_true():
    """Positive control. The assertion above is a `is not True` over a value
    parsed from a file; run it against a workflow that is wrong on purpose, or
    a parse returning None would look the same as a correct file."""
    wrong = yaml.safe_load(
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "  pull_request:\n"
        "concurrency:\n"
        "  group: g-${{ github.ref }}\n"
        "  cancel-in-progress: true\n"
    )
    assert _push_branches(wrong) == ["main"]
    assert wrong["concurrency"]["cancel-in-progress"] is True

    right = yaml.safe_load(
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "concurrency:\n"
        "  group: g-${{ github.ref }}\n"
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
    )
    flag = right["concurrency"]["cancel-in-progress"]
    assert flag is not True and "pull_request" in flag


@needs_yaml
def test_the_group_check_fires_on_a_ref_less_group():
    """Positive control for the group half: a group that does not vary by ref
    is worse than none, because one pull request's push cancels another's."""
    doc = yaml.safe_load("concurrency:\n  group: ci\n  cancel-in-progress: true\n")
    assert "github.ref" not in doc["concurrency"]["group"]
