"""#1389's own addendum -- `scripts/next_action.py`: one call answering "what
does this repo need now", composing `oss_config`, `release_trigger` and
`workspace_routes` rather than leaving the decision to prose a session
re-derives every time.

Every "must not fire" case below is paired with a "must fire" case in the
same fixture family, per this repo's own rule for a negative assertion.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import next_action  # noqa: E402
import release_trigger  # noqa: E402
import workspace_routes  # noqa: E402


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


def _git_repo(tmp_path, with_origin=True):
    root = tmp_path / "repo"
    root.mkdir()
    env = _git_env()
    done = _run(["git", "init", "--quiet", "."], cwd=root, env=env)
    if done.returncode != 0:
        pytest.skip("git init failed here: {0}".format(done.stderr.strip()))
    _run(["git", "config", "user.email", "t@example.com"], cwd=root, env=env)
    _run(["git", "config", "user.name", "t"], cwd=root, env=env)
    (root / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=root, env=env)
    _run(["git", "checkout", "--quiet", "-B", "main"], cwd=root, env=env)
    _run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, env=env)
    if with_origin:
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


# --- no config -------------------------------------------------------------


def test_no_config_and_probeable_repo_is_due_setup(tmp_path):
    root = _git_repo(tmp_path, with_origin=True)
    result = next_action.decide(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "setup"


def test_no_config_and_no_origin_is_unsafe_not_due_setup(tmp_path):
    """Positive control for the case directly above: the ONLY thing that
    differs is the missing remote, and that alone must flip the verdict."""
    root = _git_repo(tmp_path, with_origin=False)
    result = next_action.decide(root)
    assert result["state"] == next_action.UNSAFE
    assert "remote" in result["reason"]
    assert result["remedy"]


def test_no_config_and_not_a_git_repo_is_unsafe(tmp_path):
    root = tmp_path / "not-a-repo"
    root.mkdir()
    result = next_action.decide(root)
    assert result["state"] == next_action.UNSAFE
    assert result["remedy"]


# --- default_branch -----------------------------------------------------


def test_unresolvable_default_branch_is_unsafe(tmp_path):
    root = _git_repo(tmp_path)
    _write_config(root, {"default_branch": "does-not-exist"})
    result = next_action.decide(root)
    assert result["state"] == next_action.UNSAFE
    assert "does-not-exist" in result["reason"]


def test_resolvable_default_branch_is_not_unsafe(tmp_path):
    """Positive control: same repo, a real branch name, no other change --
    must not report unsafe."""
    root = _git_repo(tmp_path)
    _write_config(root)
    result = next_action.decide(root)
    assert result["state"] != next_action.UNSAFE


# --- release trigger ------------------------------------------------------


def test_release_trigger_fired_is_due_release(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root)
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_FIRED,
            "fired": ["merged_prs"],
            "unevaluated": [],
            "conditions": [],
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "release"


def test_release_trigger_could_not_tell_blocks_a_lower_priority_curate(
    tmp_path, monkeypatch
):
    """A release trigger that could not be evaluated must block the verdict
    even though curate would otherwise clearly fire -- the unresolved,
    higher-precedence check might have been the real answer."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_COULD_NOT_TELL,
            "fired": [],
            "unevaluated": ["merged_prs"],
            "conditions": [],
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.COULD_NOT_DECIDE
    assert result["blocked_on"] == "release"


def test_release_trigger_not_fired_lets_curate_through(tmp_path, monkeypatch):
    """Positive control for the test above: the only change is the release
    trigger resolving cleanly to not-fired -- curate must now fire."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "curate"


# --- self-review: a broken changelog_dir must not silently substitute the ---
# --- default fragment directory for the release trigger's own soak check ----


def test_bad_changelog_dir_blocks_the_release_trigger(tmp_path):
    """A `changelog_dir` `oss_config.changelog_dir_problem` refuses (a `..`
    segment, here) must not be silently swapped for the ordinary default
    directory -- that would let the release trigger's soak condition read
    fragments from the wrong place with nobody told."""
    root = _git_repo(tmp_path)
    _write_config(root, {"changelog_dir": "../escape"})
    result = next_action.decide(root)
    assert result["state"] == next_action.COULD_NOT_DECIDE
    assert result["blocked_on"] == "release"
    assert "changelog_dir" in result["reason"]


def test_no_changelog_dir_is_the_ordinary_case_and_does_not_block(
    tmp_path, monkeypatch
):
    """Positive control: the same repo with no `changelog_dir` at all is the
    documented, ordinary "no fragment practice" state -- it must reach the
    release trigger, not `could-not-decide`."""
    root = _git_repo(tmp_path)
    _write_config(root)
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    result = next_action.decide(root)
    assert result["state"] != next_action.COULD_NOT_DECIDE


# --- curate / triage --------------------------------------------------------


def test_curate_over_threshold_is_due_curate(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "curate"
    assert result["evidence"]["count"] == 1


def test_curate_under_threshold_is_not_due(tmp_path, monkeypatch):
    """Positive control: raise the threshold above the same one fragment,
    nothing else changes -- curate must not fire."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 100})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.NOTHING_DUE
    assert result["next"] == "dispatch"


def test_curate_could_not_count_is_could_not_decide(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        next_action.workspace_routes,
        "decide",
        lambda *a, **k: (
            None,
            {
                "release": {"configured": False},
                "curate": {
                    "configured": True,
                    "state": workspace_routes.COULD_NOT_COUNT,
                    "count": None,
                    "threshold": 0,
                    "why": "trap.d/ could not be listed",
                },
                "triage": {"configured": False},
            },
        ),
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.COULD_NOT_DECIDE
    assert result["blocked_on"] == "curate"


def test_triage_over_threshold_is_due_triage(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root, {"triage_route_threshold": 0})
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        next_action.workspace_routes,
        "decide",
        lambda *a, **k: (
            None,
            {
                "release": {"configured": False},
                "curate": {"configured": False},
                "triage": {
                    "configured": True,
                    "state": workspace_routes.OVER,
                    "count": 3,
                    "threshold": 0,
                    "why": "3 of 5 open issue(s) missing lane-* or priority-*",
                },
            },
        ),
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "triage"


def test_nothing_configured_and_nothing_fired_is_nothing_due(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root)
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.NOTHING_DUE
    assert result["next"] == "dispatch"


# --- the #1386 triage trigger, landed after this module's own first cut ----


def test_triage_trigger_due_is_due_triage_ahead_of_label_coverage(
    tmp_path, monkeypatch
):
    """The post-release trigger is checked first: a repo where it fires must
    route to triage even if the label-coverage route is not even configured."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 100})
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_DUE,
            "detail": "the last recorded triage sweep predates the tag",
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "triage"


def test_triage_trigger_not_due_falls_back_to_label_coverage(tmp_path, monkeypatch):
    """Positive control: the same repo, with the trigger reporting not-due
    instead -- the label-coverage route must still get its turn."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 100, "triage_route_threshold": 0})
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_NOT_DUE,
            "detail": "release.triggers.triage_after_release is not enabled",
        },
    )
    monkeypatch.setattr(
        next_action.workspace_routes,
        "decide",
        lambda *a, **k: (
            None,
            {
                "release": {"configured": False},
                "curate": {"configured": False},
                "triage": {
                    "configured": True,
                    "state": workspace_routes.OVER,
                    "count": 2,
                    "threshold": 0,
                    "why": "2 of 4 open issue(s) missing lane-* or priority-*",
                },
            },
        ),
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "triage"


def test_triage_trigger_could_not_tell_is_could_not_decide(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root)
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_COULD_NOT_TELL,
            "detail": "could not read the commit date of tag",
        },
    )
    result = next_action.decide(root)
    assert result["state"] == next_action.COULD_NOT_DECIDE
    assert result["blocked_on"] == "triage"


# --- self-review: an unresolved curate/triage backlog must not loop forever -


def _quiet_release_and_triage_trigger(monkeypatch):
    monkeypatch.setattr(
        next_action.release_trigger,
        "compute",
        lambda *a, **k: {
            "state": release_trigger.STATE_NOT_FIRED,
            "fired": [],
            "unevaluated": [],
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_NOT_DUE,
            "detail": "release.triggers.triage_after_release is not enabled",
        },
    )


def test_an_unchanged_curate_backlog_does_not_repeat_due_forever(tmp_path, monkeypatch):
    """The must-not-fire-again half: calling `decide()` twice in a row against
    the identical, unresolved backlog must report `due: curate` only once --
    the second call must fall through rather than looping."""
    root = _git_repo(tmp_path)
    _write_config(
        root, {"curate_route_threshold": 0, "state_file": ".max/oss-watch.json"}
    )
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_release_and_triage_trigger(monkeypatch)

    first = next_action.decide(root)
    assert first["state"] == next_action.DUE
    assert first["next"] == "curate"

    second = next_action.decide(root)
    assert second["next"] != "curate", second


def test_a_changed_curate_count_re_arms(tmp_path, monkeypatch):
    """Positive control: the same repo, but the backlog actually grows between
    the two calls -- the second call must still fire, proving the fall-through
    above is keyed to the reading, not to a route that never fires twice."""
    root = _git_repo(tmp_path)
    _write_config(
        root, {"curate_route_threshold": 0, "state_file": ".max/oss-watch.json"}
    )
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_release_and_triage_trigger(monkeypatch)

    first = next_action.decide(root)
    assert first["next"] == "curate"

    (root / "trap.d" / "2.another-lesson.md").write_text("a second lesson\n")
    second = next_action.decide(root)
    assert second["state"] == next_action.DUE
    assert second["next"] == "curate"


def test_no_state_file_configured_never_suppresses_curate(tmp_path):
    """No `state_file` means no receipt can be read or written -- this must
    fail OPEN (armed, as though never seen), the same direction every other
    unknown in this module fails, not silently treated as already-handled.
    Unit-level, at `_route_already_seen` itself: `oss_config.load` derives a
    `state_file` for almost any real repo (#608), so exercising this through
    `decide()` end to end would need a repo where derivation itself fails
    rather than one that simply never set the key."""
    root = _git_repo(tmp_path)
    seen, detail = next_action._route_already_seen(root, {}, "curate", "over:1")
    assert seen is False, detail
    assert "no state_file" in detail


def test_a_broken_receipt_read_also_fails_open(tmp_path):
    """Positive control: `state_file` IS configured, but points at something
    `oss_state._last_workspace_route` cannot parse -- still armed, never
    silently `True`."""
    root = _git_repo(tmp_path)
    state_path = root / "oss-watch.json"
    state_path.write_text("{not json at all", encoding="utf-8")
    seen, detail = next_action._route_already_seen(
        root, {"state_file": "oss-watch.json"}, "curate", "over:1"
    )
    assert seen is False, detail


# --- CLI --------------------------------------------------------------------


def test_main_json_emits_the_state(tmp_path, capsys):
    root = _git_repo(tmp_path, with_origin=False)
    rc = next_action.main(["--root", str(root), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == next_action.UNSAFE


def test_receipt_never_prints_next_for_unsafe():
    payload = {
        "state": next_action.UNSAFE,
        "reason": "no origin remote",
        "remedy": "add one",
    }
    text = next_action.receipt(payload)
    assert "next:" not in text
    assert "remedy: add one" in text
