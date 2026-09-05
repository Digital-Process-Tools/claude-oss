"""Every workflow of ours that reaches the assembler installs what the assembler needs.

`scripts/assemble_changelog.py` guards its one import and refuses to run without it: no
parser, no claim, exit non-zero. That refusal is the design. It also means a CI job that
never installs the parser does not quietly degrade -- it fails, or worse, it passes while
having checked nothing, depending on which arm of the script it reached.

Both happened. The changelog gate shipped without the install step and its first real run
failed on the parser rather than on a fragment; the comment recording that is still in
`changelog.yml`. The lesson was then applied to exactly that one file. `tests.yml` installs
`pytest pytest-cov` and nothing else, so the entire suite over the assembler -- the heading
refusal, the raw-HTML refusal, the fence state machine, all of it -- has never once been
exercised on a runner. It passes locally because the package happens to be installed there,
which is the difference between a green tick and a checked property (#38).

`scaffold.ASSEMBLER_DEPENDENCIES` is already the single declaration of what that script
needs, already held against the script's own guarded imports by AST, and already enforced
against the workflow we *generate* for other repos. It was never enforced against the two
workflows we run on ourselves. That asymmetry is the whole bug: the plugin made the
guarantee true for every repo it scaffolds except the one it lives in.

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

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
OUR_WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))

#: Our workflows that end up executing the assembler, and how they get there. Spelled out
#: rather than inferred so that adding a workflow is a decision about this list, and so the
#: reason each one qualifies survives into the failure message.
CONSUMERS = {
    "changelog.yml": "runs scripts/assemble_changelog.py directly",
    "tests.yml": "runs pytest, and the suite imports the assembler",
}

#: What makes a workflow a consumer. Used only to catch a workflow that reaches the
#: assembler and is missing from the map above.
REACHES_ASSEMBLER = ("assemble_changelog.py", "pytest")


def _text(name):
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def test_there_are_workflows_and_a_dependency_to_check():
    """Positive control. An empty glob or an empty map makes every check below vacuous."""
    assert OUR_WORKFLOWS, "no .github/workflows/*.yml found"
    assert scaffold.ASSEMBLER_DEPENDENCIES, "no assembler dependencies declared"


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_the_consumer_workflow_exists(name):
    assert (WORKFLOW_DIR / name).exists(), (
        "{} is listed as reaching the assembler but does not exist -- if it was renamed, "
        "update CONSUMERS rather than deleting the entry".format(name)
    )


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_every_consumer_installs_every_declared_assembler_dependency(name):
    text = _text(name)
    for package in scaffold.ASSEMBLER_DEPENDENCIES.values():
        assert package in text, (
            "{} {}, but never installs {}. Without it the assembler raises CannotValidate "
            "and the job's result says nothing about any fragment. The package name comes "
            "from scaffold.ASSEMBLER_DEPENDENCIES, which is the one place it is "
            "declared.".format(name, CONSUMERS[name], package)
        )


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_every_consumer_installs_before_it_runs(name):
    """Order, not just presence. An install step after the run step is not an install."""
    lines = [line.strip() for line in _text(name).splitlines()]
    for package in scaffold.ASSEMBLER_DEPENDENCIES.values():
        installs = [i for i, line in enumerate(lines) if package in line]
        uses = [
            i
            for i, line in enumerate(lines)
            if any(token in line for token in REACHES_ASSEMBLER) and package not in line
        ]
        assert installs, "{}: {} is never installed".format(name, package)
        assert uses, "{}: nothing in it reaches the assembler".format(name)
        assert min(installs) < max(uses), (
            "{}: {} is installed at line {} but the assembler is reached at line {}".format(
                name, package, min(installs) + 1, max(uses) + 1
            )
        )


def test_no_workflow_reaches_the_assembler_without_being_listed_as_a_consumer():
    """The drift guard, and the reason this file is not just two assertions.

    The hole was not that somebody made a wrong call about `tests.yml`; it is that
    `tests.yml` reaching the assembler was never a fact anything checked. A workflow added
    later that runs the suite would repeat it exactly.
    """
    unlisted = []
    for path in OUR_WORKFLOWS:
        if path.name in CONSUMERS:
            continue
        text = path.read_text(encoding="utf-8")
        hits = [token for token in REACHES_ASSEMBLER if token in text]
        if hits:
            unlisted.append("{} (mentions {})".format(path.name, ", ".join(hits)))
    assert not unlisted, (
        "these workflows reach the assembler but are not in CONSUMERS, so nothing checks "
        "that they install the parser: " + "; ".join(unlisted)
    )
