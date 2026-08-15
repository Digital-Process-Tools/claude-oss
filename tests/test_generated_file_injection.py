r"""A validated value must not be able to break the file it is written into.

`.oss.json` is a tracked file in every managed repository, so its values arrive
through ordinary contributor pull requests. Several of them are interpolated
into `.github/workflows/oss-changelog.yml` -- a file this plugin writes into
somebody else's repository -- and one of them, `changelog_dir`, lands on four
separate lines of it.

Python's `$` matches **before a trailing newline**, so `^\d+\.\d+\.\d+$` accepts
`"0.1.0\n"` and `^[A-Za-z0-9._-]+$` accepts `"changelog.d\n"` (#173). The harm
is not shell escape -- a newline cannot leave a single-quoted string. The harm
is YAML: the remainder of the command lands at column 0, which ends the `run:`
scalar and stops the workflow parsing. The forge then reports a parse error in
the Actions tab and **nothing blocks the pull request**: the changelog gate is
off, and renders exactly like a gate that found nothing. That is this
repository's own defect class, shipped into other people's repositories.

So the assertions here are about the rendered workflow's structure, not about a
regex returning False. And every "must not fire" case sits beside a "must fire"
case built from the same fixture: `test_the_structure_check_sees_a_broken_workflow`
restores the old pattern and proves the checker below reports the corruption, so
a green run on a good value means the check looked -- rather than that it could
not look at all.

Deliberately not a YAML parse: pyyaml is not a dependency of this repo (the same
reason `test_workflow_permissions.py` gives), and the mechanism is a block-scalar
boundary, which is exactly what the column-0 rule below measures.

Python 3.9 compatible.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402

GENERATED_WORKFLOW = ".github/workflows/oss-changelog.yml"

#: A line at column 0 of a YAML document may only be a top-level key, a comment
#: or blank. Anything else is a continuation line that escaped its block.
TOP_LEVEL_KEY = re.compile(r"\A[A-Za-z_][A-Za-z0-9_-]*:(?: |\Z)")

#: The top-level keys the generated workflow is supposed to have. Pinned as a set
#: because the column-0 rule alone would accept an injected key: a `changelog_dir`
#: of "changelog.d\nname: evil" breaks the same block scalar and lands on a line
#: YAML reads as perfectly legal.
EXPECTED_TOP_LEVEL = {"name", "on", "permissions", "jobs"}

#: The patterns as they stood before #173, used to reproduce the defect rather
#: than describe it. Kept verbatim: a control built by mutating the fixed pattern
#: would go stale silently the next time the pattern changes.
OLD_PATTERNS = {
    "CHANGELOG_DIR_RE": r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$",
    "CHANGELOG_UNTAGGED_RE": r"^\d+\.\d+\.\d+$",
    "REPO_RE": r"^[^/\s]+/[^/\s]+$",
}


def _config(**overrides):
    config = {
        "repo": "owner/name",
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
    config.update(overrides)
    return config


def _render(**overrides):
    return scaffold.render_owned(GENERATED_WORKFLOW, _config(**overrides))


def structure_problems(text):
    """Every way the rendered workflow has stopped being the document it claims.

    Returns a list of sentences. Empty means the structure is intact -- and the
    positive control below is what makes an empty list a measurement.
    """
    problems = []
    seen = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith(" ") or line.startswith("#"):
            continue
        if not TOP_LEVEL_KEY.match(line):
            problems.append(
                "line {}: {!r} sits at column 0 and is not a top-level key, so a "
                "block above it ended early".format(number, line)
            )
            continue
        seen.append(line.split(":", 1)[0])

    unexpected = sorted(set(seen) - EXPECTED_TOP_LEVEL)
    if unexpected:
        problems.append(
            "unexpected top-level key(s) {}: a value broke out of its block and "
            "landed on something YAML reads as a key".format(", ".join(unexpected))
        )
    missing = sorted(EXPECTED_TOP_LEVEL - set(seen))
    if missing:
        problems.append(
            "missing top-level key(s) {}: the template did not render what this "
            "check was written to inspect".format(", ".join(missing))
        )
    return problems


# --- the positive control -------------------------------------------------
#
# Without these two, every assertion further down would also pass against a
# renderer that produced an empty string and a checker that never looked.


@pytest.mark.parametrize(
    "key, attribute, value",
    [
        ("changelog_dir", "CHANGELOG_DIR_RE", "changelog.d\n"),
        ("changelog_untagged", "CHANGELOG_UNTAGGED_RE", ["0.1.0\n"]),
    ],
)
def test_the_structure_check_sees_a_broken_workflow(monkeypatch, key, attribute, value):
    """Put the pre-#173 pattern back and the corruption is real, and visible here."""
    monkeypatch.setattr(oss_config, attribute, re.compile(OLD_PATTERNS[attribute]))

    # The restored pattern must actually admit the hostile value, or this control
    # proves nothing about the renderer.
    problem = getattr(oss_config, "{}_problem".format(key))(value)
    assert problem is None, (
        "the pre-fix pattern refused {!r}, so this control never reached the "
        "renderer: {}".format(value, problem)
    )

    problems = structure_problems(_render(**{key: value}))
    assert problems, (
        "a newline in {} rendered a workflow this check called intact -- that "
        "makes the check blind, not the value safe".format(key)
    )
    assert any("column 0" in problem for problem in problems), problems


def test_the_good_render_is_intact():
    """The other half of the control: the checker passes something real."""
    assert structure_problems(_render()) == []
    assert structure_problems(_render(changelog_untagged=["0.1.0"])) == []
    assert structure_problems(_render(changelog_untagged=[])) == []


# --- the refusals ---------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "changelog.d\n",
        "\nchangelog.d",
        "changelog.d\nname: evil",
        "changelog.d\r",
        "docs/changelog.d\n",
    ],
)
def test_a_line_break_in_changelog_dir_is_refused(value):
    problem = oss_config.changelog_dir_problem(value)
    assert problem is not None, (
        "{!r} validated. It is interpolated into four `run:` lines of the "
        "workflow generated for another repository.".format(value)
    )
    assert "changelog_dir" in problem
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.fragments_dir(_config(changelog_dir=value))


@pytest.mark.parametrize(
    "value",
    [
        ["0.1.0\n"],
        ["\n0.1.0"],
        ["0.1.0\r"],
        ["0.1.0", "0.2.0\n"],
    ],
)
def test_a_line_break_in_changelog_untagged_is_refused(value):
    problem = oss_config.changelog_untagged_problem(value)
    assert problem is not None, (
        "{!r} validated. It is interpolated into the `--check-links` line of "
        "the workflow generated for another repository.".format(value)
    )
    assert "changelog_untagged" in problem
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.untagged_declaration(_config(changelog_untagged=value))


@pytest.mark.parametrize("value", ["owner/name\n", "\nowner/name", "owner/name\r"])
def test_a_line_break_in_repo_is_refused(value):
    """The third instance of the idiom, found by the sweep rather than the audit.

    `repo` reaches a generated file too: `_render_claude_md` puts it in the H1 of
    the CLAUDE.md this plugin writes. Markdown survives a stray newline where YAML
    does not, so this one is a smaller harm and the same defect -- fixed here
    because leaving one instance of an idiom live is how the idiom gets copied.
    """
    problems = oss_config.validate(_config(repo=value))
    assert [p for p in problems if p.startswith("repo:")], problems


# --- the other side: do not trade the loud bug for the quiet one ----------
#
# `scripts/oss_config.py` already says tighter than this refuses a legitimate
# repository to close a hole that quoting already closes. So every value that
# validated before the fix still has to validate after it.


@pytest.mark.parametrize(
    "value",
    ["changelog.d", "news.d", "docs/changelog.d", "changelog", "_news", "a.b-c/d_e-1"],
)
def test_legitimate_changelog_dirs_still_validate(value):
    assert oss_config.changelog_dir_problem(value) is None
    assert scaffold.fragments_dir(_config(changelog_dir=value)) == value


def test_a_null_changelog_dir_is_still_the_third_state():
    assert oss_config.changelog_dir_problem(None) is None
    assert (
        scaffold.fragments_dir(_config(changelog_dir=None))
        == scaffold.DEFAULT_FRAGMENTS_DIR
    )


@pytest.mark.parametrize("value", [["0.1.0"], [], None, ["0.1.0", "10.20.30"]])
def test_legitimate_changelog_untagged_still_validates(value):
    assert oss_config.changelog_untagged_problem(value) is None


@pytest.mark.parametrize("value", ["owner/name", "Owner/name.py", "o-w/n_1"])
def test_legitimate_repos_still_validate(value):
    assert [
        p for p in oss_config.validate(_config(repo=value)) if p.startswith("repo:")
    ] == []


# --- the sweep, pinned ----------------------------------------------------


@pytest.mark.parametrize("name", sorted(OLD_PATTERNS))
def test_every_swept_pattern_is_anchored_at_the_text_end(name):
    r"""`\A...\Z`, not `^...$`, and pinned so the idiom cannot come back by copy.

    The anchors live in the pattern rather than at the call site on purpose: a
    caller reaching for `.match` or `.search` cannot then lose them. This is the
    spelling `scripts/assemble_changelog.py` already uses, with the same reason
    written beside it.
    """
    pattern = getattr(oss_config, name).pattern
    assert pattern.startswith(r"\A"), (name, pattern)
    assert pattern.endswith(r"\Z"), (name, pattern)
