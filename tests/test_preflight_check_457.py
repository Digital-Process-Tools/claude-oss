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
