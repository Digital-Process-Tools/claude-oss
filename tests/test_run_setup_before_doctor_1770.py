"""#1770: `/oss:run` on a repository with no `.oss.json` spent a whole doctor
spawn (37 WARN/FAIL lines, ~10.5 minutes, 18 of them `not checked` only because
the config was missing) before step 2 ever reached `due: setup`.

`commands/run.md` is the whole procedure the scheduler follows, so the order is a
fact about its text: with no `.oss.json`, step 2 must be reached before the
doctor spawn, and setup must hand back to step 1 so the doctor then runs against
the config setup just wrote. With a config present, step 1 still runs first --
the positive control, since a rule that skipped the doctor always would also
pass the first assertion.
"""

from pathlib import Path

RUN_MD = Path(__file__).resolve().parent.parent / "commands" / "run.md"
DOCTOR_SPAWN = 'Agent(subagent_type: "oss:doctor"'


def _text():
    return RUN_MD.read_text(encoding="utf-8")


def _section(text, heading):
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_no_config_sends_step_1_to_step_2_before_the_doctor_spawn():
    step1 = _section(_text(), "## Step 1 --")
    assert DOCTOR_SPAWN in step1
    before_spawn = step1.split(DOCTOR_SPAWN, 1)[0]
    assert "No `.oss.json`" in before_spawn, (
        "step 1 reaches the doctor spawn before saying what to do when there is "
        "no .oss.json yet (#1770)"
    )
    assert "step 2" in before_spawn


def test_the_doctor_still_runs_first_when_a_config_exists():
    """Positive control: the carve-out is conditional on the config being absent,
    so step 1 still spawns the doctor, and is still step 1."""
    text = _text()
    assert text.index("## Step 1 --") < text.index("## Step 2 --")
    assert DOCTOR_SPAWN in _section(text, "## Step 1 --")


def test_setup_hands_back_to_step_1_not_step_2():
    """After setup writes the config, the doctor has something to check; returning
    to step 2 would skip it for the rest of the run."""
    text = _text()
    setup = _section(text, "## setup")
    assert "return to step 1" in setup
    assert "return to step 2" not in setup
    due = text.split("- **`due`**", 1)[1].split("- **`ranked`**", 1)[0]
    assert "return to step 1" in due
    assert "return to step 2" not in due
