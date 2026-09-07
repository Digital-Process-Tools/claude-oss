"""#1046: merged-but-undeleted `origin/fix/*` branches never checked by
`doctor.py` -- 57 of 58 refs on this repo's own forge were found to be
exactly this, months old, because `gh-pr-merge:...|cleanup` deletes the
remote branch only for a merge it actually ran cleanup for, and nothing
looks again after a refusal.

Three states, `ok` / a finding (`stale`) / `could-not-read`, and
`could-not-read` must never render as "none stale" -- the defect class this
whole repository is named after. Every "must not fire" case here (no stale
branches; an open PR's branch must never be flagged) is paired with a
"must fire" case in the same fixture, per CLAUDE.md's own rule that a
negative assertion needs a positive control.

Every branch listing goes through `gh api .../matching-refs/heads/<prefix>`,
never a local `git` call -- a self-review round found the first draft used
`git ls-remote --heads origin`, which needs a local `origin` remote that
neither `.oss.json`'s own `repo` key nor this suite's own fixtures guarantee.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_stale_branches as sb  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _config(repo="owner/name", branch_pattern="fix/{issue}", **overrides):
    config = {"repo": repo, "branch_pattern": branch_pattern}
    config.update(overrides)
    return config


def _run_sequence(responses):
    """One ``(returncode, stdout, stderr)`` per expected call, in call order.
    ``stdout``/``stderr`` may be ``str`` or ``bytes`` -- the module decodes
    either. Recording ``calls`` lets a test assert a call was, or was not,
    made (e.g. `gh pr list` is never reached when no branch matches)."""
    calls = []
    it = iter(responses)

    def run(cmd, **kwargs):
        calls.append(cmd)
        try:
            rc, out, err = next(it)
        except StopIteration:  # pragma: no cover - a fixture bug
            raise AssertionError("more calls than the fixture staged: {}".format(cmd))
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)

    run.calls = calls
    return run


def _matching_refs(names):
    return (0, json.dumps([{"ref": "refs/heads/" + name} for name in names]), "")


def _pr_list_json(rows):
    return (0, json.dumps(rows), "")


def _which_gh_only(name, path=None):
    return "/usr/bin/gh" if name == "gh" else None


# --------------------------------------------------------------- gating


def test_could_not_read_when_gh_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", lambda name, path=None: None)
    result = sb.stale_branches_state(tmp_path, config=_config())
    assert result["state"] == "could-not-read"
    assert "gh" in result["detail"]


def test_could_not_read_when_branch_pattern_has_no_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    result = sb.stale_branches_state(
        tmp_path, config=_config(branch_pattern="no-placeholder-here")
    )
    assert result["state"] == "could-not-read"
    assert "branch_pattern" in result["detail"]


def test_could_not_read_when_repo_slug_cannot_be_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    monkeypatch.setattr(
        doctor,
        "_origin_slug",
        lambda project_dir, run=None: (None, "no readable origin remote here"),
    )
    result = sb.stale_branches_state(tmp_path, config=_config(repo=None))
    assert result["state"] == "could-not-read"
    assert "origin" in result["detail"]


def test_a_malformed_repo_slug_is_could_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    result = sb.stale_branches_state(tmp_path, config=_config(repo="../secret"))
    assert result["state"] == "could-not-read"


# --------------------------------------------------------------- clean states


def test_no_matching_branches_is_ok_and_never_calls_gh_pr_list(tmp_path, monkeypatch):
    """Must-fire pair below (`test_a_merged_branch_is_flagged_as_stale`) proves
    this is not just an empty pipeline -- when nothing matches, `gh pr list` is
    never even reached."""
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    run = _run_sequence([_matching_refs([])])
    result = sb.stale_branches_state(tmp_path, config=_config(), run=run)
    assert result["state"] == "ok"
    assert result["stale"] == []
    assert len(run.calls) == 1
    assert "matching-refs/heads/fix/" in run.calls[0][2]


def test_matching_branches_with_no_merged_pr_are_ok(tmp_path, monkeypatch):
    """Positive control for the merged case: an OPEN PR's branch must never be
    flagged, and a branch with no PR at all must never be flagged either."""
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    run = _run_sequence(
        [
            _matching_refs(["fix/1", "fix/2"]),
            _pr_list_json(
                [
                    {"number": 1, "headRefName": "fix/1", "state": "OPEN"},
                    # fix/2 has no PR row at all
                ]
            ),
        ]
    )
    result = sb.stale_branches_state(tmp_path, config=_config(), run=run)
    assert result["state"] == "ok"
    assert result["stale"] == []


# --------------------------------------------------------------- the finding


def test_a_merged_branch_is_flagged_as_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    run = _run_sequence(
        [
            _matching_refs(["fix/1", "fix/2"]),
            _pr_list_json(
                [
                    {"number": 1, "headRefName": "fix/1", "state": "MERGED"},
                    {"number": 2, "headRefName": "fix/2", "state": "OPEN"},
                ]
            ),
        ]
    )
    result = sb.stale_branches_state(tmp_path, config=_config(), run=run)
    assert result["state"] == "stale"
    assert result["stale"] == ["fix/1"]
    assert "fix/2" not in result["stale"]


def test_check_stale_branches_reports_warn_with_the_delete_command(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    run = _run_sequence(
        [
            _matching_refs(["fix/1"]),
            _pr_list_json([{"number": 1, "headRefName": "fix/1", "state": "MERGED"}]),
        ]
    )
    sb.check_stale_branches(tmp_path, config=_config(), run=run)
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN"
    assert "fix/1" in message
    assert "owner/name" in message
    assert "gh api -X DELETE" in message


def test_check_stale_branches_reports_ok_when_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    run = _run_sequence([_matching_refs([])])
    sb.check_stale_branches(tmp_path, config=_config(), run=run)
    assert len(doctor.FINDINGS) == 1
    state, _message = doctor.FINDINGS[0]
    assert state == "OK"


# ------------------------------------------------------- could-not-read live


def test_gh_pr_list_call_that_does_not_run_is_could_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)

    calls = {"n": 0}

    def run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            rc, out, err = _matching_refs(["fix/1"])
            return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)
        raise OSError("gh vanished mid-run")

    result = sb.stale_branches_state(tmp_path, config=_config(), run=run)
    assert result["state"] == "could-not-read"
    assert "did not run" in result["detail"]


def test_check_stale_branches_reports_warn_never_ok_when_could_not_read(
    tmp_path, monkeypatch
):
    """The defect class this repository is named after: `could-not-read` must
    never render as `OK`."""
    monkeypatch.setattr(sb.gh_which, "safe_which", lambda name, path=None: None)
    sb.check_stale_branches(tmp_path, config=_config())
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN"
    assert "UNKNOWN, not clean" in message


def test_matching_refs_call_failure_is_could_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    run = _run_sequence([(1, "", "gh: could not resolve to a Repository (HTTP 404)")])
    result = sb.stale_branches_state(tmp_path, config=_config(), run=run)
    assert result["state"] == "could-not-read"


def test_undecodable_bytes_do_not_crash_the_check(tmp_path, monkeypatch):
    """#1019's own trap: bytes decoded with errors="replace", never
    universal_newlines=True, or a byte the runner's locale codec cannot
    represent raises `UnicodeDecodeError` out of a check meant to always
    return a state."""
    monkeypatch.setattr(sb.gh_which, "safe_which", _which_gh_only)
    run = _run_sequence([(1, b"bad \xff\xfe response", b"")])
    result = sb.stale_branches_state(tmp_path, config=_config(), run=run)
    assert isinstance(result["state"], str)
    assert result["state"] == "could-not-read"
