"""#1544 step 3: the calls agents/tick-merge.md documents must be real ones.

Same discipline as `tests/test_tick_review_call_shape_1544.py` and
`tests/test_tick_dispatch_call_shape_1546.py`: a brand-new spawn's own first
documented call is exactly the class of defect #1530 found (a flag that reads
plausibly and does not exist). This file checks the report shapes
`agents/tick-merge.md` promises and the merge authority claim it makes about
`scripts/agent_role.py`.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_role  # noqa: E402

TICK_MERGE = REPO_ROOT / "agents" / "tick-merge.md"


def _text():
    return TICK_MERGE.read_text(encoding="utf-8")


def test_report_back_names_all_three_states():
    text = _text()
    for state in ("MERGE: merged", "MERGE: not-merged", "MERGE: could-not-run"):
        assert state in text, (
            "agents/tick-merge.md no longer documents the {0!r} report shape -- "
            "a caller reading only this file would not learn to expect it".format(state)
        )


def _bash_command_lines(text=None):
    return [
        line.strip()
        for line in (text if text is not None else _text()).splitlines()
        if line.strip().startswith("python3 ") or line.strip().startswith("git ")
    ]


def _writes_or_clears_marker(lines):
    return [line for line in lines if "--write" in line or "--clear" in line]


def test_it_never_writes_or_clears_the_role_marker():
    """It inherits the caller's marker -- writing or clearing it here would be
    a second, competing writer of the same file (#1544 step 2's own rule for
    agents/tick-review.md, restated for the merge spawn). The file's prose
    describes the caller's own `--write`/`--clear` calls to explain
    inheritance -- what must never appear is one of THIS file's own commands
    doing either."""
    offenders = _writes_or_clears_marker(_bash_command_lines())
    assert not offenders, (
        "documented command line writes/clears the marker: {0!r}".format(offenders)
    )


def test_the_marker_check_would_have_caught_a_real_violation():
    """Positive control for the check above: without this, a predicate that
    never matches anything (because agents/tick-merge.md happens to state its
    two calls as prose rather than as ``python3 ...``/``git ...`` command
    lines) would pass vacuously forever, giving false confidence that the
    'no marker write/clear' guarantee is code-checked when nothing here
    could ever fail (found in the maintainer's own review of this file's
    first version)."""
    bad_line = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_role.py" --write sub-manager --root .'
    offenders = _writes_or_clears_marker(_bash_command_lines(bad_line))
    assert offenders == [bad_line], (
        "fixture construction failed: the offending line was not caught, so "
        "the control proves nothing"
    )


def test_it_documents_no_tag_or_publish_call():
    """Merge authority is not tag or publish authority -- no command line in
    this file should ever run `git tag` or anything under `commands/
    release.md`. Prose stating that this file never runs those is fine and
    expected; a literal invocation of them is not."""
    offenders = [line for line in _bash_command_lines() if line.startswith("git tag")]
    assert not offenders, "documents a git tag command: {0!r}".format(offenders)


def test_the_git_tag_check_would_have_caught_a_real_violation():
    """Positive control for the check above, the same reasoning as the marker
    control: agents/tick-merge.md never states `git tag` as a command line
    today, so without this the check above would pass regardless of whether
    the underlying predicate can fail at all."""
    bad_line = "git tag v9.9.9"
    offenders = [
        line for line in _bash_command_lines(bad_line) if line.startswith("git tag")
    ]
    assert offenders == [bad_line], (
        "fixture construction failed: the offending line was not caught, so "
        "the control proves nothing"
    )


def test_agent_role_withholds_release_for_sub_manager_and_nothing_else():
    """Positive control for the file's own authority claim: `agent_role.py`'s
    `forbids_release` denylists exactly `sub-manager`, nothing else -- there is
    no merge-specific function in this module to narrow. If this module ever
    grows one, `agents/tick-merge.md`'s "Merge authority is not narrowed here"
    claim needs re-checking against it, not against this test."""
    assert agent_role.SUB_MANAGER == "sub-manager"
    assert agent_role.role_forbids_release(role="sub-manager") is True
    assert agent_role.role_forbids_release(role="maintainer") is False
    assert agent_role.role_forbids_release(role=None) is False
    assert not hasattr(agent_role, "role_forbids_merge"), (
        "scripts/agent_role.py grew a merge-specific denial function -- "
        "agents/tick-merge.md's claim that merge is not withheld needs "
        "re-checking against it before this test is updated to match"
    )
