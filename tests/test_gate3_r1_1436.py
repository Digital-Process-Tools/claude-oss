"""Gate 3 v0.32.0 round one (dispatch token gate3-r1-90bae15e5253): four small,
independent findings bundled into one lane (#1436).

Each test below is the audit's own reproduction, written before the fix.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import triage_trigger  # noqa: E402

OSS_STATE = REPO_ROOT / "scripts" / "oss_state.py"


# ----------------------------- finding 1: not backslashreplace-safe --------


def test_cohort_freeze_record_reconfigures_streams():
    """`_emit` prints `gh`/`git`-authored `reason`/detail text with a bare
    `print`, unlike its sibling `release_trigger.py`, which reconfigures both
    streams to `backslashreplace` before printing anything (#966). Reasoned,
    not observed on this repo's own CI: stdout is captured here, never driven
    through a real cp1252 console."""
    source = (REPO_ROOT / "scripts" / "cohort_freeze_record.py").read_text(
        encoding="utf-8"
    )
    assert 'stream.reconfigure(errors="backslashreplace")' in source, (
        "scripts/cohort_freeze_record.py prints gh/git-authored text and does "
        "not reconfigure its streams, unlike release_trigger.py and "
        "triage_trigger.py (#1436)"
    )


def test_next_action_reconfigures_streams():
    """Same defect, same fix, in `next_action.py`'s own CLI functions -- the
    `FAIL:`/`OK:` lines in `_take_cli`/`_record_skip_cli` and `main` can carry
    `gh`/`git` stderr tails or repo-declared reasons."""
    source = (REPO_ROOT / "scripts" / "next_action.py").read_text(encoding="utf-8")
    assert 'stream.reconfigure(errors="backslashreplace")' in source, (
        "scripts/next_action.py prints gh/git-authored text and does not "
        "reconfigure its streams (#1436)"
    )


# ----------------------------- finding 2: stale inbound.md prose ------------


def test_inbound_md_no_longer_claims_the_statusline_count_is_unmeasured():
    """`skills/manager/phases/inbound.md` used to say the statusline count
    was "left for a lane that can measure it" -- but `statusline.inbound_
    reading` / `_inbound_field` already exist (#1406, landed in the same
    delta this audit ran over, commit 66f8b256). The stale sentence must be
    gone; a positive statement of what exists now must be present."""
    text = (REPO_ROOT / "skills" / "manager" / "phases" / "inbound.md").read_text(
        encoding="utf-8"
    )
    assert "left for a lane that can measure it" not in text, (
        "inbound.md still claims the statusline inbound count is unmeasured, "
        "but statusline.inbound_reading/_inbound_field already exist (#1406)"
    )
    assert "inbound_reading" in text or "_inbound_field" in text, (
        "inbound.md's rewritten sentence should name what actually measures "
        "the count now"
    )


# ----------------------------- finding 3: --triage-recorded standalone -----


def test_triage_recorded_alone_is_not_a_valid_oss_state_call():
    """Control: confirms the defect commands/tick.md's own call has. #1386
    added `--triage-recorded` as an attachment to `--decision`, not its own
    mode flag -- `oss_state.py`'s argparse requires one of the mutually
    exclusive mode flags first."""
    done = subprocess.run(
        [
            sys.executable,
            str(OSS_STATE),
            "/nonexistent",
            "--triage-recorded",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode != 0
    assert "one of the arguments" in (done.stderr or ""), done.stderr


def test_tick_md_attaches_triage_recorded_to_a_real_decision_call():
    """commands/tick.md's own call (added by #1386) must not repeat the
    control above -- `--triage-recorded` must be attached to a `--decision`
    invocation, not passed as though it were its own mode flag."""
    text = (REPO_ROOT / "commands" / "tick.md").read_text(encoding="utf-8")
    assert "--triage-recorded" in text, "the recording step itself went missing"
    idx = text.index("--triage-recorded")
    # The `--decision` flag must appear in the same command block, before
    # `--triage-recorded`, not merely somewhere else in the file.
    window = text[max(0, idx - 400) : idx]
    assert "--decision" in window, (
        "commands/tick.md's --triage-recorded call does not attach to a "
        "--decision call, so it fails exactly like the control test above "
        "(#1436)"
    )


def test_tick_mds_own_call_shape_actually_runs(tmp_path):
    """The real call, extracted from commands/tick.md's own fenced code
    block, run for real against a scratch state file -- not just a static
    substring check."""
    text = (REPO_ROOT / "commands" / "tick.md").read_text(encoding="utf-8")
    idx = text.index("--triage-recorded")
    block_start = text.rindex("```bash", 0, idx)
    block_end = text.index("```", block_start + len("```bash"))
    block = text[block_start + len("```bash") : block_end].strip()

    state_file = tmp_path / "state.json"
    now = "2026-01-01T00:00:00Z"
    command = (
        block.replace('"${CLAUDE_PLUGIN_ROOT}/scripts/oss_state.py"', str(OSS_STATE))
        .replace("<state_file>", str(state_file))
        .replace("$(date -u +%Y-%m-%dT%H:%M:%SZ)", now)
    )
    done = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    entries = json.loads(state_file.read_text(encoding="utf-8"))
    assert entries[-1]["detail"]["triage"]["recorded_at"] == now


# ----------------------------- finding 4: triage_trigger misses .oss.local.json --


def _write_config(root, with_local=True):
    (root / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "acme/widget",
                "default_branch": "main",
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": ["README.md"],
                "changelog_dir": "changelog.d",
                "docs_targets": ["README.md"],
                "labels": {"priority": [], "lanes": []},
                "release": {"triggers": {"triage_after_release": True}},
            }
        ),
        encoding="utf-8",
    )
    if with_local:
        (root / ".oss.local.json").write_text(
            json.dumps(
                {
                    "clone": str(root),
                    "worktree_root": str(root / "wt"),
                    "state_file": ".max/state.json",
                }
            ),
            encoding="utf-8",
        )


def test_oss_config_load_merges_state_file_from_local_config(tmp_path):
    """Control: `oss_config.load` itself does the right thing -- confirms the
    bug is in `triage_trigger._load_config`'s own raw `json.load`, not in the
    shared loader."""
    _write_config(tmp_path)
    config, problems = oss_config.load(tmp_path / ".oss.json")
    assert config is not None, problems
    assert config.get("state_file") == ".max/state.json"


def test_triage_trigger_load_config_sees_the_local_state_file(tmp_path):
    """The real defect: `triage_trigger._load_config` used a raw `json.load`
    over `.oss.json` alone, so it never merged `.oss.local.json` -- where
    `state_file` actually lives on a repo with a split config. It reported
    "no state file configured" even though one was."""
    _write_config(tmp_path)
    config, detail = triage_trigger._load_config(str(tmp_path / ".oss.json"))
    assert config is not None, detail
    assert config.get("state_file") == ".max/state.json", (
        "triage_trigger._load_config did not merge .oss.local.json, so "
        "state_file is missing even though it is configured (#1436)"
    )


def test_triage_trigger_cli_does_not_misreport_could_not_tell(tmp_path):
    """End-to-end: `triage_trigger.py --repo` on a repo with a split config
    (project + local) must not answer could-not-tell for a state file that
    is, in fact, configured."""
    _write_config(tmp_path)
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "triage_trigger.py"),
            "--repo",
            str(tmp_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(done.stdout)
    assert payload[
        "state"
    ] != triage_trigger.STATE_COULD_NOT_TELL or "state_file" not in (
        payload.get("detail") or ""
    ), (
        "triage_trigger reported could-not-tell citing a missing state file "
        "on a repo where .oss.local.json configures one: {0}".format(payload)
    )
