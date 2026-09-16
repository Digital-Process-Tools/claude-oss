"""#1477: setup.md's interactive stops, resolved case by case.

commands/run/setup.md is now reached unattended, through agents/scheduler-step.md,
spawned by /oss:run's own scheduler with nobody typing /oss:setup by hand -- the same
shape #1425 fixed in curate.md. Two of setup.md's own asks wrote into .oss.json, a
tracked file nothing commits until a human reviews the diff, so asking before writing
added a second stop in front of a review that already exists; those two are now write-
then-relay. The harness-permission grant is different: it writes into an untracked,
never-diffed, machine-scoped file and is the harness's only standing authorization for
a write op, so asking first is the only review it will ever get -- that one must still
ask.

A grep for the old sentences alone cannot tell "removed" from "never existed", so this
also asserts the surrounding write-without-asking language is present (the positive
control) and that the harness-permission ask survives untouched (the case that must NOT
have changed).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_MD = REPO_ROOT / "commands" / "run" / "setup.md"


def _text():
    return SETUP_MD.read_text(encoding="utf-8")


def test_config_write_no_longer_asks_first():
    text = _text()
    assert "ask before writing" not in text, (
        "setup.md still stops to ask before writing .oss.json -- unattended under "
        "/oss:run, that stop has nobody to answer it (#1477)"
    )


def test_config_write_states_it_writes_without_asking():
    text = _text()
    assert "then write it. Do not stop to ask" in text, (
        "the write-without-asking replacement sentence is missing -- a grep for the "
        "old sentence's absence alone cannot tell removal from rewording"
    )


def test_test_command_failure_no_longer_defers_to_a_live_human():
    text = _text()
    assert "let the human\ndecide" not in text and "let the human decide" not in text, (
        "the test-command verification step still hands an unattended run a decision "
        "with nobody there to make it (#1477)"
    )
    assert "write `null` and say what happened" in text, (
        "the replacement -- write null on anything but ok, and relay it -- is missing"
    )


def test_harness_permission_grant_still_asks_first():
    """Positive control: this ask must survive -- it writes an untracked,
    never-diffed, machine-scoped file with no later review point, unlike the two
    .oss.json writes above (#1477)."""
    text = _text()
    assert "Ask the\nmaintainer to add the rule; do not write it for them." in text, (
        "the harness-permission ask was removed or reworded -- it should not have "
        "changed: there is no commit-time review for .claude/settings.local.json"
    )
    assert "This one stays a question" in text, (
        "the sentence explaining why this ask survives while the others did not is "
        "missing"
    )
