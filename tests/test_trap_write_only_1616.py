"""#1616: trap.d/ is write-only in a scaffolded repo -- three gaps, one test each.

`.oss.json`'s `curate_route_threshold` was readable (`OPTIONAL_KEYS`, #1155) but nothing
wrote it into a freshly scaffolded config, so promotion was off by default everywhere,
forever -- and off in a way that reported clean (#1610 folds an unconfigured threshold
and a threshold nobody has fired into the same `not-due` state). The scaffolded
`CLAUDE.md` never named `trap.d/` at all, so the plugin's one shot at inviting a
contributor to use it went unused. And nine of fourteen Bash-granted agent briefs
carried no invitation to log a trap either.

Each gap gets its own test, mirroring the control the issue itself names: a repository
with a configured threshold and fragments under it must still be able to tell "promotion
is now armed" apart from "promotion fires on nothing" -- `test_curate_route_threshold_1303.py`
already carries that wiring check for this repository's own `.oss.json`; this file is
about the code paths that produce a *fresh* one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402
import workspace_routes  # noqa: E402

from test_delegated_test_run_877 import bash_granted_agent_names  # noqa: E402


def _probe(**overrides):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "labels": [],
        "milestones": [],
        "workflow_jobs": [],
        "files": [],
        "tags": [],
        "merge_method": "squash",
        "version_evidence": {},
    }
    probe.update(overrides)
    return probe


# ------------------------------------------------------------- gap 1: curate_route_threshold


def test_build_writes_curate_route_threshold():
    """A freshly derived config must carry the key, not leave it for a maintainer to
    discover is missing. Absent here means the #1155 /oss:curate route is never armed
    for a repo this plugin onboards, no matter how large trap.d/ grows (#1616)."""
    config = oss_config.build(_probe())
    assert "curate_route_threshold" in config, (
        "oss_config.build() does not write curate_route_threshold -- a repo scaffolded "
        "through /oss:setup gets promotion silently off by default, forever (#1616)"
    )
    assert workspace_routes._valid_threshold(config["curate_route_threshold"]), (
        "curate_route_threshold={!r} is not a usable non-negative integer -- "
        "workspace_routes.decide() would report could-not-count rather than a real "
        "comparison".format(config["curate_route_threshold"])
    )


def test_written_threshold_validates_and_is_project_scoped():
    """The key round-trips through validate() and split() the same way every other
    judgement-call default (release.triggers) already does -- never machine-scoped,
    never rejected as unknown."""
    config = oss_config.build(_probe())
    assert oss_config.validate(config) == []
    assert "curate_route_threshold" in oss_config.PROJECT_KEYS
    assert "curate_route_threshold" not in oss_config.LOCAL_KEYS


def test_written_threshold_actually_arms_the_curate_route(monkeypatch):
    """Wiring check, not just presence -- the control the issue itself names: with the
    written threshold, a fragment count one over it must arm the route (`decide()`'s
    own OVER state), and a count at the threshold must not (`UNDER`)."""
    config = oss_config.build(_probe())
    threshold = config["curate_route_threshold"]
    # #1676: build() now writes triage_route_threshold too, so decide() would
    # otherwise call the real triage_count against a fake repo slug. Pin it
    # UNDER so this test stays about curate and makes no forge call.
    monkeypatch.setattr(
        workspace_routes,
        "triage_count",
        lambda repo, gh, run, timeout=25, config=None: (
            0,
            "fixture: triage pinned under",
        ),
    )

    monkeypatch.setattr(
        workspace_routes,
        "curate_count",
        lambda repo_root, config=None, run=None, git_bin=None: (
            threshold + 1,
            "fixture: one over the written threshold",
        ),
    )
    armed_route, results = workspace_routes.decide(Path("."), config=config)
    assert results["curate"]["state"] == workspace_routes.OVER, (
        "a fragment count over the written threshold did not arm the curate route: "
        "{!r}".format(results["curate"])
    )
    assert armed_route == "curate"

    monkeypatch.setattr(
        workspace_routes,
        "curate_count",
        lambda repo_root, config=None, run=None, git_bin=None: (
            threshold,
            "fixture: at the written threshold",
        ),
    )
    armed_route, results = workspace_routes.decide(Path("."), config=config)
    assert results["curate"]["state"] == workspace_routes.UNDER, (
        "a fragment count at the written threshold armed the curate route early: "
        "{!r}".format(results["curate"])
    )
    assert armed_route is None


# ------------------------------------------------------------------- gap 2: CLAUDE_MD


def test_rendered_claude_md_names_trap_d():
    """The scaffolded CLAUDE.md gets one shot -- created once, then theirs forever
    under the ownership contract -- and used to take none of it (#1616)."""
    rendered = scaffold._render_claude_md(
        {
            "repo": "owner/name",
            "default_branch": "main",
            "test_command": "pytest",
        }
    )
    assert "trap.d/" in rendered, (
        "the rendered CLAUDE.md never mentions trap.d/ -- a contributor working in a "
        "plain session, not through any agent brief, has nowhere to be told the "
        "directory exists (#1616)"
    )


def test_claude_md_template_carries_the_trap_mention_before_render():
    """Positive control on the template itself, not only the rendered instance, so a
    future edit that removes the sentence fails here even for a render this test does
    not happen to exercise."""
    assert "trap.d/" in scaffold.CLAUDE_MD


# ---------------------------------------------------------- gap 3: agent brief invitations


#: The same population `tests/test_delegated_test_run_877.py` derives from disk --
#: every top-level `agents/*.md` file that grants `Bash`. #1616's own issue named ten
#: of them as carrying no invitation to use trap.d/ at all; the other four already did
#: (developer.md, auditor.md, release-auditor.md, sub-manager.md).
def test_every_bash_granted_agent_names_trap_d():
    granted = bash_granted_agent_names()
    assert granted, (
        "no Bash-granted agents/*.md found -- this check would vacuously pass"
    )
    missing = sorted(
        name
        for name in granted
        if "trap.d" not in (REPO_ROOT / "agents" / name).read_text(encoding="utf-8")
    )
    assert not missing, (
        "Bash-granted agent definition(s) {0} carry no mention of trap.d/ at all -- an "
        "agent that hits something worth logging has nowhere in its own brief telling "
        "it the route exists (#1616)".format(missing)
    )


def test_the_check_would_fail_on_a_file_that_lost_the_mention(tmp_path):
    """Negative-control fixture: a copy of a real brief with the sentence stripped out
    must fail the substring check above, proving it can actually see an absence rather
    than passing on anything."""
    real = (REPO_ROOT / "agents" / "doctor.md").read_text(encoding="utf-8")
    assert "trap.d" in real
    stripped = re.sub(
        r"\n## Trap\n\nSomething is not normal.*?trap\.d/README\.md`\.\n?",
        "\n",
        real,
        flags=re.DOTALL,
    )
    assert "trap.d" not in stripped, (
        "the stripping regex above did not actually remove the mention -- fix the "
        "fixture before trusting the negative control"
    )
