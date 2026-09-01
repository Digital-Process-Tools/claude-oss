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

Deliberately not a YAML parse: `triggers()` below is itself the thing under test, and
its whole point is the distinction a real parser would collapse -- an absent `on:` block
and an `on:` block that declares nothing both come back as "no events" from a library
call, and this file exists to keep those two apart. `tests/test_workflow_permissions.py`
reads the same files the same way, for its own reason.

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

# `workflow_dispatch` is a button, but the API presses it too -- so it stays flagged
# for every workflow except the ones named here, and a name has to carry a reason.
# Adding a workflow to this dict is the "re-derive docs/autonomy.md in the same
# commit" the failure message below asks for: this constant and that document's text
# are the same decision, made twice on purpose so the code and the prose cannot
# drift apart the way the rest of docs/autonomy.md's central claim is guarded
# against drifting from this file.
#
# #679 is the first entry: a maintainer running `gh workflow run tests.yml` by hand
# when the forge drops a push-triggered run on `main`, with no remedy otherwise short
# of an empty commit to the default branch. `test_the_manual_dispatch_exception_is_
# named_and_reasoned` below checks that nothing in this plugin's own scripts issues
# that call itself -- if something did, "a human presses this" would be false and the
# exception would have no basis.
MANUAL_DISPATCH_EXCEPTIONS = {
    "ours: .github/workflows/tests.yml": (
        "#679 -- the manual remedy for a push-triggered run the forge drops on "
        "main. Invoked by a maintainer running `gh workflow run tests.yml`; nothing "
        "in this plugin's own scripts, skills, agents or commands calls it."
    ),
}


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
        head = line.split("#", 1)[0].rstrip() if not line.lstrip().startswith("#") else line
        if head not in ("on:", '"on":', "'on':"):
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
    """The central claim of docs/autonomy.md, measured rather than asserted.

    `workflow_dispatch` on a workflow named in `MANUAL_DISPATCH_EXCEPTIONS` does not
    count against this: that dict is the record of a conscious decision, checked for
    staleness and for a reason by `test_the_manual_dispatch_exception_is_named_and_
    reasoned` below, which is a stronger claim than "the sweep did not happen to look
    here."
    """
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
            elif event == "workflow_dispatch" and label not in MANUAL_DISPATCH_EXCEPTIONS:
                unattended.append(
                    "{}: on.workflow_dispatch -- a button, not a clock, but the API "
                    "presses it too, and this workflow is not named in "
                    "MANUAL_DISPATCH_EXCEPTIONS".format(label)
                )

    assert not unreadable, (
        "no `on:` block found in: {}. Unknown is not clean: docs/autonomy.md claims these "
        "files fire only on a human act, and this run could not read them to check."
    ).format(", ".join(unreadable))
    assert not unattended, (
        "a workflow now fires without a human, undeclared: {}. "
        "That is not a bug -- it may be the first piece of the unattended loop #237 is "
        "about. Either name it in MANUAL_DISPATCH_EXCEPTIONS with a reason, if a human "
        "is genuinely the only thing that can press it, or treat it as the real thing "
        "#237 is about. Either way, docs/autonomy.md has to be re-derived in the same "
        "commit."
    ).format("; ".join(unattended))


def test_the_manual_dispatch_exception_is_named_and_reasoned():
    """The exception carved out above needs three things checked, or it is a way to
    silence the sweep rather than a documented decision -- the same distinction the
    dependabot exception below is checked for, on its own axis.

    * every exception carries a non-empty reason;
    * the workflow it names still exists and still declares workflow_dispatch, so a
      renamed or reverted file does not leave a stale, unfired exception behind;
    * nothing under scripts/ -- the only place this plugin's own automation lives --
      issues the call that would make "a human presses this" false. Scoped to
      scripts/ rather than every file: prose describing the manual command, in a
      workflow comment or a test docstring, is not an automated call and must not
      trip this.
    """
    sources = dict(_workflow_sources())
    for label, reason in MANUAL_DISPATCH_EXCEPTIONS.items():
        assert reason.strip(), "{}: exception with no reason".format(label)
        assert label in sources, (
            "{} is named as a manual-dispatch exception but no longer exists in "
            "the workflow sweep -- remove the stale exception, and re-derive "
            "docs/autonomy.md.".format(label)
        )
        events = triggers(sources[label])
        assert events is not None and "workflow_dispatch" in events, (
            "{} is named as a manual-dispatch exception but no longer declares "
            "workflow_dispatch -- remove the stale exception, and re-derive "
            "docs/autonomy.md.".format(label)
        )

    calling = []
    for path in sorted((REPO_ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "gh workflow run" in text or "/dispatches" in text:
            calling.append(str(path.relative_to(REPO_ROOT)))
    assert not calling, (
        "{} issue(s) a workflow-dispatch call. MANUAL_DISPATCH_EXCEPTIONS is built "
        "on 'a human presses this, the API does not' -- if this plugin's own code "
        "dispatches a workflow, that basis is gone and the exception needs "
        "re-arguing, not just re-checking.".format(", ".join(calling))
    )


def test_every_workflow_declares_a_human_trigger():
    """The positive half: silence is not enough, something must fire on a human act.

    `None` is kept out of the triggerless list rather than folded into it with
    `or []`. Both would fail the test, but the message would name the wrong
    cause -- "declares no human trigger" for a file whose triggers this run
    could not read -- which is the defect class this repository is named after,
    one layer inside the check written to hold that line.
    """
    triggerless = []
    unreadable = []
    for label, text in _workflow_sources():
        events = triggers(text)
        if events is None:
            unreadable.append(label)
        elif not any(event in ATTENDED for event in events):
            triggerless.append("{}: {}".format(label, events))
    assert not unreadable, (
        "no `on:` block found in: {}. Not the same finding as the one below -- this run "
        "could not read these files, rather than reading them and finding no human trigger."
    ).format(", ".join(unreadable))
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


UNNAMED_DISPATCH = "name: undeclared\n\non:\n  workflow_dispatch:\n"


@pytest.mark.parametrize(
    "text",
    [SCHEDULED, DISPATCHED, UNNAMED_DISPATCH],
    ids=["schedule", "repository_dispatch", "unnamed workflow_dispatch"],
)
def test_the_sweep_would_fail_on_a_planted_workflow(text, monkeypatch):
    """A planted source must redden the sweep -- otherwise it passes on anything.

    The third case is the must-fire pairing for `MANUAL_DISPATCH_EXCEPTIONS`: a
    `workflow_dispatch` on anything other than the one named workflow must still
    redden the sweep, or the exception is a way to turn the whole check off rather
    than a scoped one.
    """
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


# --- the one scheduled surface this plugin does seed, accounted for rather than invisible ---

DEPENDABOT = ".github/dependabot.yml"


def test_the_seeded_dependabot_config_is_still_the_scheduled_one():
    """`docs/autonomy.md` names exactly one thing this plugin puts in a managed
    repository that runs on a clock, and this is it: a default -- created once
    when absent, theirs forever after -- telling the forge's own dependency bot
    to open a pull request on a weekly schedule.

    It is checked here rather than swept with the workflows because it is not a
    workflow and its schedule is correct. The reason it needs a check at all is
    that it is the counter-example to the sentence beside it: a sweep that found
    only `push` and `pull_request` triggers, with this file out of scope, would
    have licensed "nothing runs on its own" -- which was the first version of
    that sentence and was wrong.

    Fails if the schedule leaves, which would make the document's exception
    stale, and fails if the file leaves `TEMPLATES`, which would make it
    fictional.
    """
    assert DEPENDABOT in scaffold.TEMPLATES, (
        "{} is no longer a default this plugin seeds. docs/autonomy.md names it as the "
        "one scheduled thing an install puts in a repository -- that is now fiction."
    ).format(DEPENDABOT)
    body = scaffold.TEMPLATES[DEPENDABOT](_config())
    assert "schedule:" in body and "interval:" in body, (
        "{} no longer declares a schedule: {!r}. The document's one stated exception to "
        "'nothing runs on its own' has gone, so the sentence has to be re-derived."
    ).format(DEPENDABOT, body)


def test_dependabot_is_a_default_and_not_an_owned_file():
    """Which contract it lands under is the whole of what the document claims
    about consent: a default is written once when absent and is theirs forever,
    so a repository that deletes it is never given it back. An owned file would
    be replaced wholesale on every run, which is a different promise."""
    assert DEPENDABOT not in scaffold.OWNED, (
        "{} became an owned file. docs/autonomy.md says the only clock an install "
        "starts is one the repository can delete and keep deleted; replacing it "
        "wholesale on every run breaks that."
    ).format(DEPENDABOT)


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
