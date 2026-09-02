"""#855: the loop had no written cadence for when a triage sweep runs relative
to ticks and releases, and nothing said the cohort freeze and the triage
sweep are two different steps. `skills/manager/SKILL.md` now states the
cadence in a `## Cadence` section, and `skills/manager/phases/accounting.md`
points at it from the step that consumes a sweep's clusters.

Every "must state" assertion is paired with a negative control on a fixture
string that must not accidentally satisfy the same pattern, per this repo's
own rule that a positive-only sweep proves nothing about specificity.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

SKILL = (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(encoding="utf-8")
ACCOUNTING = (REPO_ROOT / "skills" / "manager" / "phases" / "accounting.md").read_text(encoding="utf-8")

# --------------------------------------------------------- positive controls


def test_skill_states_the_maintainers_cadence():
    """Three to four ticks, a release, a triage sweep, repeat -- the
    maintainer's own stated cadence (#855), not implied or left to a reader's
    own inference."""
    assert re.search(r"three to four ticks", SKILL, re.IGNORECASE)
    assert "triage sweep" in SKILL


def test_skill_orders_triage_immediately_before_the_next_run_of_ticks():
    """The load-bearing ordering claim: triage feeds the *start* of the next
    run of ticks, not the end of the one that just closed."""
    assert re.search(r"immediately before", SKILL, re.IGNORECASE)


def test_skill_keeps_the_freeze_and_the_sweep_apart():
    """The cohort freeze is the maintainer's own act by hand, at the tag; the
    triager must never write a cohort-* label, and the sweep is a separate
    step that follows the freeze. Losing this distinction is exactly the
    failure #855 warns against repeating."""
    assert "triager must never write" in SKILL
    assert re.search(r"triage\s+sweep is a separate step", SKILL, re.IGNORECASE)


def test_skill_cites_855():
    assert "#855" in SKILL


def test_accounting_points_at_the_cadence_from_the_cluster_consuming_step():
    """accounting.md's own consumer of the triager's proposed clusters must
    say the sweep behind them is expected to postdate the last release,
    rather than being silent about when it ran."""
    idx = ACCOUNTING.find("proposed clusters are this rule arriving late")
    assert idx != -1, "accounting.md no longer carries the clusters-consumer paragraph this points from"
    window = ACCOUNTING[idx:idx + 900]
    assert "#855" in window
    assert re.search(r"after the previous release", window, re.IGNORECASE)


def test_skill_names_the_enforced_and_unbuilt_halves_of_the_mechanism_separately():
    """#855's own point, updated once the last-triaged half actually shipped
    (#880/#855 lane, oss_state.py): the section must say which half is a real
    receipt and which is still prose, never let the built half's existence
    imply the whole thing is done."""
    idx = SKILL.find("## Cadence")
    assert idx != -1
    window = SKILL[idx:idx + 2000]
    assert "--last-triage" in window
    assert "--triage-recorded" in window
    assert re.search(r"is not\b.{0,40}#855|is still unbuilt", window, re.IGNORECASE)


# --------------------------------------------------------- negative controls


def test_fixture_without_the_cadence_does_not_match_three_to_four_ticks():
    fixture = "Run one tick, then review and merge whatever is green."
    assert not re.search(r"three to four ticks", fixture, re.IGNORECASE)


def test_fixture_without_the_cadence_does_not_match_immediately_before():
    fixture = "Triage can happen whenever the maintainer has time for it."
    assert not re.search(r"immediately before", fixture, re.IGNORECASE)


def test_fixture_without_the_freeze_distinction_does_not_match():
    fixture = "Label the open board with a cohort tag whenever it seems useful."
    assert "triager must never write" not in fixture
    assert not re.search(r"triage sweep is a separate step", fixture, re.IGNORECASE)


def test_fixture_without_855_does_not_cite_it():
    fixture = "See #852 for the required-field mechanism."
    assert "#855" not in fixture
