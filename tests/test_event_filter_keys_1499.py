"""`pr_exclude_events` may only name keys the per-PR poller can emit -- #1499.

Observed the day supertool 0.61.0 landed: the shipped default carried
`pr_opened`, which is a `github-pr-feed` event, not a `github-pr` one, and
radar refused the whole `gh-prs` tier -- `RadarError: pr_exclude_events names
event key(s) github-pr cannot emit: pr_opened`. Zero per-PR pollers, in every
repository scaffolded with that default, rendered as a WARNING line the doctor
check reported `ok` over. Worse than unfiltered, and silent.

Two guards. The first reads supertool's own `events.json` when a checkout is
reachable through the `supertool` on PATH and skips, naming what went
untested, when it is not -- the valid set is supertool's fact, never copied
here. The second holds the four shipped copies of the list to one value.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_event_filter as dcef  # noqa: E402
import scaffold  # noqa: E402

#: A key the feed poller emits and the per-PR poller does not -- the exact
#: value that shipped wrong. Kept as the positive control for the first guard:
#: if supertool ever moves it into `github-pr`, this control fails loudly and
#: the test is re-read, rather than the guard silently proving nothing.
FEED_ONLY_KEY = "pr_opened"


def _github_pr_event_keys():
    exe = shutil.which("supertool")
    if exe is None:
        pytest.skip(
            "no `supertool` on PATH -- untested: whether INITIAL_EXCLUDE names only keys github-pr can emit"
        )
    root = Path(exe).resolve().parent
    path = root / "presets" / "watch" / "sources" / "github-pr" / "events.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pytest.skip(
            "{} not found beside the supertool on PATH -- untested: the events.json subset check".format(
                path
            )
        )
    except (OSError, ValueError) as exc:
        pytest.skip(
            "{} could not be read ({}) -- untested: the events.json subset check".format(
                path, exc
            )
        )
    return {row["key"] for row in document["events"]}


def test_initial_exclude_names_only_keys_github_pr_can_emit():
    keys = _github_pr_event_keys()
    assert FEED_ONLY_KEY not in keys, (
        "positive control: the feed-only key is now a github-pr key; re-read this test"
    )
    stray = [key for key in dcef.INITIAL_EXCLUDE if key not in keys]
    assert stray == [], "radar refuses the whole gh-prs tier over these: {}".format(
        stray
    )


def _template_exclude():
    rendered = scaffold.SUPERTOOL_JSON.replace("__WATCH_NAME__", "x")
    return json.loads(rendered)["ops"]["radar"]["radar_tiers"]["gh-prs"][
        "pr_exclude_events"
    ]


def _remedy_exclude(module):
    return module.RADAR_REMEDY_CONFIG["ops"][module.RADAR_OP][module.RADAR_TIERS_KEY][
        "gh-prs"
    ]["pr_exclude_events"]


def test_the_four_shipped_copies_agree():
    assert _template_exclude() == dcef.INITIAL_EXCLUDE
    assert _remedy_exclude(scaffold) == dcef.INITIAL_EXCLUDE
    assert _remedy_exclude(doctor) == dcef.INITIAL_EXCLUDE
