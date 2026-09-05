"""API-interpolation hardening ported from claude-supertool's own scaffolded copy
(#1035): `.oss/statusline.py` had drifted AHEAD of this plugin's own
`scripts/statusline.py` there -- three merged claude-supertool issues (#2245,
#2278, #2281) added guards this repo's source copy never received, which
inverts the owned-file contract (the source is supposed to be the copy that
never drifts behind what it scaffolds elsewhere).

`repo` and `branch` both come from `.oss.json` via `repo_config()` with no
upstream validation, and five call sites interpolate one or both of them
straight into a `gh api` argument:

- `_reading_from_check_runs` / `_reading_from_combined_status` build
  `"repos/{}/commits/{}/...".format(repo, branch)` -- both `repo` and `branch`
  in scope (#2245).
- `_gh_external_issue_count`, `_latest_release` interpolate `repo` alone,
  straight into a REST path segment (`"repos/{}/issues".format(repo)`,
  `"repos/{}/contents/...".format(repo)`), no `branch` in scope (#2278).
- `_gh_count` interpolates `repo` alone too, but NOT into a path segment --
  it builds `"repo:{} is:{} is:open".format(repo, kind)`, a search-API QUERY
  value against the fixed `search/issues` endpoint. A malformed value here
  cannot redirect the call to a different endpoint (there is only one); it
  can only widen or alter the search filter's own semantics. Guarded with
  the same `_malformed_repo` check anyway, because a value `_REPO_RE` refuses
  is not a legitimate `repo:` qualifier either, but the failure shape this
  one closes off is query-injection, not endpoint-confusion (self-review
  finding on this same round: the two failure shapes were originally
  described identically here, which was imprecise for this one site).

A malformed value makes the call address a different endpoint than the one
configured, silently, and reports the wrong branch's state as the configured
one's. `_malformed_repo` and `_malformed_api_ref` are the guards; every call
site refused reads as `None`, the same "could not look" shape every other
early-return in this module already uses -- not a new refusal a caller has to
learn.

Every "must refuse" case below is paired with a "must still call correctly"
positive control in the same fixture, per this repo's own rule -- a guard
asserted only by its absence passes when the function does nothing at all.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------------- _malformed_repo


def test_malformed_repo_rejects_missing_slash():
    assert statusline._malformed_repo("ownername") is True


def test_malformed_repo_rejects_whitespace():
    assert statusline._malformed_repo("owner/name with space") is True


def test_malformed_repo_rejects_none():
    assert statusline._malformed_repo(None) is True


def test_malformed_repo_rejects_empty_string():
    assert statusline._malformed_repo("") is True


def test_malformed_repo_rejects_extra_path_segment():
    assert statusline._malformed_repo("owner/name/extra") is True


def test_malformed_repo_rejects_dot_dot_segment():
    """Self-review finding (#1035): `_REPO_RE` alone (`\\A[^/\\\\s]+/[^/\\\\s]+\\Z`)
    only forbids a slash, a backslash and whitespace WITHIN a segment -- it
    never excludes a literal `..` segment, so `"../secret"` matches it as a
    perfectly good two-segment `owner/name` shape. Reused unchanged, that
    would leave `repos/../secret/commits/main/check-runs` reachable through
    `_malformed_repo`, the exact "malformed value reaches `gh api` unchanged
    and addresses a different endpoint" failure this whole port exists to
    close -- just moved from `branch` (which `_malformed_api_ref` already
    checks for `..` explicitly) to `repo` (which relied on `_REPO_RE` alone
    and was never checked for it)."""
    assert statusline._malformed_repo("../secret") is True
    assert statusline._malformed_repo("owner/..") is True
    assert statusline._malformed_repo("../..") is True


def test_malformed_repo_accepts_owner_slash_name():
    """The must-fire control: a well-formed repo is not flagged malformed."""
    assert statusline._malformed_repo("owner/name") is False


# ---------------------------------------------------------- _malformed_api_ref


def test_malformed_api_ref_rejects_bad_repo():
    assert statusline._malformed_api_ref("ownername", "main") is True


def test_malformed_api_ref_rejects_branch_with_whitespace():
    assert statusline._malformed_api_ref("owner/name", "ma in") is True


def test_malformed_api_ref_rejects_branch_with_question_mark():
    assert statusline._malformed_api_ref("owner/name", "ref?query=1") is True


def test_malformed_api_ref_rejects_branch_with_dot_dot():
    assert statusline._malformed_api_ref("owner/name", "../../etc") is True


def test_malformed_api_ref_rejects_none_branch():
    assert statusline._malformed_api_ref("owner/name", None) is True


def test_malformed_api_ref_rejects_empty_branch():
    assert statusline._malformed_api_ref("owner/name", "") is True


def test_malformed_api_ref_accepts_ordinary_branch_with_slash():
    """The must-fire control the issue calls out explicitly: a slash IS allowed
    in a branch name (e.g. `release/1.0`), because it is a legitimate last path
    segment, unlike a raw `..` or whitespace."""
    assert statusline._malformed_api_ref("owner/name", "release/1.0") is False


def test_malformed_api_ref_accepts_main():
    assert statusline._malformed_api_ref("owner/name", "main") is False


# ------------------------------------------------------- _reading_from_check_runs


def test_check_runs_refuses_malformed_repo(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not call _run with a malformed repo")

    monkeypatch.setattr(statusline, "_run", fail)
    assert statusline._reading_from_check_runs("bad repo", "main") is None


def test_check_runs_refuses_malformed_branch(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not call _run with a malformed branch")

    monkeypatch.setattr(statusline, "_run", fail)
    assert statusline._reading_from_check_runs("owner/name", "../../etc") is None


def test_check_runs_still_calls_with_well_formed_values(monkeypatch):
    seen = []

    def fake_run(command, timeout=None):
        seen.append(list(command))
        return None

    monkeypatch.setattr(statusline, "_run", fake_run)
    statusline._reading_from_check_runs("owner/name", "main")
    assert seen, "nothing was asked -- must-fire control failed"
    asked = " ".join(seen[0])
    assert "repos/owner/name/commits/main/check-runs" in asked, asked


# --------------------------------------------------- _reading_from_combined_status


def test_combined_status_refuses_malformed_repo(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not call _run with a malformed repo")

    monkeypatch.setattr(statusline, "_run", fail)
    assert statusline._reading_from_combined_status("bad repo", "main") is None


def test_combined_status_refuses_malformed_branch(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not call _run with a malformed branch")

    monkeypatch.setattr(statusline, "_run", fail)
    assert statusline._reading_from_combined_status("owner/name", "ref?x") is None


def test_combined_status_still_calls_with_well_formed_values(monkeypatch):
    seen = []

    def fake_run(command, timeout=None):
        seen.append(list(command))
        return None

    monkeypatch.setattr(statusline, "_run", fake_run)
    statusline._reading_from_combined_status("owner/name", "main")
    assert seen, "nothing was asked -- must-fire control failed"
    asked = " ".join(seen[0])
    assert "repos/owner/name/commits/main/status" in asked, asked


# ------------------------------------------------------------------- _gh_count


def test_gh_count_refuses_malformed_repo(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not call _run with a malformed repo")

    monkeypatch.setattr(statusline, "_run", fail)
    assert statusline._gh_count("bad repo", "issue") is None


def test_gh_count_still_calls_with_well_formed_repo(monkeypatch):
    def fake_run(command, timeout=None):
        return "3"

    monkeypatch.setattr(statusline, "_run", fake_run)
    assert statusline._gh_count("owner/name", "issue") == 3


# ---------------------------------------------------------- _gh_external_issue_count


def test_external_issue_count_refuses_malformed_repo(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not call _run with a malformed repo")

    monkeypatch.setattr(statusline, "_run", fail)
    assert statusline._gh_external_issue_count("bad repo", 3) is None


def test_external_issue_count_still_calls_with_well_formed_repo(monkeypatch):
    seen = []

    def fake_run(command, timeout=None):
        seen.append(list(command))
        return ""

    monkeypatch.setattr(statusline, "_run", fake_run)
    statusline._gh_external_issue_count("owner/name", 0)
    assert seen, "nothing was asked -- must-fire control failed"
    asked = " ".join(seen[0])
    assert "repos/owner/name/issues" in asked, asked


# --------------------------------------------------------------- _latest_release


def test_latest_release_refuses_malformed_repo(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not call _run with a malformed repo")

    monkeypatch.setattr(statusline, "_run", fail)
    assert statusline._latest_release("bad repo") is None


def test_latest_release_still_calls_with_well_formed_repo(monkeypatch):
    seen = []

    def fake_run(command, timeout=None):
        seen.append(list(command))
        return None

    monkeypatch.setattr(statusline, "_run", fake_run)
    statusline._latest_release("owner/name")
    assert seen, "nothing was asked -- must-fire control failed"
    asked = " ".join(seen[0])
    assert "contents/.claude-plugin/plugin.json" in asked, asked
