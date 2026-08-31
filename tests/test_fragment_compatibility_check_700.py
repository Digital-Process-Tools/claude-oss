"""#700: the pull-request check never read a fragment's `Compatibility` line.

Observed on a managed repository, not inferred. A fragment carrying
`- Compatibility: compatible/additive - <reason>` -- a value neither half of the
grammar recognises -- rode a pull request with seventeen green required legs,
including the scaffolded `fragment` leg, and merged. It was caught at release time
by `release_version.py`, which correctly refused to name a version and said which
file and which cause. That refusal is right and it is doing the job of a check that
should have fired, for free, on the pull request that introduced the fragment.

The two halves disagreed about what a valid fragment is, and the disagreement
surfaced at the most expensive moment available. It also lands in this repository's
own defect class one layer up: the pull-request check returned `ok` for a fragment
it never examined on this axis, and `ok` from a check that did not look is
indistinguishable from `ok` from a check that did.

## Three states, and the third one is why this is not a one-line regex

- **present and it reads** -- `breaking` or `compatible`, with a reason. Passes.
- **present and it does not read** -- an unrecognised word, a bare verdict with no
  reason, or both verdicts at once. Refused, naming the file and the value.
- **absent** -- legitimate on most sections, where a fragment that says nothing is
  read as compatible, and a finding on `removed`, where whether the removal breaks
  anything is the question the release number turns on.

A check that collapsed the last two would either block every fragment that omits an
optional line, or wave through the one that got it wrong.

## Why the grammar is transcribed rather than imported

`assemble_changelog.py` is vendored standalone into `.oss/` in every managed
repository, without `release_version.py` beside it, so it cannot import the module
the grammar was written in -- and having the release gate import the assembler
instead would put a 2,500-line module with guarded optional imports underneath the
one script whose refusal must never be a traceback. So the grammar is transcribed,
exactly as `release_version.FRAGMENT_NAME` is transcribed from the assembler's
`_NAME_RE` for the same vendoring reason (#297), and the two are **measured against
each other over a corpus** here rather than asserted to agree in a comment.

Python 3.9 compatible.
"""

import contextlib
import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Imported rather than `importorskip`ed: a missing module is a red collection error,
# which is what a missing module is. An `importorskip` renders the whole file as
# `1 skipped` -- a green run over a rule nobody executed.
import assemble_changelog  # noqa: E402
import release_version  # noqa: E402

OK = assemble_changelog.OK
SKIPPED = assemble_changelog.SKIPPED
REFUSED = assemble_changelog.REFUSED


def _check(root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = assemble_changelog.check(root / "changelog.d")
    return code, buf.getvalue()


def _repo(tmp_path, name="repo"):
    root = tmp_path / name
    (root / "changelog.d").mkdir(parents=True)
    return root


def _frag(root, name, body):
    (root / "changelog.d" / name).write_text(body, encoding="utf-8")


# ------------------------------------------------------------------ the reported bug


def test_an_unrecognised_compatibility_value_is_refused_on_the_pull_request(tmp_path):
    """The fragment from #700, verbatim. It merged."""
    root = _repo(tmp_path)
    _frag(
        root,
        "263.fixed.md",
        "- a change (#263).\n"
        "- Compatibility: compatible/additive - nothing downstream moves.\n",
    )

    code, out = _check(root)

    assert code == REFUSED, out
    assert "263.fixed.md" in out, out
    assert "compatible/additive" in out, out


def test_a_declared_and_recognised_value_still_passes(tmp_path):
    """The must-fire control. Without it, the assertion above is satisfied by a check
    that refuses every fragment carrying the word `Compatibility` at all -- which
    would block the exact declarations the format exists to collect."""
    root = _repo(tmp_path, "recognised")
    _frag(
        root,
        "1.removed.md",
        "- a key is gone (#1).\n- Compatibility: breaking - callers reading it get None.\n",
    )

    code, out = _check(root)

    assert code == OK, out
    assert "1.removed.md" in out, out


def test_a_bare_verdict_with_no_reason_is_refused(tmp_path):
    """A bare flag is the same unsourced verdict one field further along, and the
    sentence is the part worth having. Both READMEs say so; nothing enforced it at
    pull-request time."""
    root = _repo(tmp_path, "bare")
    _frag(root, "2.removed.md", "- a key is gone (#2).\n- Compatibility: breaking\n")

    code, out = _check(root)

    assert code == REFUSED, out
    assert "2.removed.md" in out, out


def test_declaring_both_verdicts_at_once_is_refused(tmp_path):
    """Two bullets, two answers, and nothing downstream can pick one. Reading the
    first would make the fragment's meaning depend on bullet order."""
    root = _repo(tmp_path, "both")
    _frag(
        root,
        "3.removed.md",
        "- a key is gone (#3).\n"
        "- Compatibility: breaking - callers reading it get None.\n"
        "- Compatibility: compatible - nobody read it.\n",
    )

    code, out = _check(root)

    assert code == REFUSED, out
    assert "3.removed.md" in out, out


# --------------------------------------------------------- the state that must pass


def test_a_fragment_that_omits_the_line_passes_where_it_is_optional(tmp_path):
    """Absent is not malformed. Every section but `removed` may say nothing and is
    read as compatible; a check that refused here would block the overwhelming
    majority of fragments in every repository this ships into."""
    root = _repo(tmp_path, "absent")
    _frag(root, "4.fixed.md", "- a fix (#4).\n")

    code, out = _check(root)

    assert code == OK, out


def test_a_removed_fragment_that_omits_the_line_is_refused(tmp_path):
    """The other half of the same state, and the one that stops the release today.
    Whether a removal breaks anything is the question the version number turns on, so
    a `removed` fragment that declares nothing is a finding rather than a default."""
    root = _repo(tmp_path, "undeclared")
    _frag(root, "5.removed.md", "- a key is gone (#5).\n")

    code, out = _check(root)

    assert code == REFUSED, out
    assert "5.removed.md" in out, out


# ------------------------------------------------- the receipt states what it read


def test_the_ok_receipt_says_the_compatibility_line_was_read(tmp_path):
    """A check that ran and did not say it ran is indistinguishable from one that did
    not run. `check`'s `ok` line already enumerates what it established -- names
    parse, each body names its own issue, markdown-it-py saw no heading -- and a new
    axis that is not in that sentence is an axis the reader cannot know was covered.
    """
    root = _repo(tmp_path, "receipt")
    _frag(
        root,
        "6.removed.md",
        "- a key is gone (#6).\n- Compatibility: compatible - nobody read it.\n",
    )

    code, out = _check(root)

    assert code == OK, out
    assert "compatibility" in out.lower(), out


def test_a_definite_refusal_is_not_lost_behind_a_parser_that_could_not_look(
    tmp_path, monkeypatch
):
    """The compatibility line needs no Markdown parser, so a run whose parser is
    missing still has a definite answer about it. Reporting `skipped` there would
    trade a finding the run actually made for the absence of one it could not --
    exactly the ordering `collect` already applies to the self-reference finding.
    """
    root = _repo(tmp_path, "noparser")
    _frag(root, "7.removed.md", "- gone (#7).\n- Compatibility: maybe - who knows.\n")

    def _no_parser(name, text):
        raise assemble_changelog.CannotValidate("markdown-it-py is not installed")

    monkeypatch.setattr(assemble_changelog, "scan_fragment_body", _no_parser)

    code, out = _check(root)

    assert code == REFUSED, out
    assert "7.removed.md" in out, out


def test_the_parser_absence_still_reaches_skipped_when_nothing_definite_fired(
    tmp_path, monkeypatch
):
    """The must-fire control beside it: a fragment with nothing wrong that no parser
    could read must still report `skipped` and claim nothing. Without this, the
    assertion above is satisfied by a check that answers `refused` to everything once
    the parser is gone."""
    root = _repo(tmp_path, "noparser-clean")
    _frag(root, "8.fixed.md", "- a fix (#8).\n")

    def _no_parser(name, text):
        raise assemble_changelog.CannotValidate("markdown-it-py is not installed")

    monkeypatch.setattr(assemble_changelog, "scan_fragment_body", _no_parser)

    code, out = _check(root)

    assert code == SKIPPED, out


# ------------------------------------------------- the grammar is not invented here

#: Bodies that exercise every arm of the grammar, in both directions. The pairs the
#: two rules must agree on are the point; a corpus of only-valid or only-invalid
#: bodies would pass against either rule answering one word to everything.
COMPAT_CORPUS = [
    "- a change (#1).\n",
    "- a change (#1).\n- Compatibility: breaking - callers get None.\n",
    "- a change (#1).\n- Compatibility: compatible - nobody read it.\n",
    "- a change (#1).\n- Compatibility: BREAKING - shouting is still a verdict.\n",
    "- a change (#1).\n-   Compatibility  :  compatible  -  spaced out.\n",
    "- a change (#1).\n- Compatibility: compatible/additive - a value nothing knows.\n",
    "- a change (#1).\n- Compatibility: maybe - who knows.\n",
    "- a change (#1).\n- Compatibility: breaking\n",
    "- a change (#1).\n- Compatibility: compatible -\n",
    "- a change (#1).\n- Compatibility:\n",
    "- a change (#1).\n- Compatibility: breaking - one.\n- Compatibility: compatible - two.\n",
    "- a change (#1).\n- Compatibility: breaking - one.\n- Compatibility: breaking - two.\n",
    "- a change (#1).\n- compatibility: compatible — an em dash separator.\n",
    "- a change (#1).\n- Compatibility: compatible: a colon separator.\n",
    "- Compatibility is discussed in the prose (#1), not declared.\n",
]


@pytest.mark.parametrize("body", COMPAT_CORPUS, ids=range(len(COMPAT_CORPUS)))
@pytest.mark.parametrize("section", release_version.SECTIONS)
def test_the_two_rules_agree_on_whether_a_fragment_declares_readably(section, body):
    """A transcription is a claim about something outside the module that holds it,
    so it is measured against that authority rather than asserted in a comment.

    A body the pull-request check accepts and the release gate refuses is #700 with
    the sign flipped -- the maintainer is stopped mid-release by a fragment that
    passed every leg. A body the pull-request check refuses and the release gate
    accepts blocks a contributor over a fragment that would have shipped fine.
    """
    verdict, problem = release_version.compatibility(body)
    gate_finding = problem is not None or (
        verdict is None and section in release_version.MUST_DECLARE
    )
    check_finding = (
        assemble_changelog.compatibility_finding("1.{0}.md".format(section), section, body)
        is not None
    )

    assert check_finding == gate_finding, (section, body, verdict, problem)


def test_the_corpus_exercises_both_answers():
    """The control on the parametrised test above: a corpus every arm of which lands
    on the same side proves the two rules agree about nothing in particular."""
    answers = {
        assemble_changelog.compatibility_finding("1.removed.md", "removed", body) is None
        for body in COMPAT_CORPUS
    }

    assert answers == {True, False}, answers


def test_the_two_rules_name_the_same_verdicts_and_the_same_required_sections():
    """The constants, held against each other directly. The corpus above measures
    behaviour over the bodies somebody thought to write down; this catches a verdict
    or a required section added on one side and not the other, which no corpus
    written before that change can see."""
    assert assemble_changelog.VERDICTS == release_version.VERDICTS
    assert assemble_changelog.MUST_DECLARE == release_version.MUST_DECLARE
