"""`board_from_cache`'s `state` field is deleted (#597).

Nothing read it -- `_board_field` reads `prs`, `issues`, `issues_external` and `checks`
directly and renders `?` per missing value regardless of what `state` said. A summary
that can disagree with the values it summarizes is a second copy of the same fact, and
#595 made that concrete: it added a rule to `state` ("a cache with `issues` but no
`issues_external` is `partial`") that could not affect anything a maintainer sees,
because no caller read the field it was added to. The per-field `?` each of `prs`,
`issues` and `issues_external` already carries is the whole answer -- this file is the
control proving that.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def test_board_from_cache_carries_no_state_key():
    """The deleted contract: nothing computes `state` any more."""
    assert "state" not in statusline.board_from_cache(None)
    assert "state" not in statusline.board_from_cache({"prs": 2, "fetched_at": 0})
    assert "state" not in statusline.board_from_cache(
        {"prs": 2, "issues": 14, "issues_external": 2, "fetched_at": 0}
    )


def test_the_per_field_questionmarks_still_distinguish_every_case_state_used_to_name():
    """Positive control for the deletion: the three states `state` used to name --
    unknown (nothing measured), partial (some measured), measured (all three) -- are
    still fully recoverable from `prs`/`issues`/`issues_external` alone.
    """
    unknown = statusline.board_from_cache(None)
    assert unknown["prs"] is None
    assert unknown["issues"] is None
    assert unknown["issues_external"] is None

    partial = statusline.board_from_cache({"prs": 2, "issues": 14, "fetched_at": 0})
    assert partial["prs"] == 2
    assert partial["issues"] == 14
    assert partial["issues_external"] is None

    measured = statusline.board_from_cache(
        {"prs": 2, "issues": 14, "issues_external": 0, "fetched_at": 0}
    )
    assert measured["prs"] == 2
    assert measured["issues"] == 14
    assert measured["issues_external"] == 0
    # the must-fire control: a genuine zero for issues_external must not collapse
    # with "missing" -- both render as different characters below.
    assert measured["issues_external"] != partial["issues_external"]


def test_render_still_distinguishes_unknown_from_measured_without_state():
    """The renderer never read `state`; confirm the rendered field still separates a
    board nothing was measured on from one fully measured, using facts a
    `board_from_cache` with no `state` key still produces.
    """
    symbols = statusline._symbols(True)
    unknown_field = statusline._board_field(statusline.board_from_cache(None), symbols)
    measured_field = statusline._board_field(
        statusline.board_from_cache(
            {"prs": 0, "issues": 0, "issues_external": 0, "fetched_at": 0}
        ),
        symbols,
    )
    assert unknown_field != measured_field
    assert "?pr" in unknown_field and "?is" in unknown_field and "?eis" in unknown_field
    assert (
        "0pr" in measured_field and "0is" in measured_field and "0eis" in measured_field
    )
