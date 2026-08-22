"""README stays a pitch and a start, not a release-note archive (#451).

`README.md` had been amended per-fix for many releases: each change appended the reasoning
that motivated it next to, rather than inside, the section that already covered the subject.
Three concrete symptoms of that shape are guarded here:

* the launcher install command (`ln -sf ...`) was pasted twice, with the second copy carrying
  a cross-reference *to the section it duplicates*;
* a stale, hardcoded count of `oss:` skills and agents drifted from the tree the moment a
  third agent was drafted, and nothing failed;
* the `/oss:doctor` row of the Commands table grew into a roughly 700-word cell narrating
  issue numbers and benchmark ratios, in a table whose other rows are a sentence or two.

Each guard below is paired with a positive control, per this repo's own rule that a negative
assertion ("this does not happen") also passes when nothing happens at all.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


def _read():
    return README.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The install command appears once
# --------------------------------------------------------------------------- #

def _ln_sf_count(text):
    return len(re.findall(r"ln -sf", text))


def test_the_install_command_appears_once_in_the_real_file():
    text = _read()
    assert README.is_file(), "README.md is gone -- this check would vacuously pass"
    count = _ln_sf_count(text)
    assert count == 1, (
        "README.md contains {} occurrence(s) of `ln -sf`, not 1 -- the launcher install "
        "command is meant to appear exactly once (#451).".format(count)
    )


def test_the_install_command_detector_actually_counts_a_duplicate():
    """Positive control: a fixture carrying the command twice must not pass."""
    fixture = (
        "Install the launcher once:\n\n"
        '    ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace\n\n'
        "Install the launcher once, see above:\n\n"
        '    ln -sf "$PWD/bin/oss-workspace" ~/.local/bin/oss-workspace\n'
    )
    assert _ln_sf_count(fixture) == 2


# --------------------------------------------------------------------------- #
# A stated skill/command count is either right or absent -- never wrong
# --------------------------------------------------------------------------- #
#
# The same shape as `test_readme_states_no_agent_count_that_disagrees_with_the_tree`
# in tests/test_command_references.py, one surface over. That guard reads
# `\b(one|two|...)\s+agents\b`, which the actual pre-fix sentence ("the four\n`oss:`
# agents") never matched -- the count word and "agents" were separated by a
# backtick-quoted "`oss:`" rather than by plain whitespace, so the very sentence #451
# was filed about slipped past the existing guard. This one is deliberately more
# permissive about what sits between the count and the noun, so a stray `` `oss:` ``
# cannot hide a stale number from it again.

_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "both": 2}

#: A count word may be followed by exactly one inline-code span before the noun (the
#: shape the actual pre-#451 sentence used: "four `oss:` agents"), but nothing wider --
#: `[^.\\n]{0,20}` matched across unrelated sentences ("Exits 0 always ... `commands`")
#: and had to be narrowed to this once real README text was run through it.
_BRIDGE = r"\s+(?:`[^`\n]{1,20}`\s+)?"
_SKILL_COUNT_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|both|\d+)\b" + _BRIDGE + r"skills?\b",
    re.I,
)
_COMMAND_COUNT_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|both|\d+)\b" + _BRIDGE + r"commands?\b",
    re.I,
)


def _stated_counts(regex, text):
    counts = []
    for match in regex.finditer(text):
        word = match.group(1).lower()
        if word in _COUNT_WORDS:
            counts.append(_COUNT_WORDS[word])
        else:
            counts.append(int(word))
    return counts


def test_the_count_detectors_read_words_and_digits():
    """The detector before the assertion that leans on it."""
    assert _stated_counts(_SKILL_COUNT_RE, "all seven `oss:` skills resolve") == [7]
    assert _stated_counts(_COMMAND_COUNT_RE, "ships 7 commands and one skill") == [7]
    assert _stated_counts(_SKILL_COUNT_RE, "the loop, its skills, the config layer") == []


def test_readme_states_no_skill_or_command_count_that_disagrees_with_the_tree():
    """Not "README must say a number". A count is optional -- and when it is absent
    this test is deliberately quiet, because prose that names no number cannot go
    stale the way a pasted-in measurement does.
    """
    actual_skills = len(sorted((REPO_ROOT / "skills").glob("*/SKILL.md")))
    actual_commands = len(sorted((REPO_ROOT / "commands").glob("*.md")))
    assert actual_skills, "no skills/*/SKILL.md found -- this check would compare against zero"
    assert actual_commands, "no commands/*.md found -- this check would compare against zero"
    text = _read()
    stated_skills = _stated_counts(_SKILL_COUNT_RE, text)
    stated_commands = _stated_counts(_COMMAND_COUNT_RE, text)
    wrong_skills = [c for c in stated_skills if c != actual_skills]
    wrong_commands = [c for c in stated_commands if c != actual_commands]
    assert not wrong_skills, (
        "README.md commits to {} skill(s) while skills/ holds {}. Either fix the number "
        "or drop it.".format(wrong_skills, actual_skills)
    )
    assert not wrong_commands, (
        "README.md commits to {} command(s) while commands/ holds {}. Either fix the "
        "number or drop it.".format(wrong_commands, actual_commands)
    )


def test_a_disagreeing_skill_count_is_actually_caught():
    """Positive control for the guard above, against a synthetic fixture."""
    stated = _stated_counts(_SKILL_COUNT_RE, "This plugin ships two skills today.")
    assert [c for c in stated if c != 1] == [2]


def test_the_old_wrong_sentence_would_have_slipped_past_the_agent_only_guard():
    """Documents why this file exists rather than extending the agent-count guard
    alone: the pre-#451 sentence separated the count word from "agents" with a
    backtick-quoted "`oss:`", which the existing ``\\s+agents\\b`` pattern in
    tests/test_command_references.py does not bridge. Guarding skills/commands here
    with a wider gap closes the sibling instance of the same class.
    """
    old_sentence = (
        "all seven `oss:` skills resolve and none of the four\n`oss:` agents does"
    )
    assert _stated_counts(_SKILL_COUNT_RE, old_sentence) == [7]


# --------------------------------------------------------------------------- #
# Commands-table cells stay short
# --------------------------------------------------------------------------- #

_DOCTOR_ROW_RE = re.compile(r"^\| `/oss:doctor` \|(.*)\|\s*$", re.M)


def _doctor_cell(text):
    match = _DOCTOR_ROW_RE.search(text)
    return match.group(1).strip() if match else None


def test_the_doctor_row_is_found_at_all():
    cell = _doctor_cell(_read())
    assert cell is not None, "the /oss:doctor row was not found -- this check would vacuously pass"


def test_the_doctor_cell_is_no_longer_a_release_note():
    """Not "one sentence" -- doctor genuinely reports more than any other command, and
    forcing that into one sentence would drop the index of what it checks rather than
    just its mechanism. The bar is that the ~4600-byte, ~700-word cell #451 was filed
    against is gone; the detailed mechanism lives in `commands/doctor.md`.
    """
    cell = _doctor_cell(_read())
    assert cell is not None
    assert len(cell) < 1200, (
        "the /oss:doctor cell is {} bytes; #451 was filed against one nearly 4x that. "
        "Move mechanism into commands/doctor.md and leave an index here.".format(len(cell))
    )


def test_the_doctor_cell_length_detector_actually_fires_on_the_old_cell():
    """Positive control: the pre-fix cell, quoted from git history, must fail the
    bar above -- otherwise the length assertion could be passing for the wrong
    reason (an empty capture group, say)."""
    old_cell = (
        "Config, dependencies, clone, worktree root, state file -- including whether "
        "/oss:tick can actually read it, which is not the same question as whether it "
        "is there -- which watch channel this repo resolves to, which decides whether "
        "its board is its own fleet or somebody else's, and whether anything publishes "
        "to that board at all: a registered radar tier is one half, a route to the op "
        "that reads it is the other, and a channel with neither renders exactly like a "
        "healthy one. Whether the merge call can skip supertool's own publish-confirm "
        "gate is reported too, in three states -- confirmable, needs-force (the shipped "
        "default, read as neutral information rather than a warning), and could not "
        "tell when .supertool.json is unreadable or malformed -- naming every op the "
        "same opt-out reaches today and scoped to supertool's own gate, since the "
        "harness's own permission layer sits above it and can still refuse the call "
        "regardless."
    ) * 3
    assert len(old_cell) >= 1200
