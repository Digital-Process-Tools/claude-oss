"""`scaffold.py` writes `trap.d/README.md` and `trap_curate.waiting()` counted
it as a fragment, so the directory's own instructions were reported forever as
a trap whose name does not parse -- a finding no manual op and no
`/oss:scaffold` run can clear, because scaffold is what writes it (#1348).

Found by CI on `pytest (macos-latest, 3.12)`, on the branch that first
committed the scaffolded README:

    AssertionError: trap.d/ fragments must be named <issue>.<slug>.md so two
    lanes never collide on a path: README.md

Two guards disagreed about the same file -- `/oss:doctor` warned it was missing
and `tests/test_trap_curate_905.py` refused it once present -- and both were
right about their own subject. The README is documentation ABOUT the fragments,
never a fragment.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import trap_curate  # noqa: E402


def _trap_d(tmp_path, names):
    d = tmp_path / trap_curate.DIRNAME
    d.mkdir()
    for name in names:
        (d / name).write_text("body\n", encoding="utf-8")
    return tmp_path


def test_the_scaffolded_readme_is_not_a_fragment(tmp_path):
    result = trap_curate.waiting(_trap_d(tmp_path, ["README.md", "904.a-slug.md"]))
    assert result["state"] == "waiting"
    assert [f["name"] for f in result["fragments"]] == ["904.a-slug.md"]


def test_a_directory_holding_only_the_readme_is_none_not_one_malformed(tmp_path):
    """The count a status line and doctor both render. One README must not read
    as one trap waiting to be curated."""
    result = trap_curate.waiting(_trap_d(tmp_path, ["README.md"]))
    assert result["state"] == "none"
    assert result["count"] == 0


def test_any_other_unparseable_name_is_still_reported(tmp_path):
    """The positive control, and the reason the exclusion is one name rather
    than a rule about non-fragments: everything outside `FRAGMENT_RE` is still
    a finding, so a second stray file in this directory is reported as one with
    no further change. Without this, an exclusion that widened to `anything
    that does not parse` would pass both tests above."""
    result = trap_curate.waiting(
        _trap_d(tmp_path, ["README.md", "NOTES.md", "904.md"])
    )
    names = {f["name"]: f["parses"] for f in result["fragments"]}
    assert names == {"NOTES.md": False, "904.md": False}
