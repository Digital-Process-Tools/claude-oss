"""#905: `trap.d/` fragments, and the three states of asking how many are waiting.

A curation pass that was silently skipped and a cycle with nothing to curate must not render
identically -- that is this repository's own defect class pointed at its own queue. So
`scripts/trap_curate.py` answers `waiting` / `none` / `could-not-read`, never a bare integer, and
never `0` for a directory it could not open.

The filename check is deliberately the only thing validated about a fragment. Content structure,
a required dimension, a match pattern and a firing proof are all *absent on purpose*: every one of
them is friction at the moment friction stops the lesson being written, which is what #905 exists
to remove. A test asserting a fragment has a heading would be re-adding the thing being removed.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import trap_curate  # noqa: E402


def _write(d, name, body="- something cost time\n"):
    (d / name).write_text(body, encoding="utf-8")


def test_a_directory_with_fragments_reports_waiting_and_names_them(tmp_path):
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.find-first-locator.md")
    _write(d, "888.rglob-swallows.md")
    r = trap_curate.waiting(tmp_path)
    assert r["state"] == "waiting"
    assert r["count"] == 2
    assert sorted(f["name"] for f in r["fragments"]) == [
        "888.rglob-swallows.md",
        "904.find-first-locator.md",
    ]


def test_an_empty_directory_reports_none_which_is_a_finding_not_an_absence(tmp_path):
    (tmp_path / "trap.d").mkdir()
    r = trap_curate.waiting(tmp_path)
    assert r["state"] == "none"
    assert r["count"] == 0


def test_an_absent_directory_reports_none_and_says_so(tmp_path):
    r = trap_curate.waiting(tmp_path)
    assert r["state"] == "none"
    assert r["count"] == 0
    assert "trap.d" in r["why"]


def test_an_unreadable_directory_never_renders_as_zero(tmp_path):
    """The whole point. A directory that cannot be listed is not an empty one.

    The deny is confirmed by attempting the exact operation the code under test performs, per this
    repository's rule that a permission fixture is a measurement and not a given.
    """
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.x.md")
    os.chmod(d, 0o000)
    try:
        try:
            os.listdir(d)
        except PermissionError:
            pass
        else:
            pytest.skip(
                "this platform still listed a 0o000 directory (root, or a filesystem ignoring the "
                "mode bit), so the unreadable arm went untested here"
            )
        r = trap_curate.waiting(tmp_path)
        assert r["state"] == "could-not-read"
        assert r["count"] is None, "a count that could not be taken must never render as a number"
    finally:
        os.chmod(d, 0o755)


def test_a_filename_that_does_not_parse_is_reported_not_ignored(tmp_path):
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.good-one.md")
    _write(d, "no-issue-number.md")
    _write(d, "904.md")
    r = trap_curate.waiting(tmp_path)
    assert r["count"] == 3, "a malformed name is still a logged trap and must not be dropped"
    bad = sorted(f["name"] for f in r["fragments"] if not f["parses"])
    assert bad == ["904.md", "no-issue-number.md"]
    good = [f for f in r["fragments"] if f["parses"]]
    assert good[0]["issue"] == 904 and good[0]["slug"] == "good-one"


def test_non_markdown_and_dotfiles_are_not_counted_as_fragments(tmp_path):
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.real.md")
    _write(d, ".DS_Store", "")
    _write(d, "notes.txt", "")
    r = trap_curate.waiting(tmp_path)
    assert r["count"] == 1


def test_this_repository_s_own_trap_d_answers_one_of_the_three_states():
    """The positive control for the negative assertions above: the real directory is readable."""
    r = trap_curate.waiting(REPO_ROOT)
    assert r["state"] in {"waiting", "none", "could-not-read"}
    assert r["state"] != "could-not-read", r.get("why")


def test_every_fragment_in_this_repository_parses_as_issue_dot_slug_dot_md():
    """This is the CI leg. It is the whole of the per-PR validation, on purpose.

    Nothing here checks content: no required heading, no dimension, no match pattern, no firing
    proof. A lane logs prose and moves on; the routing decision belongs to `/oss:curate`, taken
    later with every fragment visible at once.
    """
    r = trap_curate.waiting(REPO_ROOT)
    if r["state"] == "could-not-read":
        pytest.skip("could not read trap.d/ here: {}".format(r.get("why")))
    bad = [f["name"] for f in r["fragments"] if not f["parses"]]
    assert not bad, (
        "trap.d/ fragments must be named <issue>.<slug>.md so two lanes never collide on a path: "
        "{}".format(", ".join(bad))
    )


# --- the doctor line, in all three states -------------------------------------------------
#
# The count reaches a maintainer through `doctor` and nowhere else that runs unprompted, because
# #905 chose reported-never-blocking: a gate here would refuse a security fix over a typo somebody
# logged on Friday. That makes this line the whole forcing function, so it is tested rather than
# assumed, and tested in the state that matters most -- the one where nothing could be read.

import io                                                     # noqa: E402
import contextlib                                             # noqa: E402

import doctor                                                 # noqa: E402


def _doctor_line(root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor.check_trap_queue(str(root))
    return buf.getvalue().strip()


def test_doctor_reports_a_waiting_queue_as_notice_naming_the_fragments(tmp_path):
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.one.md")
    line = _doctor_line(tmp_path)
    assert line.startswith("NOTICE "), line
    assert "1 waiting" in line and "904.one.md" in line
    assert "/oss:curate" in line


def test_doctor_reports_an_empty_queue_as_ok_and_says_none(tmp_path):
    (tmp_path / "trap.d").mkdir()
    line = _doctor_line(tmp_path)
    assert line.startswith("OK "), line
    assert "none waiting" in line


def test_doctor_never_reports_an_unreadable_queue_as_empty(tmp_path):
    """The state this repository is named after. `could not be read` must not read as `none`."""
    d = tmp_path / "trap.d"
    d.mkdir()
    _write(d, "904.one.md")
    os.chmod(d, 0o000)
    try:
        try:
            os.listdir(d)
        except PermissionError:
            pass
        else:
            pytest.skip(
                "this platform still listed a 0o000 directory, so the WARN arm went untested here"
            )
        line = _doctor_line(tmp_path)
        assert line.startswith("WARN "), line
        assert "could not be read" in line
        assert "UNKNOWN, not zero" in line
        assert "none waiting" not in line
    finally:
        os.chmod(d, 0o755)
