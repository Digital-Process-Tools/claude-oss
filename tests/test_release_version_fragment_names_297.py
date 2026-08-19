"""A fragment name the assembler accepts, and a receipt that names what failed (#297).

Two defects, one file, and only the first one is what the issue was filed about.

  * `scripts/release_version.py` parsed `<issue>.<section>.md` and nothing else, so
    `1792.fixed.second-gate-verdict.md` -- a name `scripts/assemble_changelog.py`
    has always accepted, and which `changelog.d/README.md` in at least one managed
    repository documents -- landed in `unreadable` and stopped the release.

  * the reason line offered two causes, `a section outside the six` or `a
    compatibility line this rule does not recognise`, and **neither had fired**. A
    maintainer went looking for a malformed body in a file whose body was fine,
    then renamed a correct file and reported the agent that wrote it. That is the
    half with teeth: the receipt stated a cause the tool had not established.

The sweep for the class found a *second* unnamed cause already in the tree: a
fragment whose bytes cannot be read lands in the same bucket, and today's reason
line does not offer that either. So a single third state -- "filename did not
parse" -- would have fixed the instance and left the class. Every distinguishable
cause is named instead, and `test_every_unreadable_cause_names_itself_and_no_other`
is what stops a fifth one being folded silently into a fourth.

Every refusal below is paired with a proposal one mutation away in the same
fixture. An exit 3 out of a harness that never reached the script is
indistinguishable from a refusal.
"""

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Imported rather than `importorskip`ed: a missing module is a red collection
# error, which is what a missing module is. An `importorskip` would render this
# whole file as `1 skipped` -- a green run over a rule nobody wrote.
import release_version  # noqa: E402

PROPOSED = 0
COULD_NOT_DECIDE = 3


def _main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = release_version.main(argv)
    return code, buf.getvalue()


def _payload(argv):
    code, out = _main(list(argv) + ["--json"])
    assert out.strip(), "no JSON on stdout"
    return code, json.loads(out)


def _repo(tmp_path, name="repo"):
    root = tmp_path / name
    (root / "changelog.d").mkdir(parents=True)
    (root / ".oss.json").write_text(
        json.dumps({"changelog_dir": "changelog.d"}), encoding="utf-8"
    )
    return root


def _frag(root, name, body):
    (root / "changelog.d" / name).write_text(body, encoding="utf-8")


# ------------------------------------------------------------------ the reported bug


def test_a_slugged_fragment_name_is_read_and_the_number_is_proposed(tmp_path):
    """The issue, reproduced: the exact file name from #297, in this repository."""
    root = _repo(tmp_path)
    _frag(root, "1792.fixed.second-gate-verdict.md", "- a second verdict (#1792).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED, payload
    assert payload["unreadable"] == [], payload["unreadable"]
    assert payload["sections"] == {"fixed": 1}, payload["sections"]
    assert payload["version"] == "0.4.1", payload


def test_the_slug_does_not_make_every_name_readable(tmp_path):
    """The must-fire beside it. Without this, the assertion above is satisfied by a
    parse that accepts anything ending in `.md`."""
    root = _repo(tmp_path)
    _frag(root, "not-a-fragment.md", "- something.\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE, payload
    assert payload["unreadable"] == ["not-a-fragment.md"], payload
    assert payload["version"] is None, payload


def test_two_slugged_fragments_for_one_issue_are_two_fragments(tmp_path):
    """What the slug is *for*: one issue filing two entries in one section without
    the two pull requests colliding on a path."""
    root = _repo(tmp_path)
    _frag(root, "1792.fixed.first.md", "- one (#1792).\n")
    _frag(root, "1792.fixed.second.md", "- two (#1792).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED, payload
    assert payload["fragments"] == 2, payload
    assert payload["sections"] == {"fixed": 2}, payload


# ------------------------------------------------------- the half that misreported


def test_the_reason_does_not_state_a_cause_that_did_not_fire(tmp_path):
    """#297's real cost. The file below has a section outside the six and no
    compatibility line at all, so `a compatibility line this rule does not
    recognise` is a sentence about something that did not happen."""
    root = _repo(tmp_path)
    _frag(root, "2.improved.md", "- something (#2).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE, payload
    reason = payload["reason"]
    assert "section outside the six" in reason, reason
    assert "compatibility line" not in reason, reason


# The four causes that reach `unreadable`, each with the fixture that produces it
# and the phrase the reason must carry. `read` is a directory wearing a fragment
# name: it needs no permission bit, so it behaves the same on every platform --
# the name selects it and the read refuses it.
CAUSES = [
    (
        "name",
        lambda root: _frag(root, "no-issue.fixed.md", "- something (#1).\n"),
        "filename",
    ),
    (
        "section",
        lambda root: _frag(root, "2.improved.md", "- something (#2).\n"),
        "section outside the six",
    ),
    (
        "read",
        lambda root: (root / "changelog.d" / "3.added.md").mkdir(),
        "could not be read",
    ),
    (
        "compatibility",
        lambda root: _frag(
            root,
            "4.removed.md",
            "- a key is gone (#4).\n- Compatibility: maybe - who knows.\n",
        ),
        "compatibility line",
    ),
]

CAUSE_IDS = [case[0] for case in CAUSES]
CAUSE_PHRASES = [case[2] for case in CAUSES]


@pytest.mark.parametrize("label, arrange, phrase", CAUSES, ids=CAUSE_IDS)
def test_every_unreadable_cause_names_itself_and_no_other(tmp_path, label, arrange, phrase):
    """One cause per fixture, and the reason names that one and none of the other
    three. Asserting only that the right phrase is present would pass against a
    reason line that recited all four every time, which is the defect #297 is."""
    root = _repo(tmp_path, name=label)
    arrange(root)

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE, payload
    reason = payload["reason"]
    assert phrase in reason, (label, reason)
    for other in CAUSE_PHRASES:
        if other != phrase:
            assert other not in reason, (label, other, reason)


@pytest.mark.parametrize("label, arrange, phrase", CAUSES, ids=CAUSE_IDS)
def test_the_receipt_names_the_cause_beside_the_file_it_applies_to(
    tmp_path, label, arrange, phrase
):
    """With two unreadable fragments for two different reasons, a reason line alone
    cannot say which file had which. The row carries the cause per name."""
    root = _repo(tmp_path, name=label)
    arrange(root)

    code, out = _main(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE, out
    row = [line for line in out.splitlines() if line.startswith("unreadable")]
    assert len(row) == 1, out
    assert phrase in row[0], row[0]


def test_two_causes_at_once_are_both_named_and_attributed(tmp_path):
    """The composition. Two files, two different causes, one receipt."""
    root = _repo(tmp_path)
    _frag(root, "2.improved.md", "- something (#2).\n")
    _frag(root, "4.removed.md", "- gone (#4).\n- Compatibility: maybe - who knows.\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE, payload
    assert payload["unreadable"] == ["2.improved.md", "4.removed.md"], payload
    causes = dict(payload["unreadable_causes"])
    assert "section" in causes["2.improved.md"], causes
    assert "compatibility" in causes["4.removed.md"], causes
    assert "section outside the six" in payload["reason"], payload["reason"]
    assert "compatibility line" in payload["reason"], payload["reason"]


def test_a_clean_directory_carries_no_causes(tmp_path):
    """The must-fire control for the two above: nothing unreadable, nothing named."""
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED, payload
    assert payload["unreadable"] == [], payload
    assert payload["unreadable_causes"] == [], payload


# ------------------------------------------------- the grammar is not invented here


NAME_CORPUS = [
    "1.fixed.md",
    "906.added.md",
    "878.fixed.second-entry.md",
    "1792.fixed.second-gate-verdict.md",
    "12.changed.a.b.md",
    "12.removed.SLUG_1.md",
    "2.improved.md",
    "no-issue.fixed.md",
    "fixed.md",
    "1.fixed.txt",
    "1.fixed.-leading-dash.md",
    "1.FIXED.md",
    "1..md",
    "1.fixed.md.md",
    ".fixed.md",
]


def test_the_version_rule_and_the_assembler_agree_on_which_names_are_fragments():
    """A transcription is a claim about something outside this module, so it is
    measured against that authority rather than asserted in a comment.

    `scripts/assemble_changelog.py` is the gate a fragment must already pass to be
    folded into `CHANGELOG.md`. A name it accepts and the version rule refuses stops
    a release over a correctly-named file, which is #297; a name it refuses and the
    version rule accepts is the same divergence pointing the other way, and would
    have the release rule proposing a number for an entry that never ships.
    """
    try:
        import assemble_changelog
    except Exception as exc:  # pragma: no cover - depends on the environment
        pytest.skip(
            "scripts/assemble_changelog.py did not import ({0}: {1}), so whether the "
            "two fragment-name grammars agree went UNMEASURED -- not measured and "
            "found to agree".format(type(exc).__name__, exc)
        )

    disagreements = []
    for name in NAME_CORPUS:
        try:
            assemble_changelog.parse_fragment_name(name)
        except assemble_changelog.BadFragment:
            theirs = False
        else:
            theirs = True
        ours = release_version.fragment_name(name) is not None
        if ours != theirs:
            disagreements.append((name, "assembler" if theirs else "version rule"))

    assert not disagreements, (
        "the two fragment-name grammars disagree, and only one of them gates a "
        "release. (name, the one that accepts it): {0}".format(disagreements)
    )


def test_the_agreement_check_can_fail():
    """The positive control. Without it the sweep above passes against a corpus
    every grammar accepts, or against one nothing in it reaches."""
    accepted = [n for n in NAME_CORPUS if release_version.fragment_name(n) is not None]
    refused = [n for n in NAME_CORPUS if release_version.fragment_name(n) is None]
    assert accepted, NAME_CORPUS
    assert refused, NAME_CORPUS
