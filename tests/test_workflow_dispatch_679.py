"""#679: `tests.yml` gets `workflow_dispatch`; `changelog.yml` deliberately does not.

When a push-triggered run is simply never created by the forge -- a one-off, not a
broken trigger (see the issue's own two follow-up comments, which reproduced normal
push runs twice after the drop) -- this repository had no way to *ask* for one.
`gh workflow run tests.yml` refuses a workflow that declares no `workflow_dispatch`,
`gh run rerun` needs a run id that does not exist, and the only route left was pushing
an empty commit to `main` to provoke a trigger: a write to the default branch to work
around a missing button. `workflow_dispatch:` on `tests.yml` is that button.

Three things pinned here, one per open question the issue raises:

* **`tests.yml` declares `workflow_dispatch`.** The fix itself, and the "must fire"
  half -- red before the trigger is added, since nothing in this file declared it.

* **`changelog.yml` does not, and the control explains why rather than just asserting
  it.** The issue says explicitly not to add this to both workflows merely because
  they are both workflows. `changelog.yml`'s "A user-visible change carries a
  fragment" step reads `github.event.pull_request.labels.*.name` in its `if:` and
  `github.event.pull_request.base.ref` as `BASE_REF`. A `workflow_dispatch` run has no
  pull request: the label check evaluates against nothing (`contains(null, ...)` is
  false, so the `if:` -- which negates it -- is true and the step runs), and
  `BASE_REF` resolves to the empty string, turning
  `git diff --name-only "origin/$BASE_REF"...HEAD` into `git diff --name-only
  origin/...HEAD` -- not a ref this repository has, so the step fails outright. A
  dispatch run of this workflow would be actively broken, not merely meaningless, so
  it deliberately gets no dispatch trigger.

* **Adding the trigger does not make any leg of `tests.yml` conditional on the
  event.** The matrix and both jobs are unconditional today -- neither reads
  `github.event_name` nor any `github.event.*` expression -- and `workflow_dispatch`
  adds a third event type behind that "should not matter" claim. If a later edit adds
  such a read, this is where the third event needs to be reasoned about rather than
  assumed away.

What this file does not and cannot settle: whether a `workflow_dispatch` run's
verdict is readable by `gh-branch` afterwards. That needs a workflow actually present
on the default branch to dispatch against, which this test, running on a feature
branch pre-merge, cannot produce. See the developer report for #679 for how that
question is graded instead.

Deliberately not a YAML parse, in the same spirit as `tests/test_workflow_
permissions.py` beside it: the assertion is about what a maintainer reads in the
file, and this repository has no YAML dependency in its own test path.

Python 3.9 compatible.
"""

import os
from pathlib import Path

import pytest

# #962 added one structural assertion (no job and no step is conditional), which needs
# a parse. The text assertions above it stay text, per this module's docstring; the
# import is guarded the way every other yaml-using file here guards it, so a runner
# without pyyaml goes red rather than quiet.
try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def _text(name):
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def _on_block(text):
    """The keys directly under a top-level `on:` block, stripped to the key name.

    Returns None when no top-level `on:` key is found -- the failure this exists to
    catch is a workflow that has silently lost its trigger block, not one that
    declares an empty set of triggers. Lines nested deeper than the trigger keys
    themselves (`branches: [main]` under `push:`) are skipped rather than ending the
    scan, so a multi-line trigger does not truncate the read -- and so is a `#`
    comment at the trigger keys' own indent, so an explanatory comment beside
    `workflow_dispatch:` cannot be mistaken for a trigger of its own.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() != "on:":
            continue
        keys = []
        base_indent = None
        for following in lines[index + 1 :]:
            stripped = following.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            indent = len(following) - len(following.lstrip(" "))
            if indent == 0:
                break
            if base_indent is None:
                base_indent = indent
            if indent != base_indent:
                continue
            keys.append(stripped.split(":", 1)[0])
        return keys
    return None


def test_there_are_workflows_to_check():
    """Positive control. A missing workflows directory would make every check below
    pass having read no file."""
    assert WORKFLOW_DIR.exists() and list(WORKFLOW_DIR.glob("*.yml")), (
        "no .github/workflows/*.yml found -- the checks below are vacuous"
    )


def test_on_block_parses_known_triggers_correctly():
    """Positive control on the parser itself: `_on_block` must not silently return
    an empty or wrong list for a workflow that plainly has triggers, or the
    assertions below would pass no matter what the parser saw. `changelog.yml`'s
    single, comment-free trigger is the simple case; `tests.yml`'s three, one of
    them carrying a multi-line explanatory comment at the trigger keys' own indent,
    is the case the comment-skipping and indent-tracking logic exists for.
    """
    assert _on_block(_text("changelog.yml")) == ["pull_request"]
    assert _on_block(_text("tests.yml")) == [
        "push",
        "pull_request",
        "workflow_dispatch",
    ]


def test_tests_workflow_declares_workflow_dispatch():
    """The fix. Red until `workflow_dispatch:` is added to tests.yml's `on:` block."""
    triggers = _on_block(_text("tests.yml"))
    assert triggers is not None, "tests.yml: no `on:` block found"
    assert "workflow_dispatch" in triggers, (
        "tests.yml: expected `workflow_dispatch` under `on:`, got {!r}. Without it, "
        "a dropped run on main (#679) has no remedy short of an empty commit.".format(
            triggers
        )
    )


def test_changelog_workflow_does_not_declare_workflow_dispatch():
    """The control #679 asks for by name: do not add this to both workflows merely
    because they are both workflows. See this module's docstring for the mechanism --
    changelog.yml's fragment-required step breaks outright on a dispatch run because
    it depends on pull-request-only context (github.event.pull_request.*).
    """
    triggers = _on_block(_text("changelog.yml"))
    assert triggers is not None, "changelog.yml: no `on:` block found"
    assert "workflow_dispatch" not in triggers, (
        "changelog.yml: workflow_dispatch was added, but its fragment-required step "
        "reads github.event.pull_request.* with no pull request context on a "
        "dispatch run -- see this test module's docstring for what breaks. If that "
        "step has since been made to guard itself on event_name, update this test "
        "and say why in its docstring rather than deleting it."
    )


def test_the_parser_the_structural_half_needs_is_present_on_ci():
    """Same shape as `tests/test_shell_leg_budget_303.py`: locally pyyaml may be
    absent and the structural half skips with a reason; on a runner its absence is a
    broken install step, and `1 skipped` there is a check that could not look
    rendered as a check that looked."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the job/step conditionality "
            "assertions in this file did not run on a runner."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


@pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")
def test_tests_workflow_reads_no_event_context_outside_the_concurrency_flag():
    """Question 1 from #679, pinned: adding workflow_dispatch must not make any leg
    conditional. tests.yml read `github.event.*` nowhere at all until #962, and this
    keeps every *job and step* that way, or forces whoever adds such a read to reckon
    with a third event type explicitly.

    #962 added exactly one expression, at workflow level rather than in a leg:
    `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`. Reckoned with
    rather than exempted quietly, which is what this test's own instruction asks for:

    - on a **pull_request** run it is `true`, which is the whole point -- a superseded
      run is cancelled instead of finishing against a commit nobody will merge;
    - on a **push** run it is `false`, deliberately: a default-branch run is that
      commit's verdict for `scripts/statusline.py` and the release gates, and a
      cancelled one reports neither pass nor fail;
    - on a **workflow_dispatch** run -- the third event type this module exists for --
      it is also `false`, the same as a push. That is the safe direction and needs no
      further reasoning: a dispatch is the manual remedy for a *dropped* run (#679), so
      cancelling one because another dispatch followed would take away the remedy this
      workflow's own `on:` block was extended to provide.

    Nothing here becomes conditional: both jobs and every step still run on every
    event. That is the property the assertion below now states directly, instead of
    inferring it from the absence of a substring.
    """
    text = _text("tests.yml")
    doc = yaml.safe_load(text)

    # The property #679 actually cares about: no job and no step is skipped on the
    # basis of which *event* started the run. Not "no condition at all" -- the
    # Windows Defender exclusion step is conditional on `runner.os` and rightly so,
    # and a check demanding its deletion would be enforcing something nobody decided.
    # A platform condition means the same thing on all three event types; an event
    # condition is the one that makes a dispatch run behave unlike a push run.
    for name, job in (doc.get("jobs") or {}).items():
        assert "github.event" not in str(job.get("if", "")), (
            "tests.yml job {!r} became conditional on the event -- with three event "
            "types (push, pull_request, workflow_dispatch) whatever it evaluates to "
            "on a dispatch run has to be reasoned about here".format(name)
        )
        for i, step in enumerate(job.get("steps") or []):
            assert "github.event" not in str(step.get("if", "")), (
                "tests.yml job {!r} step {} became conditional on the event; see "
                "this test's docstring".format(name, i)
            )

    # And the event context is read in exactly one place, which the docstring above
    # accounts for event by event. `${{` is what turns `github.event...` from prose
    # (this file's own comments discuss the fact) into a live expression.
    live = [line.strip() for line in text.splitlines() if "${{ github.event" in line]
    assert live == ["cancel-in-progress: ${{ github.event_name == 'pull_request' }}"], (
        "tests.yml evaluates a github.event.* expression this test has not reckoned "
        "with: {!r}. Add the event-by-event reasoning to the docstring above rather "
        "than widening this list.".format(live)
    )


@pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")
def test_the_event_context_check_fires_on_an_unaccounted_expression():
    """Positive control. The assertion above compares a list built by a substring
    scan; run the scan over text that is wrong on purpose, or a scan that found
    nothing would look exactly like one that found only the accounted-for line."""
    text = (
        "jobs:\n"
        "  pytest:\n"
        "    if: ${{ github.event_name != 'workflow_dispatch' }}\n"
        "    steps:\n"
        "      - if: runner.os == 'Windows'\n"
    )
    live = [line.strip() for line in text.splitlines() if "${{ github.event" in line]
    assert live == ["if: ${{ github.event_name != 'workflow_dispatch' }}"]
    doc = yaml.safe_load(text)
    job = doc["jobs"]["pytest"]
    # The event condition is caught...
    assert "github.event" in str(job.get("if", ""))
    # ...and the platform condition beside it is not, which is the must-not-fire half:
    # a check that failed on both would be demanding the deletion of a step this
    # workflow legitimately runs on one OS only.
    assert "github.event" not in str(job["steps"][0].get("if", ""))
