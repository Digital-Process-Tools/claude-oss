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

import manager_docs  # noqa: E402

SPINE = (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(encoding="utf-8")

# The loop's whole prose, not the spine alone (#960): the cadence section's argument --
# the freeze/sweep separation, the #855 citation, the enforced-vs-unbuilt split -- moved
# into `phases/accounting.md`, leaving the cadence statement and the two receipts in the
# spine. Reading only the spine after that move is a guard about where the prose used to
# be, which is the shape `manager_docs` exists to remove.
SKILL = manager_docs.ManagerLoop(REPO_ROOT).read_text(encoding="utf-8")
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
    imply the whole thing is done.

    Both halves are asserted where they now live (#960). The spine's `## Cadence`
    directive carries the two receipts, because a tick that never opens the phase file
    still has to know the calls exist; the phase file carries which half is unbuilt,
    because that is argument rather than instruction. Asserting both in one window
    would pass on either document holding both, which is what the split rules out."""
    idx = SPINE.find("## Cadence")
    assert idx != -1, "the spine no longer carries a Cadence directive"
    window = SPINE[idx:idx + 2000]
    assert "--last-triage" in window
    assert "--triage-recorded" in window
    assert "skills/manager/phases/accounting.md" in window, (
        "the spine's cadence directive must name the file carrying the argument"
    )
    assert re.search(r"is not\b.{0,40}#855|is still unbuilt", SKILL, re.IGNORECASE), (
        "nothing in the loop's prose says which half of the mechanism is unbuilt"
    )


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


def test_the_spine_alone_would_not_satisfy_the_moved_assertions():
    """Positive control for the widening above (#960). If every assertion still passed
    against the spine on its own, swapping in the whole-loop reader would have proved
    nothing -- the checks would look widened while measuring the same bytes.

    Not all three markers are spine-absent, and the two that are carry the control.
    `triager must never write` is deliberately still in the spine, in the cohort-freeze
    step under *Closing a tick*, where a session performing the freeze reads it; it is
    the sweep-versus-freeze *argument* that moved. Asserting its absence would have
    been a control demanding a cut nobody made."""
    assert not re.search(r"triage\s+sweep is a separate step", SPINE, re.IGNORECASE)
    assert "#855" not in SPINE
