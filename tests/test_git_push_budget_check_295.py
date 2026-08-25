"""#295 -- a pre-push hook that runs a suite meets a 300s default nobody set,
and the refusal used to land at push time, after an agent run was already
spent. `doctor.py` now reads the structural facts a maintainer would otherwise
only discover from a failed push: whether a `pre-push` hook exists at all, and
whether `.supertool.json` raises the budget above the default in a way that
still clears `ops.git-push.timeout` from the same merged entry.

Four states, and the first one is the one #126 already taught this repo to
get right: a repo with NO pre-push hook is `not-applicable`, reported OK --
not a gap, because the 300s default is correct there and a checker that warns
on every correctly configured repo is worthless by the time anyone reads it.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _supertool_config(root, doc):
    (root / doctor.WATCH_CONFIG).write_text(json.dumps(doc), encoding="utf-8")


def _hook(root, executable=True):
    hooks = root / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    path = hooks / "pre-push"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if executable:
        path.chmod(0o755)
    return path


def test_measured_on_a_repo_with_no_hook_and_no_config(tmp_path):
    """MUST FIRE: the positive control -- no `.git/hooks/pre-push` at all is the
    ordinary, correctly-configured state this repo itself measured (#295's own
    'Measured on this repository' section), and it must be reported clean."""
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_NOT_APPLICABLE


def test_hook_present_and_budget_unset_is_actionable(tmp_path):
    """The actionable case named directly by the issue: a hook exists and
    nothing raised the budget above the 300s default."""
    _hook(tmp_path)
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_ACTIONABLE


def test_hook_present_and_no_git_push_block_at_all_is_actionable(tmp_path):
    _hook(tmp_path)
    _supertool_config(tmp_path, {"ops": {"radar": {"watch_name": "oss"}}})
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_ACTIONABLE


def test_hook_present_and_budget_set_strictly_under_timeout_is_configured(tmp_path):
    _hook(tmp_path)
    _supertool_config(tmp_path, {"ops": {"git-push": {"budget": 1500}}})
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_CONFIGURED


def test_hook_present_and_budget_not_under_an_explicit_timeout_is_actionable(tmp_path):
    """The arithmetic is done here, not discovered at push time: a budget that
    would be refused by the op itself (not strictly under the timeout from
    the same merged entry) must not be reported as satisfied."""
    _hook(tmp_path)
    _supertool_config(
        tmp_path, {"ops": {"git-push": {"budget": 1000, "timeout": 900}}}
    )
    state, detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_ACTIONABLE
    assert "1000" in detail and "900" in detail


def test_hook_present_and_budget_equal_to_explicit_timeout_is_actionable(tmp_path):
    """Strictly under, not under-or-equal -- same refusal supertool's own
    git-push op makes; equal must not read as configured."""
    _hook(tmp_path)
    _supertool_config(
        tmp_path, {"ops": {"git-push": {"budget": 900, "timeout": 900}}}
    )
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_ACTIONABLE


def test_non_positive_budget_is_actionable_not_configured(tmp_path):
    """MUST NOT FIRE as configured: `budget < timeout` alone is satisfied by any
    non-positive number, so a corrupted or badly-templated 0/negative budget
    must not read as OK -- supertool's own git-push op would refuse it outright
    (found by review)."""
    _hook(tmp_path)
    _supertool_config(tmp_path, {"ops": {"git-push": {"budget": 0}}})
    state, detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_ACTIONABLE
    assert "0" in detail

    _supertool_config(tmp_path, {"ops": {"git-push": {"budget": -50}}})
    state, detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_ACTIONABLE
    assert "-50" in detail


def test_unreadable_supertool_config_is_could_not_tell(tmp_path):
    _hook(tmp_path)
    (tmp_path / doctor.WATCH_CONFIG).write_text("{not json", encoding="utf-8")
    state, detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_COULD_NOT_TELL
    assert detail


def test_malformed_git_push_block_is_could_not_tell(tmp_path):
    _hook(tmp_path)
    _supertool_config(tmp_path, {"ops": {"git-push": []}})
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_COULD_NOT_TELL


def test_non_numeric_budget_is_could_not_tell(tmp_path):
    _hook(tmp_path)
    _supertool_config(tmp_path, {"ops": {"git-push": {"budget": "soon"}}})
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_COULD_NOT_TELL


def test_check_git_push_budget_prints_ok_for_not_applicable(tmp_path):
    doctor.FINDINGS.clear()
    doctor.check_git_push_budget(tmp_path)
    states = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()
    assert states == ["OK"]


def test_check_git_push_budget_warns_for_actionable_and_not_for_configured(tmp_path):
    _hook(tmp_path)
    doctor.FINDINGS.clear()
    doctor.check_git_push_budget(tmp_path)
    actionable = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()

    _supertool_config(tmp_path, {"ops": {"git-push": {"budget": 1500}}})
    doctor.check_git_push_budget(tmp_path)
    configured = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()

    assert actionable == ["WARN"]
    assert configured == ["OK"]


def test_check_git_push_budget_warns_for_could_not_tell_not_silently(tmp_path):
    """could-not-tell must be visible, never folded into a clean OK -- an
    unreadable config is not the same claim as a repo that has no hook."""
    _hook(tmp_path)
    (tmp_path / doctor.WATCH_CONFIG).write_text("{not json", encoding="utf-8")
    doctor.FINDINGS.clear()
    doctor.check_git_push_budget(tmp_path)
    states = [state for state, _ in doctor.FINDINGS]
    doctor.FINDINGS.clear()
    assert states == ["WARN"]


def test_check_git_push_budget_never_measures_the_hook_by_running_it(tmp_path):
    """The issue is explicit that timing the hook means running it, which a
    diagnostic must not do -- so a hook that would hang or fail if executed
    must not affect the verdict at all."""
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-push").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    # deliberately NOT chmod +x, and deliberately never executed by the check
    state, _detail = doctor.git_push_budget_state(tmp_path)
    assert state == doctor.GIT_PUSH_BUDGET_ACTIONABLE


def test_check_git_push_budget_prints_ascii_only(tmp_path):
    _hook(tmp_path)
    for doc in (
        None,
        {"ops": {"git-push": {"budget": 1500}}},
        {"ops": {"git-push": {"budget": 1000, "timeout": 900}}},
    ):
        doctor.FINDINGS.clear()
        if doc is not None:
            _supertool_config(tmp_path, doc)
        doctor.check_git_push_budget(tmp_path)
        for _state, message in doctor.FINDINGS:
            message.encode("ascii")
    doctor.FINDINGS.clear()
