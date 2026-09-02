"""#784: `agents/developer.md`'s changelog-fragment assembler lookup checked two
hardcoded candidate paths (`.oss/assemble_changelog.py`, `scripts/assemble_changelog.py`)
and, finding neither, told the agent to conclude "no assembler here" -- which is false in
a repo that wires the assembler in somewhere else (`.github/scripts/assemble_changelog.py`
is a real instance) and has it running in CI. `oss_rules.assembler_path()` checks the
identical two locations and returns `None` for the same reason, so pointing the brief at
that function does not by itself add a third state -- the brief itself has to say that
"not at either canonical path" is not the same claim as "not wired anywhere", and give the
agent something to do (check for a workflow invocation) before it renders the gap as a
clean no-assembler skip.

This file checks the prose says that, not that any code path executes -- there is no
executable assembler-resolution routine inside `agents/developer.md` to run.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"


def _flat():
    return " ".join(DEVELOPER_MD.read_text(encoding="utf-8").split())


def test_still_names_the_two_canonical_locations_in_order():
    text = _flat()
    assert ".oss/assemble_changelog.py" in text
    assert "scripts/assemble_changelog.py" in text
    assert text.index(".oss/assemble_changelog.py") < text.index(
        "scripts/assemble_changelog.py"
    )


def test_neither_candidate_existing_is_not_read_as_no_assembler():
    """The false middle=third-state collapse #784 is about: `assembler_path()` returning
    `None` must not be glossed as "this repo has no fragment checker" without a further
    check for one wired in some other way."""
    text = _flat()
    assert "not the same claim as" in text or "does not mean" in text, (
        "agents/developer.md does not say that neither canonical path existing is a "
        "different claim from 'this repo has no assembler' -- the #784 gap"
    )


def test_names_a_could_not_resolve_state_distinct_from_no_assembler():
    text = _flat()
    assert "could-not-resolve" in text or "could not resolve" in text, (
        "agents/developer.md never names a could-not-resolve state for the assembler "
        "lookup, so a wired-but-unfound assembler still has nowhere to render but "
        "'no assembler here'"
    )
