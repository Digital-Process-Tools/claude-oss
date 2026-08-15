"""A verdict in agents/auditor.md must carry the provenance of its sentences (#165).

Companion to test_content_invariants.py, which holds the auditor's class list and
verdict vocabulary. These are narrower: what a *verdict* has to carry before it is
allowed to say `clean`.

Filed from a real transcript. An `oss:auditor` spawn graded two classes clean on
sentences asserting that two blocks of text were the same -- that a brief's copy of
a referenced section "matches" the file's, and that a test fixture "is the actual
pre-fix text". The only commands it had run were an `ls -l` on the referenced path,
which returns a size and an mtime and never a byte of content, and a grep for two
phrases. Neither could have produced the comparison the verdict asserted, and a
verdict that fabricated its comparison renders exactly like one that performed it.

The third state was not the gap, which is why these anchors are not about
vocabulary. `could not check` was already in the file, already required, already
declared never to render as clean -- and the platform-band paragraph already said
to use it when the referenced section did not arrive. The auditor had somewhere
honest to put "I could not compare these" and asserted the comparison instead. So
the guard is on provenance, and the positive control is the pre-change third-state
block itself, which must fail every one of these anchors.

Anchors are matched against a flattened copy -- lowercased, every run of whitespace
collapsed to one space -- because these documents wrap at 100 columns and a
multi-word anchor lands across a newline the moment a paragraph is reflowed. A
checker whose finding is about its own reading, dressed as a finding about the
file, is the defect this plugin is named after pointed at the test suite.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDITOR = REPO_ROOT / "agents" / "auditor.md"

OTHER_EXECUTABLE_PROSE = sorted(
    p
    for p in (
        list((REPO_ROOT / "skills").rglob("SKILL.md"))
        + list((REPO_ROOT / "agents").glob("*.md"))
        + list((REPO_ROOT / "commands").glob("*.md"))
    )
    if p != AUDITOR
)


def _flatten(text):
    """Fold case and collapse every run of whitespace to one space."""
    return " ".join(text.lower().split())


# id -> substrings that must all be present for the contract to be legible.
EVIDENCE_CONTRACTS = [
    ("verdict-sentences-carry-provenance", ("provenance of its own sentences",)),
    (
        "a-comparison-claim-carries-its-command",
        ("asserts a comparison", "the command that produced it"),
    ),
    ("an-unperformed-comparison-is-could-not-check", ("you did not compare them",)),
    ("existence-is-not-content", ("existence is not content",)),
    ("the-requirement-stops-at-comparison-claims", ("longer receipt",)),
    ("the-auditor-did-not-write-the-diff", ("you did not write the diff",)),
    (
        "an-existence-check-is-not-a-read-of-the-referenced-section",
        ("confirming the path exists is not reading it",),
    ),
]

ALL_CONTRACTS = {name for name, _ in EVIDENCE_CONTRACTS}


def _evidence_contracts_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in EVIDENCE_CONTRACTS
        if not all(anchor in folded for anchor in anchors)
    }


def test_auditor_agent_exists():
    """Without the file every check below fails for the wrong reason, and a suite
    that cannot find its subject must say which of the two it is.
    """
    assert AUDITOR.is_file(), "agents/auditor.md is missing"


def test_the_auditor_states_what_a_verdict_must_carry():
    """The must-not-fire half."""
    unmet = _evidence_contracts_unmet(AUDITOR.read_text(encoding="utf-8"))
    assert not unmet, (
        "agents/auditor.md no longer states what a verdict is required to carry, so "
        "a class can be graded clean on a comparison nobody performed: "
        + repr(sorted(unmet))
    )


# The pre-change Report format block, verbatim. This is the text that was on disk
# when the reported verdict was produced: three verdicts, `could not check` named
# and required, and the rule that it never renders as clean. Every anchor above
# must report unmet against it, or these checks are satisfied by vocabulary that
# was already there and say nothing about whether a verdict carries evidence.
THE_THIRD_STATE_ALONE = """
For each class, exactly one of three verdicts:

- **`clean`** -- you looked at the whole class across the whole diff and found nothing.
- **`finding`** -- file, line, what a caller sees, the one fact that would settle it, and **the
  ranking row** (or `unranked` / `could not rank`). One line each. Platform findings additionally
  carry their coverage grade.
- **`could not check`** -- you could not look, or could only look at part of it. Name the reason and
  the part: an unreadable file, a diff you could not resolve, a referenced section that never
  arrived, a matrix you could not parse.

`could not check` is a required word and it **never renders as clean**. If nothing in the diff
belonged to a class, that is `clean`; if you did not get to it, that is `could not check`. An
auditor that cannot say it failed to look is the defect it exists to find.
"""


def test_the_contract_fires_on_the_third_state_vocabulary_alone():
    """The must-fire half, and the argument the change rests on.

    If any anchor passed against this block, the fix would be a restatement of
    prose the auditor already had in front of it while it produced the verdict
    this issue was filed about.
    """
    unmet = _evidence_contracts_unmet(THE_THIRD_STATE_ALONE)
    assert unmet == ALL_CONTRACTS, (
        "these anchors are satisfied by the third-state vocabulary that was "
        "already on disk, so they do not constrain anything new. Not firing: "
        + repr(sorted(ALL_CONTRACTS - unmet))
    )


# The pre-change platform-band paragraph, verbatim. It already routed a missing
# section to `could not check`; what it never said was that looking up whether the
# path exists is not the same as reading what is at it. The auditor ran `ls -l`,
# found the file, and reported the section as having reached it.
THE_PLATFORM_PARAGRAPH_AS_IT_STOOD = """
**The recurring shapes are enumerated once, in `${CLAUDE_PLUGIN_ROOT}/agents/developer.md`
under "Cross-platform is not your machine", and again in the manager skill.** Read that section, or
work from it if your brief carried it verbatim. Do not reconstruct it from memory and do not restate
it in your report: a third copy of that list is itself the drift defect this loop exists to file. If
neither the file nor the brief reached you, report the whole platform band as `could not check`,
naming which of the two was missing.
"""


def test_the_referenced_section_contract_fires_on_the_paragraph_as_it_stood():
    """The narrow must-fire control the broad one would not have caught.

    "Read that section, or work from it if your brief carried it verbatim" is
    satisfied, to an agent reading it, by having established that the section is
    there. Deleting only the new sentence must stay visible.
    """
    unmet = _evidence_contracts_unmet(THE_PLATFORM_PARAGRAPH_AS_IT_STOOD)
    assert "an-existence-check-is-not-a-read-of-the-referenced-section" in unmet, (
        "the referenced-section anchor is satisfied by the paragraph that was "
        "already there, so it says nothing about whether an `ls` counts as a read"
    )


def test_these_anchors_are_not_ambient_house_vocabulary():
    """An anchor already present in the sibling documents would pass on an auditor
    nobody constrained. Each phrase has to be new here, not borrowed from prose
    that ships elsewhere in the plugin.
    """
    ambient = {}
    for path in OTHER_EXECUTABLE_PROSE:
        folded = _flatten(path.read_text(encoding="utf-8"))
        hits = sorted(
            anchor
            for _, anchors in EVIDENCE_CONTRACTS
            for anchor in anchors
            if anchor in folded
        )
        if hits:
            ambient[str(path.relative_to(REPO_ROOT))] = hits
    assert not ambient, (
        "these anchors already ship in other executable prose, so the checks above "
        "would pass on an agents/auditor.md that never stated the contract: "
        "{}".format(ambient)
    )

