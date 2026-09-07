"""#1186 -- a prose finding under a `Class C` heading, with no list marker.

An `oss:auditor` spawn's final message stated a real finding, in full, as a
plain paragraph directly following a bare "Class C" label -- no numbered item,
no bullet. `scripts/review_return.py --framed` read the message's own
`FINDINGS: 1` header, counted zero enumerable blocks under it (`_BLOCK` counts
markdown markers at column zero, never prose), and answered `could-not-classify`.

The issue names two candidate fixes and leaves the choice open: loosen the
classifier to also count a paragraph trailing a class heading, or tighten
`agents/auditor.md`'s own contract so a finding is always rendered as a list
item and never as bare prose. This file's own answer is the second one, and
`tests/test_review_return_392.py::test_a_header_over_uncountable_prose_stays_could_not_classify`
is why: that test already pins `could-not-classify` for the general shape --
a `FINDINGS: n` header over uncountable prose -- as the file's own recorded
refusal of "the reviewer's proposed remedy", not a bug. Loosening `_BLOCK` to
count prose after *any* heading would flip that pinned behaviour and reopen
the exact false-positive risk this module's own docstring describes: a
"Files checked" list or a `-- clean` explanation is prose too, and nothing
in the text alone tells a stated finding from a description of the verdict.

So the fix is entirely upstream, in `agents/auditor.md`'s report-format
contract (a finding must open with a list marker `scripts/review_return.py`
already recognises), and `scripts/review_return.py` itself needs no new
heuristic. The tests below hold both halves of that decision: the shape from
the issue stays `could-not-classify` (a regression lock on the refusal, not a
bug fixed by a code change here), the same finding rendered per the tightened
contract classifies correctly, and a class heading trailing non-finding prose
never becomes a false positive.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import review_return  # noqa: E402


CLASS_C_PROSE_FINDING = """FINDINGS: 1

Class C -- untrusted text forges a boundary: the branch name printed at
scripts/ci_report.py:42 is rendered at column zero without folding, so a
branch named to contain a markdown heading forges the report's own
structure. Repro: create a branch literally named "# forged" and run the
report generator against it.

Class A -- clean
Class B -- clean
Class D, F, H -- clean
"""


def test_a_prose_finding_under_a_bare_class_heading_stays_could_not_classify():
    """The exact shape #1186 reports. This is the honest refusal this module
    already documents for uncountable prose, not the bug: a header claiming
    one finding over a body with zero enumerable markers cannot be told from
    a header claiming more than a reviewer actually delivered, so guessing in
    either direction is worse than saying so."""
    verdict = review_return.classify(CLASS_C_PROSE_FINDING)
    assert verdict["state"] == "could-not-classify", verdict
    assert verdict["claimed"] == 1, verdict
    assert verdict["stated_blocks"] == 0, verdict


CLASS_C_LIST_FINDING = """FINDINGS: 1

Class C -- untrusted text forges a boundary:
- scripts/ci_report.py:42 -- the branch name is printed at column zero
  without folding, so a branch named to contain a markdown heading forges
  the report's own structure. Repro: create a branch literally named
  "# forged" and run the report generator against it.

Class A -- clean
Class B -- clean
Class D, F, H -- clean
"""


def test_the_same_finding_rendered_per_the_tightened_contract_is_recognised():
    """Positive: once `agents/auditor.md` requires a finding to open with a
    list marker (a rule `scripts/review_return.py` already understands), the
    identical finding from the test above classifies correctly with no
    change to this module's counting logic."""
    verdict = review_return.classify(CLASS_C_LIST_FINDING)
    assert verdict["state"] == "states-findings", verdict
    assert verdict["claimed"] == 1 and verdict["stated_blocks"] >= 1, verdict


CLASS_C_NOT_A_FINDING = """FINDINGS: 0

Class C -- untrusted text forges a boundary: nothing found under this class.

Class A -- clean
Class B -- clean
Class D, F, H -- clean
"""


def test_a_class_heading_trailing_non_finding_prose_is_not_a_false_positive():
    """Positive control for the pair above, and the reason a heuristic keyed
    on "prose after a class heading" was rejected rather than added: this
    fixture has the identical shape as the two above -- a bare class label
    followed directly by a plain-prose paragraph -- and it is not a finding
    at all. A `FINDINGS: 0` header must stay `no-findings` regardless of what
    trails any class heading in the body, and it does, because nothing here
    inspects the body's prose to decide that."""
    verdict = review_return.classify(CLASS_C_NOT_A_FINDING)
    assert verdict["state"] == "no-findings", verdict
    assert verdict["claimed"] == 0, verdict


def test_the_auditor_brief_requires_a_list_marker_for_every_finding():
    """The upstream half of the fix (#1186): `agents/auditor.md`'s own
    contract must say a finding is rendered as a list item, never as bare
    prose trailing a class label -- or a compliant auditor can reproduce the
    exact loss above."""
    text = (REPO / "agents" / "auditor.md").read_text(encoding="utf-8")
    assert "list item" in text.lower()
    assert "review_return.py" in text
