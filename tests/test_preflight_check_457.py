"""Tests for scripts/preflight_check.py (#457).

Pre-flight before dispatch reads the issue but never the code, so a lane can
be dispatched for work already shipped. This is the code-side half: a
pattern search over the tree in three states -- matched, not-matched, and
could-not-search, which must never render as not-matched.

Interpreting a match as already-shipped or still-open is the caller's job,
not this module's -- see the module docstring.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import preflight_check as pc  # noqa: E402


def test_matched_reports_the_matching_file_and_line(tmp_path):
    (tmp_path / "commands").mkdir()
    target = tmp_path / "commands" / "release.md"
    target.write_text("line one\ncould not run\nline three\n", encoding="utf-8")

    result = pc.search("could not run", [tmp_path])
    assert result["state"] == "matched"
    assert result["matches"] == [
        {"path": str(target), "line": 2, "text": "could not run"}
    ]


def test_not_matched_is_a_clean_search_that_found_nothing(tmp_path):
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "release.md").write_text("nothing relevant here\n", encoding="utf-8")

    result = pc.search("could not run", [tmp_path])
    assert result["state"] == "not-matched"
    assert result["matches"] == []


def test_an_invalid_pattern_is_could_not_search_never_not_matched(tmp_path):
    """The must-not-fire half: a search that could not even run must not
    collapse to the same answer as a search that ran and found nothing --
    paired with the clean case above as the positive control."""
    (tmp_path / "f.txt").write_text("anything\n", encoding="utf-8")

    result = pc.search("([unclosed", [tmp_path])
    assert result["state"] == "could-not-search"
    assert result["state"] != "not-matched"
    assert "problem" in result and result["problem"]


def test_a_root_that_does_not_exist_is_could_not_search(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = pc.search("anything", [missing])
    assert result["state"] == "could-not-search"
    assert result["state"] != "not-matched"


def test_an_unreadable_file_is_named_not_silently_dropped(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permission bits; Windows chmod semantics differ")
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("could not run\n", encoding="utf-8")
    readable = tmp_path / "readable.txt"
    readable.write_text("could not run\n", encoding="utf-8")

    old_mode = blocked.stat().st_mode
    os.chmod(blocked, 0o000)
    try:
        try:
            blocked.read_text(encoding="utf-8")
            deny_took = False
        except PermissionError:
            deny_took = True

        result = pc.search("could not run", [tmp_path])
        if not deny_took:
            pytest.skip(
                "chmod 000 did not deny reading on this platform/user -- "
                "UNTESTED HERE: whether an unreadable file is named rather "
                "than silently excluded from the search"
            )
        assert result["state"] == "matched"  # readable.txt still matches
        assert str(blocked) in result["unreadable_files"]
    finally:
        os.chmod(blocked, old_mode)


def test_an_unreadable_file_with_no_other_match_is_could_not_search(tmp_path):
    """The finding the decoy above could not catch: when the only file
    that could have matched is unreadable, a clean miss and a blocked read
    must not render identically. Positive control: the same fixture with
    the block lifted does find the match, so this is not a broken pattern."""
    if os.name == "nt":
        pytest.skip("POSIX permission bits; Windows chmod semantics differ")
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("could not run\\n", encoding="utf-8")

    old_mode = blocked.stat().st_mode
    os.chmod(blocked, 0o000)
    try:
        try:
            blocked.read_text(encoding="utf-8")
            deny_took = False
        except PermissionError:
            deny_took = True

        result = pc.search("could not run", [tmp_path])
        if not deny_took:
            pytest.skip(
                "chmod 000 did not deny reading on this platform/user -- "
                "UNTESTED HERE: whether the only candidate file being unreadable "
                "forces could-not-search rather than not-matched"
            )
        assert result["state"] == "could-not-search"
        assert result["state"] != "not-matched"
    finally:
        os.chmod(blocked, old_mode)

    # Control: same fixture, block lifted -- the match is found, so the
    # could-not-search above is not a broken pattern.
    control = pc.search("could not run", [tmp_path])
    assert control["state"] == "matched"


def test_an_unreadable_directory_with_no_match_elsewhere_is_could_not_search(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permission bits; Windows chmod semantics differ")
    readable = tmp_path / "readable.txt"
    readable.write_text("nothing relevant\\n", encoding="utf-8")
    blocked_dir = tmp_path / "blocked"
    blocked_dir.mkdir()
    (blocked_dir / "f.txt").write_text("could not run\\n", encoding="utf-8")

    old_mode = blocked_dir.stat().st_mode
    os.chmod(blocked_dir, 0o000)
    try:
        try:
            list(blocked_dir.iterdir())
            deny_took = False
        except PermissionError:
            deny_took = True

        result = pc.search("could not run", [tmp_path])
        if not deny_took:
            pytest.skip(
                "chmod 000 did not deny listing a directory on this platform/user "
                "-- UNTESTED HERE: whether an unwalkable subdirectory forces "
                "could-not-search rather than not-matched"
            )
        assert result["state"] == "could-not-search"
        assert result["state"] != "not-matched"
    finally:
        os.chmod(blocked_dir, old_mode)

    # Control: same fixture, block lifted -- the match under the formerly
    # blocked directory is found, so the could-not-search above is real.
    control = pc.search("could not run", [tmp_path])
    assert control["state"] == "matched"


# #727: a `not-matched` over one file and a `not-matched` over the whole
# tree render identically once a human retypes the answer as prose -- the
# receipt already carries `files_searched`, but not the paths that were
# actually asked for, so a reader still has to remember the `--path`
# argument separately to quote the scope honestly. `roots` closes that: the
# searched paths, verbatim, in the same JSON the state comes from.


def test_result_names_the_roots_it_searched(tmp_path):
    (tmp_path / "f.py").write_text("nothing relevant\n", encoding="utf-8")

    result = pc.search("could not run", [tmp_path])
    assert result["roots"] == [str(tmp_path)]


def test_result_names_every_root_when_several_are_given(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()

    result = pc.search("could not run", [first, second])
    assert result["roots"] == [str(first), str(second)]


def test_a_could_not_search_result_still_names_its_roots(tmp_path):
    """The scope must be recoverable from the receipt even on the state a
    maintainer is most likely to escalate rather than quote verbatim."""
    result = pc.search("([unclosed", [tmp_path])
    assert result["state"] == "could-not-search"
    assert result["roots"] == [str(tmp_path)]


def test_a_missing_root_result_also_names_its_roots(tmp_path):
    """The other early-return could-not-search path (a root that does not
    exist) must not drop the scope either -- covers the second of the two
    early exits in search(), the invalid-pattern case above covers the
    first."""
    missing = tmp_path / "does-not-exist"
    result = pc.search("anything", [missing])
    assert result["state"] == "could-not-search"
    assert result["roots"] == [str(missing)]


def test_one_missing_root_among_several_is_could_not_search_even_with_a_clean_miss_elsewhere(tmp_path):
    """#457's own multi-part/bundle use passes several --path roots in one
    call. If one candidate's path was mistyped or moved, that must not be
    masked by another root searching cleanly and finding nothing."""
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "f.txt").write_text("nothing relevant\\n", encoding="utf-8")
    missing = tmp_path / "does-not-exist"

    result = pc.search("could not run", [existing, missing])
    assert result["state"] == "could-not-search"
    assert result["state"] != "not-matched"
    assert str(missing) in result["missing_roots"]


def test_main_cli_matched_and_not_matched_exit_codes(tmp_path, capsys):
    target = tmp_path / "f.txt"
    target.write_text("could not run\n", encoding="utf-8")

    code = pc.main(["--pattern", "could not run", "--path", str(tmp_path)])
    assert code == pc.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "matched"

    code = pc.main(["--pattern", "nowhere to be found", "--path", str(tmp_path)])
    assert code == pc.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "not-matched"


def test_main_cli_could_not_search_exits_nonzero(tmp_path, capsys):
    code = pc.main(["--pattern", "([unclosed", "--path", str(tmp_path)])
    assert code == pc.EXIT_COULD_NOT_SEARCH
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "could-not-search"


# #717: an undecodable file (a __pycache__/*.pyc, on every real Python tree)
# has no text to search, ever, regardless of who is asking -- it is not the
# same failure as a permission-denied file, and folding it into
# unreadable_files made could-not-search fire on precisely the negative
# answer (nothing else to report) and never on the positive one (a match
# elsewhere still reports matched with the identical undecodable file
# present). These fixtures write raw invalid-UTF-8 bytes directly, so
# nothing here depends on chmod semantics or a platform's permission model.

_INVALID_UTF8 = bytes([0xFF, 0xFE, 0x00, 0x01, 0x0D, 0x0D, 0x0A, 0x0A])


def test_undecodable_file_alone_is_not_matched_never_could_not_search(tmp_path):
    """The must-not-fire half: an undecodable file with nothing else to find
    must not suppress the honest not-matched answer -- paired below with the
    must-fire half, a genuinely permission-denied file, which still forces
    could-not-search."""
    (tmp_path / "module.pyc").write_bytes(_INVALID_UTF8)
    (tmp_path / "clean.py").write_text("nothing relevant here\n", encoding="utf-8")

    result = pc.search("could not run", [tmp_path])
    assert result["state"] == "not-matched"
    assert result["state"] != "could-not-search"


def test_undecodable_file_is_reported_as_skipped_not_unreadable(tmp_path):
    target = tmp_path / "module.pyc"
    target.write_bytes(_INVALID_UTF8)

    result = pc.search("anything", [tmp_path])
    assert str(target) in result["skipped_files"]
    assert str(target) not in result["unreadable_files"]


def test_undecodable_file_present_alongside_a_real_match_still_matches(tmp_path):
    (tmp_path / "module.pyc").write_bytes(_INVALID_UTF8)
    target = tmp_path / "source.py"
    target.write_text("could not run\n", encoding="utf-8")

    result = pc.search("could not run", [tmp_path])
    assert result["state"] == "matched"
    assert result["matches"] == [
        {"path": str(target), "line": 1, "text": "could not run"}
    ]


def test_skipped_files_key_is_always_present_even_when_empty(tmp_path):
    """A skipped count is not free of the same hazard as could-not-search --
    it must be printed always, never suppressed at zero (#717)."""
    (tmp_path / "clean.py").write_text("nothing relevant\n", encoding="utf-8")

    result = pc.search("could not run", [tmp_path])
    assert result["state"] == "not-matched"
    assert result["skipped_files"] == []


# Review finding on #717: any UnicodeDecodeError was folded into skipped_files
# categorically, on the claim that an undecodable file "has no text to search,
# ever" -- true for genuine binary garbage, false for a real source file
# encoded in something other than UTF-8 (Latin-1, cp1252, ...), which has a
# real match this search would then silently miss. The distinguishing signal
# is a NUL byte -- the same heuristic `git diff` and `grep -I` use to call a
# file binary -- present in every one of the fixtures above (a genuine .pyc
# does contain one) and absent from ordinary non-UTF-8 text.


def test_non_utf8_text_with_no_null_byte_is_ambiguous_and_forces_could_not_search(tmp_path):
    """The must-fire half of the review finding: Latin-1 text with a real
    match must not silently downgrade to not-matched just because it isn't
    UTF-8 -- there is no NUL byte here, so this could be real text, and the
    honest answer is could-not-search, not a guess."""
    target = tmp_path / "legacy.py"
    target.write_bytes('match_target = "caf\xe9 marker"\n'.encode("latin-1"))
    assert b"\x00" not in target.read_bytes()

    result = pc.search("marker", [tmp_path])
    assert result["state"] == "could-not-search"
    assert str(target) in result["unreadable_files"]
    assert str(target) not in result["skipped_files"]


def test_a_null_byte_is_what_makes_an_undecodable_file_skipped(tmp_path):
    """The must-not-fire half, paired with the test above: a file with a NUL
    byte (the actual #717 target -- every real .pyc has one) is skipped, not
    forced to could-not-search, even though it also fails UTF-8 decoding."""
    target = tmp_path / "module.pyc"
    target.write_bytes(_INVALID_UTF8)
    assert b"\x00" in target.read_bytes()

    result = pc.search("anything", [tmp_path])
    assert result["state"] == "not-matched"
    assert str(target) in result["skipped_files"]
    assert str(target) not in result["unreadable_files"]


def test_a_permission_denied_file_still_forces_could_not_search_despite_717(tmp_path):
    """The must-fire half, kept beside the undecodable-file relief above: a
    genuinely permission-denied file is not the same failure as an
    undecodable one, and #717's fix must not blur that distinction back
    into a quiet not-matched."""
    if os.name == "nt":
        pytest.skip("POSIX permission bits; Windows chmod semantics differ")
    blocked = tmp_path / "blocked.py"
    blocked.write_text("could not run\n", encoding="utf-8")

    old_mode = blocked.stat().st_mode
    os.chmod(blocked, 0o000)
    try:
        try:
            blocked.read_bytes()
            deny_took = False
        except PermissionError:
            deny_took = True

        result = pc.search("could not run", [tmp_path])
        if not deny_took:
            pytest.skip(
                "chmod 000 did not deny reading on this platform/user -- "
                "UNTESTED HERE: whether a permission-denied file still forces "
                "could-not-search after #717's undecodable-file relief"
            )
        assert result["state"] == "could-not-search"
        assert str(blocked) in result["unreadable_files"]
        assert str(blocked) not in result["skipped_files"]
    finally:
        os.chmod(blocked, old_mode)
