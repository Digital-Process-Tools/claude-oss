"""#1170: `changelog.d/1157.fixed.md` (folded into `CHANGELOG.md` at v0.26.0)
and `scripts/gh_which.py`'s own docstring were flagged, at v0.26.0's own
release audit, as overclaiming a complete sweep of every bare `gh`/`git`
resolution call site in this repo -- "Every site now resolves through one
new shared helper" and "the one place this repo resolves an external
binary before spawning it", both written at a time when at least 9 sites
were still unconverted.

This asserts the two things the issue's fix actually requires now that the
fragment has already folded into published history:

1. The folded `CHANGELOG.md` entry for #1157 must not leave the "every
   site" overclaim standing uncorrected -- it must be followed, within the
   same entry, by text that retracts it and names the tracking issue
   (#1165) for what remained unconverted at the time.
2. `scripts/gh_which.py`'s docstring "the one place" claim must actually be
   true today -- i.e. the repo-wide sweep (`test_bare_gh_git_spawn_sweep_
   1165.py`) must currently find zero live, unconverted bare-spawn sites.
   If that sweep ever regresses, this docstring's claim becomes false again
   and this test must fail alongside it.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_changelog_1157_fragment_no_longer_exists_as_a_loose_file():
    # Folded into CHANGELOG.md already; the loose fragment must not still
    # be sitting in changelog.d/ making the same claim unmoderated.
    assert not (REPO_ROOT / "changelog.d" / "1157.fixed.md").exists()


def test_changelog_folded_entry_retracts_the_every_site_overclaim():
    raw = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # Markdown hard-wraps this entry's prose across lines, so compare
    # against whitespace-collapsed text rather than the raw bytes.
    text = " ".join(raw.split())
    claim = "Every site now resolves through one new shared helper"
    assert claim in text, (
        "the folded #1157 entry's original claim should still be present "
        "as the historical record of what that commit said -- this test "
        "is not asking to delete it"
    )
    idx = text.index(claim)
    # The retraction lives later in the same entry, before the changelog
    # moves on to describe a different, unrelated fix.
    window = text[idx : idx + 6000]
    assert "overclaimed" in window, (
        "the folded entry no longer explicitly retracts its own 'every "
        "site' claim within a reasonable distance"
    )
    assert "#1165" in window, (
        "the folded entry's retraction must name #1165 as the tracker for "
        "whatever remained unconverted"
    )


def test_gh_which_docstring_the_one_place_claim_is_currently_true():
    """`gh_which.py`'s docstring says it is 'the one place this repo
    resolves an external binary before spawning it'. That is a live claim
    about the current tree, not a historical one, so it is checked against
    the sweep rather than against fixed prose: if any other site still
    resolves and spawns a bare `gh`/`git` outside `gh_which.safe_which`,
    this docstring is currently lying.
    """
    import sys

    tests_dir = str(REPO_ROOT / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    import test_bare_gh_git_spawn_sweep_1165 as sweep

    violations, unscannable = sweep._scan_repository()
    assert not unscannable, "could not scan: {}".format(unscannable)
    live = {
        key: kind_name
        for key, kind_name in violations.items()
        if key not in sweep._ALLOWED
    }
    assert not live, (
        "gh_which.py's docstring claims to be 'the one place' resolution "
        "happens, but these live sites still bypass it: {}".format(
            {"{}:{}".format(*k): v for k, v in live.items()}
        )
    )
