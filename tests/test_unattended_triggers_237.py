"""Nothing this plugin runs -- here or in a repo that installs it -- starts by itself.

`docs/autonomy.md` says that in prose. This file derives it, which is the only
version of the claim worth having: a document asserting the tree and a test
asserting the document would state one claim twice and pass whenever both were
wrong together.

Two surfaces, both derived rather than listed:

* this repository's own `.github/workflows/*.yml`;
* every workflow in `scaffold.OWNED` -- the files written into somebody else's
  repository and replaced wholesale on every run.

A workflow whose `on:` block cannot be found is `unknown` and **fails**. That is
the whole point: "read the triggers and found none that fire on their own" and
"could not read the triggers" must not render alike, which is the defect class
this repository is named after.

`workflow_dispatch` is deliberately counted with the unattended ones. It is a
button somebody presses, but the API presses it too, so it is not a human this
repository can point to -- and it is the trigger an unattended loop would most
plausibly arrive on. It is named separately in the failure message so the
distinction survives.

Deliberately not a YAML parse: pyyaml is not a dependency here, and
`tests/test_workflow_permissions.py` reads the same files the same way.

Python 3.9 compatible.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402

# Fires without anybody doing anything, or on a signal from outside the repo.
UNATTENDED = ("schedule", "repository_dispatch")

# A human act on this repository.
ATTENDED = ("push", "pull_request", "pull_request_target", "issues", "issue_comment")


def _config():
    return {
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


def triggers(text):
    """The top-level event names under a workflow's `on:` key.

    Returns None when no indented `on:` block was found -- absent, not empty. An
    empty list would read as "declared, and fires on nothing", which is a
    different file and a passing one.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() not in ("on:", '"on":', "'on':"):
            continue
        events = []
        for following in lines[index + 1 :]:
            if not following.strip() or following.lstrip().startswith("#"):
                continue
            if not following[:1].isspace():
                break  # back at column 0: the `on:` block ended.
            if following.startswith("  ") and not following.startswith("   "):
                name = following.strip().rstrip(":").strip()
                if name and not name.startswith("-"):
                    events.append(name)
        return events
    return None


def _workflow_sources():
    """(label, text) for every workflow this repository runs or writes.

    Derived from the tree and from `scaffold.OWNED`, so a workflow added to
    either side is covered by the commit that adds it rather than by somebody
    remembering to extend a list here.
    """
    sources = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        sources.append(("ours: .github/workflows/" + path.name, path.read_text(encoding="utf-8")))
    for name in sorted(scaffold.OWNED):
        if name.startswith(".github/workflows/"):
            sources.append(("written: " + name, scaffold.render_owned(name, _config())))
    return sources


def test_there_is_something_to_check():
    """A sweep that found no workflows has checked nothing."""
    sources = _workflow_sources()
    ours = [label for label, _ in sources if label.startswith("ours:")]
    written = [label for label, _ in sources if label.startswith("written:")]
    assert ours, "no workflows found under .github/workflows/ -- the sweep below is vacuous"
    assert written, (
        "scaffold.OWNED names no workflow. Either this plugin stopped writing one into "
        "managed repositories -- which is the far more interesting half of docs/autonomy.md "
        "-- or the .github/workflows/ prefix no longer matches how it is keyed."
    )


def test_no_workflow_starts_by_itself():
    """The central claim of docs/autonomy.md, measured rather than asserted."""
    unattended = []
    unreadable = []
    for label, text in _workflow_sources():
        events = triggers(text)
        if events is None:
            unreadable.append(label)
            continue
        for event in events:
            if event in UNATTENDED:
                unattended.append("{}: on.{}".format(label, event))
            elif event == "workflow_dispatch":
                unattended.append(
                    "{}: on.workflow_dispatch -- a button, not a clock, but the API "
                    "presses it too".format(label)
                )

    assert not unreadable, (
        "no `on:` block found in: {}. Unknown is not clean: docs/autonomy.md claims these "
        "files fire only on a human act, and this run could not read them to check."
    ).format(", ".join(unreadable))
    assert not unattended, (
        "a workflow now fires without a human: {}. "
        "That is not a bug -- it may be the first piece of the unattended loop #237 is "
        "about. It does mean docs/autonomy.md is stale and has to be re-derived in the "
        "same commit."
    ).format("; ".join(unattended))


def test_every_workflow_declares_a_human_trigger():
    """The positive half: silence is not enough, something must fire on a human act."""
    triggerless = []
    for label, text in _workflow_sources():
        events = triggers(text) or []
        if not any(event in ATTENDED for event in events):
            triggerless.append("{}: {}".format(label, events))
    assert not triggerless, (
        "workflow(s) with no human trigger: {}. A file that fires on nothing passes the "
        "check above for the wrong reason."
    ).format("; ".join(triggerless))


# --- the detector itself, so the two checks above are not passing on a broken reader ---

SCHEDULED = """name: nightly

on:
  schedule:
    - cron: "0 3 * * *"

jobs:
  tick:
    runs-on: ubuntu-latest
"""

DISPATCHED = """name: remote

on:
  repository_dispatch:
    types: [tick]
"""

NO_ON_BLOCK = """name: broken

jobs:
  tick:
    runs-on: ubuntu-latest
"""

SHORTHAND = """name: shorthand

on: [push, pull_request]
"""


def test_detector_sees_a_clock():
    assert triggers(SCHEDULED) == ["schedule"]


def test_detector_sees_a_remote_dispatch():
    assert triggers(DISPATCHED) == ["repository_dispatch"]


def test_detector_reports_absent_rather_than_empty():
    """The third state. `[]` here would mean "declared and fires on nothing"."""
    assert triggers(NO_ON_BLOCK) is None


def test_detector_reads_our_own_workflows_as_attended():
    """The must-not-fire half needs a reader that genuinely parses the real files."""
    for label, text in _workflow_sources():
        events = triggers(text)
        assert events, "{}: reader returned {!r}".format(label, events)


@pytest.mark.parametrize("text", [SCHEDULED, DISPATCHED])
def test_the_sweep_would_fail_on_a_planted_workflow(text, monkeypatch):
    """A planted source must redden the sweep -- otherwise it passes on anything."""
    monkeypatch.setattr(
        sys.modules[__name__],
        "_workflow_sources",
        lambda: [("planted: nightly.yml", text)],
    )
    with pytest.raises(AssertionError) as caught:
        test_no_workflow_starts_by_itself()
    assert "without a human" in str(caught.value)


def test_the_sweep_would_fail_on_an_unreadable_workflow(monkeypatch):
    monkeypatch.setattr(
        sys.modules[__name__],
        "_workflow_sources",
        lambda: [("planted: broken.yml", NO_ON_BLOCK)],
    )
    with pytest.raises(AssertionError) as caught:
        test_no_workflow_starts_by_itself()
    assert "Unknown is not clean" in str(caught.value)


def test_shorthand_list_form_is_not_silently_read_as_empty():
    """`on: [push]` on one line has no indented block, so the reader reports absent
    and the sweep fails loudly rather than calling the file clean. Known limit,
    pinned here so it is a decision rather than a surprise."""
    assert triggers(SHORTHAND) is None


# --- the document exists and README's pointer to it resolves ---

DOC = "docs/autonomy.md"


def test_the_document_exists():
    assert (REPO_ROOT / DOC).is_file(), (
        "{} is gone. The checks above are the measurement; the document is what "
        "they are a measurement of.".format(DOC)
    )


def test_readme_points_at_it():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert DOC in readme, (
        "README.md no longer links {} -- an installer reading only the README would "
        "not learn that this plugin does not run in their repository.".format(DOC)
    )
