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

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDITOR = REPO_ROOT / "agents" / "auditor.md"


def _raise(error):
    raise error


def _markdown_under(directory):
    """Every `.md` below `directory`, walked so that an unreadable subtree raises.

    Not `rglob` and not `glob`. Both swallow the `PermissionError` raised while
    walking and yield nothing for the subtree, so a directory this process cannot
    enter returns the same empty list as a directory with nothing in it -- and the
    ambient-vocabulary check below reads an empty list as "no sibling document uses
    these words". A test that could not read its inputs must fail, not pass, so
    `os.walk` is given an `onerror` that re-raises the exception it was handed
    rather than a second question to the filesystem about why the first failed.
    """
    found = []
    for parent, _dirs, names in os.walk(directory, onerror=_raise):
        found.extend(Path(parent) / name for name in names if name.endswith(".md"))
    return found


OTHER_EXECUTABLE_PROSE = sorted(
    p
    for p in (
        [p for p in _markdown_under(REPO_ROOT / "skills") if p.name == "SKILL.md"]
        + _markdown_under(REPO_ROOT / "agents")
        + _markdown_under(REPO_ROOT / "commands")
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


def _ambient_hits(text):
    """Every anchor phrase this document already carries."""
    folded = _flatten(text)
    return sorted(
        anchor
        for _, anchors in EVIDENCE_CONTRACTS
        for anchor in anchors
        if anchor in folded
    )


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
    """The must-fire half: these anchors are not satisfied by what was already there.

    This proves lexical novelty and nothing stronger, which is worth stating
    because the temptation is to read it as proof that the pre-change file did not
    already carry the *requirement*. It cannot show that -- the anchors are
    substrings of the sentences the change wrote, so their absence beforehand is
    true by construction. What it does rule out is the failure this repo has
    shipped five times: an anchor satisfied by prose already on disk, which
    constrains nothing and reports green forever.

    The argument that the third state was not the gap rests on the transcript,
    not on this test.
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


def test_the_sibling_documents_were_actually_found():
    """The positive control for the negative assertion below.

    `assert not ambient` passes just as readily over a list nobody built. The walk
    has to have found the documents whose absence of these phrases is the claim.
    """
    names = {p.name for p in OTHER_EXECUTABLE_PROSE}
    assert "SKILL.md" in names, "the manager skill was not found"
    assert "developer.md" in names, "agents/developer.md was not found"
    assert AUDITOR not in OTHER_EXECUTABLE_PROSE, (
        "the auditor is in its own comparison set, which makes every anchor look "
        "ambient the moment the change lands"
    )


def test_the_ambient_check_fires_on_a_document_that_does_carry_a_phrase():
    """The must-fire half. `_ambient_hits` reporting nothing has to mean nothing
    was there, not that the checker never matches.
    """
    plausible = "The requirement stops at comparison claims: the same defect with a longer receipt."
    assert _ambient_hits(plausible) == ["longer receipt"], repr(
        _ambient_hits(plausible)
    )


def test_these_anchors_are_not_ambient_house_vocabulary():
    """An anchor already present in the sibling documents would pass on an auditor
    nobody constrained. Each phrase has to be new here, not borrowed from prose
    that ships elsewhere in the plugin.
    """
    ambient = {}
    for path in OTHER_EXECUTABLE_PROSE:
        hits = _ambient_hits(path.read_text(encoding="utf-8"))
        if hits:
            ambient[path.relative_to(REPO_ROOT).as_posix()] = hits
    assert not ambient, (
        "these anchors already ship in other executable prose, so the checks above "
        "would pass on an agents/auditor.md that never stated the contract: "
        "{}".format(ambient)
    )


def test_the_walk_raises_instead_of_dropping_an_unreadable_subtree(tmp_path):
    """The control for the only reason `_markdown_under` exists rather than `rglob`.

    Both halves are here. The readable tree must be found -- otherwise "raises on
    an unreadable one" is satisfied by a walk that finds nothing ever -- and the
    unreadable one must reach the caller as an exception rather than as a shorter
    list, which is the state `rglob` produces and cannot be talked out of.

    The deny is measured, not assumed. Root ignores the mode bit, some filesystems
    ignore it, and Windows' `os.chmod` on a directory toggles a read-only attribute
    that does not stop a listing -- so the exact operation is attempted first, and
    a platform where it did not take gets a skip naming what went untested rather
    than an assertion about an error code from a table. The skip is deliberately
    outside the `pytest.raises` block: pytest's outcome exceptions derive from
    `BaseException`, so a skip raised inside one sails past it and the enclosing
    test reports green over an assertion that never ran.
    """
    root = tmp_path / "prose"
    locked = root / "locked"
    locked.mkdir(parents=True)
    (root / "visible.md").write_text("y", encoding="utf-8")
    (locked / "hidden.md").write_text("x", encoding="utf-8")

    assert sorted(p.name for p in _markdown_under(root)) == [
        "hidden.md",
        "visible.md",
    ], (
        "the walk does not find a readable tree, so raising on an unreadable one "
        "would prove nothing"
    )

    os.chmod(locked, 0o000)
    try:
        try:
            os.listdir(locked)
        except OSError:
            denied = True
        else:
            denied = False

        if not denied:
            pytest.skip(
                "chmod 000 did not stop a listing of {} on this platform, so what "
                "went untested is whether _markdown_under surfaces an unreadable "
                "subtree instead of silently returning the shorter list".format(locked)
            )

        with pytest.raises(OSError):
            _markdown_under(root)
    finally:
        os.chmod(locked, 0o700)
