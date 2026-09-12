"""#1435: two independent script-hygiene findings from a hands-on pass.

1. `--root` and `--repo` name the same concept (the repo this script acts on)
   but are spelled differently across scripts -- `next_action.py` and
   `statusline.py` used `--root`; `triage_trigger.py` and
   `cohort_freeze_record.py` used `--repo`. Each script now accepts both
   spellings via an `add_argument` alias (or, for `statusline.py`'s manual
   `_arg_value` parsing, the same fallback), so a caller using the "wrong"
   one for a given script is not refused.

2. `next_action.py`'s `--record-skip`/`--take` write paths had no
   `--state-file` override, so the write path could not be pointed at a
   scratch file in isolation. `--state-file` now overrides the state file
   used for both.

Every "must fire" case here is paired with a "must not fire" (or "still
works the old way") case in the same fixture family, per this repo's own
rule for a negative assertion.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import cohort_freeze  # noqa: E402
import cohort_freeze_record as cfr  # noqa: E402
import next_action  # noqa: E402
import statusline  # noqa: E402
import triage_trigger  # noqa: E402


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run(args, cwd, env=None):
    return subprocess.run(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=env or _git_env(),
    )


def _git_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    env = _git_env()
    _run(["git", "init", "--quiet", "."], cwd=root, env=env)
    _run(["git", "config", "user.email", "t@example.com"], cwd=root, env=env)
    _run(["git", "config", "user.name", "t"], cwd=root, env=env)
    (root / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=root, env=env)
    _run(["git", "checkout", "--quiet", "-B", "main"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, env=env)
    _run(
        ["git", "remote", "add", "origin", "https://example.invalid/repo.git"],
        cwd=root,
        env=env,
    )
    return root


def _write_config(root, extra=None):
    config = {
        "repo": "example/example",
        "default_branch": "main",
        "changelog_dir": "changelog.d",
    }
    if extra:
        config.update(extra)
    (root / ".oss.json").write_text(json.dumps(config))
    return config


def _quiet_inbound(monkeypatch):
    monkeypatch.setattr(
        next_action,
        "_fresh_inbound_reading",
        lambda repo: {
            "state": "measured",
            "unruled_issues": 0,
            "unreviewed_prs": 0,
            "unanswered_comments": None,
        },
    )


def _not_fired_release(monkeypatch):
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {"state": "not-due", "reason": "no fragments"},
    )


def _quiet_triage_trigger(monkeypatch):
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_NOT_DUE,
            "detail": "release.triggers.triage_after_release is not enabled",
        },
    )


def _candidate(payload, source):
    for entry in payload.get("candidates", []):
        if entry["source"] == source:
            return entry
    return None


# --------------------------------------------------------- --root / --repo aliases


def test_next_action_accepts_repo_alias_for_root(tmp_path, monkeypatch):
    """Must fire: `--repo` must work exactly like `--root` on next_action.py."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    rc = next_action.main(["--repo", str(root), "--json"])
    assert rc == 0


def test_next_action_still_accepts_root(tmp_path, monkeypatch):
    """Must-not-break control: the pre-existing `--root` spelling keeps working."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    rc = next_action.main(["--root", str(root), "--json"])
    assert rc == 0


def test_triage_trigger_accepts_root_alias_for_repo(tmp_path):
    """Must fire: `--root` must work exactly like `--repo` on triage_trigger.py."""
    root = _git_repo(tmp_path)
    _run(["git", "tag", "v1.0.0"], cwd=root)
    _write_config(root, {"release": {"triggers": {"triage_after_release": False}}})

    rc = triage_trigger.main(["--root", str(root), "--json"])
    assert rc in (0, 1)


def test_triage_trigger_still_accepts_repo(tmp_path):
    """Must-not-break control: the pre-existing `--repo` spelling keeps working."""
    root = _git_repo(tmp_path)
    _run(["git", "tag", "v1.0.0"], cwd=root)
    _write_config(root, {"release": {"triggers": {"triage_after_release": False}}})

    rc = triage_trigger.main(["--repo", str(root), "--json"])
    assert rc in (0, 1)


def _fake_record_freeze_result():
    return {
        "state": cohort_freeze.STATE_FROZEN,
        "reason": "",
        "label": "cohort-1",
        "tag": "v1.0.0",
        "cutoff": "2026-01-01T00:00:00Z",
        "count": 1,
        "members": [1],
        "added": [1],
        "dry_run": True,
    }


def test_cohort_freeze_record_accepts_root_alias_for_repo(monkeypatch):
    """Must fire: `--root` must work exactly like `--repo` on
    cohort_freeze_record.py -- `record_freeze` itself is stubbed so this
    proves only that the flag is accepted and reaches the same code path,
    without shelling out to a real `gh`."""
    monkeypatch.setattr(
        cfr, "record_freeze", lambda *a, **k: _fake_record_freeze_result()
    )

    rc = cfr.main(
        [
            "--root",
            "example/example",
            "--tag",
            "v1.0.0",
            "--cohort",
            "1",
            "--state",
            "/nonexistent/state.json",
            "--at",
            "2026-01-01T00:00:00Z",
            "--gh",
            "gh",
        ]
    )
    assert rc == 0


def test_cohort_freeze_record_still_accepts_repo(monkeypatch):
    """Must-not-break control: the pre-existing `--repo` spelling keeps working."""
    monkeypatch.setattr(
        cfr, "record_freeze", lambda *a, **k: _fake_record_freeze_result()
    )

    rc = cfr.main(
        [
            "--repo",
            "example/example",
            "--tag",
            "v1.0.0",
            "--cohort",
            "1",
            "--state",
            "/nonexistent/state.json",
            "--at",
            "2026-01-01T00:00:00Z",
            "--gh",
            "gh",
        ]
    )
    assert rc == 0


def test_statusline_mark_stale_accepts_repo_alias_for_root(monkeypatch, capsys):
    """Must fire: statusline.py's manual `_arg_value` parsing accepts
    `--repo` for `--mark-stale` the same way it accepts `--root`."""
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "org/repo"})
    monkeypatch.setattr(statusline, "mark_board_stale", lambda repo: True)

    rc = statusline.main(["--mark-stale", "--repo", "/some/path"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "marked" in out.lower()


def test_statusline_mark_stale_still_accepts_root(monkeypatch, capsys):
    """Must-not-break control: the pre-existing `--root` spelling keeps working."""
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "org/repo"})
    monkeypatch.setattr(statusline, "mark_board_stale", lambda repo: True)

    rc = statusline.main(["--mark-stale", "--root", "/some/path"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "marked" in out.lower()


# --------------------------------------------------------- next_action.py --state-file


def test_take_with_state_file_override_writes_scratch_not_configured_file(
    tmp_path, monkeypatch
):
    """Must fire: `--state-file` diverts the write path (`--take`'s
    `_arm_route_source` call) to a scratch file, leaving the repo's own
    configured state file completely untouched -- provable in isolation
    rather than only by hashing the real state file before/after."""
    root = _git_repo(tmp_path)
    _write_config(
        root, {"curate_route_threshold": 0, "state_file": ".max/oss-watch.json"}
    )
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    scratch = tmp_path / "scratch-state.json"

    first = next_action.rank(root)
    assert _candidate(first, "curate")["state"] == next_action.CANDIDATE_DUE

    rc = next_action.main(
        ["--root", str(root), "--take", "curate", "--state-file", str(scratch)]
    )
    assert rc == 0

    assert scratch.exists()
    real_configured = root / ".max" / "oss-watch.json"
    assert not real_configured.exists()

    # And the real, configured state file was never touched: reading it
    # unarmed produces the same due reading as before, proving the
    # suppression was recorded in the scratch file, not the real one.
    second = next_action.rank(root)
    assert _candidate(second, "curate")["state"] == next_action.CANDIDATE_DUE


def test_take_without_state_file_override_still_writes_configured_file(
    tmp_path, monkeypatch
):
    """Must-not-break control: with no `--state-file` override, `--take`
    keeps writing to the repo's own configured state file, exactly as
    before."""
    root = _git_repo(tmp_path)
    _write_config(
        root, {"curate_route_threshold": 0, "state_file": ".max/oss-watch.json"}
    )
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    first = next_action.rank(root)
    assert _candidate(first, "curate")["state"] == next_action.CANDIDATE_DUE

    rc = next_action.main(["--root", str(root), "--take", "curate"])
    assert rc == 0

    assert (root / ".max" / "oss-watch.json").exists()

    second = next_action.rank(root)
    assert _candidate(second, "curate") is None, second


def test_record_skip_with_state_file_override_writes_scratch_not_configured_file(
    tmp_path, monkeypatch
):
    """Must fire: the same `--state-file` override reaches `--record-skip`'s
    own write path too, not only `--take`'s."""
    root = _git_repo(tmp_path)
    _write_config(
        root, {"curate_route_threshold": 0, "state_file": ".max/oss-watch.json"}
    )
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    # Both `inbound` and `curate` are due here, so `curate` is a genuine
    # deviation from `inbound`'s own top rank (`DEFAULT_ORDER` puts
    # `inbound` ahead of `curate`) -- `record_skip` refuses a taken_source
    # that is not itself one of `rank()`'s own ranked sources.
    monkeypatch.setattr(
        next_action,
        "_fresh_inbound_reading",
        lambda repo: {
            "state": "measured",
            "unruled_issues": 1,
            "unreviewed_prs": 0,
            "unanswered_comments": None,
        },
    )
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    scratch = tmp_path / "scratch-state.json"

    rc = next_action.main(
        [
            "--root",
            str(root),
            "--record-skip",
            "curate",
            "--reason",
            "quiet board",
            "--state-file",
            str(scratch),
        ]
    )
    assert rc == 0
    assert scratch.exists()
    assert not (root / ".max" / "oss-watch.json").exists()
