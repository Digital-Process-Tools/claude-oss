"""#917: the cohort freeze was done by hand, at whatever instant the maintainer
got to it, and the same tag produced three different membership counts across
one afternoon (27 / 30 / 32 for v0.20.0, depending on whether it was read at
tag-object time, release-publish time, or an hour later). This module makes
the freeze reproducible: membership is derived from the TAG OBJECT's own
`tagger.date`, never from `now`, so a late freeze and a prompt one compute the
identical set.

Three states, and the third is the point (this repo's own defect class,
applied to its own bookkeeping): `frozen N` / `already-frozen, nothing to do`
/ `could-not-read` -- and `could-not-read` must never render as a cohort of
zero. `test_freeze_could_not_read_when_tag_unresolvable` and
`test_freeze_already_frozen_zero_members_is_a_real_zero` are the paired
must-not-fire / must-fire control for exactly that: one is a real empty
cohort (`count == 0`), the other is a failed read (`count is None`), and
nothing before this module returns the same shape for both.

`test_cohort_members_v0_20_0_real_fixture` is traceable to the acceptance
number in the issue: `cohort-16` for `v0.20.0` is 27 issues open at
`2026-09-03T08:13:40Z`, the tag object's own `tagger.date` (verified against
the live tracker while writing this fix: `gh api
repos/Digital-Process-Tools/claude-oss/git/tags/4d79d6e4f5efc93c0215115dc9061632e0896087`
carries that exact tagger.date, and `gh-labels:tally=cohort-` already shows
`cohort-16` frozen at 27 with the identical 27 issue numbers below). The 27
member rows and the handful of near-boundary non-members are real
`created_at`/`closed_at` pairs read off that tracker, not invented ones --
#903 in particular was created 2026-09-03T08:20:22Z, seven minutes after the
tag, which is the closest real near-miss available and a sharper boundary
check than a synthetic timestamp would be.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import cohort_freeze  # noqa: E402


CUTOFF = "2026-09-03T08:13:40Z"

REPO = "Digital-Process-Tools/claude-oss"
TAG = "v0.20.0"
TAG_SHA = "4d79d6e4f5efc93c0215115dc9061632e0896087"
TAG_REF_URL_ARGS = ["gh", "api", "repos/{}/git/refs/tags/{}".format(REPO, TAG)]


class _Done:
    """A stand-in for `subprocess.CompletedProcess` -- only the three fields
    every caller here reads."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _scripted_run(script):
    """`run(command, **kwargs)` that answers from a dict keyed by the command's
    own first three-ish tokens, joined -- so a test only has to name the calls
    it cares about and anything unscripted is a loud KeyError, never a silent
    empty success.
    """

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        key = tuple(command)
        if key not in script:
            raise AssertionError("unscripted gh call: {}".format(command))
        result = script[key]
        if isinstance(result, Exception):
            raise result
        return result

    run.calls = calls
    return run


def _annotated_tag_script(extra=None):
    script = {
        tuple(TAG_REF_URL_ARGS): _Done(
            0,
            json.dumps(
                {"object": {"sha": TAG_SHA, "type": "tag"}}
            ),
        ),
        (
            "gh",
            "api",
            "repos/{}/git/tags/{}".format(REPO, TAG_SHA),
        ): _Done(
            0,
            json.dumps({"tagger": {"date": CUTOFF}}),
        ),
    }
    if extra:
        script.update(extra)
    return script


# --------------------------------------------------------------- resolve_tag_timestamp


def test_resolve_tag_timestamp_annotated_tag_ok():
    run = _scripted_run(_annotated_tag_script())
    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result == {"state": "ok", "timestamp": CUTOFF, "reason": ""}


def test_resolve_tag_timestamp_lightweight_tag_uses_commit_committer_date():
    script = {
        tuple(TAG_REF_URL_ARGS): _Done(
            0, json.dumps({"object": {"sha": "abc123", "type": "commit"}})
        ),
        ("gh", "api", "repos/{}/git/commits/abc123".format(REPO)): _Done(
            0, json.dumps({"committer": {"date": CUTOFF}})
        ),
    }
    run = _scripted_run(script)
    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result == {"state": "ok", "timestamp": CUTOFF, "reason": ""}


def test_resolve_tag_timestamp_could_not_read_when_gh_not_on_path():
    def run(command, **kwargs):
        raise OSError("gh not found")

    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["timestamp"] is None
    assert "gh not found" in result["reason"]


def test_resolve_tag_timestamp_could_not_read_on_nonzero_exit():
    script = {
        tuple(TAG_REF_URL_ARGS): _Done(1, "", "gh: Not Found (HTTP 404)"),
    }
    run = _scripted_run(script)
    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["timestamp"] is None
    assert "404" in result["reason"]


def test_resolve_tag_timestamp_could_not_read_on_unparseable_json():
    script = {
        tuple(TAG_REF_URL_ARGS): _Done(0, "not json"),
    }
    run = _scripted_run(script)
    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["timestamp"] is None


def test_resolve_tag_timestamp_could_not_read_when_object_missing_sha_or_type():
    """The other unguarded shape of `resolve_tag_timestamp`, alongside the
    missing-tagger.date case below: `object` present but without `sha`/`type`
    at all (a response shape this module has never actually observed, but
    JSON from a remote API is not a contract)."""
    script = {tuple(TAG_REF_URL_ARGS): _Done(0, json.dumps({"object": {}}))}
    run = _scripted_run(script)
    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["timestamp"] is None


def test_resolve_tag_timestamp_could_not_read_on_unexpected_object_type():
    """`object.type` is neither `"tag"` nor `"commit"` -- GitHub can return
    `"blob"` or `"tree"` for other ref shapes. Neither a tag object's
    `tagger.date` nor a commit's `committer.date` exists to fall back to, so
    this is `could-not-read`, never a guess."""
    script = {
        tuple(TAG_REF_URL_ARGS): _Done(
            0, json.dumps({"object": {"sha": "deadbeef", "type": "blob"}})
        )
    }
    run = _scripted_run(script)
    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["timestamp"] is None
    assert "blob" in result["reason"]


def test_resolve_tag_timestamp_could_not_read_when_tag_object_missing_tagger_date():
    script = _annotated_tag_script(
        extra={
            (
                "gh",
                "api",
                "repos/{}/git/tags/{}".format(REPO, TAG_SHA),
            ): _Done(0, json.dumps({"tagger": {}})),
        }
    )
    run = _scripted_run(script)
    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["timestamp"] is None


# --------------------------------------------------------------- cohort_members


def test_cohort_members_created_at_cutoff_is_inclusive():
    issues = [{"number": 1, "created_at": CUTOFF, "closed_at": None}]
    assert cohort_freeze.cohort_members(issues, CUTOFF) == [1]


def test_cohort_members_created_after_cutoff_excluded():
    issues = [
        {"number": 1, "created_at": "2026-09-03T08:13:41Z", "closed_at": None}
    ]
    assert cohort_freeze.cohort_members(issues, CUTOFF) == []


def test_cohort_members_closed_exactly_at_cutoff_excluded():
    """'closed after it' per the issue -- closed IN the same instant as the
    tag is not 'still open then', so this is excluded rather than included.
    The boundary is unlikely to matter in practice; it must still be
    unambiguous."""
    issues = [
        {
            "number": 1,
            "created_at": "2026-09-01T00:00:00Z",
            "closed_at": CUTOFF,
        }
    ]
    assert cohort_freeze.cohort_members(issues, CUTOFF) == []


def test_cohort_members_closed_one_second_after_cutoff_included():
    issues = [
        {
            "number": 1,
            "created_at": "2026-09-01T00:00:00Z",
            "closed_at": "2026-09-03T08:13:41Z",
        }
    ]
    assert cohort_freeze.cohort_members(issues, CUTOFF) == [1]


def test_cohort_members_still_open_included():
    issues = [
        {"number": 1, "created_at": "2026-09-01T00:00:00Z", "closed_at": None}
    ]
    assert cohort_freeze.cohort_members(issues, CUTOFF) == [1]


def test_cohort_members_closed_before_cutoff_excluded():
    issues = [
        {
            "number": 1,
            "created_at": "2026-08-01T00:00:00Z",
            "closed_at": "2026-08-02T00:00:00Z",
        }
    ]
    assert cohort_freeze.cohort_members(issues, CUTOFF) == []


def test_cohort_members_v0_20_0_real_fixture():
    """Traceable to the issue's own acceptance number: 27 real issues, real
    timestamps, read off the tracker (see module docstring)."""
    members_rows = [
        (383, "2026-08-20T11:43:59Z", None),
        (455, "2026-08-22T10:13:15Z", None),
        (581, "2026-08-26T12:55:14Z", None),
        (583, "2026-08-26T12:55:17Z", None),
        (635, "2026-08-28T21:30:21Z", None),
        (683, "2026-08-29T08:06:18Z", None),
        (699, "2026-08-31T08:35:47Z", "2026-09-03T11:25:49Z"),
        (724, "2026-08-31T20:48:43Z", None),
        (732, "2026-09-01T06:33:58Z", None),
        (748, "2026-09-01T08:29:29Z", None),
        (755, "2026-09-01T09:43:43Z", None),
        (760, "2026-09-01T10:25:52Z", None),
        (761, "2026-09-01T10:30:58Z", None),
        (777, "2026-09-01T16:42:10Z", None),
        (779, "2026-09-01T16:42:43Z", None),
        (780, "2026-09-01T16:43:21Z", "2026-09-03T12:55:39Z"),
        (783, "2026-09-01T17:24:57Z", None),
        (833, "2026-09-02T07:43:26Z", "2026-09-03T12:55:39Z"),
        (845, "2026-09-02T09:04:45Z", "2026-09-03T12:01:09Z"),
        (846, "2026-09-02T09:06:09Z", None),
        (892, "2026-09-03T06:21:30Z", "2026-09-03T12:59:09Z"),
        (895, "2026-09-03T06:54:21Z", "2026-09-03T12:59:10Z"),
        (896, "2026-09-03T06:54:23Z", None),
        (897, "2026-09-03T06:54:24Z", "2026-09-03T11:51:28Z"),
        (898, "2026-09-03T06:54:26Z", None),
        (899, "2026-09-03T06:54:28Z", None),
        (901, "2026-09-03T07:17:17Z", None),
    ]
    # Real near-boundary non-members, closest available real data to the cutoff.
    nonmembers_rows = [
        (903, "2026-09-03T08:20:22Z", None),  # created 7 min after the tag
        (908, "2026-09-03T09:52:36Z", "2026-09-03T10:15:36Z"),
        (910, "2026-09-03T09:57:55Z", None),
        (913, "2026-09-03T10:20:30Z", "2026-09-03T12:51:39Z"),
        (914, "2026-09-03T10:39:43Z", None),
        (915, "2026-09-03T10:48:25Z", "2026-09-03T11:14:51Z"),
        (917, "2026-09-03T10:57:05Z", None),
        (918, "2026-09-03T11:36:11Z", "2026-09-03T13:16:06Z"),
    ]
    issues = [
        {"number": n, "created_at": c, "closed_at": z}
        for (n, c, z) in members_rows + nonmembers_rows
    ]
    result = cohort_freeze.cohort_members(issues, CUTOFF)
    assert result == sorted(n for (n, _, _) in members_rows)
    assert len(result) == 27


# --------------------------------------------------------------- fetch_issues


def test_fetch_issues_ok():
    lines = "\n".join(
        json.dumps({"number": n, "created_at": c, "closed_at": z})
        for (n, c, z) in [(1, "2026-01-01T00:00:00Z", None)]
    )
    run = _scripted_run(
        {
            (
                "gh",
                "api",
                "--paginate",
                "-X",
                "GET",
                "repos/{}/issues".format(REPO),
                "-f",
                "state=all",
                "-f",
                "per_page=100",
                "--jq",
                ".[] | select(.pull_request == null) | {number, created_at, closed_at}",
            ): _Done(0, lines)
        }
    )
    result = cohort_freeze.fetch_issues(REPO, "gh", run)
    assert result["state"] == "ok"
    assert result["issues"] == [
        {"number": 1, "created_at": "2026-01-01T00:00:00Z", "closed_at": None}
    ]


def test_fetch_issues_could_not_read_on_bad_line():
    key = (
        "gh",
        "api",
        "--paginate",
        "-X",
        "GET",
        "repos/{}/issues".format(REPO),
        "-f",
        "state=all",
        "-f",
        "per_page=100",
        "--jq",
        ".[] | select(.pull_request == null) | {number, created_at, closed_at}",
    )
    run = _scripted_run({key: _Done(0, "not json")})
    result = cohort_freeze.fetch_issues(REPO, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["issues"] is None


def test_fetch_issues_could_not_read_on_nonzero_exit():
    key = (
        "gh",
        "api",
        "--paginate",
        "-X",
        "GET",
        "repos/{}/issues".format(REPO),
        "-f",
        "state=all",
        "-f",
        "per_page=100",
        "--jq",
        ".[] | select(.pull_request == null) | {number, created_at, closed_at}",
    )
    run = _scripted_run({key: _Done(1, "", "rate limited")})
    result = cohort_freeze.fetch_issues(REPO, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["issues"] is None
    assert "rate limited" in result["reason"]


# --------------------------------------------------------------- label_members


def test_label_members_ok():
    label = "cohort-16"
    key = (
        "gh",
        "api",
        "--paginate",
        "-X",
        "GET",
        "repos/{}/issues".format(REPO),
        "-f",
        "state=all",
        "-f",
        "labels={}".format(label),
        "-f",
        "per_page=100",
        "--jq",
        ".[] | select(.pull_request == null) | .number",
    )
    run = _scripted_run({key: _Done(0, "383\n455\n")})
    result = cohort_freeze.label_members(REPO, label, "gh", run)
    assert result == {"state": "ok", "numbers": [383, 455], "reason": ""}


def test_label_members_could_not_read():
    label = "cohort-16"
    key = (
        "gh",
        "api",
        "--paginate",
        "-X",
        "GET",
        "repos/{}/issues".format(REPO),
        "-f",
        "state=all",
        "-f",
        "labels={}".format(label),
        "-f",
        "per_page=100",
        "--jq",
        ".[] | select(.pull_request == null) | .number",
    )
    run = _scripted_run({key: _Done(1, "", "bad credentials")})
    result = cohort_freeze.label_members(REPO, label, "gh", run)
    assert result["state"] == "could-not-read"
    assert result["numbers"] is None


# ------------------------------------------------------- non-UTF-8 subprocess output
#
# #112's shape, reintroduced in this module and closed the same way: passing
# `universal_newlines=True` (or `text=True`) to `subprocess.run` decodes with the
# *locale* codec, strictly, and a `UnicodeDecodeError` is a `ValueError` -- not
# caught by any `except (OSError, subprocess.SubprocessError)` guarding these calls,
# so it would crash `main()` with a traceback instead of reaching `could-not-read`.
# These assert two things at once: that `run` is never called with `text=True` /
# `universal_newlines=True` at all (so real `subprocess.run` hands back bytes, not a
# strict decode), and that raw bytes containing a byte invalid UTF-8 flow through as
# `could-not-read` rather than raising -- reproducing this with a `_Done` stand-in
# alone could not catch the bug, since the mock never exercises real decoding; the
# `assert "text" not in kwargs` guard below is what actually pins the fix.


def test_resolve_tag_timestamp_decodes_nonutf8_bytes_without_raising():
    def run(command, **kwargs):
        assert "universal_newlines" not in kwargs
        assert kwargs.get("text") is not True
        return _Done(1, b"", b"gh: tag caf\xe9 not found")

    result = cohort_freeze.resolve_tag_timestamp(REPO, TAG, "gh", run)
    assert result["state"] == "could-not-read"
    assert "caf" in result["reason"]


def test_fetch_issues_decodes_nonutf8_bytes_without_raising():
    def run(command, **kwargs):
        assert "universal_newlines" not in kwargs
        assert kwargs.get("text") is not True
        return _Done(1, b"", b"gh: rate limited by caf\xe9 proxy")

    result = cohort_freeze.fetch_issues(REPO, "gh", run)
    assert result["state"] == "could-not-read"
    assert "caf" in result["reason"]


def test_label_members_decodes_nonutf8_bytes_without_raising():
    def run(command, **kwargs):
        assert "universal_newlines" not in kwargs
        assert kwargs.get("text") is not True
        return _Done(1, b"", b"gh: bad credentials caf\xe9")

    result = cohort_freeze.label_members(REPO, "cohort-16", "gh", run)
    assert result["state"] == "could-not-read"
    assert "caf" in result["reason"]


def test_apply_labels_decodes_nonutf8_bytes_without_raising():
    def run(command, **kwargs):
        assert "universal_newlines" not in kwargs
        assert kwargs.get("text") is not True
        return _Done(1, b"", b"422 could not add label caf\xe9")

    result = cohort_freeze.apply_labels(REPO, "cohort-16", [1], "gh", run)
    assert result["added"] == []
    assert len(result["failed"]) == 1
    assert "caf" in result["failed"][0]["reason"]


# --------------------------------------------------------------- freeze (orchestration)


def _freeze_script(members_numbers, already_numbers, apply_ok=True):
    label = "cohort-16"
    script = _annotated_tag_script()
    lines = "\n".join(
        json.dumps({"number": n, "created_at": CUTOFF, "closed_at": None})
        for n in members_numbers
    )
    script[
        (
            "gh",
            "api",
            "--paginate",
            "-X",
            "GET",
            "repos/{}/issues".format(REPO),
            "-f",
            "state=all",
            "-f",
            "per_page=100",
            "--jq",
            ".[] | select(.pull_request == null) | {number, created_at, closed_at}",
        )
    ] = _Done(0, lines)
    script[
        (
            "gh",
            "api",
            "--paginate",
            "-X",
            "GET",
            "repos/{}/issues".format(REPO),
            "-f",
            "state=all",
            "-f",
            "labels={}".format(label),
            "-f",
            "per_page=100",
            "--jq",
            ".[] | select(.pull_request == null) | .number",
        )
    ] = _Done(0, "\n".join(str(n) for n in already_numbers))
    for n in members_numbers:
        if n in already_numbers:
            continue
        if apply_ok:
            script[
                ("gh", "issue", "edit", str(n), "--repo", REPO, "--add-label", label)
            ] = _Done(0, "")
        else:
            script[
                ("gh", "issue", "edit", str(n), "--repo", REPO, "--add-label", label)
            ] = _Done(1, "", "422 could not add label")
    return script


def test_freeze_dry_run_computes_but_does_not_write():
    script = _freeze_script(members_numbers=[1, 2, 3], already_numbers=[])
    run = _scripted_run(script)
    result = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=False)
    assert result["state"] == "frozen"
    assert result["count"] == 3
    assert result["added"] == [1, 2, 3]
    assert result["dry_run"] is True
    assert not any(call[:3] == ["gh", "issue", "edit"] for call in run.calls)


def test_freeze_execute_writes_labels():
    script = _freeze_script(members_numbers=[1, 2, 3], already_numbers=[])
    run = _scripted_run(script)
    result = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=True)
    assert result["state"] == "frozen"
    assert result["count"] == 3
    assert sorted(result["added"]) == [1, 2, 3]
    assert result["dry_run"] is False
    edit_calls = [call for call in run.calls if call[:3] == ["gh", "issue", "edit"]]
    assert len(edit_calls) == 3


def test_freeze_already_frozen_nothing_to_add():
    script = _freeze_script(members_numbers=[1, 2, 3], already_numbers=[1, 2, 3])
    run = _scripted_run(script)
    result = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=True)
    assert result["state"] == "already-frozen"
    assert result["added"] == []
    assert result["count"] == 3
    assert not any(call[:3] == ["gh", "issue", "edit"] for call in run.calls)


def test_freeze_is_idempotent_second_run_no_op():
    """Re-running after a real freeze must add nothing and change nothing --
    the acceptance criterion, exercised end to end rather than asserted only
    against `label_members` in isolation."""
    script = _freeze_script(members_numbers=[1, 2, 3], already_numbers=[])
    run = _scripted_run(script)
    first = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=True)
    assert first["state"] == "frozen"

    # second run: everything is now already labelled
    script2 = _freeze_script(members_numbers=[1, 2, 3], already_numbers=[1, 2, 3])
    run2 = _scripted_run(script2)
    second = cohort_freeze.freeze(REPO, TAG, 16, "gh", run2, execute=True)
    assert second["state"] == "already-frozen"
    assert second["added"] == []


def test_freeze_partial_add_leaves_the_rest_for_next_run():
    script = _freeze_script(members_numbers=[1, 2, 3], already_numbers=[1])
    run = _scripted_run(script)
    result = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=True)
    assert result["state"] == "frozen"
    assert sorted(result["added"]) == [2, 3]


def test_freeze_execute_partial_failure_is_could_not_read_not_frozen():
    script = _freeze_script(
        members_numbers=[1, 2], already_numbers=[], apply_ok=False
    )
    run = _scripted_run(script)
    result = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=True)
    assert result["state"] == "could-not-read"
    # `count`/`members` are NOT None here -- membership was already computed
    # before the write failed, and the docstring is explicit that only
    # `state` is the authoritative could-not-read signal, never the shape of
    # `count` alone. `added` carries the empty list: nothing actually landed
    # since both writes in this fixture fail.
    assert result["count"] == 2
    assert result["members"] == [1, 2]
    assert result["added"] == []


# ----------------------------------------------- the must-fire / must-not-fire pair


def test_freeze_could_not_read_when_tag_unresolvable():
    """MUST-FIRE half of the pair below: a genuine failure to read must never
    render as an empty cohort. `count` is `None`, not `0`."""
    run = _scripted_run({tuple(TAG_REF_URL_ARGS): _Done(1, "", "HTTP 404")})
    result = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=False)
    assert result["state"] == "could-not-read"
    assert result["count"] is None
    assert result["members"] is None


def test_freeze_already_frozen_zero_members_is_a_real_zero():
    """MUST-NOT-FIRE half of the pair: a tag with genuinely no open-or-recently
    -closed issues at cutoff is a real `already-frozen` with `count == 0`,
    distinguishable in shape (not just in prose) from the could-not-read case
    above -- `count` is `0`, an int, never `None`."""
    script = _freeze_script(members_numbers=[], already_numbers=[])
    run = _scripted_run(script)
    result = cohort_freeze.freeze(REPO, TAG, 16, "gh", run, execute=True)
    assert result["state"] == "already-frozen"
    assert result["count"] == 0
    assert result["members"] == []


# --------------------------------------------------------------- CLI wiring


def test_main_could_not_read_exit_code(monkeypatch, tmp_path):
    config = tmp_path / ".oss.json"
    config.write_text(json.dumps({"repo": REPO}), encoding="utf-8")

    def fake_run(command, **kwargs):
        raise OSError("no gh")

    monkeypatch.setattr(cohort_freeze.subprocess, "run", fake_run)
    monkeypatch.setattr(cohort_freeze.shutil, "which", lambda name: "gh")
    code = cohort_freeze.main(
        ["--repo", str(tmp_path), "--tag", TAG, "--cohort", "16", "--json"]
    )
    assert code == cohort_freeze.EXIT_COULD_NOT_READ


def test_main_could_not_read_when_gh_missing(tmp_path, monkeypatch):
    config = tmp_path / ".oss.json"
    config.write_text(json.dumps({"repo": REPO}), encoding="utf-8")
    monkeypatch.setattr(cohort_freeze.shutil, "which", lambda name: None)
    code = cohort_freeze.main(
        ["--repo", str(tmp_path), "--tag", TAG, "--cohort", "16"]
    )
    assert code == cohort_freeze.EXIT_COULD_NOT_READ


def test_main_repo_resolution_rejects_missing_config(tmp_path):
    code = cohort_freeze.main(
        ["--repo", str(tmp_path), "--tag", TAG, "--cohort", "16"]
    )
    assert code == cohort_freeze.EXIT_COULD_NOT_READ


def test_main_accepts_explicit_slug(monkeypatch):
    monkeypatch.setattr(cohort_freeze.shutil, "which", lambda name: None)
    code = cohort_freeze.main(
        ["--repo", REPO, "--tag", TAG, "--cohort", "16"]
    )
    # gh missing either way -- this only proves the slug itself was accepted
    # without needing a .oss.json on disk, not that the freeze ran.
    assert code == cohort_freeze.EXIT_COULD_NOT_READ

