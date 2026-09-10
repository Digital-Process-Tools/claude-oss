"""#1410: freezing a cohort's LABELS was already made reproducible by #917's
`cohort_freeze.py`, but everything after the label write -- confirming the count
against a second, independent route, writing that decision into the state file,
and refreshing the label's own description with the tag and date -- was still a
maintainer's own three follow-up steps, run by hand from a paragraph in
`skills/manager/phases/accounting.md` rather than from anything a test can hold.
`v0.31.0` froze cohort-28 at 14 and it became 15 minutes later when #383 was
reopened -- every step was correct when taken, the count was simply read at one
moment and trusted at another.

Three top-level states, and the third is the point (this repo's own defect
class, applied a second time to the same feature): `frozen` / `partial` /
`could-not-freeze`. `test_record_freeze_idempotent_second_run_appends_nothing`
is the must-not-fire half of a pair; `test_record_freeze_frozen_writes_state_
and_description` is its must-fire control -- the first run DOES write, so the
second run's silence is proven to mean "already done" rather than "nothing
runs at all".
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import cohort_freeze  # noqa: E402
import cohort_freeze_record as cfr  # noqa: E402
import oss_state  # noqa: E402

REPO = "Digital-Process-Tools/claude-oss"
TAG = "v0.31.0"
COHORT = 28
LABEL = "cohort-28"
CUTOFF = "2026-09-09T13:18:41Z"
AT = "2026-09-09T13:20:00Z"


def _fake_gh():
    return "gh"


def _fake_run(*args, **kwargs):
    raise AssertionError("no gh call should have reached subprocess.run in this test")


def _frozen_freeze_result(count=12, added=None):
    return {
        "state": cohort_freeze.STATE_FROZEN,
        "reason": "",
        "label": LABEL,
        "tag": TAG,
        "cutoff": CUTOFF,
        "count": count,
        "members": list(range(1, count + 1)),
        "added": added if added is not None else list(range(1, count + 1)),
        "dry_run": False,
    }


def _already_freeze_result(count=12):
    return {
        "state": cohort_freeze.STATE_ALREADY,
        "reason": "",
        "label": LABEL,
        "tag": TAG,
        "cutoff": CUTOFF,
        "count": count,
        "members": list(range(1, count + 1)),
        "added": [],
        "dry_run": False,
    }


def _patch_freeze(monkeypatch, result):
    monkeypatch.setattr(cohort_freeze, "freeze", lambda *a, **kw: result)


def _patch_label_members(monkeypatch, count, state="ok", reason=""):
    numbers = list(range(1, count + 1)) if state == "ok" else None
    monkeypatch.setattr(
        cohort_freeze,
        "label_members",
        lambda *a, **kw: {"state": state, "numbers": numbers, "reason": reason},
    )


def _patch_description_already_set(monkeypatch):
    monkeypatch.setattr(
        cfr,
        "ensure_label_description",
        lambda *a, **kw: (cfr.DESCRIPTION_ALREADY_SET, ""),
    )


def test_record_freeze_frozen_writes_state_and_description(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, _frozen_freeze_result(count=12))
    _patch_label_members(monkeypatch, count=12)
    _patch_description_already_set(monkeypatch)

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )

    assert result["state"] == cfr.STATE_FROZEN
    assert result["count"] == 12
    assert result["state_written"] is True

    entries = oss_state.read(str(state_path))
    assert len(entries) == 1
    assert entries[0]["detail"]["cohort_freeze"]["cohort"] == LABEL
    assert entries[0]["detail"]["cohort_freeze"]["state"] == oss_state.COHORT_MEASURED
    assert entries[0]["detail"]["cohort_freeze"]["count"] == 12


def test_record_freeze_idempotent_second_run_appends_nothing(tmp_path, monkeypatch):
    """Must-not-fire control for the test above: re-running an already-recorded
    freeze must change nothing on disk -- and this is only meaningful paired
    with a prior test proving the first run DOES write (above)."""
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, _already_freeze_result(count=12))
    _patch_label_members(monkeypatch, count=12)
    _patch_description_already_set(monkeypatch)

    first = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )
    assert first["state"] == cfr.STATE_FROZEN
    entries_after_first = oss_state.read(str(state_path))
    assert len(entries_after_first) == 1

    second = cfr.record_freeze(
        REPO,
        TAG,
        COHORT,
        _fake_gh(),
        _fake_run,
        str(state_path),
        "2026-09-09T14:00:00Z",
        execute=True,
    )
    assert second["state"] == cfr.STATE_FROZEN
    assert second["count"] == 12
    assert "already recorded" in second["reason"]

    entries_after_second = oss_state.read(str(state_path))
    assert entries_after_second == entries_after_first


def test_record_freeze_partial_when_routes_disagree(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, _frozen_freeze_result(count=14))
    _patch_label_members(monkeypatch, count=12)  # disagrees with the cutoff scan
    _patch_description_already_set(monkeypatch)

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )

    assert result["state"] == cfr.STATE_PARTIAL
    assert result["count"] is None

    entries = oss_state.read(str(state_path))
    assert len(entries) == 1
    assert entries[0]["detail"]["cohort_freeze"]["state"] == oss_state.COHORT_UNKNOWN


def test_record_freeze_partial_when_label_filter_route_unreadable(
    tmp_path, monkeypatch
):
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, _frozen_freeze_result(count=12))
    _patch_label_members(
        monkeypatch, count=None, state="could-not-read", reason="gh timed out"
    )
    _patch_description_already_set(monkeypatch)

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )

    assert result["state"] == cfr.STATE_PARTIAL
    entries = oss_state.read(str(state_path))
    assert (
        entries[0]["detail"]["cohort_freeze"]["state"]
        == oss_state.COHORT_COULD_NOT_COUNT
    )


def test_record_freeze_could_not_freeze_when_label_missing(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        cohort_freeze,
        "freeze",
        lambda *a, **kw: {
            "state": cohort_freeze.STATE_LABEL_MISSING,
            "reason": "cohort-28 does not exist on {} yet".format(REPO),
            "label": LABEL,
            "tag": TAG,
            "cutoff": CUTOFF,
            "count": 12,
            "members": list(range(1, 13)),
            "added": None,
            "dry_run": False,
        },
    )

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )

    assert result["state"] == cfr.STATE_COULD_NOT_FREEZE
    assert not state_path.exists()


def test_record_freeze_partial_when_label_write_itself_partial(tmp_path, monkeypatch):
    """A run that labels 8 of 14 issues and then fails must report neither
    success nor a clean failure -- the case the issue names explicitly."""
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        cohort_freeze,
        "freeze",
        lambda *a, **kw: {
            "state": cohort_freeze.STATE_COULD_NOT_READ,
            "reason": "labelled 8 of 14 issue(s) with cohort-28; failed: [...]",
            "label": LABEL,
            "tag": TAG,
            "cutoff": CUTOFF,
            "count": 14,
            "members": list(range(1, 15)),
            "added": list(range(1, 9)),
            "dry_run": False,
        },
    )

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )

    assert result["state"] == cfr.STATE_PARTIAL
    assert result["added"] == list(range(1, 9))
    assert not state_path.exists()


def test_record_freeze_partial_when_description_update_fails(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, _frozen_freeze_result(count=12))
    _patch_label_members(monkeypatch, count=12)
    monkeypatch.setattr(
        cfr,
        "ensure_label_description",
        lambda *a, **kw: (cfr.DESCRIPTION_COULD_NOT_UPDATE, "gh label edit failed"),
    )

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )

    assert result["state"] == cfr.STATE_PARTIAL
    assert "gh label edit failed" in result["reason"]
    # the state entry itself still recorded -- the description is the only
    # thing that failed
    entries = oss_state.read(str(state_path))
    assert len(entries) == 1


def test_record_freeze_preview_mode_touches_no_state_file(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, dict(_frozen_freeze_result(count=12), dry_run=True))

    def _boom(*a, **kw):
        raise AssertionError("preview mode must never touch label_members")

    monkeypatch.setattr(cohort_freeze, "label_members", _boom)

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=False
    )

    assert result["mode"] == cfr.MODE_PREVIEW
    assert result["state"] not in cfr.RECORD_STATES
    assert not state_path.exists()


def test_ensure_label_description_already_set_is_a_no_op(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return type(
            "Done",
            (),
            {
                "returncode": 0,
                "stdout": b'{"description": "Open at the v0.30.0 tag, 2026-09-09. Frozen: nothing joins a cohort."}',
                "stderr": b"",
            },
        )()

    state, reason = cfr.ensure_label_description(
        REPO, "cohort-27", "v0.30.0", "2026-09-09T13:18:41Z", "gh", run
    )
    assert state == cfr.DESCRIPTION_ALREADY_SET
    assert len(calls) == 1  # only the read, no edit


def test_ensure_label_description_updates_stale_text(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["gh", "api"]:
            return type(
                "Done",
                (),
                {
                    "returncode": 0,
                    "stdout": b'{"description": "cohort, frozen at a release"}',
                    "stderr": b"",
                },
            )()
        return type("Done", (), {"returncode": 0, "stdout": b"", "stderr": b""})()

    state, reason = cfr.ensure_label_description(
        REPO, "cohort-24", "v0.24.0", "2026-08-01T00:00:00Z", "gh", run
    )
    assert state == cfr.DESCRIPTION_UPDATED
    assert calls[1][:3] == ["gh", "label", "edit"]
    assert "--description" in calls[1]
    idx = calls[1].index("--description")
    assert (
        calls[1][idx + 1]
        == "Open at the v0.24.0 tag, 2026-08-01. Frozen: nothing joins a cohort."
    )


# ----------------------------------------------------------- self-review fixes (#1410)


def test_record_freeze_preview_reports_could_not_freeze_on_a_real_failure(
    monkeypatch, tmp_path
):
    """Must-fire half: a preview run must not hide a real `cohort_freeze.freeze`
    failure (an unresolvable tag, a missing label) behind the informational
    `preview` state -- that state is not in `RECORD_STATES` and always exits 0,
    which would mask a genuine pre-flight problem from any caller scripting on
    the exit code."""
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        cohort_freeze,
        "freeze",
        lambda *a, **kw: {
            "state": cohort_freeze.STATE_COULD_NOT_READ,
            "reason": "could not resolve the timestamp of tag v0.31.0",
            "label": LABEL,
            "tag": TAG,
            "cutoff": None,
            "count": None,
            "members": None,
            "added": None,
            "dry_run": True,
        },
    )

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=False
    )

    assert result["mode"] == cfr.MODE_PREVIEW
    assert result["state"] == cfr.STATE_COULD_NOT_FREEZE
    assert cfr._exit_code(result["state"]) == cfr.EXIT_COULD_NOT_FREEZE


def test_record_freeze_preview_clean_dry_run_still_exits_ok(monkeypatch, tmp_path):
    """Must-not-fire control for the test above: a preview that resolved
    cleanly must keep exiting 0 -- otherwise the fix above would just be
    trading one silent failure mode for the opposite one."""
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, dict(_frozen_freeze_result(count=12), dry_run=True))

    result = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=False
    )

    assert result["mode"] == cfr.MODE_PREVIEW
    assert result["state"] not in cfr.RECORD_STATES
    assert cfr._exit_code(result["state"]) == cfr.EXIT_OK


def test_record_freeze_rerun_under_a_different_tag_is_not_treated_as_already_recorded(
    tmp_path, monkeypatch
):
    """Must-fire half: idempotency is keyed on cohort AND tag, never on the
    route-check record alone. A second call for the same cohort number under a
    different (e.g. mistyped) tag that happens to produce the identical
    two-route count must still append a fresh state entry -- collapsing it
    into "already recorded, nothing changed" would leave the state file
    silently disagreeing with whatever tag the label's own description was
    just rewritten to name (#1122's own failure mode, one layer up)."""
    state_path = tmp_path / "state.json"
    _patch_freeze(monkeypatch, _frozen_freeze_result(count=12))
    _patch_label_members(monkeypatch, count=12)
    _patch_description_already_set(monkeypatch)

    first = cfr.record_freeze(
        REPO, TAG, COHORT, _fake_gh(), _fake_run, str(state_path), AT, execute=True
    )
    assert first["state"] == cfr.STATE_FROZEN
    entries_after_first = oss_state.read(str(state_path))
    assert len(entries_after_first) == 1
    assert entries_after_first[0]["detail"]["cohort_freeze_tag"] == TAG

    other_tag = "v0.32.0-mistyped"
    second = cfr.record_freeze(
        REPO,
        other_tag,
        COHORT,
        _fake_gh(),
        _fake_run,
        str(state_path),
        "2026-09-09T15:00:00Z",
        execute=True,
    )
    assert "already recorded" not in second["reason"]

    entries_after_second = oss_state.read(str(state_path))
    assert len(entries_after_second) == 2
    assert entries_after_second[1]["detail"]["cohort_freeze_tag"] == other_tag


def test_main_preflight_bad_repo_reports_preview_mode_without_execute(
    monkeypatch, capsys
):
    """Must-fire half: `main()`'s two pre-flight checks (bad `--repo`, missing
    `gh`) run before `--execute` is even considered, and must still report
    which mode was actually requested rather than hardcoding `mode: "execute"`
    regardless."""
    exit_code = cfr.main(
        [
            "--repo",
            "not-a-slug-and-not-a-directory-either",
            "--tag",
            TAG,
            "--cohort",
            str(COHORT),
            "--state",
            "/tmp/does-not-matter-1410.json",
            "--at",
            AT,
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == cfr.EXIT_COULD_NOT_FREEZE
    assert '"mode": "preview"' in out


def test_main_preflight_bad_repo_reports_execute_mode_with_execute(monkeypatch, capsys):
    """Must-not-fire control for the test above: the same pre-flight failure
    with `--execute` passed must report `mode: "execute"`, not `preview`."""
    exit_code = cfr.main(
        [
            "--repo",
            "not-a-slug-and-not-a-directory-either",
            "--tag",
            TAG,
            "--cohort",
            str(COHORT),
            "--state",
            "/tmp/does-not-matter-1410.json",
            "--at",
            AT,
            "--execute",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == cfr.EXIT_COULD_NOT_FREEZE
    assert '"mode": "execute"' in out
