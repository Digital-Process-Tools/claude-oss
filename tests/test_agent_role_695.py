"""`scripts/agent_role.py` -- the code half of #695's second binding constraint.

The issue is explicit that release (tag, publish) authority must not reach
the per-tick sub-manager, and that the withholding must be "in the code, not
only in prose": #696 files the releaser agent separately -- now built as
`agents/releaser.md` -- and nothing may let a sub-manager spawn reach a
publish call, regardless of whether a releaser agent exists to run one
instead.

Prose in `agents/sub-manager.md` says the sub-manager never runs the release
phase. This module is what makes that a fact `release_publish.py` checks for
itself rather than a request the sub-manager's own brief could ignore --
the same "prose is a request, a grant is not enforced by prose" argument
`CLAUDE.md` already makes about tool grants, applied to a role instead of a
tool.

The mechanism: `OSS_AGENT_ROLE=sub-manager` in the environment. A sub-manager
sets it before doing anything else, and `release_publish.py` refuses before
reading `.oss.json`, before extracting notes, before anything -- if that
role is present, publishing is not attempted at all, regardless of what
policy the repository states.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agent_role  # noqa: E402


def test_no_role_set_does_not_forbid(monkeypatch):
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    assert agent_role.role_forbids_release() is False


def test_maintainer_role_does_not_forbid(monkeypatch):
    """Positive control: a role that legitimately holds release authority
    must not be caught by the same check."""
    monkeypatch.setenv(agent_role.ROLE_ENV, "maintainer")
    assert agent_role.role_forbids_release() is False


def test_sub_manager_role_forbids_release(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "sub-manager")
    assert agent_role.role_forbids_release() is True


def test_sub_manager_role_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "  Sub-Manager  ")
    assert agent_role.role_forbids_release() is True


def test_explicit_role_argument_overrides_environment(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "sub-manager")
    assert agent_role.role_forbids_release(role="maintainer") is False


def test_release_refusal_names_the_role_and_the_action():
    refusal = agent_role.release_refusal("publish a GitHub Release", role="sub-manager")
    assert refusal["forbidden"] is True
    assert refusal["role"] == "sub-manager"
    assert "publish a GitHub Release" in refusal["reason"]
    assert "696" in refusal["reason"]


def test_release_refusal_when_not_forbidden():
    refusal = agent_role.release_refusal("publish a GitHub Release", role="maintainer")
    assert refusal["forbidden"] is False
