"""`release_publish.py` refuses a sub-manager before doing anything else (#695).

The issue requires release (tag, publish) authority to be withheld from the
per-tick sub-manager "in the code, not only in prose". `scripts/agent_role.py`
is that code; this test proves `release_publish.main()` actually calls it,
and calls it *first* -- before the config is read, before the changelog is
opened, before `gh` is even resolved -- so a sub-manager cannot reach a
publish call by way of a repository whose `.oss.json` says `loop`.

The positive control matters here specifically: a gate that fires on every
role would make this repository's own release path un-runnable, which is
exactly the kind of over-broad guard #695 warns against for the release
authority key it borrows the three-state shape from.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release_publish.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import agent_role  # noqa: E402
import spawn_guard  # noqa: E402
import release_publish  # noqa: E402


def _run(tmp_path, env_role, tag="v1.0.0", version="1.0.0", repo=None, execute=False):
    env = dict(os.environ)
    if env_role is None:
        env.pop(agent_role.ROLE_ENV, None)
    else:
        env[agent_role.ROLE_ENV] = env_role
    argv = [
        sys.executable,
        str(SCRIPT),
        "--repo",
        str(repo or tmp_path),
        "--version",
        version,
        "--tag",
        tag,
        "--json",
    ]
    if execute:
        argv.append("--execute")
    return spawn_guard.run(
        argv,
        subject="what release_publish.py's role gate answers for this role",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_sub_manager_role_is_refused_before_config_is_even_read(tmp_path):
    # No .oss.json in tmp_path at all -- if the gate ran after the config
    # read, this would fail on a missing file instead of the role.
    result = _run(tmp_path, "sub-manager")
    payload = json.loads(result.stdout)
    assert payload["state"] == "role-forbidden"
    assert "sub-manager" in payload["reason"]
    assert "696" in payload["reason"]
    assert result.returncode == release_publish.EXIT_ROLE_FORBIDDEN


def test_no_role_reaches_past_the_gate(tmp_path):
    """Positive control: an ordinary invocation, no role set, must not be
    caught by this gate -- it should fail later, on the missing config,
    never on the role check."""
    result = _run(tmp_path, None)
    payload = json.loads(result.stdout)
    assert payload["state"] != "role-forbidden"


def test_maintainer_role_reaches_past_the_gate(tmp_path):
    result = _run(tmp_path, "maintainer")
    payload = json.loads(result.stdout)
    assert payload["state"] != "role-forbidden"
