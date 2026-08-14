"""Every script a command promises must exist.

A command file is prose that gets executed. A path in it that resolves to nothing
fails at the worst moment -- mid-task, in someone else's session -- and the failure
reads as the plugin being broken rather than as a line nobody checked.

The regexes here are asserted to match something. A pattern that found no references
has not verified the commands; it has only failed to look.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS = sorted((REPO_ROOT / "commands").glob("*.md"))

# ${CLAUDE_PLUGIN_ROOT}/... in a fenced command line.
PLUGIN_PATH_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")


def test_commands_exist():
    assert COMMANDS, "no commands/*.md found -- the checks below would vacuously pass"


def test_every_command_declares_frontmatter():
    for path in COMMANDS:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), "{}: no frontmatter".format(path.name)
        block = text[4 : text.index("\n---\n", 3)]
        assert "description:" in block, "{}: no description".format(path.name)
        assert "allowed-tools:" in block, "{}: no allowed-tools".format(path.name)


def test_referenced_scripts_exist():
    references = []
    missing = []
    for path in COMMANDS:
        text = path.read_text(encoding="utf-8")
        for match in PLUGIN_PATH_RE.finditer(text):
            target = match.group(1)
            references.append((path.name, target))
            if not (REPO_ROOT / target).exists():
                missing.append("{}: references {} which does not exist".format(path.name, target))

    assert references, (
        "no ${CLAUDE_PLUGIN_ROOT}/... references found in commands/. Either the commands "
        "stopped invoking scripts, or PLUGIN_PATH_RE no longer matches how they are written "
        "-- a pattern that matched nothing has checked nothing."
    )
    assert not missing, "\n  ".join([""] + missing)


def test_commands_use_the_plugin_root_variable_for_scripts():
    """A relative path works in whichever directory the author happened to be in."""
    offenders = []
    for path in COMMANDS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("python3 ") or stripped.startswith("bash ")):
                continue
            if "${CLAUDE_PLUGIN_ROOT}" not in stripped:
                offenders.append("{}:{}: {}".format(path.name, number, stripped))
    assert not offenders, (
        "script invocations must be rooted at ${CLAUDE_PLUGIN_ROOT}:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------- #
# Prose facts the surfaces have to carry.
#
# These are the easiest assertions in the repo to write vacuously: "does this
# file mention X" passes on a file that mentions X while saying the opposite,
# and on a file long enough that everything is in it somewhere. So every
# predicate below is checked three ways -- against the real file, against a
# file that says nothing on the subject, and against the real file with the
# load-bearing lines deleted. A predicate surviving all three has looked.
# --------------------------------------------------------------------------- #

SETUP_MD = REPO_ROOT / "commands" / "setup.md"
README_MD = REPO_ROOT / "README.md"

# Mentions no command, no settings file and no subject for identity.md.
SILENT = "# Setup\n\nProbe the repo and write the config. Then stop.\n"


def _without_lines_matching(text, pattern):
    return "\n".join(
        line for line in text.splitlines() if not re.search(pattern, line, re.I)
    )


def _names_the_agent_as_identity_subject(text):
    return "identity.md" in text and bool(re.search(r"who the agent is", text, re.I))


def _points_at_an_identity_example(text):
    return "identity.example.md" in text


def _names_scaffold_as_the_next_step(text):
    return "/oss:scaffold" in text and bool(re.search(r"tracked file", text, re.I))


def _names_the_settings_file_for_the_merge_rule(text):
    return ".claude/settings.local.json" in text


def _covers_both_path_spellings(text):
    return "./supertool" in text and bool(re.search(r"absolute path", text, re.I))


def _says_the_two_merge_strings_differ(text):
    return "gh-pr-merge:N:squash|force" in text and bool(
        re.search(r"different .{0,40}string", text, re.I)
    )


def _says_the_harness_gate_is_a_fourth_one(text):
    return bool(re.search(r"fourth", text, re.I)) and bool(
        re.search(r"no_publish_confirm|three opt-outs", text, re.I)
    )


# (label, predicate, pattern whose lines carry the fact)
SETUP_FACTS = [
    ("identity.md describes the agent", _names_the_agent_as_identity_subject, r"who the agent is"),
    ("an identity example is pointed at", _points_at_an_identity_example, r"identity\.example\.md"),
    ("scaffold is the next step", _names_scaffold_as_the_next_step, r"/oss:scaffold|tracked file"),
    (
        "the merge rule's file is named",
        _names_the_settings_file_for_the_merge_rule,
        r"settings\.local\.json",
    ),
    ("both path spellings are covered", _covers_both_path_spellings, r"\./supertool|absolute path"),
    ("the two merge strings differ", _says_the_two_merge_strings_differ, r"different .{0,40}string"),
    ("the harness gate is the fourth", _says_the_harness_gate_is_a_fourth_one, r"fourth"),
]

README_FACTS = [
    ("scaffold is in the launcher path", _names_scaffold_as_the_next_step, r"/oss:scaffold|tracked file"),
]

ALL_FACTS = SETUP_FACTS + README_FACTS


@pytest.mark.parametrize("label,predicate,_pattern", SETUP_FACTS, ids=[f[0] for f in SETUP_FACTS])
def test_setup_carries_the_fact(label, predicate, _pattern):
    assert predicate(SETUP_MD.read_text(encoding="utf-8")), "commands/setup.md: {}".format(label)


@pytest.mark.parametrize("label,predicate,_pattern", README_FACTS, ids=[f[0] for f in README_FACTS])
def test_readme_carries_the_fact(label, predicate, _pattern):
    assert predicate(README_MD.read_text(encoding="utf-8")), "README.md: {}".format(label)


@pytest.mark.parametrize("label,predicate,_pattern", ALL_FACTS, ids=[f[0] for f in ALL_FACTS])
def test_a_silent_file_fails_every_prose_predicate(label, predicate, _pattern):
    """The negative control. Without it, every assertion above also passes on a
    file that says nothing about the subject at all."""
    assert not predicate(SILENT), "{}: predicate passes on a file that says nothing".format(label)


@pytest.mark.parametrize("label,predicate,pattern", SETUP_FACTS, ids=[f[0] for f in SETUP_FACTS])
def test_deleting_the_carrying_lines_fails_the_predicate(label, predicate, pattern):
    """The targeted control: the real file minus the lines carrying the fact. A
    predicate still passing here is matching something incidental."""
    mutated = _without_lines_matching(SETUP_MD.read_text(encoding="utf-8"), pattern)
    assert not predicate(mutated), "{}: predicate passes with its own lines deleted".format(label)
