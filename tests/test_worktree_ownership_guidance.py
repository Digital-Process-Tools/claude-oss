"""Guards on how skills/manager/SKILL.md answers worktree ownership.

Companion to test_content_invariants.py, which holds the cross-document prose
guards; this file is only about the worktree questions the manager loop asks --
which tree is safe to reap, and whether an agent is still in it.

Three kinds of guard live here and they are not interchangeable. Which kind a
guard is says what its passing is worth, so each is labelled rather than left to
read like the others:

* **Routing guards** -- the skill must name the op that answers the question.
  Six of these, each measured red against `HEAD^`'s SKILL.md before the change.
* **A regression guard** -- the skill must not print the raw listing supertool's
  guard refuses. This one was already green before the change: the literal
  command never appeared in the old file either, so it proves nothing about this
  fix and only holds the ground going forward. Saying so is the point; a guard
  that never fired red reads exactly like one that did.
* **Doctrine-retention guards** -- naming a tool must not cost the paragraph the
  reason the rule exists. These are green by construction against a file that
  still carries the doctrine, so each one is paired with a synthetic fixture
  that omits the doctrine and *must* be reported. A retention guard with no such
  pair passes just as happily over a paragraph that was deleted as over one that
  was kept, which is this plugin's own defect class pointed at its test suite.

Every anchor is matched against a flattened copy of the document -- lowercased,
every run of whitespace collapsed to one space -- because these documents wrap
at 100 columns and a multi-word anchor lands across a newline the moment a
paragraph is reflowed.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from manager_docs import ManagerLoop  # noqa: E402

#: The manager loop's whole prose -- SKILL.md plus every phase file it defers
#: to. The checks below ask "does the loop say X", never "does one file say
#: X"; pinned to the spine alone they would have gone quietly narrower than
#: their own subject the moment a paragraph moved into a phase file.
SKILL = ManagerLoop(REPO_ROOT)

OP = "git-worktrees"

#: The doctrine the liveness bullet has to keep, whatever tool it points at.
#: Each entry is (label, anchor). The labels are what a failure reports, so a
#: reader learns which idea went missing rather than which substring did.
LIVENESS_DOCTRINE = [
    ("default is live", "an agent is live until it has told you otherwise"),
    ("a surviving tree proves nothing", "surviving worktree is not evidence of a"),
    ("an empty tree proves nothing", "is not evidence of a dead one"),
    ("the commit is last", "the commit is the last thing"),
    ("an empty scan is no evidence", "it is no evidence"),
    ("only the notification ends a run", "the only thing that ends a run"),
    ("do not brief a second agent in", "never brief a second agent into that worktree"),
]


def _flatten(text):
    """Fold case and collapse every run of whitespace to one space."""
    return " ".join(text.lower().split())


def _skill():
    return SKILL.read_text(encoding="utf-8")


def _bullet(text, opener):
    """Return the one markdown bullet whose first line contains `opener`.

    Raises rather than returning "" for a missing bullet: an empty string would
    make every "must contain" assertion below fail with a message about prose
    when the real finding is that this reader stopped matching the file.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("- ") and opener in line.lower()]
    if len(starts) != 1:
        raise AssertionError(
            "expected exactly one bullet opening with %r, found %d -- "
            "the reader, not the prose, is what failed here" % (opener, len(starts))
        )
    start = starts[0]
    end = start + 1
    while end < len(lines) and not (lines[end].startswith("- ") or lines[end].startswith("#")):
        end += 1
    return "\n".join(lines[start:end])


def doctrine_gaps(bullet_text):
    """Labels of the liveness doctrine this text does not carry.

    A pure function over text so the retention guards can be pointed at a
    synthetic paragraph as well as at the real one.
    """
    folded = _flatten(bullet_text)
    return [label for label, anchor in LIVENESS_DOCTRINE if anchor not in folded]


# --------------------------------------------------------------------------
# Routing: the skill has to name the op, in the two places it asks the question
# --------------------------------------------------------------------------


def test_the_ops_table_carries_a_worktree_row():
    """The reads table is where a maintainer looks for the op for a question."""
    text = _skill()
    table = text.split("## Deciding what to build")[0]
    assert OP in table, (
        "the ops table names no op for worktree ownership, so a maintainer "
        "asking 'is an agent in this tree?' has nowhere to look but raw git"
    )


def test_the_removal_gate_names_the_op_before_the_removal():
    bullet = _bullet(_skill(), "delete merged worktrees")
    folded = _flatten(bullet)
    assert OP in folded, (
        "the removal bullet still reaches for raw git alone; it must gate the "
        "removal on the op that answers occupancy"
    )
    assert folded.index(OP) < folded.index("git worktree remove"), (
        "the op is named after the removal it is supposed to gate"
    )


def test_the_removal_gate_carries_the_squash_merge_caveat():
    """The branch bullet warns that ancestry cannot see a squash merge.

    The worktree bullet asks the same question about the same refs and until
    #145 said nothing, so a reader could reap on ancestry alone.
    """
    folded = _flatten(_bullet(_skill(), "delete merged worktrees"))
    assert "cannot see a squash merge" in folded, (
        "the worktree removal bullet does not carry the squash-merge blind spot, "
        "though the branch bullet beside it does and the same blind spot applies. "
        "The anchor is the whole clause on purpose: a bare 'squash' is satisfied "
        "by prose asserting the opposite"
    )


def test_the_exit_code_caveat_names_the_route_that_distinguishes():
    """`cannot tell` must not be reachable only as 'not zero'.

    Measured 2026-08-15 against supertool 0.44.0 by running both routes over the
    same paths: the preset script exits 2 for a path it cannot decide and 1 for
    an occupied one, while supertool returns 1 for both. That measurement is not
    reproduced here -- supertool is not vendored into this repo and a test that
    shelled out to whatever version is installed would report the runner's
    environment as a verdict on the prose. This asserts only that the skill
    carries the caveat, in the same bullet that makes the claim it qualifies.
    """
    folded = _flatten(_bullet(_skill(), "delete merged worktrees"))
    assert "cannot tell" in folded, "the third occupancy state is never named"
    assert "worktrees.py" in folded, (
        "the skill never names the route that distinguishes `cannot tell` from "
        "`occupied`, so a reader branching on supertool's exit code silently "
        "folds the two together"
    )


def test_the_skill_does_not_route_the_reader_into_the_refused_command():
    """Must-not-fire, and green before #145 as well as after.

    The old file never printed the literal command either -- it routed the
    reader there by describing the question and naming no op. So this holds
    ground rather than proving a fix, and it is grouped with the retention
    guards for that reason. Its must-fire pair is the test directly below.
    """
    folded = _flatten(_skill())
    assert "git worktree list" not in folded, (
        "the skill instructs a raw command supertool's guard refuses"
    )


def test_the_refused_command_check_can_actually_fire():
    """Positive control for the assertion above.

    Without this, a reader that stopped matching the document at all would make
    the must-not-fire case pass by finding nothing anywhere.
    """
    synthetic = "Some prose that says run `git worktree list` and read the paths."
    assert "git worktree list" in _flatten(synthetic)


# --------------------------------------------------------------------------
# Retention: naming a tool must not cost the paragraph its reason
# --------------------------------------------------------------------------


def test_the_liveness_bullet_keeps_every_piece_of_its_doctrine():
    gaps = doctrine_gaps(_bullet(_skill(), "an agent is live until"))
    assert gaps == [], (
        "the liveness bullet lost doctrine: %s. An op that reports occupancy "
        "implements part of this rule; it does not replace the reason for it."
        % ", ".join(gaps)
    )


def test_the_liveness_bullet_points_at_the_op_that_does_the_scan():
    folded = _flatten(_bullet(_skill(), "an agent is live until"))
    assert OP in folded, (
        "the liveness bullet still tells the reader to reason about ps/lsof by "
        "hand, without naming the op that runs that scan and reports what it saw"
    )


def test_an_idle_verdict_is_not_read_as_the_end_of_a_run():
    """The trap the whole edit exists to avoid.

    If the bullet names the op, it has to say that `idle` is a reading of the
    tree at one instant and not the task notification -- otherwise pointing at
    the op turns a three-state measurement into permission.
    """
    folded = _flatten(_bullet(_skill(), "an agent is live until"))
    assert "idle" in folded, "the bullet names the op but never its idle verdict"
    assert "the only thing that ends a run" in folded, (
        "an `idle` verdict sits in this bullet with nothing saying it is not "
        "the notification"
    )


@pytest.mark.parametrize(
    "paragraph, expected",
    [
        pytest.param(
            "- **An agent is live until it has told you otherwise.** A surviving "
            "worktree is not evidence of a live agent; an *empty* worktree is not "
            "evidence of a dead one, because the commit is the last thing an agent "
            "does. `git-worktrees` runs that scan, and an empty scan is not weak "
            "evidence of death, it is no evidence. A task notification is the only "
            "thing that ends a run. Until it arrives, never brief a second agent "
            "into that worktree.",
            [],
            id="doctrine-kept",
        ),
        pytest.param(
            "- **Check occupancy with `git-worktrees`** and reap the idle ones.",
            [label for label, _ in LIVENESS_DOCTRINE],
            id="doctrine-replaced-by-a-tool-name",
        ),
        pytest.param(
            "- **An agent is live until it has told you otherwise.** A surviving "
            "worktree is not evidence of a live agent; an *empty* worktree is not "
            "evidence of a dead one, because the commit is the last thing an agent "
            "does. `git-worktrees` reports `idle` when nothing holds the tree, and "
            "an empty scan is not weak evidence of death, it is no evidence. Until "
            "then, never brief a second agent into that worktree.",
            ["only the notification ends a run"],
            id="notification-clause-dropped",
        ),
    ],
)
def test_the_doctrine_check_fires_on_a_paragraph_that_lost_it(paragraph, expected):
    """Must-fire control for every retention guard in this file.

    The first case is a paragraph that kept the doctrine and must report
    nothing; the two after it each lost something and must report exactly what.
    Same fixture, both directions, so silence from the checker cannot be
    mistaken for a clean paragraph.
    """
    assert doctrine_gaps(paragraph) == expected
