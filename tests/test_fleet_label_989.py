"""#989: a dispatch site that types subagent_type by hand can omit it silently.

A sub-manager tick found all three of its Agent() calls running as general-purpose
because subagent_type: "oss:developer" was never restated at the call site -- nothing
caught it until the tick reported the omission itself. `agent_call` renders the whole
literal Agent(...) invocation, not only the description string fleet_label already
composed, so a caller pastes the whole call rather than retyping subagent_type by
habit. An omitted or misspelled subagent_type must refuse, not render a call that
quietly spawns the wrong agent -- the CLI's positional argument makes omission a
Python-level missing-argument error, and this module additionally refuses a
misspelled one.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import fleet_label as fl  # noqa: E402


def test_agent_call_renders_the_whole_invocation():
    call = fl.agent_call(534, [534, 537, 495], "auto-update path", "oss:developer", model="sonnet")
    assert call == (
        'Agent(subagent_type: "oss:developer", model: "sonnet", '
        'run_in_background: false, description: "Lane 534 x3  auto-update path", '
        'prompt: "<brief>")'
    )


def test_agent_call_refuses_a_subagent_type_not_in_this_loop():
    # The historical failure ran as "general-purpose" -- that string must never
    # render as a valid call for this loop's own dispatch step.
    with pytest.raises(fl.FleetLabelError):
        fl.agent_call(534, [534], "auto-update path", "general-purpose")


def test_agent_call_refuses_a_missing_subagent_type():
    with pytest.raises(TypeError):
        fl.agent_call(534, [534], "auto-update path")


def test_agent_call_accepts_triager():
    call = fl.agent_call(534, [534], "board cleanup", "oss:triager")
    assert 'subagent_type: "oss:triager"' in call
    assert "model:" not in call


def test_cli_prints_the_whole_agent_call():
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fleet_label.py"),
         "534", "534,537,495", "auto-update path", "oss:developer", "--model", "sonnet"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == (
        'Agent(subagent_type: "oss:developer", model: "sonnet", '
        'run_in_background: false, description: "Lane 534 x3  auto-update path", '
        'prompt: "<brief>")'
    )


def test_cli_refuses_an_unknown_agent_type():
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fleet_label.py"),
         "534", "534", "auto-update path", "general-purpose"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode != 0


def test_agent_call_escapes_a_quote_in_the_phrase():
    # oss:auditor finding (#989 self-review): an unescaped quote in ``phrase``
    # closed the ``description`` field early and left the rest of the phrase as
    # bare tokens after the paste -- a phrase crafted with
    # ``", subagent_type: "general-purpose`` would silently re-open a new
    # keyword and could flip the very subagent_type this module exists to
    # protect, live through the field the module never validated.
    call = fl.agent_call(534, [534], 'do "the thing" now', "oss:developer")
    assert call == (
        'Agent(subagent_type: "oss:developer", run_in_background: false, '
        'description: "Lane 534  do \\"the thing\\" now", prompt: "<brief>")'
    )
    # A follow-up field-count check was tried and dropped: the exact-string
    # assertion above already pins the escaped output completely, and a
    # separate substring count over an escaped string is fragile in exactly
    # the way this fix is about (see #989 self-review).


def test_agent_call_escapes_a_backslash_in_the_phrase():
    # A trailing backslash must not swallow the escaped closing quote.
    call = fl.agent_call(534, [534], "trailing backslash \\", "oss:developer")
    assert call.endswith(
        'description: "Lane 534  trailing backslash \\\\", prompt: "<brief>")'
    )

def test_cli_without_agent_type_still_prints_only_the_label():
    # Positive control -- the original three-argument form is untouched.
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fleet_label.py"),
         "534", "534,537,495", "auto-update path"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Lane 534 x3  auto-update path"
