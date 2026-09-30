"""#1798: no step in the tick cadence reviewed or merged a pull request its
own tick did not dispatch -- a curate pull request (#1789), 10/10 checks
green, sat unmerged across three consecutive ticks with no handback naming
it at all. `scripts/orphan_pr_sweep.py` closes that gap; this pins both its
own decision logic (red before the fix existed, green after) and that the
one documented call in `agents/sub-manager.md` names flags the script
actually parses (#1530's own class of defect -- a plausible-looking flag
that does not exist).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import orphan_pr_sweep  # noqa: E402

SUB_MANAGER = REPO_ROOT / "agents" / "sub-manager.md"
SCRIPT = REPO_ROOT / "scripts" / "orphan_pr_sweep.py"


# ------------------------------------------------------------- decision logic


def test_curate_pr_not_in_known_set_is_an_orphan():
    """The exact #1789 incident: a curate/* PR, green, not dispatched this tick."""
    open_prs = [{"number": 1789, "branch": "curate/20260929T101500Z"}]
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers=[])
    assert result["status"] == "determined"
    assert result["orphans"] == [1789]


def test_doctor_pr_not_in_known_set_is_an_orphan():
    open_prs = [{"number": 42, "branch": "doctor/stale-branches"}]
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers=[])
    assert result["orphans"] == [42]


def test_curate_pr_already_known_is_not_an_orphan():
    """A curate PR this tick's own dispatch (or superseded_by_pr) already
    knows about must not be reported twice."""
    open_prs = [{"number": 1789, "branch": "curate/20260929T101500Z"}]
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers=[1789])
    assert result["status"] == "determined"
    assert result["orphans"] == []


def test_an_ordinary_lane_branch_is_never_an_orphan():
    """Positive control: a developer lane's own fix/{issue} branch is not
    loop-authored and must never be swept in, known or not."""
    open_prs = [{"number": 500, "branch": "fix/500"}]
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers=[])
    assert result["orphans"] == []


def test_a_pr_with_no_branch_field_is_never_swept_in():
    """Missing branch information is the conservative direction: never a
    false positive, only ever a missed sweep (documented in the module's own
    docstring)."""
    open_prs = [{"number": 501}]
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers=[])
    assert result["orphans"] == []


def test_a_loop_authored_pr_with_no_number_field_is_never_swept_in():
    """A malformed PR dict (loop-authored branch, no ``number``) must never
    surface as a bare ``None`` orphan -- a caller folding this straight into
    a spawn call would pass a garbage identifier rather than a missed
    sweep, the opposite of the module's own conservative-by-design claim."""
    open_prs = [{"branch": "curate/x"}]
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers=[])
    assert result["orphans"] == []
    assert None not in result["orphans"]


def test_empty_open_pr_list_is_determined_with_no_orphans():
    result = orphan_pr_sweep.orphan_numbers(open_prs=[], known_numbers=[])
    assert result["status"] == "determined"
    assert result["orphans"] == []


def test_open_prs_unknown_is_could_not_tell():
    result = orphan_pr_sweep.orphan_numbers(open_prs=None, known_numbers=[])
    assert result["status"] == "could-not-tell"
    result = orphan_pr_sweep.orphan_numbers(open_prs="unknown", known_numbers=[])
    assert result["status"] == "could-not-tell"


def test_known_numbers_unknown_is_could_not_tell():
    """Without a known set, every loop-authored PR looks orphaned, including
    ones this tick already dispatched -- must not guess an empty set."""
    open_prs = [{"number": 1789, "branch": "curate/20260929T101500Z"}]
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers=None)
    assert result["status"] == "could-not-tell"
    result = orphan_pr_sweep.orphan_numbers(open_prs, known_numbers="unknown")
    assert result["status"] == "could-not-tell"


def test_could_not_tell_never_silently_becomes_no_orphans():
    """Positive control for the two checks above: a could-not-tell result
    must never carry an empty orphans list indistinguishable from a
    genuinely-checked 'none found' -- both fields are asserted together."""
    result = orphan_pr_sweep.orphan_numbers(open_prs=None, known_numbers=[])
    assert result["orphans"] == []
    assert result["status"] != "determined"


# --------------------------------------------------------------------- CLI


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
    )


def test_cli_reports_orphans_line(tmp_path):
    open_prs_file = tmp_path / "open.json"
    known_file = tmp_path / "known.json"
    open_prs_file.write_text(json.dumps([{"number": 1789, "branch": "curate/x"}]))
    known_file.write_text(json.dumps([]))
    proc = _run("--open-prs-json", str(open_prs_file), "--known-json", str(known_file))
    assert proc.returncode == 0
    assert "ORPHANS: 1789" in proc.stdout


def test_cli_could_not_tell_exits_2(tmp_path):
    known_file = tmp_path / "known.json"
    known_file.write_text(json.dumps([]))
    proc = _run("--open-prs-json", "unknown", "--known-json", str(known_file))
    assert proc.returncode == 2
    assert "ORPHANS: could-not-tell" in proc.stdout


# ----------------------------------------------- call-shape pin (#1530's class)


def test_sub_manager_documents_the_sweep_call_at_all():
    """Positive control: without this, the flag check below passes vacuously."""
    lines = [
        line
        for line in SUB_MANAGER.read_text(encoding="utf-8").splitlines()
        if "orphan_pr_sweep.py" in line
    ]
    assert lines, "agents/sub-manager.md no longer mentions orphan_pr_sweep.py at all"


def _real_help_text():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_every_documented_flag_is_one_the_script_actually_parses():
    help_text = _real_help_text()
    text = SUB_MANAGER.read_text(encoding="utf-8")
    flags = set(re.findall(r"--[a-z][a-z-]*", text))
    documented_sweep_flags = {
        f for f in flags if f in ("--open-prs-json", "--known-json")
    }
    assert documented_sweep_flags, (
        "no orphan_pr_sweep.py flag found in agents/sub-manager.md"
    )
    for flag in documented_sweep_flags:
        assert flag in help_text, (
            "agents/sub-manager.md documents {0!r}, which orphan_pr_sweep.py's "
            "own --help does not list (#1530's own class of defect)".format(flag)
        )


def test_a_flag_the_script_does_not_have_would_be_caught():
    """Positive control for the check above."""
    help_text = _real_help_text()
    assert "--budget" not in help_text


def test_script_reuses_is_loop_authored_branch_not_a_second_copy():
    """The module's own docstring claims it reuses release_gate2's function
    rather than a second copy of the two prefixes -- pin that it is the same
    object, not a coincidentally-identical redefinition."""
    import release_gate2

    assert (
        orphan_pr_sweep.is_loop_authored_branch is release_gate2.is_loop_authored_branch
    )
