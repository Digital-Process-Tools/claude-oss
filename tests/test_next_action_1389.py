"""#1389's own addendum, ranked rather than arbitrated by #1405 --
`scripts/next_action.py`: `rank()` composes `oss_config`, `release_trigger`,
`workspace_routes`, `triage_trigger` and (#1405/#1406) `statusline.
inbound_reading`, and returns every source's own reading, ordered, rather
than stopping at the first one.

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


def _quiet_inbound(monkeypatch, unruled=0, unreviewed=0, measured=True):
    """The default double for every test below that is not itself testing
    the inbound candidate: a clean, `not-due` reading, so `rank()`'s other
    three sources can be exercised in isolation without this call actually
    shelling out to `gh` (`_inbound_candidate` would otherwise try a real
    network round trip for every fixture's `"example/example"` repo)."""
    monkeypatch.setattr(
        next_action,
        "_fresh_inbound_reading",
        lambda repo: {
            "state": "measured" if measured else "could-not-tell",
            "unruled_issues": unruled,
            "unreviewed_prs": unreviewed,
            "unanswered_comments": None,
        },
    )


def _not_fired_release(monkeypatch):
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


def _candidate(result, source):
    """The one candidate named `source` in a `RANKED` result's `candidates`
    list, or `None` -- test-only convenience, not part of the module."""
    for entry in result.get("candidates", []):
        if entry["source"] == source:
            return entry
    return None


# --- no config -------------------------------------------------------------


def test_no_config_and_probeable_repo_is_due_setup(tmp_path):
    root = _git_repo(tmp_path, with_origin=True)
    result = next_action.rank(root)
    assert result["state"] == next_action.DUE
    assert result["next"] == "setup"


def test_no_config_and_no_origin_is_unsafe_not_due_setup(tmp_path):
    """Positive control for the case directly above: the ONLY thing that
    differs is the missing remote, and that alone must flip the verdict."""
    root = _git_repo(tmp_path, with_origin=False)
    result = next_action.rank(root)
    assert result["state"] == next_action.UNSAFE
    assert "remote" in result["reason"]
    assert result["remedy"]


def test_no_config_and_not_a_git_repo_is_unsafe(tmp_path):
    root = tmp_path / "not-a-repo"
    root.mkdir()
    result = next_action.rank(root)
    assert result["state"] == next_action.UNSAFE
    assert result["remedy"]


# --- default_branch -----------------------------------------------------


def test_unresolvable_default_branch_is_unsafe(tmp_path):
    root = _git_repo(tmp_path)
    _write_config(root, {"default_branch": "does-not-exist"})
    result = next_action.rank(root)
    assert result["state"] == next_action.UNSAFE
    assert "does-not-exist" in result["reason"]


def test_resolvable_default_branch_is_not_unsafe(tmp_path, monkeypatch):
    """Positive control: same repo, a real branch name, no other change --
    must not report unsafe."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    assert result["state"] != next_action.UNSAFE


# --- unsafe is a refusal, never a candidate ---------------------------------


def test_unsafe_never_appears_inside_a_candidates_list(tmp_path):
    """#1405's own instruction: `unsafe` is a refusal, not a candidate --
    it must never show up nested inside a `RANKED` payload's own list."""
    root = _git_repo(tmp_path)
    _write_config(root, {"default_branch": "does-not-exist"})
    result = next_action.rank(root)
    assert result["state"] == next_action.UNSAFE
    assert "candidates" not in result


# --- release trigger ------------------------------------------------------


def test_release_trigger_fired_is_ranked_due(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch)
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
    result = next_action.rank(root)
    assert result["state"] == next_action.RANKED
    release = _candidate(result, "release")
    assert release["state"] == next_action.CANDIDATE_DUE
    assert release["rank"] == 1


def test_release_trigger_could_not_tell_is_listed_never_dropped(tmp_path, monkeypatch):
    """#1405's second requirement, and the direct replacement for the old
    blocking behaviour: a release trigger that could not be evaluated must
    still be LISTED as `could-not-tell` -- and it must NOT prevent curate,
    which resolves cleanly to `due`, from also appearing. Both are real
    candidates an agent can see at once."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
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
    result = next_action.rank(root)
    assert result["state"] == next_action.RANKED
    release = _candidate(result, "release")
    assert release["state"] == next_action.CANDIDATE_COULD_NOT_TELL
    curate = _candidate(result, "curate")
    assert curate is not None
    assert curate["state"] == next_action.CANDIDATE_DUE


def test_release_trigger_not_fired_lets_curate_through(tmp_path, monkeypatch):
    """Positive control for the test above: the only change is the release
    trigger resolving cleanly to not-fired -- curate must still fire, and
    release itself must not be in `candidates` at all (it is `not_due`)."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    assert result["state"] == next_action.RANKED
    assert _candidate(result, "release") is None
    curate = _candidate(result, "curate")
    assert curate["state"] == next_action.CANDIDATE_DUE


# --- self-review: a broken changelog_dir must not silently substitute the ---
# --- default fragment directory for the release trigger's own soak check ----


def test_bad_changelog_dir_makes_release_could_not_tell(tmp_path, monkeypatch):
    """A `changelog_dir` `oss_config.changelog_dir_problem` refuses (a `..`
    segment, here) must not be silently swapped for the ordinary default
    directory -- that would let the release trigger's soak condition read
    fragments from the wrong place with nobody told."""
    root = _git_repo(tmp_path)
    _write_config(root, {"changelog_dir": "../escape"})
    _quiet_inbound(monkeypatch)
    result = next_action.rank(root)
    assert result["state"] == next_action.RANKED
    release = _candidate(result, "release")
    assert release["state"] == next_action.CANDIDATE_COULD_NOT_TELL
    assert "changelog_dir" in release["reason"]


def test_no_changelog_dir_is_the_ordinary_case_and_does_not_block(
    tmp_path, monkeypatch
):
    """Positive control: the same repo with no `changelog_dir` at all is the
    documented, ordinary "no fragment practice" state -- it must not become
    a `could-not-tell` release candidate."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    release = _candidate(result, "release")
    assert release is None  # not-fired, resolved cleanly -> not_due, not a candidate


# --- curate / triage --------------------------------------------------------


def test_curate_over_threshold_is_ranked_due(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    curate = _candidate(result, "curate")
    assert curate["state"] == next_action.CANDIDATE_DUE
    assert curate["evidence"]["count"] == 1


def test_curate_under_threshold_is_not_due(tmp_path, monkeypatch):
    """Positive control: raise the threshold above the same one fragment,
    nothing else changes -- curate must not be a candidate and everything
    resolving cleanly with nothing due is `NOTHING_DUE`."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 100})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    assert result["state"] == next_action.NOTHING_DUE
    assert result["next"] == "dispatch"


def test_curate_could_not_count_is_ranked_could_not_tell(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
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
    result = next_action.rank(root)
    curate = _candidate(result, "curate")
    assert curate["state"] == next_action.CANDIDATE_COULD_NOT_TELL


def test_triage_over_threshold_is_ranked_due(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root, {"triage_route_threshold": 0})
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
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
    result = next_action.rank(root)
    triage = _candidate(result, "triage")
    assert triage["state"] == next_action.CANDIDATE_DUE


def test_nothing_configured_and_nothing_fired_is_nothing_due(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    assert result["state"] == next_action.NOTHING_DUE
    assert result["next"] == "dispatch"
    sources = {entry["source"] for entry in result["not_due"]}
    assert sources == {"inbound", "release", "curate", "triage"}


# --- the #1386 triage trigger, landed after this module's own first cut ----


def test_triage_trigger_due_is_ranked_ahead_of_label_coverage(tmp_path, monkeypatch):
    """The post-release trigger is checked first: a repo where it fires must
    rank triage as due even if the label-coverage route is not configured."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 100})
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_DUE,
            "detail": "the last recorded triage sweep predates the tag",
        },
    )
    result = next_action.rank(root)
    triage = _candidate(result, "triage")
    assert triage["state"] == next_action.CANDIDATE_DUE


def test_triage_trigger_not_due_falls_back_to_label_coverage(tmp_path, monkeypatch):
    """Positive control: the same repo, with the trigger reporting not-due
    instead -- the label-coverage route must still get its turn."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 100, "triage_route_threshold": 0})
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
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
    result = next_action.rank(root)
    triage = _candidate(result, "triage")
    assert triage["state"] == next_action.CANDIDATE_DUE


def test_triage_trigger_could_not_tell_is_ranked_could_not_tell(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_COULD_NOT_TELL,
            "detail": "could not read the commit date of tag",
        },
    )
    result = next_action.rank(root)
    triage = _candidate(result, "triage")
    assert triage["state"] == next_action.CANDIDATE_COULD_NOT_TELL


# --- self-review: an unresolved curate/triage backlog must not loop forever -


def _quiet_triage_trigger(monkeypatch):
    monkeypatch.setattr(
        next_action.triage_trigger,
        "compute",
        lambda *a, **k: {
            "state": next_action.triage_trigger.STATE_NOT_DUE,
            "detail": "release.triggers.triage_after_release is not enabled",
        },
    )


def test_rank_alone_never_arms_the_curate_receipt(tmp_path, monkeypatch):
    """#1414's own follow-up self-review finding (Explore reviewer): `rank()`
    is a read. Calling it any number of times, on its own, must never arm
    curate's repeat-suppression receipt -- only an explicit `--take`/
    `--record-skip` commitment may. A plain, repeated `--json` read (what
    step 2 of `commands/run.md` does every single loop) must keep reporting
    the identical, unresolved backlog as due forever."""
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

    second = next_action.rank(root)
    assert _candidate(second, "curate")["state"] == next_action.CANDIDATE_DUE

    third = next_action.rank(root)
    assert _candidate(third, "curate")["state"] == next_action.CANDIDATE_DUE


def test_taking_curate_arms_it_so_the_next_read_does_not_repeat_due_forever(
    tmp_path, monkeypatch
):
    """The must-not-fire-again half now lives one layer up: `--take curate`
    is the commitment that arms the receipt, and only a call that actually
    commits may suppress a later, identical reading."""
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

    second = next_action.rank(root)
    assert _candidate(second, "curate") is None, second


def test_a_changed_curate_count_re_arms(tmp_path, monkeypatch):
    """Positive control: the same repo, taken once, but the backlog actually
    grows before the next read -- it must fire again, proving the
    suppression above is keyed to the reading, not to a route that never
    fires twice."""
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
    assert next_action.main(["--root", str(root), "--take", "curate"]) == 0

    (root / "trap.d" / "2.another-lesson.md").write_text("a second lesson\n")
    second = next_action.rank(root)
    assert _candidate(second, "curate")["state"] == next_action.CANDIDATE_DUE


def test_a_lower_ranked_curate_candidate_is_not_falsely_suppressed(
    tmp_path, monkeypatch
):
    """Self-review finding (Explore reviewer, #1405): the repeat-suppression
    receipt used to be armed the moment `_curate_candidate`/`_triage_candidate`
    were merely EVALUATED, regardless of whether that candidate ended up being
    the one actually surfaced as the answer. Under full composition every
    source is evaluated every call, so a curate backlog ranked BELOW release
    (which the caller takes instead) used to get silently marked "already
    routed" on the very first tick it appeared -- reintroducing the exact
    permanent-divert defect #1390/#1064/#1155 exist to close, one call later.
    Only the entry that ends up at `candidates[0]` may be armed."""
    root = _git_repo(tmp_path)
    _write_config(
        root, {"curate_route_threshold": 0, "state_file": ".max/oss-watch.json"}
    )
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)

    # Tick 1: release fires and ranks first; curate is due too, ranked second.
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
    first = next_action.rank(root)
    assert _candidate(first, "release")["state"] == next_action.CANDIDATE_DUE
    assert _candidate(first, "curate")["state"] == next_action.CANDIDATE_DUE

    # Tick 2: release no longer fires, and the curate backlog is UNCHANGED --
    # nobody curated anything. Curate must still be due: it was never the
    # candidate actually taken, so it must not have been armed on tick 1.
    _not_fired_release(monkeypatch)
    second = next_action.rank(root)
    curate_second = _candidate(second, "curate")
    assert curate_second is not None, second
    assert curate_second["state"] == next_action.CANDIDATE_DUE


def test_no_state_file_configured_never_suppresses_curate(tmp_path):
    """No `state_file` means no receipt can be read or written -- this must
    fail OPEN (armed, as though never seen), the same direction every other
    unknown in this module fails, not silently treated as already-handled."""
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


# --- inbound (#1405/#1406) ---------------------------------------------------


def test_inbound_pending_is_ranked_first_by_default(tmp_path, monkeypatch):
    """The composition gap #1405 names: an outside issue or pull request
    still open must appear as a real candidate, and `DEFAULT_ORDER` puts it
    ahead of the other three."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch, unruled=2, unreviewed=1)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    assert result["state"] == next_action.RANKED
    inbound = _candidate(result, "inbound")
    assert inbound["state"] == next_action.CANDIDATE_DUE
    assert inbound["rank"] == 1
    assert "2 outside issue" in inbound["reason"]
    assert "1 outside pull request" in inbound["reason"]


def test_no_outside_work_is_not_due_positive_control(tmp_path, monkeypatch):
    """Positive control for the test above: zero and zero, everything else
    identical -- inbound must not be a candidate."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch, unruled=0, unreviewed=0)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    assert _candidate(result, "inbound") is None


def test_inbound_could_not_tell_is_listed_never_read_as_nothing_pending(
    tmp_path, monkeypatch
):
    """#1405's second requirement, applied to the fourth source: a reading
    that could not be taken must be `could-not-tell`, never dropped and
    never folded into a false `not-due`."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch, measured=False)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    inbound = _candidate(result, "inbound")
    assert inbound is not None
    assert inbound["state"] == next_action.CANDIDATE_COULD_NOT_TELL


def test_inbound_with_no_repo_configured_is_could_not_tell(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(root, {"repo": None})
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    inbound = _candidate(result, "inbound")
    assert inbound["state"] == next_action.CANDIDATE_COULD_NOT_TELL
    assert "no repo configured" in inbound["reason"]


# --- ranking order, several due at once -------------------------------------


def test_several_due_candidates_keep_default_order_and_sequential_ranks(
    tmp_path, monkeypatch
):
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch, unruled=1)
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
    result = next_action.rank(root)
    sources_in_order = [entry["source"] for entry in result["candidates"]]
    assert sources_in_order == ["inbound", "release", "curate"]
    assert [entry["rank"] for entry in result["candidates"]] == [1, 2, 3]


# --- record_skip (#1405's third requirement) --------------------------------


def test_record_skip_writes_a_decision_naming_both_sources(tmp_path):
    state_path = tmp_path / "oss-watch.json"
    candidates = [
        {"source": "inbound", "state": next_action.CANDIDATE_DUE},
        {"source": "release", "state": next_action.CANDIDATE_DUE},
    ]
    entry = next_action.record_skip(
        str(state_path), candidates, "release", "release audit wants a quiet board"
    )
    assert "took release over inbound" in entry["decision"]
    assert "release audit wants a quiet board" in entry["decision"]


def test_record_skip_refuses_when_taken_matches_the_top_candidate(tmp_path):
    """Positive control: calling `record_skip` when nothing was actually
    skipped must fail loudly rather than write a no-op entry that would
    later look identical to a real deviation."""
    state_path = tmp_path / "oss-watch.json"
    candidates = [{"source": "release", "state": next_action.CANDIDATE_DUE}]
    with pytest.raises(ValueError):
        next_action.record_skip(str(state_path), candidates, "release", "no reason")


def test_record_skip_refuses_on_an_empty_candidate_list(tmp_path):
    state_path = tmp_path / "oss-watch.json"
    with pytest.raises(ValueError):
        next_action.record_skip(str(state_path), [], "release", "no reason")


def test_record_skip_refuses_an_unknown_taken_source(tmp_path):
    """#1414's own follow-up self-review finding (Explore reviewer and
    oss:auditor, independently): neither existing check catches a typo or a
    hallucinated source name -- it is not the top candidate, and the list is
    not empty. Without this, `--record-skip relaese --reason "..."` would be
    written into the state file's permanent decision log exactly as
    confidently as a real deviation."""
    state_path = tmp_path / "oss-watch.json"
    candidates = [
        {"source": "release", "state": next_action.CANDIDATE_DUE},
        {"source": "curate", "state": next_action.CANDIDATE_DUE},
    ]
    with pytest.raises(ValueError):
        next_action.record_skip(str(state_path), candidates, "relaese", "typo")


def test_skipping_curate_over_triage_does_not_arm_curates_receipt(
    tmp_path, monkeypatch
):
    """The exact scenario the Explore reviewer's own repro used, pinned as a
    regression test (#1414's follow-up self-review, finding 1): curate is
    ranked first (`DEFAULT_ORDER` puts it ahead of triage); the scheduler
    deliberately takes triage instead via `--record-skip`. Curate was never
    acted on -- its backlog is completely unchanged -- so it must still
    report `due` on the very next read, not silently fall to `not-due` for
    having merely been passed over."""
    root = _git_repo(tmp_path)
    _write_config(root, {"curate_route_threshold": 0, "triage_route_threshold": 0})
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    monkeypatch.setattr(
        next_action.workspace_routes,
        "decide",
        lambda *a, **k: (
            None,
            {
                "release": {"configured": False},
                "curate": {
                    "configured": True,
                    "state": workspace_routes.OVER,
                    "count": 1,
                    "threshold": 0,
                    "why": "1 of 1 fragment(s) waiting",
                },
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
    _write_config(
        root,
        {
            "curate_route_threshold": 0,
            "triage_route_threshold": 0,
            "state_file": ".max/oss-watch.json",
        },
    )

    first = next_action.rank(root)
    assert _candidate(first, "curate")["rank"] == 1
    assert _candidate(first, "triage")["rank"] == 2

    rc = next_action.main(
        [
            "--root",
            str(root),
            "--record-skip",
            "triage",
            "--reason",
            "label coverage matters more this tick",
        ]
    )
    assert rc == 0

    second = next_action.rank(root)
    curate_second = _candidate(second, "curate")
    assert curate_second is not None, second
    assert curate_second["state"] == next_action.CANDIDATE_DUE


def test_take_cli_refuses_a_source_that_is_not_the_top_candidate(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    _write_config(
        root, {"curate_route_threshold": 0, "state_file": ".max/oss-watch.json"}
    )
    (root / "trap.d").mkdir()
    (root / "trap.d" / "1.some-lesson.md").write_text("a lesson\n")
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    rc = next_action.main(["--root", str(root), "--take", "release"])
    assert rc != 0


def test_take_cli_on_an_inbound_or_release_top_candidate_is_a_harmless_no_op(
    tmp_path, monkeypatch
):
    """Positive control: `--take` must still succeed on a source that ends
    up writing no receipt -- a uniform commitment step, not one that only
    makes sense for curate/triage. `release` never has a receipt of its
    own; `inbound` gained one at #1433, but this fixture's config carries
    no `state_file` (`_write_config(root)` with no extra), so
    `_route_already_seen` fails open here too -- for a different reason
    than `release`'s, not because `inbound` still has no mechanism at all.
    See `test_taking_inbound_arms_it_so_the_next_read_does_not_repeat_due_
    forever` for the state_file-configured case where `--take inbound`
    really does write and later suppress a receipt."""
    root = _git_repo(tmp_path)
    _write_config(root)
    _quiet_inbound(monkeypatch, unruled=1)
    _not_fired_release(monkeypatch)
    rc = next_action.main(["--root", str(root), "--take", "inbound"])
    assert rc == 0


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


def test_receipt_names_could_not_tell_candidates_by_that_word(tmp_path, monkeypatch):
    root = _git_repo(
        tmp_path,
    )
    _write_config(root)
    _quiet_inbound(monkeypatch, measured=False)
    _not_fired_release(monkeypatch)
    result = next_action.rank(root)
    text = next_action.receipt(result)
    assert "could-not-tell" in text
    assert "inbound" in text


# --- --record-skip CLI (#1414: the markdown-driven scheduler has no way to --
# --- call the plain Python record_skip() function directly) -----------------


def test_record_skip_cli_writes_a_state_entry(tmp_path, monkeypatch, capsys):
    root = _git_repo(tmp_path)
    _write_config(root, {"state_file": ".max/oss-watch.json"})
    _quiet_inbound(monkeypatch, unruled=1)
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
    rc = next_action.main(
        ["--root", str(root), "--record-skip", "release", "--reason", "quiet board"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK:" in out
    assert "took release over inbound" in out
    state_path = root / ".max" / "oss-watch.json"
    assert "quiet board" in state_path.read_text(encoding="utf-8")


def test_record_skip_cli_needs_reason(tmp_path, capsys):
    root = _git_repo(tmp_path, with_origin=False)
    rc = next_action.main(["--root", str(root), "--record-skip", "release"])
    assert rc != 0
    assert "--reason" in capsys.readouterr().out


def test_record_skip_cli_fails_loudly_when_nothing_is_ranked(
    tmp_path, monkeypatch, capsys
):
    """Positive control: the same repo with nothing due at all -- the CLI
    must refuse rather than silently writing a no-op entry."""
    root = _git_repo(tmp_path)
    _write_config(root, {"state_file": ".max/oss-watch.json"})
    _quiet_inbound(monkeypatch)
    _not_fired_release(monkeypatch)
    rc = next_action.main(
        ["--root", str(root), "--record-skip", "release", "--reason", "no reason"]
    )
    assert rc != 0
    assert "FAIL:" in capsys.readouterr().out


def test_record_skip_cli_traps_a_too_long_reason_as_fail_not_a_traceback(
    tmp_path, monkeypatch, capsys
):
    """#1437: `_record_skip_cli`'s own docstring promises "Never raises past
    this point: every failure is a printed FAIL:", but it only caught
    `ValueError` -- `record_skip` -> `oss_state.append` raises `oss_state.
    StateError` (a plain `Exception`, not a `ValueError`) when the composed
    decision string exceeds `oss_state.MAX_DECISION` (200 chars). A
    maintainer session writing free-form `--reason` prose (`commands/run.md`
    hands it exactly that) got an uncaught traceback instead of the
    documented `FAIL:` line."""
    root = _git_repo(tmp_path)
    _write_config(root, {"state_file": ".max/oss-watch.json"})
    _quiet_inbound(monkeypatch, unruled=1)
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
    too_long_reason = "x" * 250
    rc = next_action.main(
        ["--root", str(root), "--record-skip", "release", "--reason", too_long_reason]
    )
    assert rc != 0
    assert "FAIL:" in capsys.readouterr().out


# --- inbound repeat-suppression (#1433) -------------------------------------


def test_rank_alone_never_arms_the_inbound_receipt(tmp_path, monkeypatch):
    """The same discipline #1405/#1414 gave curate and triage: a plain,
    repeated `rank()` read must never persist an inbound repeat-suppression
    receipt on its own -- only an explicit `--take`/`--record-skip`
    commitment may. Without this, an unanswered external pull request would
    keep firing forever, exactly the defect #1433 names."""
    root = _git_repo(tmp_path)
    _write_config(root, {"state_file": ".max/oss-watch.json"})
    _quiet_inbound(monkeypatch, unruled=1)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    first = next_action.rank(root)
    assert _candidate(first, "inbound")["state"] == next_action.CANDIDATE_DUE

    second = next_action.rank(root)
    assert _candidate(second, "inbound")["state"] == next_action.CANDIDATE_DUE

    third = next_action.rank(root)
    assert _candidate(third, "inbound")["state"] == next_action.CANDIDATE_DUE


def test_taking_inbound_arms_it_so_the_next_read_does_not_repeat_due_forever(
    tmp_path, monkeypatch
):
    """The must-fire-again half's positive control lives right below --
    this is the must-not-fire-forever half: `--take inbound` is the
    commitment that arms the receipt."""
    root = _git_repo(tmp_path)
    _write_config(root, {"state_file": ".max/oss-watch.json"})
    _quiet_inbound(monkeypatch, unruled=1)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    first = next_action.rank(root)
    assert _candidate(first, "inbound")["state"] == next_action.CANDIDATE_DUE

    rc = next_action.main(["--root", str(root), "--take", "inbound"])
    assert rc == 0

    second = next_action.rank(root)
    assert _candidate(second, "inbound") is None, second


def test_a_changed_inbound_reading_re_arms(tmp_path, monkeypatch):
    """Positive control for the test above: the same repo, taken once, but
    the outside count actually changes before the next read -- it must
    fire again, proving the suppression is keyed to the reading, not to a
    route that simply never fires twice."""
    root = _git_repo(tmp_path)
    _write_config(root, {"state_file": ".max/oss-watch.json"})
    _quiet_inbound(monkeypatch, unruled=1)
    _not_fired_release(monkeypatch)
    _quiet_triage_trigger(monkeypatch)

    first = next_action.rank(root)
    assert _candidate(first, "inbound")["state"] == next_action.CANDIDATE_DUE
    assert next_action.main(["--root", str(root), "--take", "inbound"]) == 0

    _quiet_inbound(monkeypatch, unruled=2)
    second = next_action.rank(root)
    assert _candidate(second, "inbound")["state"] == next_action.CANDIDATE_DUE
