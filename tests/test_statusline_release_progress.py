"""How much of a release is banked, against how big a release here usually is.

The status line answered "how many pull requests and issues are open" and nothing about
where the next release stands. This field is that: commits landed since the newest version
tag, over the median size of the recent releases -- `4/17`.

Both halves are derived from this clone's own tags, and both have the third state this
repository is named after. A repository with no version tag has taken no measurement, and
must not render `0/0`: zero commits since a tag and no tag at all are different facts, and
so are "releases here are usually 17 commits" and "nobody could tell". Every assertion
below pairs the `?` with a must-fire control that produces a number in the same shape.

The history window is bounded on purpose -- a status line renders on every message -- so
the case where the window does not reach far enough back to hold two tags is tested as a
first-class outcome rather than as a smaller number.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _commits(count):
    """`count` fake hashes, newest first, the shape `git rev-list HEAD` returns."""
    return ["{:040x}".format(index) for index in range(count)]


# ------------------------------------------------------------------ the two halves


def test_no_tag_at_all_is_unknown_on_both_halves_and_never_zero():
    progress = statusline.release_progress(_commits(20), {})
    assert progress["state"] == "unknown"
    assert progress["since"] is None
    assert progress["typical"] is None


def test_a_tag_on_head_reports_zero_commits_since_it():
    """The must-fire control for the half above: zero is a measurement."""
    commits = _commits(20)
    tags = {commits[0]: ["v0.2.0"], commits[10]: ["v0.1.0"]}
    progress = statusline.release_progress(commits, tags)
    assert progress["since"] == 0
    assert progress["typical"] == 10
    assert progress["state"] == "measured"


def test_one_tag_measures_the_delta_and_refuses_to_invent_a_typical_size():
    """One tag is one boundary and no gap. Half the field is real; half is not."""
    commits = _commits(20)
    progress = statusline.release_progress(commits, {commits[4]: ["v0.1.0"]})
    assert progress["since"] == 4
    assert progress["typical"] is None
    assert progress["state"] == "partial"


def test_the_typical_size_is_the_median_of_the_recent_gaps():
    commits = _commits(60)
    tags = {
        commits[3]: ["v0.4.0"],
        commits[8]: ["v0.3.0"],  # gap 5
        commits[28]: ["v0.2.0"],  # gap 20
        commits[38]: ["v0.1.0"],  # gap 10
    }
    progress = statusline.release_progress(commits, tags)
    assert progress["since"] == 3
    assert progress["typical"] == 10  # median of 5, 20, 10
    assert progress["state"] == "measured"


def test_an_even_number_of_gaps_still_reports_a_whole_number_of_commits():
    commits = _commits(60)
    tags = {commits[0]: ["v0.3.0"], commits[5]: ["v0.2.0"], commits[16]: ["v0.1.0"]}
    progress = statusline.release_progress(commits, tags)
    assert progress["typical"] == 8  # median of 5 and 11, rounded


def test_only_the_most_recent_gaps_count_toward_the_typical_size():
    """A release train that changed pace is described by its recent pace, not its whole
    history -- and the bound is stated here so a change to it fails a test rather than
    quietly re-describing the field."""
    commits = _commits(400)
    tags = {}
    position = 0
    # Newest gaps are 2 commits each; the older ones are 50.
    for index, gap in enumerate([0] + [2] * statusline.RELEASE_GAPS + [50] * 5):
        position += gap
        tags[commits[position]] = ["v9.{}.0".format(999 - index)]
    progress = statusline.release_progress(commits, tags)
    assert progress["typical"] == 2


# -------------------------------------------------------------- what counts as a tag


def test_a_tag_that_is_not_a_version_is_not_a_release_boundary():
    """`wip/274-preserved` is a real tag in this repository and never shipped."""
    commits = _commits(30)
    tags = {commits[2]: ["wip/274-preserved"], commits[9]: ["v0.1.0"]}
    progress = statusline.release_progress(commits, tags)
    assert progress["since"] == 9
    assert progress["typical"] is None


def test_the_boundary_is_the_newest_version_not_the_nearest_tag_by_name():
    commits = _commits(30)
    tags = {commits[2]: ["v0.9.0"], commits[7]: ["v0.10.0"]}
    progress = statusline.release_progress(commits, tags)
    # v0.10.0 is the newer release even though it sits further back in the log.
    assert progress["since"] == 7
    assert progress["typical"] is None


# ------------------------------------------------------------- the bounded window


def test_a_window_that_does_not_reach_the_previous_tag_says_so():
    """The truncation is reported, not rendered as a smaller history."""
    commits = _commits(statusline.RELEASE_WINDOW)
    progress = statusline.release_progress(commits, {commits[1]: ["v0.2.0"]})
    assert progress["since"] == 1
    assert progress["typical"] is None
    assert progress["state"] == "partial"


def test_no_commits_at_all_is_unknown():
    assert statusline.release_progress([], {})["state"] == "unknown"


# ------------------------------------------------------------------------ rendering


def test_the_field_renders_both_numbers():
    field = statusline._release_field({"state": "measured", "since": 4, "typical": 17})
    assert field == "rel 4/17"


def test_the_field_marks_each_unknown_half_separately():
    assert (
        statusline._release_field({"state": "partial", "since": 4, "typical": None})
        == "rel 4/?"
    )
    assert (
        statusline._release_field({"state": "unknown", "since": None, "typical": None})
        == "rel ?/?"
    )
    assert statusline._release_field(None) == "rel ?/?"


def test_the_whole_line_carries_the_field_and_the_unknown_shape_of_it():
    facts = {
        "model": "Opus",
        "percent": 10,
        "repo_name": "oss",
        "branch": "main",
        "board": {"prs": 2, "issues": 14},
        "release": {"state": "measured", "since": 4, "typical": 17},
    }
    assert "rel 4/17" in statusline.render(facts, ascii_only=True)
    facts["release"] = None
    assert "rel ?/?" in statusline.render(facts, ascii_only=True)
