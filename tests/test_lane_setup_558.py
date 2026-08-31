"""#558: the held-file set (open pull requests, live lane records) was retyped by
hand every tick, so a lane could be excluded before any measurement ran, and the
exclusion rendered identically to an `overlap` a real check would have reported.
Read literally off the issue: "Both close the tick with the issue unnamed and the
fleet reported `under-filled` with a reason. That is this repository's own defect
class sitting on the mechanism built to prevent it."

Two mechanical sources, both already read by this loop, now derivable rather than
hand-carried:

  - every open pull request's own file list (`held_from_open_prs`, via `gh pr list
    --json number,files` -- data, not a diff to parse);
  - every live lane record's own file list (`held_from_live_lanes`, the same
    registry `lane_count` already reads, extended to carry `files`).

`derive_held_set` combines them; a per-candidate verdict (available / blocked /
could-not-derive-the-held-set) is computed in `lane_report` for the `--lane` side
against the derived set. The issue's own two judgement calls, decided here:

  - the *fill* verdict (filled / under-filled / could-not-tell) is NOT computed by
    this script -- it needs the full candidate list under consideration this tick,
    a judgement about which issues are even being weighed, which this script has
    no way to know from one `--lane` argument. It stays prose in the tick.
  - the forge call is opt-in (`--derive-held` / `compute(..., derive_held=True)`),
    never the default, so the existing local/offline `--lane`/`--against` path is
    unchanged for every caller that does not ask for it.

A forge call that fails, or a live lane record missing the file list #558 depends
on, must never render as an empty confident held set -- `could-not-derive`, never
`resolved` with `held={}`, per the issue's own words: "This must never render as
`available`, and it must not render as `blocked` either."
"""

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import lane_setup  # noqa: E402
import spawn_guard  # noqa: E402


def _write_record(worktree_root, issue, files=None, age_seconds=0):
    root = lane_setup.lane_registry_dir(worktree_root)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "{0}.json".format(issue))
    payload = {
        "issue": issue,
        "branch": "fix/{0}".format(issue),
        "path": None,
        "recorded_at": time.time() - age_seconds,
        "pid": 1,
    }
    if files is not None:
        payload["files"] = files
    with open(path, "w") as fh:
        json.dump(payload, fh)


# --- record_lane: files threaded through and preserved across a plain call ------


def test_record_lane_stores_files_when_given(tmp_path):
    result = lane_setup.record_lane(tmp_path, 558, "fix/558", str(tmp_path / "558"), files=["a.py", "b.py"])
    assert result["state"] == "recorded"
    with open(result["path"]) as fh:
        assert json.load(fh)["files"] == ["a.py", "b.py"]


def test_record_lane_preserves_files_across_a_later_plain_call(tmp_path):
    """The ordinary sequence: a `--lane`-carrying overlap check, then a later plain
    `lane_setup.py <issue>` call (SKILL.md's own "writing each brief" row) that
    passes no `--lane` at all. The second call must not blank out the first call's
    files, or the held-set derivation degrades back to could-not-derive on its own
    the moment the brief is written."""
    lane_setup.record_lane(tmp_path, 558, "fix/558", str(tmp_path / "558"), files=["a.py", "b.py"])
    result = lane_setup.record_lane(tmp_path, 558, "fix/558", str(tmp_path / "558"))
    assert result["state"] == "recorded"
    with open(result["path"]) as fh:
        assert json.load(fh)["files"] == ["a.py", "b.py"]


def test_record_lane_files_empty_list_is_stored_as_given(tmp_path):
    """A `--lane` that genuinely resolved to zero files is a real, distinct state
    from "no --lane was given at all" -- must not be confused with the preserve
    case above."""
    lane_setup.record_lane(tmp_path, 558, "fix/558", str(tmp_path / "558"), files=["a.py"])
    result = lane_setup.record_lane(tmp_path, 558, "fix/558", str(tmp_path / "558"), files=[])
    with open(result["path"]) as fh:
        assert json.load(fh)["files"] == []


def test_record_lane_degrades_to_could_not_derive_when_the_prior_record_is_corrupt(tmp_path):
    """The preserve is best-effort: a corrupt previous record cannot be read back,
    so a plain call after it stores `files=None` rather than raising or claiming a
    file list it cannot verify. That is a real, if rare, loss -- but the very next
    reader (`held_from_live_lanes`) must see the same `files=None` as "recorded
    without --lane" and report `could-not-derive`, never a silently narrower
    `resolved`. This is the control that pins the read-modify-write's failure
    direction rather than merely asserting it in prose."""
    root = lane_setup.lane_registry_dir(tmp_path)
    os.makedirs(root, exist_ok=True)
    record_path = os.path.join(root, "558.json")
    with open(record_path, "w") as fh:
        fh.write("{not valid json")

    result = lane_setup.record_lane(tmp_path, 558, "fix/558", str(tmp_path / "558"))
    assert result["state"] == "recorded"
    with open(result["path"]) as fh:
        assert json.load(fh)["files"] is None

    held = lane_setup.held_from_live_lanes(tmp_path)
    assert held["state"] == "could-not-derive"


# --- held_from_live_lanes: control pair -----------------------------------------


def test_held_from_live_lanes_resolved_when_every_record_carries_files(tmp_path):
    _write_record(tmp_path, 1, files=["scripts/a.py"])
    _write_record(tmp_path, 2, files=["scripts/b.py", "scripts/a.py"])
    result = lane_setup.held_from_live_lanes(tmp_path)
    assert result["state"] == "resolved"
    assert set(result["held"]["scripts/a.py"]) == {"lane #1", "lane #2"}
    assert result["held"]["scripts/b.py"] == ["lane #2"]


def test_held_from_live_lanes_could_not_derive_when_a_live_record_lacks_files():
    """Must not fire the silent case: a live record recorded without --lane (or by
    a pre-#558 version of this script) makes the whole derivation untrustworthy,
    not a partial one that quietly omits that lane's files."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        _write_record(tmp, 3, files=None)
        result = lane_setup.held_from_live_lanes(tmp)
        assert result["state"] == "could-not-derive"


def test_held_from_live_lanes_excludes_the_named_issue(tmp_path):
    """A lane must not be told it collides with itself."""
    _write_record(tmp_path, 558, files=["scripts/lane_setup.py"])
    result = lane_setup.held_from_live_lanes(tmp_path, exclude_issue=558)
    assert result["state"] == "unknown"
    assert result["held"] == {}


def test_held_from_live_lanes_unknown_when_registry_never_written(tmp_path):
    result = lane_setup.held_from_live_lanes(tmp_path / "never-created")
    assert result["state"] == "unknown"


def test_held_from_live_lanes_prunes_expired_records_from_the_held_set(tmp_path):
    _write_record(tmp_path, 4, files=["scripts/old.py"], age_seconds=lane_setup.LANE_RECORD_TTL_SECONDS + 3600)
    result = lane_setup.held_from_live_lanes(tmp_path)
    assert result["state"] == "unknown"
    assert result["held"] == {}


# --- held_from_open_prs: control pair, via a stubbed `gh` -----------------------


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_held_from_open_prs_resolved_with_open_prs(monkeypatch):
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    payload = json.dumps(
        [{"number": 12, "files": [{"path": "scripts/foo.py"}, {"path": "scripts/bar.py"}]}]
    )
    monkeypatch.setattr(
        lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, payload, "")
    )
    result = lane_setup.held_from_open_prs("owner/repo")
    assert result["state"] == "resolved"
    assert result["held"]["scripts/foo.py"] == ["PR #12"]
    assert result["held"]["scripts/bar.py"] == ["PR #12"]


def test_held_from_open_prs_resolved_with_zero_open_prs(monkeypatch):
    """Must fire the positive control: zero open PRs is a confirmed zero, not an
    absence to fold into could-not-derive."""
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, "[]", ""))
    result = lane_setup.held_from_open_prs("owner/repo")
    assert result["state"] == "resolved"
    assert result["held"] == {}


def test_held_from_open_prs_could_not_derive_when_gh_is_not_on_path(monkeypatch):
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: None)
    result = lane_setup.held_from_open_prs("owner/repo")
    assert result["state"] == "could-not-derive"


def test_held_from_open_prs_could_not_derive_on_nonzero_exit(monkeypatch):
    """Must not fire the silent case: a failed `gh` call must never render as a
    confident, empty held set."""
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(
        lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(1, "", "boom: not authenticated")
    )
    result = lane_setup.held_from_open_prs("owner/repo")
    assert result["state"] == "could-not-derive"
    assert "boom" in result["detail"]


def test_held_from_open_prs_could_not_derive_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, "not json", ""))
    result = lane_setup.held_from_open_prs("owner/repo")
    assert result["state"] == "could-not-derive"


def test_held_from_open_prs_could_not_derive_when_the_page_limit_is_hit(monkeypatch):
    """Must not silently fire the truncation case as a confident `resolved`: a
    result that reaches `_PR_LIST_LIMIT` is indistinguishable from a page that was
    cut off mid-list, so it must be reported the same way a failed call is -- never
    folded into `resolved` with whatever partial `held` it managed to build."""
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh")
    limit = lane_setup._PR_LIST_LIMIT
    payload = json.dumps(
        [{"number": n, "files": [{"path": "scripts/f{0}.py".format(n)}]} for n in range(limit)]
    )
    monkeypatch.setattr(lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, payload, ""))
    result = lane_setup.held_from_open_prs("owner/repo")
    assert result["state"] == "could-not-derive"


def test_held_from_open_prs_resolved_when_under_the_page_limit(monkeypatch):
    """Positive control for the truncation case above: a result comfortably under
    the limit is still `resolved`, or the limit itself would be indistinguishable
    from a broken derivation."""
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh")
    payload = json.dumps([{"number": 1, "files": [{"path": "scripts/f.py"}]}])
    monkeypatch.setattr(lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, payload, ""))
    result = lane_setup.held_from_open_prs("owner/repo")
    assert result["state"] == "resolved"


# --- derive_held_set: combined states -------------------------------------------


def test_derive_held_set_resolved_combines_both_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh")
    payload = json.dumps([{"number": 5, "files": [{"path": "scripts/pr_file.py"}]}])
    monkeypatch.setattr(lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, payload, ""))
    _write_record(tmp_path, 9, files=["scripts/lane_file.py"])
    result = lane_setup.derive_held_set("owner/repo", tmp_path)
    assert result["state"] == "resolved"
    assert "scripts/pr_file.py" in result["held"]
    assert "scripts/lane_file.py" in result["held"]


def test_derive_held_set_could_not_derive_when_the_forge_call_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: None)
    result = lane_setup.derive_held_set("owner/repo", tmp_path)
    assert result["state"] == "could-not-derive"


def test_derive_held_set_could_not_derive_when_a_lane_record_is_untrustworthy(tmp_path, monkeypatch):
    monkeypatch.setattr(lane_setup.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(lane_setup.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, "[]", ""))
    _write_record(tmp_path, 9, files=None)
    result = lane_setup.derive_held_set("owner/repo", tmp_path)
    assert result["state"] == "could-not-derive"


# --- lane_report availability: control pair --------------------------------------


def test_lane_report_availability_available_when_disjoint_from_the_derived_set(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free_file.py").write_text("x\n")
    derived = {"state": "resolved", "held": {"scripts/other.py": ["PR #1"]}, "detail": ""}
    report = lane_setup.lane_report(tmp_path, ["scripts/free_file.py"], None, derived_held=derived)
    assert report["availability"]["state"] == "available"


def test_lane_report_availability_blocked_when_the_derived_set_overlaps(tmp_path):
    """Must not silently render `available`: an overlap with the derived set names
    the file and its holder(s), the way #558 asks."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "shared.py").write_text("x\n")
    derived = {"state": "resolved", "held": {"scripts/shared.py": ["PR #9"]}, "detail": ""}
    report = lane_setup.lane_report(tmp_path, ["scripts/shared.py"], None, derived_held=derived)
    assert report["availability"]["state"] == "blocked"
    assert report["availability"]["files"] == ["scripts/shared.py"]
    assert "PR #9" in report["availability"]["holders"]


def test_lane_report_availability_could_not_derive_never_reads_as_available_or_blocked(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "shared.py").write_text("x\n")
    derived = {"state": "could-not-derive", "held": {}, "detail": "gh is not on PATH"}
    report = lane_setup.lane_report(tmp_path, ["scripts/shared.py"], None, derived_held=derived)
    assert report["availability"]["state"] == "could-not-derive-the-held-set"
    assert report["availability"]["state"] not in ("available", "blocked")


def test_lane_report_still_works_unmodified_when_derived_held_is_none(tmp_path):
    """Backward compatibility: `derived_held` defaults to None, and the existing
    hand-typed --against path is byte-for-byte the old shape -- no `availability`
    key at all, so an old caller (`test_lane_setup_432.py`'s own fixtures among
    them) never has to handle a field that predates it."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x.py").write_text("x\n")
    report = lane_setup.lane_report(tmp_path, ["scripts/x.py"], None)
    assert "availability" not in report
    assert "held_source" not in report


# --- receipt: the verdict a developer brief actually reads -----------------------


def _minimal_payload(repo, derived_held, lane_patterns):
    return {
        "issue": 558,
        "repo": str(repo),
        "config": {"state": "ok", "problems": []},
        "base": {
            "state": "resolved", "remote": "origin", "ref": "origin/main",
            "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "detail": "",
        },
        "branch": {
            "state": "resolved", "pattern": "fix/{issue}", "name": "fix/558",
            "detail": "", "exists_local": False, "exists_remote": False,
        },
        "worktree": {"state": "resolved", "root": "/tmp", "path": "/tmp/558", "detail": "", "exists": False},
        "board": {"state": "ok", "lines": []},
        "lanes": None,
        "lane": lane_setup.lane_report(repo, lane_patterns, None, derived_held=derived_held),
    }


def test_receipt_names_the_holder_when_blocked(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "shared.py").write_text("x\n")
    derived = {"state": "resolved", "held": {"scripts/shared.py": ["PR #9"]}, "detail": ""}
    payload = _minimal_payload(tmp_path, derived, ["scripts/shared.py"])
    text = lane_setup.receipt(payload)
    assert "verdict : BLOCKED" in text
    assert "PR #9" in text


def test_receipt_says_available_when_disjoint(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("x\n")
    derived = {"state": "resolved", "held": {"scripts/other.py": ["PR #1"]}, "detail": ""}
    payload = _minimal_payload(tmp_path, derived, ["scripts/free.py"])
    text = lane_setup.receipt(payload)
    assert "verdict : available" in text


def test_receipt_says_could_not_derive_never_available_or_blocked(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "free.py").write_text("x\n")
    derived = {"state": "could-not-derive", "held": {}, "detail": "gh is not on PATH"}
    payload = _minimal_payload(tmp_path, derived, ["scripts/free.py"])
    text = lane_setup.receipt(payload)
    assert "verdict : COULD NOT DERIVE THE HELD SET" in text
    assert "verdict : available" not in text
    assert "verdict : BLOCKED" not in text


def test_receipt_does_not_reuse_the_only_one_side_given_wording_when_no_lane_given(tmp_path):
    """#558 review round: `--derive-held` with no `--lane` is "nothing to check",
    not "only the against side is missing" -- the pre-#558 sentence, reused
    unchanged, would misdescribe a call that never named a candidate at all."""
    derived = {"state": "resolved", "held": {"scripts/other.py": ["PR #1"]}, "detail": ""}
    payload = _minimal_payload(tmp_path, derived, None)
    text = lane_setup.receipt(payload)
    assert "only one side given" not in text
    assert "no --lane given" in text


# --- CLI: --derive-held / --against mutual exclusion, and the offline default ---


def _cli(tmp_path, *extra_args):
    (tmp_path / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "example/example",
                "default_branch": "main",
                "clone": "/tmp/does-not-matter",
                "worktree_root": "/tmp/does-not-matter-wt",
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": [],
                "changelog_dir": None,
                "docs_targets": [],
                "labels": {"priority": [], "lanes": []},
                "state_file": "/tmp/does-not-matter-state.json",
            }
        )
    )
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return spawn_guard.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "lane_setup.py"), "558", "--repo", str(tmp_path)]
        + list(extra_args),
        subject="what lane_setup.py's CLI answers for this tree and these flags",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_refuses_derive_held_together_with_against(tmp_path):
    result = _cli(tmp_path, "--lane", "x.py", "--against", "y.py", "--derive-held")
    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr


def test_compute_never_derives_the_held_set_without_derive_held(tmp_path, monkeypatch):
    """The offline path stays offline: `derive_held_set` -- and so `gh` -- must
    never run unless `derive_held=True` is passed, so a machine with no network
    and no `gh` still gets the ordinary --lane/--against answer instead of paying
    for a call it never asked for."""

    def _boom(*args, **kwargs):
        raise AssertionError("derive_held_set must not run without derive_held=True")

    monkeypatch.setattr(lane_setup, "derive_held_set", _boom)
    result = lane_setup.compute(tmp_path, 558, lane_patterns=["scripts/x.py"])
    # No .oss.json here, so this hits the early could-not-run branch -- which is
    # exactly the path that used to skip derive_held_set entirely and must still.
    assert result["config"]["state"] == "could-not-run"
