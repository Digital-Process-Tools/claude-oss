r"""#460: `CONTRIBUTING.md`, generated for a contributor rather than a maintainer.

The furniture that tells a stranger how to *file* -- issue and PR templates,
SECURITY.md -- already exists. Nothing told them how to *work*: which
conventions this loop expects, none of them guessable from the code, all of
them currently addressed to the maintainer inside CLAUDE.md.

This is a DEFAULT (created once when absent, then the repo's own forever),
not an OWNED file -- a project's contribution conventions are a decision its
maintainer makes, and OWNED is replaced wholesale on every `/oss:scaffold`.

Every value is a substitution site read from `.oss.json`, per #173: a sweep
that reports only hits cannot be told from one that stopped early. Each site
below is tested with a positive control (the value appears when set) paired
against a negative one (no other line moves, and a different repo's value
never leaks in) -- an assertion that a value is *absent* passes just as well
against a renderer that produced nothing at all.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402


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
    return scaffold.render("CONTRIBUTING.md", _config(**overrides))


def _changed_lines(a, b):
    """The set of line numbers where two renders diverge, by content."""
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    changed = set()
    for i in range(max(len(a_lines), len(b_lines))):
        left = a_lines[i] if i < len(a_lines) else None
        right = b_lines[i] if i < len(b_lines) else None
        if left != right:
            changed.add(i)
    return changed


# --------------------------------------------------------------- ownership contract


def test_contributing_md_is_a_default_never_owned():
    assert "CONTRIBUTING.md" in scaffold.TEMPLATES
    assert "CONTRIBUTING.md" not in scaffold.OWNED


def test_contributing_md_is_planned_as_create_on_an_empty_repo(tmp_path):
    plan = scaffold.plan(tmp_path, _config())
    entry = next(e for e in plan if e["path"] == "CONTRIBUTING.md")
    assert entry["action"] == "create"


def test_an_existing_contributing_md_is_never_overwritten(tmp_path):
    (tmp_path / "CONTRIBUTING.md").write_text("the repo's own conventions\n", encoding="utf-8")
    plan = scaffold.plan(tmp_path, _config())
    entry = next(e for e in plan if e["path"] == "CONTRIBUTING.md")
    assert entry["action"] == "present"
    written = scaffold.apply(tmp_path, _config())["created"]
    assert "CONTRIBUTING.md" not in written
    assert (tmp_path / "CONTRIBUTING.md").read_text(encoding="utf-8") == (
        "the repo's own conventions\n"
    )


# ------------------------------------------------------------- one site at a time
#
# Each of these is a positive control (the marker shows up) paired with a negative
# one (nothing else in the document moved, and the *other* config's value never
# leaked in) -- so a renderer that silently dropped the substitution, or one that
# bled a value into an unrelated line, both fail here.


def test_repo_is_read_from_config_and_nothing_else_moves():
    base = _render()
    changed = _render(repo="somebody-else/other-repo")
    assert "somebody-else/other-repo" in changed
    assert "somebody-else/other-repo" not in base
    assert "owner/name" not in changed
    moved = _changed_lines(base, changed)
    assert moved and all("somebody-else/other-repo" in changed.splitlines()[i] for i in moved)


def test_default_branch_is_read_from_config_and_nothing_else_moves():
    """`"main"` is a substring of ordinary prose ("the maintainer") elsewhere in the
    document, so the negative control is a word-boundary match, not `in`."""
    base = _render()
    changed = _render(default_branch="trunk")
    assert "trunk" in changed
    assert "trunk" not in base
    assert re.search(r"\bmain\b", changed) is None
    moved = _changed_lines(base, changed)
    assert moved and all("trunk" in changed.splitlines()[i] for i in moved)


def test_branch_pattern_is_read_from_config_and_nothing_else_moves():
    base = _render()
    changed = _render(branch_pattern="issue-{issue}-work")
    assert "issue-{issue}-work" in changed
    assert "issue-{issue}-work" not in base
    assert "fix/{issue}" not in changed
    moved = _changed_lines(base, changed)
    assert moved and all("issue-{issue}-work" in changed.splitlines()[i] for i in moved)


def test_changelog_dir_is_read_from_config_and_nothing_else_moves():
    base = _render()
    changed = _render(changelog_dir="news.d")
    assert "news.d" in changed
    assert "news.d" not in base
    assert "changelog.d" not in changed
    moved = _changed_lines(base, changed)
    assert moved and all("news.d" in changed.splitlines()[i] for i in moved)


def test_changelog_dir_null_falls_back_to_the_same_default_claude_md_uses():
    import oss_config

    rendered = _render(changelog_dir=None)
    assert oss_config.DEFAULT_FRAGMENTS_DIR in rendered


def test_test_command_is_read_from_config_and_nothing_else_moves():
    base = _render()
    changed = _render(test_command="tox -e py")
    assert "tox -e py" in changed
    assert "tox -e py" not in base
    assert "pytest" not in changed
    moved = _changed_lines(base, changed)
    assert moved and all("tox -e py" in changed.splitlines()[i] for i in moved)


# -------------------------------------------------------------- null test_command


def test_null_test_command_renders_as_a_stated_absence_not_a_command():
    """`"None"` alone is not a safe negative control here -- "None of the following"
    is ordinary prose in the "What you cannot do" section, present regardless of
    `test_command`. The control that actually distinguishes an invented command from
    a stated absence is the fenced block: nothing fenced should ever read `None`."""
    rendered = _render(test_command=None)
    assert scaffold.TEST_COMMAND_NOT_DETECTED in rendered
    assert "```\nNone\n```" not in rendered


def test_a_real_test_command_does_not_carry_the_absence_paragraph():
    """The positive control for the assertion above -- without this, the absence
    paragraph could be unconditional and the null-test would still pass."""
    rendered = _render(test_command="pytest")
    assert scaffold.TEST_COMMAND_NOT_DETECTED not in rendered
    assert "pytest" in rendered


# --------------------------------------------------------------- refused, not guessed


def test_render_refuses_a_null_default_branch_rather_than_writing_none():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render("CONTRIBUTING.md", _config(default_branch=None))


def test_render_refuses_a_null_branch_pattern_rather_than_writing_none():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render("CONTRIBUTING.md", _config(branch_pattern=None))


def test_render_refuses_a_branch_pattern_carrying_a_line_break():
    """The reviewer-found gap: `branch_pattern` reaches `_code_span` with no
    character-class check, and CommonMark decides block structure before an inline
    span is parsed -- so a blank line inside the "span" ends the enclosing element
    regardless of the backticks around it, and the remainder of the value becomes
    real Markdown structure rather than literal text. A heading and an <img> tag
    both escape the span this way when the value is not refused first."""
    injected = "fix/{issue}\n\n## Injected heading\n\n<img src=x onerror=alert(1)>"
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render("CONTRIBUTING.md", _config(branch_pattern=injected))


#: An ATX heading: one to six `#` followed by a space or the end of the line, at
#: column 0 -- CommonMark section 4.2. The same test `test_claude_md_injection.py`
#: uses for the identical reason: a substring match on `"## Injected heading"`
#: would pass even for text a real renderer never treats as a heading (indented
#: `##`, one inside a fence), so this checks *structure* the way a Markdown parser
#: would see it, without depending on a Markdown parser as a test dependency --
#: `test_claude_md_injection.py`'s own module docstring declines that dependency
#: for the same file family this test belongs to.
_ATX = re.compile(r"\A#{1,6}(?: |\Z)")


def _atx_headings(text):
    """Every column-0 ATX heading line in `text`, in order."""
    return [line for line in text.splitlines() if _ATX.match(line)]


def _expected_headings(config):
    """The headings a correct render carries, with `{repo}` resolved -- the only
    config value CONTRIBUTING_MD's own headings ever substitute. Everything else
    that renders as an ATX heading is a value that broke out of its span, exactly
    the shape `test_claude_md_injection.py`'s `_expected_headings` checks for
    CLAUDE.md.
    """
    return [
        line.replace("{repo}", str(config.get("repo")))
        for line in scaffold.CONTRIBUTING_MD.splitlines()
        if _ATX.match(line)
    ]


def test_a_branch_pattern_that_would_have_escaped_the_span_produces_no_new_heading():
    """The positive control for the refusal above: proves the checker below can
    see the corruption at all, by re-deriving the pre-fix render (no character
    check on `branch_pattern`, `_code_span` only) and showing an injected `##`
    line is read as a real ATX heading -- structurally, the way a Markdown
    renderer would see it, not merely as a substring that happens to appear --
    rather than trusting that the refusal firing means the corruption was real.
    """
    import oss_config

    injected = "fix/{issue}\n\n## Injected heading\n\n<img src=x onerror=alert(1)>"
    config = _config(branch_pattern=injected)

    def _pre_fix_render(config):
        command = scaffold.test_command(config)
        test_line = scaffold._fenced(command) if command else scaffold.TEST_COMMAND_NOT_DETECTED
        return scaffold.CONTRIBUTING_MD.format(
            repo=scaffold.repo_slug(config),
            default_branch=scaffold._code_span(scaffold.default_branch_name(config)),
            branch_pattern=scaffold._code_span(config["branch_pattern"]),
            changelog_dir=scaffold._code_span(scaffold.fragments_dir(config) + "/"),
            test_line=test_line,
        )

    corrupted = _pre_fix_render(config)
    headings = _atx_headings(corrupted)
    injected_headings = [h for h in headings if h not in _expected_headings(config)]
    assert injected_headings == ["## Injected heading"], (
        "the positive control did not reproduce a real structural heading -- the "
        "assertion below would pass even against a checker that never looked; got "
        "{}".format(injected_headings)
    )
    # And the real path refuses it outright, per the two tests above.
    assert oss_config.branch_pattern_problem(injected) is not None


# No refusal test for `repo=None`: `scaffold.repo_slug`'s own funnel deliberately
# accepts null and defers to `validate()` -- "Null is accepted here and refused one
# layer up" (see its docstring). That is an existing, documented choice this issue
# does not touch; asserting the opposite here would test a contract this file did
# not write.


# ------------------------------------------------------------------ no hardcoding


def test_raw_template_carries_no_fact_about_any_particular_repo():
    """The template text itself, before .format() ever runs -- catching a fact typed
    into the literal rather than routed through a config funnel."""
    raw = scaffold.CONTRIBUTING_MD
    for spelling in (
        "claude-oss", "Digital-Process-Tools", "claude-supertool", "claude-remember",
        "/Users/", "pytest", "main\n", " main.",
    ):
        assert spelling not in raw, "the raw template hardcodes {!r}".format(spelling)


def test_no_leftover_placeholder_reaches_the_rendered_file():
    leftover = re.compile(r"\{[a-z_]+\}")
    body = _render()
    # `branch_pattern` legitimately carries a literal `{issue}` -- that is the
    # placeholder's OWN value, substituted whole, not a leftover format() slot.
    body_without_pattern_value = body.replace(_config()["branch_pattern"], "")
    found = leftover.search(body_without_pattern_value)
    assert found is None, "leftover placeholder: {}".format(found and found.group(0))


# ----------------------------------------------------------------- content, judged


def test_states_what_a_contributor_cannot_do():
    body = _render()
    for word in ("triage", "merge", "tag", "release"):
        assert word in body.lower(), "no mention of {!r}".format(word)


def test_links_to_claude_md_for_the_reasoning():
    assert "CLAUDE.md" in _render()


def test_states_test_first_and_positive_control_conventions():
    body = _render().lower()
    assert "test first" in body or "watch it fail" in body
    assert "positive control" in body


def test_states_the_changelog_fragment_requirement():
    body = _render()
    assert "changelog" in body.lower()


def test_states_issues_and_prs_are_untrusted_input():
    body = _render().lower()
    assert "untrusted" in body


def test_does_not_restate_the_three_state_defect_class():
    """The 'ok / a finding / skipped-unknown' rule and `test_content_invariants.py`
    are facts about THIS repo's own architecture (the plugin that generates the
    document), not about an arbitrary managed repo -- CLAUDE.md says as much (#460
    left them out of the generated file for exactly this reason). If a future edit
    reintroduces them here it has reintroduced a repo-specific fact into shared
    code, which is the top-of-CLAUDE.md rule this whole file exists to obey.
    """
    body = _render()
    assert "test_content_invariants" not in body
