"""The seed rule scaffold writes into a repo's rules directory.

It is a rule about writing rules, so it has to survive being one: valid frontmatter,
keywords that actually match what someone types when they have this problem, and no
"go look it up" indirection -- an entry that loads and still leaves the reader guessing
cost a load and returned nothing.

These assert content because content is the product here. Prose has no compiler.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402

RULE_PATH = ".claude/jit-context/00-writing-rules.md"


def _config():
    return {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": None,
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "ci": {"required_checks": 0},
        "state_file": ".max/oss-watch.json",
    }


def _body():
    return scaffold.render(RULE_PATH, _config())


def test_the_seed_rule_is_scaffolded():
    assert RULE_PATH in scaffold.TEMPLATES


def test_it_lands_in_the_rules_directory_where_the_matcher_looks(tmp_path):
    scaffold.apply(tmp_path, _config())
    assert (tmp_path / ".claude" / "jit-context" / "00-writing-rules.md").is_file()


def test_it_has_the_frontmatter_a_rule_needs():
    body = _body()
    assert body.startswith("---\n")
    block = body[4 : body.index("\n---\n", 3)]
    for key in ("title:", "description:", "keywords:"):
        assert key in block, key


def test_its_keywords_match_what_someone_would_actually_type():
    """Keywords are how it is found. The words belong to whoever has the problem, not
    to whoever already knows the answer.
    """
    block = _body().split("\n---\n")[0]
    keywords = re.search(r"^keywords:\s*(.+)$", block, re.MULTILINE).group(1)
    listed = {k.strip() for k in keywords.split(",")}
    for expected in ("rule", "vocabulary", "gotcha", "write a rule"):
        assert expected in listed, expected


def test_it_says_the_index_is_what_the_matcher_reads():
    """The one failure that makes every other rule silently useless."""
    body = _body()
    assert "index" in body
    assert "rebuild" in body.lower()


def test_it_gives_the_three_kinds_worth_writing():
    body = _body()
    assert "looked up twice" in body
    assert "cost a run" in body
    assert "exact" in body


def test_it_carries_a_worked_example_of_bad_and_good():
    """Telling someone to be specific, without showing it, is itself the vague advice
    it warns against.
    """
    body = _body()
    assert "Bad" in body and "Good" in body


def test_it_contains_no_go_look_it_up_indirection():
    """Quoted anti-examples do not count. The rule names "see the docs" as the thing
    not to write, and a check that cannot tell a quotation from a use would force the
    text to stop demonstrating its own point.
    """
    body = _body().lower()
    for phrase in ("see the docs", "refer to the documentation", "check the wiki"):
        unquoted = re.compile(r'(?<!["“\'])' + re.escape(phrase))
        assert unquoted.search(body) is None, phrase


def test_it_names_no_specific_repo():
    body = _body()
    for spelling in ("Digital-Process-Tools", "claude-supertool", "claude-remember"):
        assert spelling not in body, spelling
