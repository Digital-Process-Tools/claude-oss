"""The `01-oss` rule layer this repository ships and the copy it has committed under

`.claude/jit-context/*/01-oss/` are two statements of one fact, and #1063 found
nothing in `tests/` compared them for the index files: three of the four
`00-index.tsv`/`.md` bodies matched their generator, one did not, and the drift
sat on `main` unnoticed because `tests/test_supertool_rule_sync_577.py` only ever
covered one specific pair of bodies (`TOOLS_SUPERTOOL` against its `.md`).

This closes the same gap for the whole layer: every file `scaffold.plan_rules()`
says it would `replace` is compared, byte for byte after line-ending
normalisation, against what is actually committed at that path -- the same
normalisation `test_supertool_rule_sync_577.py` already uses and for the same
reason, the `.gitattributes` LF pin makes a checkout-level CRLF safe to ignore.

Positive control included, per this repo's own CLAUDE.md rule that a "must not
differ" assertion needs a "must differ" case in the same fixture: a one-sided
edit to a committed file must fail this guard, driven against a synthetic pair
so it does not depend on today's repo state.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402


def _normalize(text):
    """Line-ending normalisation only, never a content transform -- CI runs Windows
    legs where a checkout can arrive with CRLF, and the `.gitattributes` LF pin makes
    that safe to ignore here the same way #577's own normalisation does.

    Deliberately narrower than #577's own `_normalize`, which also strips trailing
    whitespace per line: these bodies include `00-index.tsv` rows, where a trailing
    tab is not incidental whitespace but the exact byte #1063 was filed over. Stripping
    it here would normalise the drift itself away and pass on a fixture this guard
    exists to catch -- confirmed against the pre-fix committed file, which this test's
    own positive control below also pins.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _bodies_match(a, b):
    return _normalize(a) == _normalize(b)


def _this_repo_rule_layer_replace_rows():
    config, problems = oss_config.load(REPO_ROOT / oss_config.CONFIG_NAME)
    assert config is not None, problems
    rules_plan = scaffold.plan_rules(REPO_ROOT, config)
    assert rules_plan["state"] == "previewed", rules_plan
    return [e for e in rules_plan["entries"] if e["action"] == "replace"]


def test_every_committed_01_oss_file_matches_what_this_repo_would_write():
    rows = _this_repo_rule_layer_replace_rows()
    assert rows, "the plan produced no rule-layer rows at all -- nothing was checked"
    mismatched = []
    for row in rows:
        committed_path = REPO_ROOT / row["path"]
        if not committed_path.is_file():
            mismatched.append("{} -- not committed at all".format(row["path"]))
            continue
        committed = committed_path.read_text(encoding="utf-8")
        if not _bodies_match(committed, row["body"]):
            mismatched.append(row["path"])
    assert not mismatched, (
        "the committed 01-oss rule layer has drifted from what oss_rules.install() "
        "would write (#1063): {}".format(mismatched)
    )


def test_control_an_edit_to_both_copies_the_same_way_still_matches():
    a = "keyword\tfile.md\n"
    b = "keyword\tfile.md\n"
    assert _bodies_match(a, b)


def test_control_an_edit_to_exactly_one_copy_is_caught():
    a = "keyword\tfile.md\n"
    b = "keyword\tDIFFERENT.md\n"
    assert not _bodies_match(a, b)


def test_control_a_checkout_level_crlf_alone_does_not_count_as_drift():
    a = "keyword\tfile.md\n"
    b = "keyword\tfile.md\r\n"
    assert _bodies_match(a, b)


def test_control_a_trailing_tab_is_caught_the_1063_case_exactly():
    """#1063 itself: the committed file carried ``keyword\\tfile\\t``, the generator
    wrote ``keyword\\tfile``. A guard that stripped trailing whitespace, the way #577's
    own ``_normalize`` does, would have passed on this exact drift -- this is the
    fixture that caught it (see ``_normalize``'s own docstring above).
    """
    generated = "keyword\tfile.md\n"
    committed = "keyword\tfile.md\t\n"
    assert not _bodies_match(generated, committed)
