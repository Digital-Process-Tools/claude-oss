r"""#843: the `--lane` comma split needs a real quoting/escaping rule, not
another heuristic patch, and two enumerations in `lane_setup.py` still
predated `resolved-to-nothing`.

Part 1 -- `_split_lane_value` replaces #836's stat-based
`_raw_comma_pattern_names_one_existing_path` heuristic entirely. That
heuristic decided whether an unsplit, comma-containing `--lane` value was
one real path or a comma-joined list by looking at the filesystem, and
#840's own review found three residual gaps in exactly that lookup:

  (a) a glob combined with a comma in a directory name was excluded from
      the whole-string check outright, because `_is_lane_glob(raw)`
      returned early before the existence check ever ran;
  (b) a held file that does not exist *yet* -- the ordinary shape of a
      `literal` pattern -- could never pass the existence check, so a
      not-yet-existing comma-named path always split, no matter what was
      meant;
  (c) a `PermissionError` on an unreadable ancestor fell through to the
      bogus split rather than to a third `could-not-check` state -- this
      repository's own defect class, a check that could not look
      degrading into an answer.

`_split_lane_value` is a purely lexical scan (`\,` a literal comma, `\\`
a literal backslash, any other `,` a delimiter) that never touches the
filesystem, so none of the three gaps above has anywhere left to live: (a)
and (b) no longer ask the filesystem anything, and (c) cannot raise
`PermissionError` because nothing is `stat()`-ed. Every case below pairs
the fix with a positive control, per this repo's own rule that a negative
assertion needs one.

Part 2 -- `lane_report`'s docstring (near the old line 822) and a comment
inside `receipt()` (near the old line 2428) still enumerated only the four
pre-#809 availability states, the exact defect #837 already fixed one
function away in `skills/manager/phases/dispatch.md`. `tests/
test_lane_verdict_docs_837.py` already guards the *document*; nothing
guarded the *script's own prose* naming the same set, so both sites are
grepped directly here.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402


# --- (a): a glob combined with a comma in a directory name --------------------


def test_glob_with_comma_in_directory_name_stays_whole_when_escaped(tmp_path):
    """The issue's gap (a): under the #836 heuristic, `_is_lane_glob(raw)`
    returned early and this always split into `my` and `dir/*.py`, even
    though `my,dir` is the real directory. Escaping the comma keeps it one
    glob member and it resolves against the real directory."""
    d = tmp_path / "my,dir"
    d.mkdir()
    (d / "a.py").write_text("x\n")
    (d / "b.py").write_text("x\n")
    resolved = lane_setup.resolve_lane(tmp_path, ["my\\,dir/*.py"])
    assert len(resolved["patterns"]) == 1
    assert resolved["patterns"][0]["state"] == "glob-resolved"
    assert resolved["files"] == ["my,dir/a.py", "my,dir/b.py"]


def test_control_unescaped_glob_with_comma_in_directory_name_still_splits(tmp_path):
    """Control: without the escape, the comma is an ordinary delimiter and
    the value still splits into two members, neither of which resolves to
    the real directory -- proving the escape above is doing the work, not
    some other path."""
    d = tmp_path / "my,dir"
    d.mkdir()
    (d / "a.py").write_text("x\n")
    resolved = lane_setup.resolve_lane(tmp_path, ["my,dir/*.py"])
    assert len(resolved["patterns"]) == 2
    # "my" is a bare literal (asserted, not checked against the tree) and
    # "dir/*.py" is a glob matching nothing under tmp_path -- neither
    # resolves against the real "my,dir" directory the escaped case above
    # does.
    assert resolved["files"] == ["my"]
    states = [e["state"] for e in resolved["patterns"]]
    assert "literal" in states
    assert "glob-no-match" in states


# --- (b): a held file that does not exist yet, with a comma in its name -------


def test_not_yet_existing_comma_named_path_stays_whole_when_escaped(tmp_path):
    """The issue's gap (b): a changelog fragment about to be created, with a
    comma in its own name, can never pass an existence check -- so #836's
    heuristic always split it. The escape rule never asks the filesystem,
    so it stays one literal member regardless of whether it exists."""
    resolved = lane_setup.resolve_lane(
        tmp_path, ["changelog.d/843.fixed\\,not-yet-created.md"]
    )
    assert len(resolved["patterns"]) == 1
    assert resolved["patterns"][0]["state"] == "literal"
    assert resolved["files"] == ["changelog.d/843.fixed,not-yet-created.md"]


def test_control_not_yet_existing_comma_list_without_escape_still_splits(tmp_path):
    """Control: two not-yet-existing changelog fragments joined by an
    ordinary comma still split into two literal members, exactly as #809
    intended."""
    resolved = lane_setup.resolve_lane(
        tmp_path, ["changelog.d/843.a.md,changelog.d/843.b.md"]
    )
    assert len(resolved["patterns"]) == 2
    assert resolved["files"] == ["changelog.d/843.a.md", "changelog.d/843.b.md"]


# --- (c): a PermissionError mid-check must never degrade into a bogus split ---


def test_split_never_touches_the_filesystem_so_no_permission_error_is_reachable(
    tmp_path, monkeypatch
):
    """The issue's gap (c), and the sharpest of the three: #836's heuristic
    called `.stat()` on the unsplit raw value, so a `PermissionError` on an
    unreadable ancestor fell through to the bogus split branch instead of a
    third state. `_split_lane_value` never calls `.stat()`, `os.walk`, or
    any other filesystem primitive at all -- proved here by making every
    such call raise, then confirming a comma-containing value still splits
    on the ordinary lexical rule rather than raising or silently guessing."""
    import os

    def _boom(*_args, **_kwargs):
        raise PermissionError("simulated: filesystem must not be consulted")

    monkeypatch.setattr(Path, "stat", _boom)
    monkeypatch.setattr(os, "walk", _boom)
    # Plain split: no escapes, so an ordinary delimiter comma still splits
    # cleanly with no filesystem call anywhere on this path.
    assert lane_setup._split_lane_value("a.md,b.md") == ["a.md", "b.md"]
    # Escaped: the literal comma survives untouched, again with no
    # filesystem call.
    assert lane_setup._split_lane_value("docs/comma\\,name.md") == [
        "docs/comma,name.md"
    ]


def test_control_resolve_lane_still_reports_refused_for_a_real_permission_denial(
    tmp_path,
):
    """Control: gap (c) is about the *split* step never degrading, not about
    permission errors disappearing from this module altogether --
    `resolve_lane` itself must still surface a real unreadable ancestor as
    `refused`, the same contract `test_lane_setup_809.py`'s own swallow
    test already covers for `_expand_directory`. Skips, rather than
    asserts blind, if this platform/filesystem/user does not honour the
    deny (CLAUDE.md's own permission-fixture rule)."""
    import os
    import pytest

    guarded = tmp_path / "guarded"
    guarded.mkdir()
    (guarded / "x.py").write_text("x\n")
    os.chmod(guarded, 0)
    try:
        try:
            list(guarded.iterdir())
            took = False
        except PermissionError:
            took = True
        except OSError:
            took = False
        if not took:
            pytest.skip(
                "chmod 0 did not deny listing on this platform/filesystem/user "
                "-- cannot measure the refusal here"
            )
        resolved = lane_setup.resolve_lane(tmp_path, ["guarded"])
        assert resolved["patterns"][0]["state"] == "refused"
    finally:
        os.chmod(guarded, 0o755)


# --- the escaping rule itself, at the _split_lane_value level -----------------


def test_split_lane_value_unescapes_a_literal_comma():
    assert lane_setup._split_lane_value("docs/comma\\,name.md") == [
        "docs/comma,name.md"
    ]


def test_split_lane_value_unescapes_a_literal_backslash():
    assert lane_setup._split_lane_value("a\\\\b,c") == ["a\\b", "c"]


def test_split_lane_value_strips_whitespace_after_unescaping():
    assert lane_setup._split_lane_value("a.md, b.md") == ["a.md", "b.md"]


def test_split_lane_value_plain_value_with_no_comma_is_unaffected():
    assert lane_setup._split_lane_value("scripts/lane_setup.py") == [
        "scripts/lane_setup.py"
    ]


def test_control_windows_style_single_backslash_separator_is_not_an_escape(tmp_path):
    """Control: a Windows-style single backslash separator (#267) must not be
    consumed as an escape character -- only a backslash immediately before a
    comma or another backslash is special."""
    assert lane_setup._split_lane_value("commands\\tick.md") == ["commands\\tick.md"]


# --- part 2: the two stale pre-#809 enumerations named by the issue -----------


def test_lane_report_docstring_names_resolved_to_nothing():
    source = (REPO_ROOT / "scripts" / "lane_setup.py").read_text(encoding="utf-8")
    def_start = source.index("\ndef lane_report(")
    doc_open = source.index('"""', def_start)
    doc_close = source.index('"""', doc_open + 3)
    docstring = source[doc_open:doc_close]
    assert "resolved-to-nothing" in docstring, (
        "lane_report's own docstring enumerates the availability states and "
        "must name resolved-to-nothing beside the pre-#809 four (#843)"
    )


def _receipt_availability_comment():
    """The comment block sitting directly above `receipt()`'s
    `availability["state"] == "available"` branch -- normalized to collapse
    a line-wrapped word (`# comment\n            # continuation`) back into
    one contiguous string, so a check for a compound term like
    `could-not-derive-the-held-set` cannot be defeated by where the prose
    happens to wrap."""
    source = (REPO_ROOT / "scripts" / "lane_setup.py").read_text(encoding="utf-8")
    start = source.index("def receipt(")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    comment_block = body[: body.index('availability["state"] == "available"')]
    import re

    return re.sub(r"\n\s*# ?", " ", comment_block)


def test_receipt_comment_names_resolved_to_nothing():
    assert "resolved-to-nothing" in _receipt_availability_comment(), (
        "receipt()'s own comment above the availability branch must name "
        "resolved-to-nothing beside the pre-#809 four (#843)"
    )


def test_control_receipt_comment_still_names_the_older_states_too():
    """Control: the guard above must not pass merely because the word
    appears somewhere in the file -- the older three states must still be
    named in the same comment block, proving nothing was deleted to add
    the new one."""
    comment_block = _receipt_availability_comment()
    for state in (
        "available",
        "blocked",
        "could-not-check",
        "could-not-derive-the-held-set",
    ):
        assert state in comment_block, comment_block
