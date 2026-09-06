"""#1071: `agents/auditor.md` and `agents/release-auditor.md` shared ~10% of
their 8-grams (286 out of ~2,500 each, measured on `main` at `ef9a1bc`) --
the total `Bash` grant's explanation, how a read happens through
`supertool`, and "test behaviour is reasoned, not run" were near-verbatim in
both. That prose now lives once, in `agents/audit/shared.md`, and both
agent definitions point at it instead of repeating it.

Three things this file checks, each with a must-fire control alongside the
must-not-fire assertion (a negative assertion needs a positive control):

  - both parents actually reference the fragment by path;
  - the fragment is within its own budget, tracked in
    ``scripts/audit_shared.py`` rather than in either single-parent
    registry;
  - the measured duplication between the two parents is now far below the
    pre-extraction figure, with its own must-fire control: a synthetic pair
    built from the exact paragraph #1071 was filed against, proving the
    8-gram helper can still find real duplication rather than never firing.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_shared  # noqa: E402


def _words(path):
    return re.findall(r"[A-Za-z0-9']+", path.read_text(encoding="utf-8").lower())


def _shared_8grams(path_a, path_b):
    def ngrams(words, n=8):
        return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}

    return ngrams(_words(path_a)) & ngrams(_words(path_b))


def test_both_parents_reference_the_fragment():
    result = audit_shared.check()
    missing = [p for p, ref in result["referenced"].items() if ref is not True]
    assert not missing, f"parent(s) do not name the fragment: {missing}"


def test_an_unread_parent_is_reported_as_none_not_false():
    # Must-fire control, paired with the assertion above: a parent this
    # module cannot read must not render the same as a parent that read
    # fine and simply did not mention the fragment.
    orig_parents = audit_shared.PARENTS
    audit_shared.PARENTS = ("agents/does-not-exist-1071.md",)
    try:
        result = audit_shared.check()
    finally:
        audit_shared.PARENTS = orig_parents
    assert result["referenced"] == {"agents/does-not-exist-1071.md": None}


def test_fragment_is_within_its_own_budget():
    result = audit_shared.check()
    assert result["state"] == "ok", result


def test_fragment_reports_missing_rather_than_silently_ok():
    # Must-fire control for the budget check itself.
    orig_fragment = audit_shared.FRAGMENT
    audit_shared.FRAGMENT = "agents/audit/does-not-exist-1071.md"
    try:
        result = audit_shared.check()
    finally:
        audit_shared.FRAGMENT = orig_fragment
    assert result["state"] == "missing"


def test_duplication_between_the_two_agents_dropped_far_below_the_filed_count():
    shared = _shared_8grams(
        ROOT / "agents" / "auditor.md", ROOT / "agents" / "release-auditor.md"
    )
    # Filed at 286 (skill_phases-style paragraph shingling) / measured here
    # at 261 with this test's own word tokenizer against the pre-extraction
    # files. Comfortably below either number is the signal the extraction
    # actually removed the duplicated prose rather than just moving a
    # pointer to it.
    assert len(shared) < 150, (
        f"{len(shared)} shared 8-grams remain between agents/auditor.md and "
        "agents/release-auditor.md -- #1071's extraction should have moved "
        "the duplicated prose out, not left it in place"
    )


def test_the_duplication_check_actually_fires_on_real_duplication(tmp_path):
    # Must-fire control for the assertion above: a synthetic pair carrying
    # the fragment's own text (the near-verbatim prose #1071 was filed
    # against, before it was extracted) reproduced word-for-word in both
    # files must trip the identical threshold this test enforces on the
    # real files -- otherwise a passing test above would be
    # indistinguishable from a helper that can never find anything.
    duplicated_paragraph = (
        audit_shared.repo_root()
        .joinpath(*audit_shared.FRAGMENT.split("/"))
        .read_text(encoding="utf-8")
    )
    file_a = tmp_path / "a.md"
    file_b = tmp_path / "b.md"
    file_a.write_text(duplicated_paragraph + " unique to a only", encoding="utf-8")
    file_b.write_text(duplicated_paragraph + " unique to b only", encoding="utf-8")
    shared = _shared_8grams(file_a, file_b)
    assert len(shared) >= 150, (
        "the 8-gram helper found only "
        f"{len(shared)} shared grams in a synthetic pair built by "
        "duplicating the fragment's own text into both files -- the check "
        "cannot be trusted to fire on real duplication"
    )
