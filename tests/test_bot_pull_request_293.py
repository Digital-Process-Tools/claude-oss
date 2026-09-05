"""A bot-opened pull request cannot use the gate's own escape hatch (#293).

Three scaffolded pieces compose into one defect, each correct alone. `.github/dependabot.yml`
opens action-bump pull requests. `oss-changelog.yml` lists `labeled` in its `types:`, for the
reason its own comment gives. Dependabot applies its OWN labels at open, so each one starts a
run and each run fails, because a dependabot pull request carries no fragment. Applying
`no-changelog` by hand afterwards makes a PASSING run exist and retracts nothing, so a merge
gate that aggregates every run on the head sha refuses a pull request the forge calls
`mergeable_state: clean`, with no action left that would change it.

The repair that belongs in THIS file is therefore not "make a passing run exist" -- it is
"do not create the failing run in the first place", which has to happen before the first
label event lands.

Two things are asserted here and they are not the same strength:

  * The author exemption is **executed**. The gate's own `run:` body is extracted from the
    rendered template and put in front of a real git repository, exactly as
    `tests/test_changelog_gate.py` does it, and the exit status is read. A test that only
    checked the template for a substring would pass while the shell was broken.
  * The `concurrency:` group cannot be executed by anything here -- it is a scheduling
    instruction to the forge. It is read structurally, with a matched control proving the
    reader discriminates rather than always answering yes.

Deliberately not a YAML parse: pyyaml is not installed on any leg of this repo's CI, so a
parse-based assertion would skip on all thirteen and a check that never runs is the defect
this plugin is named after.

The shell machinery is imported from `tests/test_changelog_gate.py` rather than copied. That
module carries a measured probe for which `bash` a Windows runner actually reaches -- WSL's
`bash.exe` is first on PATH there and is not a shell -- and a second copy of it would be a
second thing to keep right.

Python 3.9 compatible.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import scaffold  # noqa: E402

from test_changelog_gate import (  # noqa: E402
    BASH,
    GENERATED_WORKFLOW,
    _child_env,
    _config,
    _gate_script,
    _pull_request,
    _require,
    _run_script,
)

BOT = "dependabot[bot]"


def _run_gate(repo, author=None):
    """The gate step, over `repo`, as the forge would run it for `author`.

    `author` of None is the unset case on purpose: it is what an expression that
    evaluated to nothing would leave behind, and `set -u` is in force in that block.
    """
    for tool in ("git", "grep", "sed"):
        _require(tool)
    extra = {"BASE_REF": "main"}
    if author is not None:
        extra["PR_AUTHOR"] = author
    return _run_script(_gate_script(), repo, _child_env(BASH, **extra))


# A pull request that changes product code and adds no fragment: the exact shape the gate
# exists to refuse, and the exact shape every dependabot pull request has.
NO_FRAGMENT = {"src.py": "value = 2\n"}


# ------------------------------------------------------------------ the matched pair
#
# The exemption is a "must not fire" assertion, so the "must fire" half sits in the same
# fixture: same repository, same diff, same script, one environment variable apart. Without
# it, a gate that had stopped refusing anything at all would read as a working exemption.


def test_a_human_pull_request_with_no_fragment_is_still_refused(tmp_path):
    done = _run_gate(_pull_request(tmp_path, NO_FRAGMENT), author="a-human")
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout


def test_a_dependabot_pull_request_with_no_fragment_is_skipped_and_says_so(tmp_path):
    done = _run_gate(_pull_request(tmp_path, NO_FRAGMENT), author=BOT)
    assert done.returncode == 0, done.stdout
    # Announced, not silent. A check that declined to look and a check that looked and
    # found nothing must not print the same thing -- if a receiving repo points dependabot
    # at a runtime ecosystem, this line is the only place the omission is visible.
    assert "skipped" in done.stdout
    assert BOT in done.stdout


# ------------------------------------------------------- the exemption is exact, not loose
#
# An author is chosen by whoever opens the pull request, including on a fork, so a match that
# was a prefix, a substring or case-insensitive would be an exemption anyone could claim.


@pytest.mark.parametrize(
    "author",
    [
        "evil-dependabot[bot]",
        "dependabot[bot]-x",
        "dependabot",
        "Dependabot[bot]",
        "dependabot[bot] ",
        "",
    ],
)
def test_an_author_that_is_not_exactly_the_bot_is_not_exempt(tmp_path, author):
    done = _run_gate(_pull_request(tmp_path, NO_FRAGMENT), author=author)
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout


def test_an_unset_author_is_refused_rather_than_crashing_the_block(tmp_path):
    """`set -u` is in force, so an unset variable would abort the step with a shell error.

    That is a different failure from the one the gate means, and it would arrive as a red
    check with no receipt. The default has to be "not a bot", which is the closed direction.
    """
    done = _run_gate(_pull_request(tmp_path, NO_FRAGMENT), author=None)
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout
    assert "unbound" not in done.stdout.lower()


# ------------------------------------- the exemption is the narrowest change that helps
#
# It changes exactly one outcome: the one that currently fails with nothing left to do. Every
# other branch of the gate must answer for a bot exactly as it does for a human, and the two
# below are the ones with teeth -- a waved-through deletion drops somebody else's approved
# entry from the next release, silently, which is the #87 defect wearing a bot's name.


def test_a_dependabot_pull_request_that_deletes_a_pending_fragment_is_still_refused(
    tmp_path,
):
    repo = _pull_request(
        tmp_path, {"changelog.d/906.added.md": None, "src.py": "value = 2\n"}
    )
    done = _run_gate(repo, author=BOT)
    assert done.returncode == 1, done.stdout
    assert "deleted without being assembled" in done.stdout


def test_a_dependabot_pull_request_that_carries_a_fragment_reports_it_normally(
    tmp_path,
):
    repo = _pull_request(tmp_path, {"changelog.d/1.fixed.md": "- a thing (#1).\n"})
    done = _run_gate(repo, author=BOT)
    assert done.returncode == 0, done.stdout
    assert "Fragment present" in done.stdout
    # Not the exemption receipt: this one looked, and found one.
    assert "skipped" not in done.stdout


# ---------------------------------------------------- which field the author is read from
#
# The issue proposed `github.actor`. That is whoever triggered the EVENT, and on a `labeled`
# event it is whoever applied the label -- so a human labelling any pull request at all would
# be exempting themselves from the gate. The author of the pull request is `user.login`.


def test_the_author_comes_from_the_pull_request_author_and_never_from_the_actor():
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    assert "${{ github.event.pull_request.user.login }}" in body
    # Named in a comment is fine and is the point -- the template says why it is the wrong
    # field. Named in an `${{ }}` expression is the defect, so that is what is refused, and
    # the two are told apart rather than the whole string being banned.
    used = [
        line
        for line in body.splitlines()
        if "github.actor" in line and "${{" in line.split("github.actor")[0]
    ]
    assert used == [], used


def test_the_author_reaches_the_script_through_env_rather_than_interpolation():
    """A `${{ }}` expansion is textual substitution into shell source, and a login is
    attacker-chosen on a fork pull request. The rest of this step already takes that care
    with `BASE_REF`; the new value is the same class of input.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    for line in body.splitlines():
        if "github.event.pull_request.user.login" in line:
            assert line.strip().startswith("PR_AUTHOR:"), line
            break
    else:  # pragma: no cover - the assertion above names the failure
        pytest.fail("the rendered workflow never reads the pull request author")
    assert "$PR_AUTHOR" in body or "${PR_AUTHOR" in body


# ------------------------------------------------------------------ the concurrency group
#
# Nothing here can execute a scheduling instruction to the forge, so this is graded as a
# structural read and the control below is what stops it being a substring match that
# always says yes.


def _concurrency(text):
    """The workflow-level `concurrency:` mapping, or None.

    Top level only: a `concurrency:` nested inside a job is a different instruction, and a
    reader that accepted one would report a per-job group as a per-workflow one.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip() != "concurrency:":
            continue
        block = {}
        for follow in lines[i + 1 :]:
            if not follow.strip():
                continue
            if not follow.startswith("  ") or follow.startswith("   "):
                break
            key, _, value = follow.strip().partition(":")
            block[key] = value.strip()
        return block
    return None


def test_the_concurrency_reader_says_absent_when_it_is_absent():
    """The control. Without it, a reader that returned a truthy value for any text would
    make the assertion below pass against a workflow that declares nothing.
    """
    assert _concurrency("name: x\non:\n  pull_request:\n") is None
    # A per-JOB group is not a per-workflow one, and must not be mistaken for it.
    nested = "name: x\njobs:\n  a:\n    concurrency:\n      group: g\n"
    assert _concurrency(nested) is None


def test_the_workflow_groups_its_runs_per_pull_request_and_supersedes_them():
    block = _concurrency(scaffold.render_owned(GENERATED_WORKFLOW, _config()))
    assert block is not None, (
        "the workflow declares no workflow-level concurrency group"
    )
    assert block.get("cancel-in-progress") == "true", block
    group = block.get("group", "")
    # Per pull request. A constant group would serialise unrelated pull requests against
    # each other and cancel their runs, which is a worse defect than the one being fixed.
    assert "github.ref" in group, group
