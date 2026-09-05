"""#343: `changelog_dir` had a validating guard at the `.oss.json` entrance and none
at the second entrance #327 opened.

`scaffolded_changelog_gate` reads a `--dir` value back out of the tracked, owned
`.github/workflows/oss-changelog.yml` and handed it to callers as
`present-other-dir` with `problem=None`. `release_version._fragment_dir` then did
`Path(repo) / detail`, where an absolute string discards `repo` and a `..` chain
walks out of it -- and `commands/changelog.md` prints that directory as the one
"used for every command below", the last of which is a fold that unlinks every
fragment it consumes.

Two entrances, one value, one downstream use. This file is the join: whatever the
`.oss.json` entrance refuses, the workflow entrance must refuse too, and whatever
one accepts the other must accept. Stating it as an equivalence rather than as a
second copy of the rule is deliberate -- a copy passes when both copies are wrong
together, and this fails when either entrance drifts.

The third state is the point. A value that does not validate is neither `present`
nor `present-other-dir`: collapsing it into either is #325 one condition to the
left, a repo told confidently about a directory nobody validated. It is not
`unknown` either -- `unknown` means the gate could not be read, and here it was
read perfectly well and says something inadmissible. That distinction is asserted
below rather than left to the reader.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import release_version  # noqa: E402


REFUSED = "present-refused-dir"


# Values the `.oss.json` entrance already refuses, each with the harm it reaches.
# The regex is a string rule and evaluates identically on every platform; the harm
# it prevents does not, which is why the Windows spellings are here even though
# this suite resolves them under POSIX rules.
HOSTILE = [
    ("absolute-posix", "/etc"),
    ("traversal", "../../../../../../tmp"),
    ("traversal-suffixed", "changelog.d/../../../../tmp"),
    ("single-dot", "."),
    ("command-substitution", "$(rm -rf /)"),
    ("backtick", "`id`"),
    ("windows-drive", "C:/Windows/Temp"),
    ("windows-backslash", r"..\..\tmp"),
    ("newline", "changelog.d\n"),
]

# The must-not-fire half. Every one of these is a directory a real repository may
# legitimately have been scaffolded with, and the guard must leave all of them alone.
BENIGN = [
    ("default", "changelog.d"),
    ("nested", "docs/frags"),
    ("underscored", "news_d"),
    ("dashed", "change-log.d"),
    ("deeply-nested", "docs/news/frags"),
]


def _repo_with_gate(tmp_path, named):
    """A repo carrying our owned gate workflow whose `--dir` names `named`.

    `changelog_dir` is left null by the callers below, which is the reachable
    state: scaffold writes the workflow and deliberately does not write the key.
    """
    workflow = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: oss changelog\n"
        "jobs:\n"
        "  fragment:\n"
        "    steps:\n"
        "      - run: python3 .oss/assemble_changelog.py --check --dir '{0}' "
        "--changelog CHANGELOG.md\n".format(named),
        encoding="utf-8",
    )
    return tmp_path


# --- the producer: never return a value that does not validate ---------------


@pytest.mark.parametrize("label,named", HOSTILE, ids=[label for label, _ in HOSTILE])
def test_the_gate_refuses_a_dir_the_config_entrance_would_refuse(
    tmp_path, label, named
):
    root = _repo_with_gate(tmp_path, named)

    state, detail = oss_config.scaffolded_changelog_gate(root)

    assert state == REFUSED, (
        "the workflow --dir named {!r}, which the .oss.json entrance refuses "
        "outright, and the gate answered {!r} -- a state whose whole meaning is "
        "that the directory may be used".format(named, state)
    )
    assert detail, "the refusal must say what it refused, not refuse silently"


@pytest.mark.parametrize("label,named", BENIGN, ids=[label for label, _ in BENIGN])
def test_the_gate_still_accepts_every_legitimate_directory(tmp_path, label, named):
    """The must-not-fire half of the block above, in the same fixture. Without it a
    guard that refused everything would pass every one of those cases."""
    root = _repo_with_gate(tmp_path, named)

    state, detail = oss_config.scaffolded_changelog_gate(root)

    if named == oss_config.DEFAULT_FRAGMENTS_DIR:
        assert (state, detail) == ("present", "")
    else:
        assert (state, detail) == ("present-other-dir", named)


def test_the_refusal_is_not_the_unknown_state():
    """`unknown` means the gate could not be read. This one was read fine and says
    something inadmissible, and a caller may want to word those differently."""
    assert REFUSED != "unknown"
    assert REFUSED not in ("present", "present-other-dir", "absent")


# --- the join: one rule, two entrances ---------------------------------------


@pytest.mark.parametrize(
    "label,named", HOSTILE + BENIGN, ids=[label for label, _ in HOSTILE + BENIGN]
)
def test_both_entrances_agree_about_every_value(tmp_path, label, named):
    """The equivalence, in both directions, over one value set.

    This is what makes the two entrances one rule rather than two rules that
    currently coincide: it fails if `changelog_dir_problem` is loosened without the
    gate following, and it fails if the gate is tightened past the config key.
    """
    config_refuses = oss_config.changelog_dir_problem(named) is not None
    state, _ = oss_config.scaffolded_changelog_gate(_repo_with_gate(tmp_path, named))
    gate_refuses = state == REFUSED

    assert config_refuses == gate_refuses, (
        "{!r}: the .oss.json entrance {} it and the workflow entrance {} it. Same "
        "value, same downstream use -- a fold that deletes every fragment in "
        "whatever it names.".format(
            named,
            "refuses" if config_refuses else "accepts",
            "refuses" if gate_refuses else "accepts",
        )
    )


# --- the resolver: never resolve one either ----------------------------------


@pytest.mark.parametrize("label,named", HOSTILE, ids=[label for label, _ in HOSTILE])
def test_the_resolver_returns_no_directory_for_a_refused_gate(tmp_path, label, named):
    """`_fragment_dir` is the caller that turns the state into `Path(repo) / detail`.
    It must return no path at all and a problem that says why -- not a path plus
    `problem=None`, which is what the reproduction in #343 measured."""
    root = _repo_with_gate(tmp_path, named)

    directory, problem = release_version._fragment_dir(
        root, None, {"changelog_dir": None}
    )

    assert directory is None, "resolved {0!r} from a --dir of {1!r}".format(
        str(directory), named
    )
    assert problem, "a refusal with no reason is a silence"
    assert "changelog_dir" in problem or "--dir" in problem


@pytest.mark.parametrize("label,named", BENIGN, ids=[label for label, _ in BENIGN])
def test_the_resolver_still_resolves_every_legitimate_directory(tmp_path, label, named):
    root = _repo_with_gate(tmp_path, named)

    directory, problem = release_version._fragment_dir(
        root, None, {"changelog_dir": None}
    )

    assert problem is None
    assert directory == root.joinpath(*named.split("/"))


# --- the entrance the issue called the control -------------------------------


@pytest.mark.parametrize("label,named", HOSTILE, ids=[label for label, _ in HOSTILE])
def test_the_config_entrance_is_guarded_on_the_path_that_actually_runs(
    tmp_path, label, named
):
    """Found reviewing the fix for #343, and it inverts the issue's framing.

    `changelog_dir_problem` is reached from `oss_config.validate()`, and
    `release_version._read_config` is a bespoke `json.loads` that never calls it --
    so `changelog_dir` straight out of `.oss.json` reached `Path(repo) / named` with
    exactly the escape the workflow entrance had. Measured before the fix:

        _fragment_dir('/some/repo', None, {'changelog_dir': '/etc'})
        -> (PosixPath('/etc'), None)

    `.oss.json` is tracked, so this arrives the same way, and `/oss:changelog` prints
    it as the directory the fold deletes every fragment in. Not one entrance guarded
    and one not: neither, on the paths a release walks.
    """
    directory, problem = release_version._fragment_dir(
        tmp_path, None, {"changelog_dir": named}
    )

    assert directory is None, "resolved {0!r} straight out of .oss.json".format(
        str(directory)
    )
    assert problem and "changelog_dir" in problem


@pytest.mark.parametrize("label,named", BENIGN, ids=[label for label, _ in BENIGN])
def test_the_config_entrance_still_resolves_every_legitimate_directory(
    tmp_path, label, named
):
    """The must-not-fire half, in the same fixture."""
    directory, problem = release_version._fragment_dir(
        tmp_path, None, {"changelog_dir": named}
    )

    assert problem is None
    assert directory == tmp_path.joinpath(*named.split("/"))


# --- an empty --dir is a value somebody named, not an absent line ------------


@pytest.mark.parametrize("quote", ["'", chr(34)], ids=["single", "double"])
def test_an_empty_dir_value_is_refused_rather_than_read_as_no_dir_line(tmp_path, quote):
    """`--dir ''` and a workflow with no `--dir` line at all are two different facts.

    `_gate_directories` dropped falsy values, so the first collapsed into the second
    and the gate answered `present` -- silently falling back to `changelog.d` for a
    workflow that named something inadmissible. No escape, but a directory nobody
    named, which is #299 and #325's class rather than this issue's.
    """
    workflow = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "      - run: python3 .oss/assemble_changelog.py --check --dir {0}{0} "
        "--changelog CHANGELOG.md\n".format(quote),
        encoding="utf-8",
    )

    state, detail = oss_config.scaffolded_changelog_gate(tmp_path)

    assert state == REFUSED, "answered {!r} for an empty --dir".format(state)
    assert detail


def test_a_workflow_with_no_dir_line_at_all_is_still_present(tmp_path):
    """The must-not-fire twin. The two cases share a code path and must not share
    an answer -- and `present` has to survive, because an older or hand-trimmed
    workflow genuinely polices the default."""
    workflow = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: oss changelog\n", encoding="utf-8")

    assert oss_config.scaffolded_changelog_gate(tmp_path) == ("present", "")


def test_the_resolved_directory_never_leaves_the_repository(tmp_path):
    """The property the states are a means to, asserted directly so a future state
    that forgets to refuse is still caught: whatever `_fragment_dir` resolves from a
    gate on disk is inside the repository it was pointed at.

    Not a restatement of the parametrised refusals above -- those pin the state
    machine, this pins the outcome, and a fifth state resolving a path would slip
    past the first and not the second.
    """
    escaped = []
    for index, (_label, named) in enumerate(HOSTILE + BENIGN):
        root = _repo_with_gate(tmp_path / "case{0}".format(index), named)
        directory, _problem = release_version._fragment_dir(
            root, None, {"changelog_dir": None}
        )
        if directory is None:
            continue
        try:
            Path(directory).resolve().relative_to(Path(root).resolve())
        except ValueError:
            escaped.append((named, str(directory)))
    assert not escaped, "resolved outside the repository: {0!r}".format(escaped)
