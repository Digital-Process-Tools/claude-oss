"""#1690: a doctor spawn was observed running `scaffold.py --apply`, committing the
result to the default branch and pushing it, in a run whose own prompt explicitly
said not to. `agents/doctor.md`'s own prose ("scripted repairs, never push, never a
pull request") was already there and did not stop it -- a sentence is not a
mechanism, the same lesson #695 names for release authority.

The fix: `agents/doctor.md` now writes a "doctor" role marker as its very first
step, via `scripts/agent_role.py --write doctor`. That marker is what
`scaffold.py --apply` (scripts/scaffold.py's own CLI, gated by
`agent_role.scaffold_apply_refusal`) refuses under without `--i-was-asked` -- code
a doctor spawn's own brief cannot silently route around the way it could a
sentence. The brief also snapshots `.claude/settings.local.json`'s digest
(`agent_role.settings_local_digest`) before and after the run, so an unexplained
permission write is a reportable finding.

This is a content-pin test over `agents/doctor.md`'s own prose (the same class as
`tests/test_doctor_branch_protection_gate_1649.py` and
`tests/test_recon_call_shape_1586.py`) -- it cannot prove a spawn obeys its brief,
only that the brief still says what it must.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_MD = REPO_ROOT / "agents" / "doctor.md"


def _text():
    return DOCTOR_MD.read_text(encoding="utf-8")


def test_the_role_marker_is_written_before_anything_else():
    text = _text()
    marker_idx = text.find("agent_role.py")
    # The literal diagnostic invocation, not any mention of the word
    # "doctor.sh" -- the frontmatter description names it too, near the top
    # of the file, which would make this pass regardless of ordering.
    diagnostic_idx = text.find('bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh"')
    assert marker_idx != -1
    assert diagnostic_idx != -1
    assert marker_idx < diagnostic_idx, (
        "the role marker must be written before the diagnostic runs, so the "
        "scaffold-apply gate is live for the whole rest of the spawn"
    )


def test_the_marker_write_names_the_doctor_role_literally():
    assert "--write doctor" in _text()


def test_the_settings_digest_is_taken_before_and_after():
    text = _text()
    assert text.count("settings_local_digest") >= 2, (
        "one call alone cannot answer whether the file changed -- a before "
        "and an after are both required"
    )


def test_the_scaffold_apply_call_carries_the_escape_hatch():
    """The brief's own sanctioned repair must pass --i-was-asked, or its own
    normal 'Ours to repair' step would be refused by the gate it just made
    live for itself."""
    assert "scaffold.py --apply --i-was-asked" in _text()


def test_never_git_push_still_appears_beside_the_new_guardrail():
    """The existing #1649 guardrail (never git push) must not have been
    silently dropped while adding the new one."""
    assert "never `git push`" in _text()
