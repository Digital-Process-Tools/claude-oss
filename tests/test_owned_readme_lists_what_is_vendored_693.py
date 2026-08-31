"""`.oss/README.md`'s "What is here" must name every file `/oss:scaffold` writes
into `.oss/` -- #693.

Measured in a repository this loop manages: `git ls-files .oss/` returned three
files and the README's list had one bullet, for `assemble_changelog.py`.
`statusline.py` -- 1,918 lines -- was named nowhere in the file.

## Why it costs something rather than being untidy

The README states its own contract two paragraphs above the gap: everything in the
directory is replaced wholesale on every run, so an edit here is overwritten. A
maintainer who notices the omission **cannot fix it locally**; the list can only be
corrected where it is generated. And `statusline.py` is the one of the three that a
maintainer has to wire up by hand rather than let CI call, so it is the file that
needs the documentation most and had none.

## Derived, not hand-listed

The list this test checks against is `scaffold.OWNED`, which is the same dict
`plan()` and `apply()` walk -- so the next file vendored into `.oss/` reddens this
rather than going unmentioned for a release. A hand-written list here would be a
second copy of the thing that already drifted once.

Both halves are present: a must-fire control proving the check can fail (a README
body with a file missing from its list is caught), and the real assertion.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402

SECTION = "## What is here"


def _config():
    return {
        "repo": "acme/widget",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }


def vendored_filenames():
    """Every path `scaffold.OWNED` writes inside the owned directory, basename only.

    Derived from the dict `apply()` itself walks. `.github/workflows/` is excluded
    because it is not in this directory and the README says so in its own "The one
    exception" section, which is a different claim from this list.
    """
    prefix = scaffold.OWNED_DIR + "/"
    return sorted(
        name[len(prefix):] for name in scaffold.OWNED if name.startswith(prefix)
    )


def unlisted(body, filenames):
    """Which of `filenames` the "What is here" section does not name.

    The section is read as the span from its own heading to the next `## ` heading,
    so a filename mentioned somewhere else in the README -- the shell command at the
    bottom names `assemble_changelog.py` -- does not count as being listed.
    """
    start = body.find(SECTION)
    if start < 0:
        return list(filenames)
    rest = body[start + len(SECTION):]
    end = re.search(r"^## ", rest, re.MULTILINE)
    section = rest[: end.start()] if end else rest
    return [name for name in filenames if name not in section]


# --- controls ------------------------------------------------------------------------


def test_control_a_section_missing_a_file_is_caught():
    """Must fire. This is #693 itself, reduced: the exact shape the shipped README
    had -- one bullet, three files.
    """
    body = "## What is here\n\n- `a.py` -- does a thing.\n\n## Next\n\n- `b.py`\n"
    assert unlisted(body, ["a.py", "b.py"]) == ["b.py"]


def test_control_a_section_naming_everything_is_clean():
    body = "## What is here\n\n- `a.py` -- x\n- `b.py` -- y\n\n## Next\n"
    assert unlisted(body, ["a.py", "b.py"]) == []


def test_control_a_mention_after_the_section_does_not_count():
    """The section ends at the next heading. Without this the shipped README would
    have passed on `assemble_changelog.py` alone via the shell command near the
    bottom of the file, which is not a description of what the file is.
    """
    body = "## What is here\n\n- `a.py` -- x\n\n## Running it\n\npython3 .oss/b.py\n"
    assert unlisted(body, ["a.py", "b.py"]) == ["b.py"]


def test_control_a_body_with_no_such_section_reports_everything():
    """Not silence. A README that lost the heading entirely documents none of them,
    and an empty finding there would read as a complete list.
    """
    assert unlisted("# nothing here\n", ["a.py"]) == ["a.py"]


def test_control_the_derivation_reached_the_owned_dict_at_all():
    """The positive control for the derivation: an empty `vendored_filenames()`
    would make the assertion below pass while checking nothing. Three were observed
    when #693 was fixed; the floor is stated as "more than one" so that vendoring a
    fourth, or retiring one, does not redden an unrelated pull request.
    """
    names = vendored_filenames()
    assert len(names) > 1, names
    assert "README.md" in names, names


# --- the invariant -------------------------------------------------------------------


def test_the_owned_readme_names_every_file_scaffold_vendors_beside_it():
    body = scaffold.render_owned(scaffold.OWNED_DIR + "/README.md", _config())
    missing = unlisted(body, vendored_filenames())
    assert missing == [], (
        "{}/README.md's 'What is here' section does not name {} -- and the README "
        "is replaced wholesale on every scaffold run, so a maintainer who notices "
        "cannot fix it in their own repository (#693)".format(scaffold.OWNED_DIR, missing)
    )


def test_the_statusline_bullet_says_it_is_opt_in_and_where_the_setting_goes():
    """Naming the file is not the whole of #693. `statusline.py` is the one of the
    three nothing calls on its own, so the two facts a maintainer actually needed --
    that it is inert until something points at it, and which file that setting lives
    in -- are pinned here rather than left to whatever the bullet happens to say.
    """
    body = scaffold.render_owned(scaffold.OWNED_DIR + "/README.md", _config())
    assert "statusline.py" in body, body
    assert scaffold.SETTINGS_PATH in body, scaffold.SETTINGS_PATH
    assert "statusLine" in body
