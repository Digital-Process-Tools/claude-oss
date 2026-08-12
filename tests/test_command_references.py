"""Every script a command promises must exist.

A command file is prose that gets executed. A path in it that resolves to nothing
fails at the worst moment -- mid-task, in someone else's session -- and the failure
reads as the plugin being broken rather than as a line nobody checked.

The regexes here are asserted to match something. A pattern that found no references
has not verified the commands; it has only failed to look.
"""

import re
from pathlib import Path

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
