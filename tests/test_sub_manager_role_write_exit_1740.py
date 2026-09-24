"""#1740: `agents/sub-manager.md`'s step 1 wrote its own role marker
(`agent_role.py --write sub-manager --root .`) without ever reading the
exit code. `scripts/agent_role.py` refuses with exit 3 (`_MARKER_CONFLICT`,
#1716) when a live marker already names a *different* role -- most
plausibly a stale `doctor` marker (the residue #1728 exists to clear).
When that refusal is silently ignored, `role_forbids_release` reads the
stale role for the rest of the tick, and since `doctor` is not on
`release_publish.py`'s own denylist, the code-level refusal to publish a
release is silently disabled with nothing printed that says so.

The fix: step 1 must capture the write's own exit code, retry once with
`--force` when (and only when) the live marker names `doctor` (short-lived
residue, safe to clobber -- the mirror image of `agents/doctor.md`'s own
reciprocal refusal, which never forces over a live `sub-manager` marker
because that one might genuinely be mid-tick), and hand back rather than
silently proceeding for any other role.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUB_MANAGER = REPO_ROOT / "agents" / "sub-manager.md"


def _flatten(text):
    return " ".join(text.lower().split())


def _unmet(text, anchors):
    folded = _flatten(text)
    return [anchor for anchor in anchors if anchor not in folded]


WRITE_EXIT_ANCHORS = [
    "write-exit:$?",
    "write-exit:3",
    "--force",
    "doctor",
    "could-not-run",
]


def test_sub_manager_checks_its_own_write_exit_code():
    """Without this, a refused write (exit 3) is silently ignored and the
    tick proceeds un-declared, per #1740."""
    text = SUB_MANAGER.read_text(encoding="utf-8")
    assert not _unmet(text, WRITE_EXIT_ANCHORS)


def test_the_write_exit_check_fires_on_the_prior_step_one():
    """The document as it stood before #1740: the write call with no exit
    code capture at all -- a positive control showing the anchors above
    are absent from the un-fixed text."""
    prior_step_one = (
        "```bash\n"
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/agent_role.py" --write sub-manager --root .\n'
        "```\n"
        "\n"
        "Run this in your very first shell call, before reading the board or doing anything else."
    )
    missing = _unmet(prior_step_one, WRITE_EXIT_ANCHORS)
    assert missing, (
        "the write-exit check passes against the document's prior step-1 "
        "text, which never checks the exit code at all: {}".format(missing)
    )


def test_sub_manager_force_is_conditioned_on_doctor_role_only():
    """The fix must not force-overwrite an arbitrary conflicting role --
    only a `doctor` marker is safe to clobber (short-lived residue); any
    other role (most plausibly a rival `sub-manager`, genuinely mid-tick)
    must hand back instead, mirroring agents/doctor.md's own reciprocal
    refusal rather than blindly retrying with --force for every conflict."""
    text = _flatten(SUB_MANAGER.read_text(encoding="utf-8"))
    assert "names role" in text or "names a different role" in text
    assert "doctor" in text
    assert "could-not-run" in text


def test_sub_manager_checks_the_forced_retrys_own_exit_code_too():
    """A first self-review round found the initial fix checked write-exit
    but never force-write-exit -- `--force` bypasses the conflict check,
    not a genuine underlying write failure, so an agent following the
    unpatched prose literally could believe itself declared when the
    forced retry itself failed."""
    text = _flatten(SUB_MANAGER.read_text(encoding="utf-8"))
    assert "force-write-exit" in text


def test_sub_manager_hand_back_actually_classifies_as_could_not_run():
    """A first self-review round found the initial fix's hand-back used
    agents/doctor.md's free-prose `could-not-tell: ...` style, but
    sub-manager.md's own handback is machine-parsed by
    `scripts/tick_handback.py`, which requires a `TICK: <state>` header
    plus that state's own companion field on a separate line
    (`REASON:` for `could-not-run`) -- a single-line `could-not-run: ...`
    sentence has no `TICK:` header at all and classifies as
    `could-not-classify`, not `could-not-run`, defeating the whole point
    of the fix one step later. This runs the actual classifier against
    the fix's own template, extracted from the file rather than
    retyped, so drift between the two is caught here rather than only in
    a human re-read."""
    import re
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import tick_handback  # noqa: E402

    text = SUB_MANAGER.read_text(encoding="utf-8")
    match = re.search(
        r"```\n(TICK: could-not-run\nREASON:.*?)\n```",
        text,
        re.DOTALL,
    )
    assert match, (
        "no TICK: could-not-run / REASON: fenced block found near the role-write fix"
    )
    template = match.group(1)
    filled = template.replace("<N>[, force-write-exit:<M>]", "3, force-write-exit:1")
    verdict = tick_handback.classify(filled)
    assert verdict["state"] == "could-not-run", (
        "the role-write hand-back template does not classify as could-not-run: "
        "{}".format(verdict)
    )
