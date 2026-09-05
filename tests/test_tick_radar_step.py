"""The doctor state `commands/tick.md` cites is measured, not asserted twice.

The tick's radar step tells the loop that a bare `radar` which refused to run for
a missing preset is reported by `/oss:doctor` under a particular state name. That
is a claim about `doctor.radar_publish_state`, living in a different file, and
nothing was checking it -- #208 itself was filed naming `route-unknown` for that
case, which is the wrong one: `route-unknown` is what the function returns when
`presets` cannot be read at all, and a maintainer sent to it would be told the
route is unknown for a repo whose route is plainly absent.

So this is a *second measurement* rather than a second assertion. The name is
extracted from the prose and compared against what the function actually returns
for that exact configuration. Restating the name in a test would pass whenever the
document and the test were wrong together, which is the failure mode this repo's
own CLAUDE.md names as the reason to prefer a measurement.

The extraction is asserted to have matched. A pattern that found nothing has not
checked the document; it has only failed to look.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

# #1037: this content moved out of commands/tick.md into its own phase file,
# read by a sub-manager rather than injected into the scheduler on every tick.
TICK_MD = REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md"

#: The sentence in the radar step that attributes the missing-preset case to a
#: doctor state. Anchored on the fact, not on a heading, so a reordering of the
#: step does not silently stop checking it.
CITED_STATE_RE = re.compile(
    r"preset is absent from `presets`, which `/oss:doctor` reports as `([a-z-]+)`"
)


def _flowed(path):
    """The document with its line wrapping collapsed.

    A markdown paragraph breaks wherever the column ran out, so a sentence-level
    pattern read against the raw bytes is really a pattern about where the author
    pressed return. That is not a fact worth guarding, and a reflow that silently
    stopped the check would be indistinguishable from a document that stopped
    making the claim.
    """
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _write_supertool_config(root, document):
    root.mkdir(parents=True, exist_ok=True)
    (root / doctor.WATCH_CONFIG).write_text(json.dumps(document), encoding="utf-8")
    return root


def _state_for(root, document):
    return doctor.radar_publish_state(_write_supertool_config(root, document))[0]


def test_the_citation_pattern_matches():
    """The positive control for every assertion below.

    Without it a reworded step turns all of them into vacuous passes -- the exact
    shape of failure this file exists to make impossible for the state name.
    """
    assert CITED_STATE_RE.search(_flowed(TICK_MD)), (
        "commands/tick.md no longer attributes the missing-preset case to a "
        "/oss:doctor state in the shape CITED_STATE_RE reads. Either the step "
        "stopped naming which state a maintainer will see, or the pattern went "
        "stale -- a pattern that matched nothing has checked nothing."
    )


def test_the_cited_state_is_what_doctor_returns_for_a_missing_preset(tmp_path):
    cited = CITED_STATE_RE.search(_flowed(TICK_MD)).group(1)
    measured = _state_for(
        tmp_path / "missing-preset",
        {"presets": ["git"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
    )
    assert cited == measured, (
        "commands/tick.md sends a maintainer to `{}` for a repo whose `watch` "
        "preset is absent, but doctor.radar_publish_state answers `{}` for exactly "
        "that configuration.".format(cited, measured)
    )


def test_an_unreadable_presets_key_is_a_different_state(tmp_path):
    """The control that makes the test above non-trivial.

    If every misconfiguration produced one state, matching the cited name would
    prove nothing. These two are the pair #208 conflated, so they are measured
    apart rather than described apart.
    """
    absent = _state_for(
        tmp_path / "absent",
        {"presets": ["git"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
    )
    unreadable = _state_for(
        tmp_path / "unreadable",
        {"presets": "watch", "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
    )
    assert absent != unreadable, (
        "doctor.radar_publish_state no longer distinguishes an absent preset from "
        "an unreadable `presets` key, so the tick's step cannot name which one a "
        "maintainer is in."
    )


@pytest.mark.parametrize("bogus", ["no-radar", "route-unknown", "publishes"])
def test_a_wrong_citation_would_fail(tmp_path, bogus):
    """The negative control, pointed at the assertion rather than the document.

    `route-unknown` is in this list on purpose: it is the name #208 used, and a
    check that could not reject it would have certified the filing's own error.
    """
    measured = _state_for(
        tmp_path / bogus,
        {"presets": ["git"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}},
    )
    assert bogus != measured
