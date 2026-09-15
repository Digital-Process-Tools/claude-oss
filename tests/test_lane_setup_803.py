"""#803: `main`'s `--release` arm dropped `oss_config.load`'s `problems` list in
exactly the case #791 did not fix. #791 fixed `config is None` -- the project half
(`.oss.json`) could not be read at all. `worktree_root` only ever lives in
`.oss.local.json` (`LOCAL_KEYS`, `scripts/oss_config.py`), so when the *local* half
is present but unparseable, `oss_config.load` returns a non-None `config` -- with
no `worktree_root` key, since the unreadable local half was never merged in -- and
the real parse error sits in `problems` instead of in `config is None`. The old
`else` arm, reached whenever `config is not None`, dropped that list the same way
the pre-#791 code did and rendered the same benign "no registry" sentence written
for a config that genuinely has no `worktree_root` key configured.

Three arms, matching the issue body:

  A  .oss.local.json present and malformed -- must surface the parse error.
  B  .oss.json malformed -- already correct pre-#803 (this is the control that
     proves the fix does not touch the already-working path).
  C  no local file at all -- must read differently from arm A's (arm C genuinely
     has nothing to report; arm A has a concrete parse error). #608: `worktree_root`
     used to be simply absent for arm C, rendering the benign "no registry"
     sentence; `oss_config.load` now DERIVES it from the repository root instead,
     so arm C reaches the ordinary `not-found` outcome -- still benign, still
     distinct from arm A, reached a different way.

A naive "gate on any `problems`" over-corrects: pre-#608, `oss_config.load` always
added a "missing required key: worktree_root" advisory to `problems` whenever
`worktree_root` was absent, read failure or not, which was exactly arm C's own
ordinary case -- so a fourth control below (a syntactically valid `.oss.local.json`
that simply omits `worktree_root`) pins that the benign outcome still holds even
where that advisory would have fired.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import spawn_guard  # noqa: E402

PROJECT_CONFIG = {
    "repo": "example/example",
    "default_branch": "main",
    "branch_pattern": "fix/{issue}",
    "test_command": "pytest",
    "version_sites": [],
    "changelog_dir": None,
    "docs_targets": [],
    "labels": {"priority": [], "lanes": []},
}


def _cli(tmp_path, issue, *extra_args):
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return spawn_guard.run(
        [sys.executable, str(SCRIPT), str(issue), "--repo", str(tmp_path), "--json"]
        + list(extra_args),
        subject="lane_setup.py --release",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _release(tmp_path, issue=999):
    done = _cli(tmp_path, issue, "--release")
    return json.loads(done.stdout)


# #1532 changed what this arm is even asking. `--release` needed TWO config
# values -- `worktree_root`, to find the lane registry holding the record to
# release, and `repo`, to aim the assignee call. `worktree_root` lives only in
# `.oss.local.json`, which is why an unparseable local half had to be told
# apart from a benign missing key: the first is a read that failed, the second
# is a value nobody set, and #803 was filed because they rendered identically.
#
# There is no registry, so `--release` no longer reads `worktree_root` at all.
# `repo` comes from the project half. That collapses arms c, d and e (all
# `worktree_root` shapes) to nothing, and inverts arm a: a malformed
# `.oss.local.json` no longer blocks a release, because nothing the release
# needs was in it.
#
# What survives is the distinction #803 and #791 were both really about, and it
# is asserted below: a read that FAILED must never render as a benign absence.


def test_a_malformed_project_config_still_blocks_and_names_the_parse_error(tmp_path):
    """The project half carries `repo`. Unparseable, and the repository the
    assignee call would be aimed at is genuinely unknown -- so this refuses,
    and says why in the words of the parse error rather than as a bare
    absence."""
    (tmp_path / ".oss.json").write_text("{not json")

    payload = _release(tmp_path)

    assert payload["state"] == "could-not-release"
    assert "could not parse as JSON" in payload["detail"]


def test_an_absent_project_config_is_a_different_sentence_from_a_malformed_one(
    tmp_path,
):
    """The pair to the test above, and the whole point of both #791 and #803:
    `not found` and `could not parse` are different facts and must not share a
    sentence. Both refuse; only one of them is a file somebody wrote wrong."""
    payload = _release(tmp_path)

    assert payload["state"] == "could-not-release"
    assert "not found" in payload["detail"]
    assert "could not parse as JSON" not in payload["detail"]


def test_a_malformed_local_config_no_longer_blocks_the_release(tmp_path):
    """The inversion #1532 causes, asserted rather than left to be discovered.

    This used to be arm a: a valid project config beside an unparseable
    `.oss.local.json` refused, because `worktree_root` -- which lives only in
    the local half -- was needed to find the lane record. It is not needed any
    more, so refusing here would be refusing over a file the operation does not
    read.

    The release therefore proceeds past the config, to the assignee call. This
    asserts only that it got that far -- that the config half did not stop it
    -- and not what the forge answered, which needs a live `gh` this test has
    no business requiring."""
    (tmp_path / ".oss.json").write_text(json.dumps(PROJECT_CONFIG))
    (tmp_path / ".oss.local.json").write_text("{not json")

    payload = _release(tmp_path)

    config_refusal = payload.get(
        "state"
    ) == "could-not-release" and "the repository is not known" in payload.get(
        "detail", ""
    )
    assert not config_refusal, payload
