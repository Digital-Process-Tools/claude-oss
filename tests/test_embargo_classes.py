"""The join between the security policy's embargo classes and the ranking table (#139).

`SECURITY.md` promises embargoed handling -- fixed and released before it is discussed
publicly -- for a named list of classes. `skills/manager/SKILL.md` ranks classes by cost
and marks some of them release-blocking. After #83 the second list grew to six rows while
the first still named three, so a reporter reading the policy could not tell that a
`forges` finding would stop a tag, and could read the narrow list as permission to
disclose publicly first.

## These are two lists on purpose, and the difference is the point

Blocking a tag asks *what may this project ship*. An embargo asks *should a reporter hold
disclosure*. They agree on most rows and they do not agree on all of them:

- `destroys`, `discloses`, `containment (read)`, `containment (write)` and `forges` all
  become an exploit recipe the moment they are described in public, against installed
  users who have no fix yet. `forges` most sharply of all -- the attacker's delivery
  channel *is* a public tracker, so a public writeup is the payload.
- `ships-local-state` blocks a release for a reason that says nothing about disclosure:
  the release is the mechanism by which it takes effect. The value is baked into an
  artifact anybody can already read, so there is no window of privileged knowledge for an
  embargo to protect, and the fastest fix comes from reporting it in the open. (A local
  path that is itself a *secret* is `discloses`, which is a different row.)

So the guard below is not set equality. It is a declared mapping, and the state that
matters is the one where a row is in neither half: a seventh blocking row appears and
nobody decided whether a reporter should hold it.

## Why a mapping and not a reference

`SECURITY.md` could simply point at the ranking table and stay in step by construction.
It must not: it is one of the `defaults` this plugin scaffolds into other people's
repositories, where `skills/manager/SKILL.md` does not exist -- and a security policy that
redirects a reporter into a maintainer-facing process file is worse for the person reading
it. It names its own classes, in reporter-facing words, and this test is the join.

## `containment` is one bullet on purpose

The table has two `containment` rows because they invite different fixes. A reporter does
not choose our chokepoint, so the policy keeps one bullet whose description covers both
directions, and the mapping below is many-to-one. That is a decision, not an oversight.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402

# The ranking table parser ships once, in the module that owns it -- the same discipline
# the rows themselves are held to. A second copy here would drift exactly like a second
# copy of the rows.
from test_content_invariants import (  # noqa: E402
    RANKING_BLOCKS,
    _ranking_table,
)

SECURITY_MD = REPO_ROOT / "SECURITY.md"

EMBARGO_MARKER = "before it is discussed publicly"
EMBARGO_BULLET = re.compile(r"^- \*\*([a-z][a-z -]*)\*\* --")


def _embargo_classes(text):
    """The classes SECURITY.md promises embargoed handling for.

    None when the promise sentence is not findable at all, which is a different answer
    from "the list is empty": a policy that was reworded is not a policy with no classes,
    and the callers below must never read the first as agreement.
    """
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if EMBARGO_MARKER in line:
            start = i
            break
    if start is None:
        return None
    names = []
    seen_list = False
    for line in lines[start + 1:]:
        match = EMBARGO_BULLET.match(line)
        if match:
            seen_list = True
            names.append(match.group(1).strip())
            continue
        if seen_list and line.strip() and not line.startswith(" "):
            break
    return names


# Every blocking ranking row is in exactly one of these two. The value on the left is the
# reporter-facing bullet in SECURITY.md; two rows mapping to one bullet is intended.
EMBARGOED_BY_ROW = {
    "destroys": "destroys",
    "discloses": "discloses",
    "containment (read)": "containment",
    "containment (write)": "containment",
    "forges": "forges",
}

# A blocking row deliberately outside the embargo promise, with the reason. A bare set
# would render "we decided not to" identically to "nobody got to it".
NOT_EMBARGOED_BY_ROW = {
    "ships-local-state": (
        "the value is already readable in the released artifact, so there is no window "
        "of privileged knowledge an embargo could protect; it blocks a tag because the "
        "release is how it takes effect, which is an argument about tags and not about "
        "disclosure timing"
    ),
}


def _embargo_join_problems(rows, classes, embargoed, not_embargoed):
    """Every way the two lists can disagree, as a tuple of sentences. Empty means they
    agree. Shared by the real check and its positive controls, so the controls exercise
    the same code the check runs.
    """
    if rows is None:
        return ("no ranking table",)
    if classes is None:
        return ("no embargo class list",)
    blocking = {name for name, verdict in rows if verdict == RANKING_BLOCKS}
    if not blocking and not classes:
        # Two absences agreeing is not agreement.
        return ("no classes on either side",)

    problems = []

    both = sorted(set(embargoed) & set(not_embargoed))
    if both:
        problems.append(
            "these rows are declared both embargoed and deliberately not: {!r}".format(both)
        )

    reasonless = sorted(row for row, why in not_embargoed.items() if not (why or "").strip())
    if reasonless:
        problems.append(
            "these rows are declared outside the embargo with no reason: {!r}".format(reasonless)
        )

    for row in sorted(blocking):
        if row in embargoed:
            bullet = embargoed[row]
            if bullet not in classes:
                problems.append(
                    "blocking row {!r} maps to embargo class {!r}, which SECURITY.md "
                    "does not name".format(row, bullet)
                )
        elif row not in not_embargoed:
            problems.append(
                "blocking row {!r} is neither mapped to an embargo class nor declared "
                "deliberately outside the embargo -- decide which".format(row)
            )

    mapped = set(embargoed.values())
    for name in sorted(classes):
        if name not in mapped:
            problems.append(
                "SECURITY.md promises embargoed handling for {!r}, which no blocking "
                "ranking row maps to".format(name)
            )

    stale = sorted((set(embargoed) | set(not_embargoed)) - blocking)
    if stale:
        problems.append(
            "these rows are classified here but no longer block a release, so nobody "
            "re-decided them: {!r}".format(stale)
        )

    return tuple(problems)


def test_the_embargo_list_is_findable_and_named():
    """Vacuity guard. Every check below reads this list; a policy that was reworded
    would make them pass over nothing, which is this plugin's own defect class arriving
    inside the suite meant to catch it.
    """
    classes = _embargo_classes(SECURITY_MD.read_text(encoding="utf-8"))
    assert classes is not None, (
        "SECURITY.md no longer contains {!r}, so the embargo list cannot be parsed and "
        "every check below would pass vacuously".format(EMBARGO_MARKER)
    )
    assert classes, "SECURITY.md's embargo list parsed as empty"
    assert len(classes) == len(set(classes)), "duplicate embargo classes: {!r}".format(classes)


def test_the_security_policy_and_the_ranking_table_agree_about_the_embargo():
    """The join. A row added to the ranking table as blocking goes red here until
    somebody decides whether a reporter should hold disclosure for it.
    """
    problems = _embargo_join_problems(
        _ranking_table(),
        _embargo_classes(SECURITY_MD.read_text(encoding="utf-8")),
        EMBARGOED_BY_ROW,
        NOT_EMBARGOED_BY_ROW,
    )
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    "rows, classes, embargoed, not_embargoed, expected_fragment",
    [
        # A seventh blocking row nobody ruled on -- the case this test exists for.
        (
            [("destroys", RANKING_BLOCKS), ("mangles", RANKING_BLOCKS)],
            ["destroys"],
            {"destroys": "destroys"},
            {},
            "'mangles' is neither mapped",
        ),
        # A mapped row whose bullet the policy does not actually name.
        (
            [("forges", RANKING_BLOCKS)],
            ["destroys"],
            {"forges": "forges"},
            {},
            "which SECURITY.md does not name",
        ),
        # A promise with nothing behind it.
        (
            [("destroys", RANKING_BLOCKS)],
            ["destroys", "invents"],
            {"destroys": "destroys"},
            {},
            "no blocking ranking row maps to",
        ),
        # A row declared outside the embargo with no reason given.
        (
            [("destroys", RANKING_BLOCKS), ("ships-local-state", RANKING_BLOCKS)],
            ["destroys"],
            {"destroys": "destroys"},
            {"ships-local-state": "   "},
            "with no reason",
        ),
        # Both halves at once.
        (
            [("destroys", RANKING_BLOCKS)],
            ["destroys"],
            {"destroys": "destroys"},
            {"destroys": "because"},
            "both embargoed and deliberately not",
        ),
        # The table shrank and the mapping did not.
        (
            [("destroys", RANKING_BLOCKS)],
            ["destroys"],
            {"destroys": "destroys", "forges": "forges"},
            {},
            "no longer block a release",
        ),
        # Neither list could be read. Both must report, never agree.
        (None, ["destroys"], {}, {}, "no ranking table"),
        ([("destroys", RANKING_BLOCKS)], None, {}, {}, "no embargo class list"),
        ([], [], {}, {}, "no classes on either side"),
        ([("misreports", "can ship behind a filed issue")], [], {}, {}, "no classes on either side"),
    ],
)
def test_the_embargo_join_fires(rows, classes, embargoed, not_embargoed, expected_fragment):
    """Positive controls, one per arm. A join assertion over two lists parsed out of two
    files passes just as readily when both parsers return nothing, so every way it is
    meant to complain is run against input that is wrong on purpose.
    """
    problems = _embargo_join_problems(rows, classes, embargoed, not_embargoed)
    assert any(expected_fragment in p for p in problems), (
        "expected {!r} in {!r}".format(expected_fragment, problems)
    )


def test_the_embargo_join_is_quiet_when_the_two_agree():
    """The other half of the control: the same function must return nothing on input
    that is right, or every assertion above is satisfied by a function that always
    complains.
    """
    rows = [
        ("destroys", RANKING_BLOCKS),
        ("containment (read)", RANKING_BLOCKS),
        ("containment (write)", RANKING_BLOCKS),
        ("ships-local-state", RANKING_BLOCKS),
        ("misreports", "can ship behind a filed issue"),
    ]
    assert _embargo_join_problems(
        rows,
        ["destroys", "containment"],
        {
            "destroys": "destroys",
            "containment (read)": "containment",
            "containment (write)": "containment",
        },
        {"ships-local-state": "already public in the artifact"},
    ) == ()


def test_the_scaffolded_template_carries_the_same_classes_as_this_repos_policy():
    """`SECURITY.md` exists twice: this repo's own copy, and `SECURITY_MD` in
    scripts/scaffold.py, which is shipped into other people's repositories under the
    `defaults` contract. Fixing one and not the other is how a repo scaffolded tomorrow
    gets the list this issue was filed about.
    """
    ours = _embargo_classes(SECURITY_MD.read_text(encoding="utf-8"))
    template = _embargo_classes(scaffold.SECURITY_MD)
    assert template is not None, (
        "scripts/scaffold.py's SECURITY_MD no longer contains {!r}".format(EMBARGO_MARKER)
    )
    assert ours == template, (
        "this repo's SECURITY.md and the scaffolded template disagree about the embargo "
        "classes: {!r} vs {!r}".format(ours, template)
    )


# The list alone still reads as exhaustive, which is the half of #139 that a longer list
# does not fix: a reporter with a `ships-local-state` finding sees the classes, none of
# them theirs, and concludes the project does not consider it serious. The policy has to
# say that blocking and embargo are different questions.
EXHAUSTIVENESS_ANCHORS = (
    "release-blocking",
    "reported in the open",
)


def _flatten(text):
    """Fold case and collapse whitespace -- these anchors are multi-word and the file is
    hard-wrapped, so a raw match reports "the policy does not say this" about a policy
    that says it either side of a line break.
    """
    return " ".join(text.lower().split())


def _exhaustiveness_unmet(text):
    folded = _flatten(text)
    return tuple(a for a in EXHAUSTIVENESS_ANCHORS if a not in folded)


def test_both_security_policies_say_the_embargo_list_is_not_the_blocking_list():
    for label, text in (
        ("SECURITY.md", SECURITY_MD.read_text(encoding="utf-8")),
        ("scripts/scaffold.py SECURITY_MD", scaffold.SECURITY_MD),
    ):
        unmet = _exhaustiveness_unmet(text)
        assert not unmet, (
            "{} lists embargo classes without saying that release-blocking is a wider "
            "set, so the list reads as exhaustive: missing {!r}".format(label, unmet)
        )


def test_the_exhaustiveness_anchor_fires_on_a_policy_that_only_lists():
    """Positive control for a prose anchor -- the kind that otherwise passes green
    against a sentence nobody wrote. A bare list must report both anchors unmet, and a
    policy carrying the paragraph must report none.
    """
    only_lists = (
        "Anything in these classes is fixed and released before it is discussed "
        "publicly:\n\n- **destroys** -- data is gone with no copy anywhere\n"
    )
    assert _exhaustiveness_unmet(only_lists) == EXHAUSTIVENESS_ANCHORS
    carries_it = only_lists + (
        "\nNot everything release-blocking needs an embargo, and such a defect can be\n"
        "reported in the open.\n"
    )
    assert _exhaustiveness_unmet(carries_it) == ()
