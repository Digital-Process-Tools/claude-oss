"""What a watch channel name may be, as one rule with one owner (#230).

`bin/oss-workspace` produces such a name by two routes -- one declared in a managed
repository's tracked `.supertool.json`, one derived from `repo` in `.oss.json` -- and
until #230 only the second was checked. A guard and its bypass in one file.

The rule tested here is deliberately NOT the consumer's own `NAME_RE`. That pattern
belongs to supertool, it caps the length at 32 and it constrains the first character,
and transcribing it into this repository would put a second spelling of somebody
else's rule here to drift. What `watch_name_problem` refuses is the narrower thing
this plugin can argue for on its own: a value that cannot be used as a PATH
COMPONENT, because the consumer turns the name into a socket path and a poller state
directory. Whether the consumer will then also accept it is a different question,
asked at run time and reported rather than refused (#231).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import oss_config  # noqa: E402

BACKSLASH = chr(92)

#: Every value the launcher exported verbatim before #230, measured on the real
#: script rather than imagined: see the table in the issue.
REFUSED = [
    "../../../tmp/pwned",
    "a\nb",
    "..",
    ".",
    "sub/dir",
    "back" + BACKSLASH + "slash",
    "",
    "has space",
    "tab\there",
    "nul\x00byte",
]


@pytest.mark.parametrize("value", REFUSED)
def test_a_name_that_is_not_a_path_component_is_refused(value):
    problem = oss_config.watch_name_problem(value)
    assert problem, "{!r} was accepted".format(value)
    # The sentence has to carry the value, because the receipt the launcher prints
    # is the only place a maintainer sees which of their two files said this.
    assert "watch name" in problem


#: The must-fire half. Without it every assertion above is satisfied by a function
#: that refuses everything, which would take the private channel away from every
#: repository that has one -- the exact cost weighed in the issue.
ACCEPTED = [
    "owner-name",
    "Digital-Process-Tools-claude-oss",
    # Longer than the consumer's cap and not this function's business to refuse:
    # #231 asks the consumer about this one and reports the answer.
    "Digital-Process-Tools-claude-supertool",
    # A leading dash: refused by the consumer, and not a path harm. Same split.
    "-owner-name",
    "a",
    "dots.and_1-2",
]


@pytest.mark.parametrize("value", ACCEPTED)
def test_a_usable_name_is_accepted(value):
    assert oss_config.watch_name_problem(value) is None


def test_a_non_string_is_refused_rather_than_coerced():
    """`None` is the value a caller reaches by asking for a key that is not there.

    Coercing it would export the string 'None' -- a private socket nobody publishes
    to, which is the quiet wrong state the launcher's whole shape refuses.
    """
    for value in (None, 42, ["a"]):
        assert oss_config.watch_name_problem(value)


def test_every_name_the_derivation_can_produce_passes_this_rule():
    """The claim `watch_channel_name`'s docstring makes, measured instead of argued.

    That docstring says a validated slug carries exactly one slash, the fold always
    turns it into a dash, so the result holds no separator and can never be `.` or
    `..`. It is stated as prose beside the code. Here it is a measurement over the
    values that reach it, so a later edit to `REPO_RE` or to the fold that breaks
    the claim reddens rather than quietly widening what the launcher exports.
    """
    slugs = [
        "owner/name",
        "Org.Name/re+po",
        "Digital-Process-Tools/claude-oss",
        "Digital-Process-Tools/claude-supertool",
        "-owner/name",
        "./..",
        "a/b",
        "中文/中文",
    ]
    checked = 0
    for slug in slugs:
        name, problem = oss_config.watch_channel_name(slug)
        if problem:
            continue
        checked += 1
        assert oss_config.watch_name_problem(name) is None, (
            "{!r} folds to {!r}, which the name rule refuses".format(slug, name)
        )
    # The positive control on the loop itself: a fixture list where every entry was
    # refused upstream would satisfy the loop without measuring anything.
    assert checked >= 4, "fixture produced only {} accepted folds".format(checked)
