"""A repository that DECLARES its channel name in its own tracked
`.supertool.json` owns that channel whether or not the current process happens
to carry `SUPERTOOL_WATCH_NAME`.

`_channel_reading` attributed on the environment variable alone: the
declaration route was reached only when `actual is not None`, so every session
not started by `bin/oss-workspace` fell through to `not-attributable` and
`/oss:doctor` reported

    the cached channel reading does not attribute to this repository -- neither
    derived from `.oss.json` nor declared in `.supertool.json` -- renders `ch?`

about a repository whose `.supertool.json` declares exactly the name the repo
derives. Its remedy asks the maintainer to declare `ops.<name>.watch_name` --
which was already declared, so no manual op and no `/oss:scaffold` run could
clear it, which by this repository's own rule makes it a bug in the check.

It also flaps: a `--refresh` run that happens to carry the variable writes
`derivation` and one without writes `not-attributable`, for one unchanged
repository, so the marker moves on its own.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402

NAME = "Digital-Process-Tools-claude-oss"
CONFIG = {"repo": "Digital-Process-Tools/claude-oss"}


def _repo(tmp_path, declared):
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"ops": {"channel": {"watch_name": declared}}}), encoding="utf-8"
    )
    return tmp_path


def _attribution(tmp_path, monkeypatch, declared, env_name=None):
    monkeypatch.delenv(statusline.WATCH_NAME_ENV, raising=False)
    if env_name is not None:
        monkeypatch.setenv(statusline.WATCH_NAME_ENV, env_name)
    # `_channel_reading` shells out to `channel:health` once attribution is
    # settled; only the attribution is under test here.
    monkeypatch.setattr(statusline, "_watch_preset_declared", lambda _root: False)
    _, attribution = statusline._channel_reading(
        str(_repo(tmp_path, declared)), CONFIG
    )
    return attribution


def test_a_declared_name_matching_the_derivation_attributes_with_no_env(
    tmp_path, monkeypatch
):
    """The bug. The declaration is a tracked file in the repository saying this
    repository owns this channel; whether THIS process was handed the variable
    says nothing about ownership."""
    assert _attribution(tmp_path, monkeypatch, NAME) == "declaration"


def test_the_exported_variable_still_attributes_when_it_is_present(
    tmp_path, monkeypatch
):
    """Positive control for the route that already worked -- without it, a fix
    that attributed everything unconditionally would pass the test above."""
    assert _attribution(tmp_path, monkeypatch, NAME, env_name=NAME) == "derivation"


def test_a_declared_name_that_is_neither_derived_nor_exported_stays_unattributed(
    tmp_path, monkeypatch
):
    """The negative half, and the reason this fix is narrow: a repository
    genuinely sharing another project's fleet must still render `ch?` rather
    than claim a socket it does not own."""
    assert _attribution(tmp_path, monkeypatch, "somebody-elses-fleet") == (
        "not-attributable"
    )


def test_a_declared_name_matching_an_exported_one_still_attributes(
    tmp_path, monkeypatch
):
    """#754's own case, unchanged: a repository whose declared name differs
    from its derivation but matches what is exported."""
    assert _attribution(
        tmp_path, monkeypatch, "custom-fleet", env_name="custom-fleet"
    ) == "declaration"
