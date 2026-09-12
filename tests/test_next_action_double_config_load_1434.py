"""`next_action.py`'s `_take_cli`/`_record_skip_cli` used to load `.oss.json`
twice: once inside `rank()` (to confirm the payload is `RANKED`), and a
second time, independently, just to read `state_file` (#1434).

If the second read diverges from the first -- the file removed or
corrupted in the narrow window between the two calls, or a future refactor
that makes the two reads disagree -- the error folds into the same "no
state_file configured" text a genuinely unconfigured repo produces. A
caller cannot tell "never configured" from "config vanished a moment
later".

This is reasoned, not observed: reproducing the real fold would mean racing
the filesystem so the second read diverges from the first. The test below
proves the fix removes the second, independent load call entirely --
the honest fix here is a real refactor (`rank()` exposes the config it
already loaded, and both CLI functions reuse it), not a rewording of what
the fold says when it happens, per this issue's own text. A fix that
removes the second read leaves nothing left to demonstrate the fold
against: any test racing a second `oss_config.load` call directly, rather
than through `_take_cli`/`_record_skip_cli`, would exercise none of the
code this issue is actually about (self-review, Explore reviewer).
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import next_action  # noqa: E402
import oss_config  # noqa: E402


def _write_config(root):
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
            }
        ),
        encoding="utf-8",
    )
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


def _fake_ranked_payload(config):
    return {
        "state": next_action.RANKED,
        "candidates": [
            {
                "source": "release",
                "state": next_action.CANDIDATE_DUE,
                "reason": "x",
                "evidence": {},
                "rank": 1,
            }
        ],
        "not_due": [],
        "config": config,
    }


def test_oss_config_load_is_called_exactly_once_by_take_cli(tmp_path, monkeypatch):
    """The fixed shape: `_take_cli` must not call `oss_config.load` a second
    time once `rank()` has already loaded it -- one call for the whole
    operation, not two."""
    _write_config(tmp_path)

    calls = []
    real_load = oss_config.load

    def _counting_load(path):
        calls.append(path)
        return real_load(path)

    monkeypatch.setattr(oss_config, "load", _counting_load)
    monkeypatch.setattr(
        next_action, "_arm_route_source", lambda repo_root, config, routes, source: None
    )
    monkeypatch.setattr(next_action, "_default_branch_unreadable", lambda *a, **k: None)
    monkeypatch.setattr(next_action, "_routes", lambda *a, **k: {})
    monkeypatch.setattr(
        next_action,
        "_inbound_candidate",
        lambda repo_root, config: {
            "source": "inbound",
            "state": next_action.CANDIDATE_NOT_DUE,
            "reason": "x",
            "evidence": {},
        },
    )
    monkeypatch.setattr(
        next_action,
        "_release_candidate",
        lambda repo_root, config, now=None: {
            "source": "release",
            "state": next_action.CANDIDATE_DUE,
            "reason": "x",
            "evidence": {},
        },
    )
    monkeypatch.setattr(
        next_action,
        "_curate_candidate",
        lambda repo_root, config, routes, arm=False: {
            "source": "curate",
            "state": next_action.CANDIDATE_NOT_DUE,
            "reason": "x",
            "evidence": {},
        },
    )
    monkeypatch.setattr(
        next_action,
        "_triage_candidate",
        lambda repo_root, config, routes, arm=False: {
            "source": "triage",
            "state": next_action.CANDIDATE_NOT_DUE,
            "reason": "x",
            "evidence": {},
        },
    )

    # A separate, throwaway rank() call establishes the payload really is
    # RANKED on this fixture -- its own load is not what this test counts.
    probe_payload = next_action.rank(str(tmp_path))
    assert probe_payload["state"] == next_action.RANKED
    source = probe_payload["candidates"][0]["source"]

    calls.clear()
    result = next_action._take_cli(str(tmp_path), source)
    assert result == 0
    assert len(calls) == 1, (
        "_take_cli should call oss_config.load exactly once for the whole "
        "operation (inside its own rank() call) -- it called it {0} times, "
        "the exact double-load #1434 is about".format(len(calls))
    )
