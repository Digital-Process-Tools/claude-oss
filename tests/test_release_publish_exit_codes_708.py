"""commands/release.md must name every exit code release_publish.py can emit -- #708.

The 0.16.0 release gate's round-two audit found `release_publish.py` gained a fourth
publish-lifecycle exit code, `EXIT_ROLE_FORBIDDEN = 5` (#697), while
`commands/release.md`'s own outcomes section still names three -- and so does the
script's own module docstring. Two pull requests, each defensible alone -- one added
the exit code, one edited the document that maps exit codes -- and neither review saw
the gap, which is exactly what this guard closes: it compares the two sets by
computation, not by eye, the mechanism issue #708 itself proposes.

**Reachability was not assumed here.** The auditor's own finding rested on the pure
functions and a regex over the document, not on an end-to-end CLI receipt, because its
two live calls were denied by the harness classifier -- the issue says so itself.
`tests/test_release_publish_role_gate_695.py` already runs the script as a real
subprocess with the sub-manager role set and asserts
`result.returncode == release_publish.EXIT_ROLE_FORBIDDEN`, so exit 5 is *observed*,
not merely reasoned, and this file leans on that existing coverage rather than
re-proving reachability from scratch.

**The trap named in this issue does not apply here.** A fourth code that renders
identically to one of the other three (to every caller) would mean documenting it
closes nothing. `role-forbidden` does not: its JSON `state` is its own string, distinct
from `create`/`created`/`skipped`/`could-not-run`/`could-not-create`, and its exit code
(5) is distinct from 0/3/4 -- both checked directly below.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_publish  # noqa: E402

RELEASE_MD = REPO_ROOT / "commands" / "release.md"

OUTCOMES_ANCHOR = "exit codes because a shell reads those and never reads prose"
DOCSTRING_ANCHOR = "Exit codes, because a shell reads those and never reads prose:"


def _publish_lifecycle_exit_codes():
    """Every exit code `_exit_code` can return for a state this module actually emits."""
    return {
        release_publish._exit_code(state) for state in release_publish.PUBLISH_STATES
    }


def _outcomes_window(text):
    """The prose between the publish-outcomes anchor and the next `## ` heading.

    Scoped rather than swept whole-file: `commands/release.md` documents several
    *other* scripts' exit codes (`release_delta.py`, `release_version.py`) in the same
    file, and a bare "exit N" regex over the whole document would fold those
    unrelated codes into this script's set.
    """
    lower = text.lower()
    start = lower.index(OUTCOMES_ANCHOR)
    rest = text[start:]
    heading = rest.find("\n## ", 1)
    return rest if heading == -1 else rest[:heading]


def _documented_exit_codes(text):
    window = _outcomes_window(text)
    return {int(n) for n in re.findall(r"\bexit (\d+)\b", window, re.IGNORECASE)}


def _docstring_exit_codes(text):
    # The anchor line is immediately followed by a blank line, so splitting on the
    # first "\n\n" without stripping that leading blank first returns an empty
    # string for `first_para` -- measured directly, not assumed: a run against the
    # real docstring with this bug in place reported "missing 0, 3, 4, 5" for a
    # docstring that plainly names three of those four, which is itself a version
    # of #708's own failure mode inside the guard meant to catch it.
    block = text.split(DOCSTRING_ANCHOR, 1)[1].lstrip("\n")
    first_para = block.split("\n\n", 1)[0]
    return {int(n) for n in re.findall(r"^\s*(\d+)\s", first_para, re.MULTILINE)}


# --------------------------------------------------------------------------- #
# The extractor itself, on fixtures, before it is ever pointed at a real file.
# Must-fire (sees a real exit 5) paired with must-not-fire (does not leak the
# *next* section's unrelated "exit 9" into this section's set) in the same
# fixture, and a second pair proving the extractor reports an absence as an
# absence rather than as a false "everything's here".
# --------------------------------------------------------------------------- #

SAMPLE_WITH_FOUR_OUTCOMES = (
    "Four outcomes, exit codes because a shell reads those and never reads prose:\n"
    "\n"
    "- **exit 0, `create` / `created`** -- ok\n"
    "- **exit 4, `skipped`** -- ok\n"
    "- **exit 3, `could-not-run`** -- ok\n"
    "- **exit 5, `role-forbidden`** -- ok\n"
    "\n"
    "## Next section\n"
    "unrelated prose mentioning exit 9, which must never be picked up\n"
)

SAMPLE_WITH_THREE_OUTCOMES = (
    "Three outcomes, exit codes because a shell reads those and never reads prose:\n"
    "\n"
    "- **exit 0, `create` / `created`** -- ok\n"
    "- **exit 4, `skipped`** -- ok\n"
    "- **exit 3, `could-not-run`** -- ok\n"
    "\n"
    "## Next section\n"
    "unrelated prose mentioning exit 9, which must never be picked up\n"
)


def test_extractor_sees_a_real_exit_5_and_ignores_the_next_section():
    codes = _documented_exit_codes(SAMPLE_WITH_FOUR_OUTCOMES)
    assert codes == {0, 3, 4, 5}, codes


def test_extractor_reports_the_absence_this_issue_describes():
    """The must-not-fire counterpart on the same mechanism: three outcomes documented,
    and the extractor must say so -- not silently see a 5 that is not there."""
    codes = _documented_exit_codes(SAMPLE_WITH_THREE_OUTCOMES)
    assert codes == {0, 3, 4}, codes
    assert 5 not in codes


# --------------------------------------------------------------------------- #
# The real files.
# --------------------------------------------------------------------------- #


def test_outcomes_window_finds_the_real_anchor_in_release_md():
    """Positive control for the two checks below: if the anchor text ever moves or is
    reworded, this fails loudly instead of the checks below silently comparing empty
    sets and passing for the wrong reason."""
    text = RELEASE_MD.read_text(encoding="utf-8")
    window = _outcomes_window(text)
    assert "exit" in window.lower()
    assert len(window) < len(text), "the window swallowed the rest of the file"


def test_release_md_names_every_exit_code_release_publish_can_emit():
    text = RELEASE_MD.read_text(encoding="utf-8")
    documented = _documented_exit_codes(text)
    reachable = _publish_lifecycle_exit_codes()
    missing = reachable - documented
    assert not missing, (
        "release_publish.py can exit with {0}, undocumented in commands/release.md's "
        "outcomes section (documents {1}). #708.".format(
            sorted(missing), sorted(documented)
        )
    )


def test_release_md_does_not_document_an_exit_code_the_script_cannot_emit():
    """Would this test still pass if the code did nothing? No: a typo'd `exit 7` in the
    doc trips this even though the check above stays green either way."""
    text = RELEASE_MD.read_text(encoding="utf-8")
    documented = _documented_exit_codes(text)
    reachable = _publish_lifecycle_exit_codes()
    extra = documented - reachable
    assert not extra, (
        "commands/release.md documents exit code(s) {0} that _exit_code() cannot "
        "produce for any state in PUBLISH_STATES ({1})".format(
            sorted(extra), sorted(reachable)
        )
    )


def test_module_docstring_names_every_exit_code_it_can_emit():
    text = Path(release_publish.__file__).read_text(encoding="utf-8")
    docstring_codes = _docstring_exit_codes(text)
    reachable = _publish_lifecycle_exit_codes()
    missing = reachable - docstring_codes
    assert not missing, (
        "release_publish.py's own module docstring Exit codes section is missing "
        "{0}, which _exit_code() can return. #708.".format(sorted(missing))
    )


def test_role_forbidden_is_distinguishable_from_every_other_state():
    """The trap check, run rather than argued: role-forbidden must not render
    identically to another state's exit code or its own `state` string."""
    codes_by_state = {
        state: release_publish._exit_code(state)
        for state in release_publish.PUBLISH_STATES
    }
    assert codes_by_state[release_publish.STATE_ROLE_FORBIDDEN] == 5
    other_codes = {
        code
        for state, code in codes_by_state.items()
        if state != release_publish.STATE_ROLE_FORBIDDEN
    }
    assert 5 not in other_codes
    assert release_publish.STATE_ROLE_FORBIDDEN not in (
        s
        for s in release_publish.PUBLISH_STATES
        if s != release_publish.STATE_ROLE_FORBIDDEN
    )
