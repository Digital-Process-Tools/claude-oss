"""#1759: a `/oss:curate` pass opens a pull request that changes only `trap.d/`
and `.claude/jit-context/` -- no user-visible change, ever -- but `curate.md`
never told it to set the `no-changelog` label, so the changelog gate's own
escape hatch had to be pointed out by hand (PR #1710). Same file, second gap:
the "prove it fires" step drives the general jit-context tool's own
`rebuild-tsv.sh` against the live worktree, which can rewrite
`.claude/jit-context/*/01-oss/00-index.tsv` -- the layer `oss_rules.install()`
owns wholesale -- with a version that then drifts from what `oss_rules.install()`
would write, exactly the failure `tests/test_rule_layer_sync_1063.py` caught on
4 pytest legs (job 106910952028).

Content-invariant checks, the same `_collapse` + substring pattern already used
by `tests/test_curate_pr_no_close_1552.py` and `tests/test_content_invariants.py`
for pinning prose in this command file.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE = REPO_ROOT / "commands" / "run" / "curate.md"


def _collapse(text):
    return re.sub(r"\s+", " ", text)


def _curate_text():
    return CURATE.read_text(encoding="utf-8")


def test_curate_md_sets_no_changelog_label_in_the_pr_payload():
    collapsed = _collapse(_curate_text())
    assert re.search(r'labels\s*=\s*\[\s*"no-changelog"\s*\]', collapsed), (
        'curate.md never sets labels = ["no-changelog"] in its own pull '
        "request payload -- without it a curate PR relies on the changelog "
        "workflow's path filter alone, and a maintainer has to point out the "
        "escape hatch by hand (#1710)"
    )


def test_curate_md_says_the_label_is_unconditional_not_oss_json_gated():
    collapsed = _collapse(_curate_text())
    assert "unconditionally" in collapsed and "no-changelog" in collapsed, (
        "curate.md does not say the no-changelog label is set unconditionally "
        "-- without that, it reads as gated on .oss.json the same way "
        "labels.priority/labels.lane_other are, which is the wrong model for "
        "a fixed convention name"
    )


def test_curate_md_warns_against_staging_01_oss():
    collapsed = _collapse(_curate_text())
    assert "01-oss" in collapsed and (
        "never stage" in collapsed or "stage only" in collapsed
    ), (
        "curate.md's firing-proof section never warns that driving the hook "
        "can dirty the owned 01-oss layer, or tell the pass not to stage it "
        "-- without that, an accidental commit reproduces the "
        "test_rule_layer_sync_1063.py drift (job 106910952028)"
    )


def test_curate_md_names_the_rule_layer_sync_test_as_the_consequence():
    collapsed = _collapse(_curate_text())
    assert "test_rule_layer_sync_1063" in collapsed, (
        "curate.md does not name the guard that catches the 01-oss drift it "
        "warns about, so the warning reads as an unsupported opinion rather "
        "than a stated, checkable consequence"
    )
