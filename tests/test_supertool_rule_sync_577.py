"""The supertool rule body exists twice: the tracked

`.claude/jit-context/tools/01-oss/supertool-required.md`, which this repository's own
sessions read, and `TOOLS_SUPERTOOL` in `scripts/oss_rules.py`, which is what gets
*written into every scaffolded repository*. Nothing used to compare them (#577).
The issue that reported this gap cited `tests/test_content_invariants.py`'s #250
check as covering the pair narrowly; it does not cover it at all -- that check is
about a different pair entirely (`agents/developer.md` and `skills/manager/SKILL.md`)
and never mentions either file here (`grep -n TOOLS_SUPERTOOL tests/test_content_invariants.py`
and `grep -n supertool-required tests/test_content_invariants.py` both return nothing).
So this pair had zero coverage,
not narrow coverage.

#570 is the demonstration this issue was filed over: the `requires:` paragraph went
stale in both copies at once and was corrected in both by hand, which only worked
because one lane happened to hold both files.

The two directions are not symmetric. A stale `.md` here is a rule this repository's own
sessions read. A stale `TOOLS_SUPERTOOL` is a rule written into somebody else's
repository, where nobody here will ever see it.

**#888: the pair grew to three (`supertool-required.md`, `merge-gate.md`,
`pr-create-gate.md`) and this file kept comparing only the first one.** The other two
`TOOLS_*` constants (`TOOLS_MERGE_GATE`, `TOOLS_PR_CREATE_GATE`, added by #859/#861) had
zero coverage of their own -- same gap #577 closed for the supertool pair, reopened one
file over, because closing it here meant hand-adding a test function per new tools rule
and nobody did.

So this no longer hardcodes a list of pairs. `oss_rules.RULES["tools"]` is the single
dict `install()` and `scaffold` both render from -- filename -> body constant -- so it is
read here too, and every entry in it is compared against the committed `.md` file of the
same name under `.claude/jit-context/tools/01-oss/`. A fourth `tools` rule added to that
dict later is covered the moment it is added, with no second edit to this file: the
extension this issue is about is now structural rather than a habit to remember.

Deriving one side's *content* from the other -- reading `TOOLS_SUPERTOOL` off the `.md`
file at import time, or generating the `.md` file from the constant -- was weighed again
here, the same trade #577 weighed for the original single pair, and declined again, for
the same reason plus one new one:  the two sides are populated by different code paths
(the `.md` is a committed file edited in place when the rule changes; the constant is
what `install()` writes into every scaffolded repository) and serve different audiences,
so collapsing them into one either makes `scripts/oss_rules.py` read a repo-relative file
at import time -- a bigger blast radius now that it is three rules doing it, not one --
or makes the committed rule layer generated from Python rather than hand-edited, which is
a change to how the layer is authored that this issue was not asked to make. A comparison
test costs one file and answers the same question three pairs run.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402

RULE_LAYER_DIR = REPO_ROOT / ".claude" / "jit-context" / "tools" / "01-oss"


def _normalize(text):
    """Line-ending and trailing-whitespace normalisation only, never a content
    transform. CI runs Windows legs where a checkout can arrive with CRLF, so the two
    copies have to agree in substance rather than in which line-ending convention this
    particular checkout happened to use.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


def _bodies_match(a, b):
    return _normalize(a) == _normalize(b)


# --- the invariant itself, derived from the same dict install() renders from ---------

_TOOLS_PAIRS = sorted(oss_rules.RULES["tools"].items())


@pytest.mark.parametrize("filename, py_body", _TOOLS_PAIRS, ids=[name for name, _ in _TOOLS_PAIRS])
def test_tools_rule_matches_its_tracked_md_body(filename, py_body):
    """Every `tools` rule constant must say the same thing as its committed `.md`.

    Frontmatter included: measured against the repo at the moment this test was
    written, every pair was byte-identical including frontmatter, so there is no
    established reason for a `TOOLS_*` constant to carry a different `title:`/`match:`/
    etc. than the tracked `.md` -- if that ever becomes intentional, this test is the
    place to carve out the exception, with the reason recorded here.
    """
    md_path = RULE_LAYER_DIR / filename
    assert md_path.is_file(), (
        "oss_rules.RULES['tools'] declares {!r} but no such file is committed under "
        "{} -- a rule constant with nothing on disk to compare against".format(
            filename, RULE_LAYER_DIR
        )
    )
    md_body = md_path.read_text(encoding="utf-8")
    assert _bodies_match(md_body, py_body), (
        "scripts/oss_rules.py's RULES['tools'][{!r}] and {}/{} have diverged -- "
        "the constant is what gets written into every scaffolded repository, so a "
        "drift here ships a stale rule nobody in this repository will ever see "
        "(#577, #888)".format(filename, RULE_LAYER_DIR, filename)
    )


def test_every_committed_tools_md_is_represented_in_the_dict():
    """The other direction: a committed `.md` with no entry in `RULES["tools"]` is
    compared against nothing above, because the loop only ever walks the dict's own
    keys. `00-index.tsv` is not a rule body and is excluded by extension.
    """
    on_disk = {p.name for p in RULE_LAYER_DIR.glob("*.md")}
    declared = set(oss_rules.RULES["tools"])
    assert on_disk == declared, (
        "mismatch between the committed rule files and oss_rules.RULES['tools']: "
        "on disk but not declared: {} -- declared but not on disk: {}".format(
            sorted(on_disk - declared), sorted(declared - on_disk)
        )
    )


def test_the_tools_dict_has_more_than_one_entry():
    """A positive control on the parametrize source itself: if `RULES["tools"]` ever
    shrank to one entry, the loop above would still pass and look identical to a
    healthy three-or-more-entry run -- this is what tells the two apart.
    """
    assert len(oss_rules.RULES["tools"]) >= 3, sorted(oss_rules.RULES["tools"])


def test_every_tools_md_file_is_readable_and_substantial():
    """Half of the positive control: a sameness assertion also passes when both
    files are empty or unreadable, so this pins that every file compared above is
    neither -- a genuine rule body, not a placeholder.

    #757 trimmed `supertool-required.md` to under 1 KB on purpose -- its whole body
    re-injects on every refused call -- so this floor is deliberately low; it is
    checking "not empty", not "not trimmed".
    """
    for filename in oss_rules.RULES["tools"]:
        body = (RULE_LAYER_DIR / filename).read_text(encoding="utf-8")
        assert len(body) > 200, "{}: suspiciously short: {} bytes".format(filename, len(body))


def test_every_tools_constant_is_substantial():
    """The other half: every `RULES["tools"]` constant is not empty or trivially short."""
    for filename, body in oss_rules.RULES["tools"].items():
        assert len(body) > 200, "{}: suspiciously short constant: {} bytes".format(filename, len(body))


# --- the control pair, driven against synthetic bodies so it does not depend on ------
# --- today's repo state (#577 requires both halves) -----------------------------------


def test_control_an_edit_to_both_copies_the_same_way_still_matches():
    a = "---\ntitle: x\n---\n\nSame body, same rule.\n"
    b = "---\ntitle: x\n---\n\nSame body, same rule.\n"
    assert _bodies_match(a, b)


def test_control_an_edit_to_exactly_one_copy_is_caught():
    a = "---\ntitle: x\n---\n\nSame body, same rule.\n"
    b = "---\ntitle: x\n---\n\nSame body, DIFFERENT rule.\n"
    assert not _bodies_match(a, b)


def test_control_line_ending_and_trailing_whitespace_alone_do_not_count_as_drift():
    """CI runs Windows; a checkout-level CRLF difference must not fail this guard."""
    a = "---\ntitle: x\n---\n\nSame body.  \n"
    b = "---\r\ntitle: x\r\n---\r\n\r\nSame body.\r\n"
    assert _bodies_match(a, b)
