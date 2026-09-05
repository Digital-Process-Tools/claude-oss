"""#309: `same_directory` had two answers for a three-answer question.

`os.path.samefile` asks the filesystem for device and inode, and it **raises when
either path is absent**. The version this replaces caught that and fell back to
comparing `os.path.abspath` strings -- so two spellings of one directory answered
`False` while the directory did not exist and `True` once it did. The verdict moved
with the filesystem's state rather than with the question asked, and `False` there
reads as *these are different trees*, which is an accusation rather than a shrug.

The three states are **same**, **different** and **could not tell**, and the third one
is what every test here is about. The positive half of each pair is never left out:
"no warning fired" is exactly what a comparison that cannot see anything prints, so
each silence below sits in the same fixture as a firing.

**The symlink is measured, never assumed.** A fixture that could not create a second
spelling has not tested the thing it names, so it skips carrying the platform, the
error and what went untested -- rather than asserting against a table of error codes,
which cannot report a value it does not contain.

**Which of these were red before the fix, said here rather than left to be
re-derived.** Seven were. Four were already green against the two-state comparison and
are locks rather than assertions about #309, which is worth writing down because a file
whose name is an issue number is read as coverage of that issue:
`test_an_identical_spelling_of_an_absent_directory_is_still_same` and
`test_two_spellings_of_the_attested_plugin_root_agree_once_it_exists` are the
must-not-regress halves -- the answers the old code got right, and the ones a fix that
answered "could not tell" to everything would break;
`test_the_helper_never_raises_on_a_path_a_user_can_type` locks doctor's exit-0 contract
against a future edit to the comparison rather than against this one; and
`test_config_search_path_does_not_widen_on_an_undecided_verdict` passed before only
because `None` is falsy, which is the accident it exists to stop depending on.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _two_spellings(tmp_path):
    """``(target, alias)`` -- one directory reachable under two names, or a skip.

    The link is **attempted and then measured**: created is not the same as working.
    A filesystem that accepts `symlink` and then resolves it to somewhere else, or a
    Windows leg where the call raises, would otherwise leave every assertion below
    passing for a reason that has nothing to do with the code under test.
    """
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            "symlink refused on {} ({!r}, errno {}); the two-spellings comparison went "
            "untested".format(sys.platform, exc, getattr(exc, "errno", None))
        )
    try:
        linked = os.path.samefile(str(alias), str(target))
    except OSError as exc:
        pytest.skip(
            "the link was created and could not be stat'd on {} ({!r}, errno {}); the "
            "two-spellings comparison went untested".format(
                sys.platform, exc, getattr(exc, "errno", None)
            )
        )
    if not linked:
        pytest.skip(
            "the link was created and does not name the target on {}; the "
            "two-spellings comparison went untested".format(sys.platform)
        )
    assert str(alias) != str(target)
    return target, alias


# --------------------------------------------------------------------------
# The helper itself: three answers.
# --------------------------------------------------------------------------


def test_two_spellings_of_one_absent_directory_are_undecided_not_different(tmp_path):
    """The whole issue, in one fixture, with both controls beside it.

    The bar this has to clear: it must fail if the comparison does nothing. It does --
    the string comparison returns `False` for the absent case, which is the value the
    caller renders as "different trees".
    """
    target, alias = _two_spellings(tmp_path)

    # Could not tell: neither spelling exists yet, and they differ as text.
    assert doctor.same_directory(alias / "child", target / "child") is None

    # Must-fire control, same fixture: create it and the same two spellings are `True`.
    # Without this the assertion above is satisfied by a helper that answers `None` to
    # everything.
    (target / "child").mkdir()
    assert doctor.same_directory(alias / "child", target / "child") is True

    # And the other must-fire control: two directories that exist and are different
    # must still be `False`, or "could not tell" has swallowed the negative answer.
    (target / "other").mkdir()
    assert doctor.same_directory(target / "child", target / "other") is False


def test_an_identical_spelling_of_an_absent_directory_is_still_same(tmp_path):
    """`abspath` equality is a sound `True` with no filesystem behind it.

    Two equal normalised paths denote one directory by construction, existing or not,
    so the cheap positive answer is kept and only the negative one is refused. Without
    this arm every absent path in the tree would answer "could not tell", including the
    ones the old code was right about.
    """
    absent = tmp_path / "nowhere"
    assert doctor.same_directory(absent, absent) is True
    assert (
        doctor.same_directory(str(absent), os.path.join(str(tmp_path), ".", "nowhere"))
        is True
    )


def test_the_undecided_verdict_carries_the_reason_from_the_exception_in_hand(tmp_path):
    """`compare_directories` returns *why*, and it comes from the raised error.

    Asking the filesystem a second question to explain why the first one failed is the
    trap `release_delta.py` was bitten by: `Path.exists()` swallows a short list of
    errnos and re-raises the rest, so the line added to explain a bad read is the line
    that kills the process. The `OSError` already in hand names the path and the reason.
    """
    target, alias = _two_spellings(tmp_path)
    verdict, why = doctor.compare_directories(alias / "child", target / "child")
    assert verdict is None
    assert why, "the undecided verdict must say what stopped it"
    assert "child" in why, why

    # Must-fire control: a decided verdict carries no reason, so a caller cannot print
    # an explanation for an answer that needs none.
    (target / "child").mkdir()
    assert doctor.compare_directories(alias / "child", target / "child") == (True, None)


def test_the_helper_never_raises_on_a_path_a_user_can_type(tmp_path):
    """doctor.py's contract is exit 0 always, one VERDICT line. #124 was this contract
    dying three frames away from the check that broke it, so the comparison is asserted
    to be total rather than trusted to be.

    The inputs are the ones that can actually arrive: argv and the environment cannot
    carry an embedded NUL, so a `ValueError` from `os.stat` is not reachable here and
    is deliberately not caught -- catching it would newly swallow a bug in this file.
    """
    for left, right in (
        (tmp_path / "a", tmp_path / "b"),
        ("", str(tmp_path)),
        (str(tmp_path), ""),
        (str(tmp_path / "a" / "b" / "c" / "d"), str(tmp_path)),
    ):
        verdict = doctor.same_directory(left, right)
        assert verdict in (True, False, None), (left, right, verdict)


# --------------------------------------------------------------------------
# Call site: `resolve_project_dir` -- --root beside CLAUDE_PROJECT_DIR.
# --------------------------------------------------------------------------


def test_root_and_env_naming_one_absent_tree_are_not_reported_as_disagreeing(tmp_path):
    """`--root` naming a directory that is not there is an ordinary user error -- the
    check three lines below reports exactly that. Until #309 the comparison above it
    also fired, on the same run, claiming the flag and the environment named two
    different trees. They may name one; nothing here can tell.
    """
    target, alias = _two_spellings(tmp_path)
    missing_via_alias = str(alias / "tree")
    missing_via_target = str(target / "tree")

    _, findings = doctor.resolve_project_dir(
        missing_via_alias, missing_via_target, str(tmp_path)
    )
    messages = [m for _, m in findings]
    assert not any("disagree" in m for m in messages), messages
    assert any("could not be compared" in m for m in messages), messages

    # Must-fire control, same fixture: two directories that both exist and are
    # genuinely different must still be reported as disagreeing. Without it this test
    # passes against a resolver that stopped comparing altogether.
    (target / "tree").mkdir()
    other = target / "elsewhere"
    other.mkdir()
    _, findings = doctor.resolve_project_dir(
        str(other), missing_via_target, str(tmp_path)
    )
    assert any("disagree" in m for _, m in findings), findings

    # And the second control: the two spellings of the tree that now exists agree.
    _, findings = doctor.resolve_project_dir(
        missing_via_alias, missing_via_target, str(tmp_path)
    )
    messages = [m for _, m in findings]
    assert not any("disagree" in m for m in messages), messages
    assert not any("could not be compared" in m for m in messages), messages


def test_the_undecided_disagreement_still_names_the_other_tree(tmp_path):
    """A reader of the could-not-tell line needs the same two facts the disagreement
    line gives them: which path the environment named, and that the flag won.
    """
    target, alias = _two_spellings(tmp_path)
    _, findings = doctor.resolve_project_dir(
        str(alias / "tree"), str(target / "tree"), str(tmp_path)
    )
    line = [m for state, m in findings if "could not be compared" in m]
    assert len(line) == 1, findings
    assert str(target / "tree") in line[0], line[0]
    assert "--root won" in line[0], line[0]


# --------------------------------------------------------------------------
# Call site: `plugin_provenance` -- the attested plugin root, and the checkout.
# --------------------------------------------------------------------------


SCOPE = "plugin copy scope:"
COPY = "plugin copy:"


def _plugin_tree(root, name="oss", version="0.5.0"):
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_bytes(
        (json.dumps({"name": name, "version": version}) + "\n").encode("utf-8")
    )
    return root


def _scope_line(lines):
    matched = [(level, m) for level, m in lines if m.startswith(SCOPE)]
    assert len(matched) == 1, lines
    return matched[0]


def test_an_attested_plugin_root_that_is_not_there_is_undecided_not_a_mismatch(
    tmp_path,
):
    """`--plugin-root /typo` is a path that does not exist, and the old comparison
    turned that into "names X, but doctor.py ran from Y" -- a sentence about a
    disagreement between two trees, one of which was never looked at.
    """
    answered = _plugin_tree(tmp_path / "installed")
    checkout = tmp_path / "clone"
    checkout.mkdir()

    level, message = _scope_line(
        doctor.plugin_provenance(
            answered,
            checkout,
            attested=tmp_path / "typo",
            attested_source="--plugin-root",
        )
    )
    assert level == "WARN", message
    assert "could not be determined" in message, message
    assert "but doctor.py ran from" not in message, message
    assert str(tmp_path / "typo") in message, message

    # Must-fire control, same fixture: a tree that exists and is genuinely a different
    # one is still reported as a mismatch, with the old sentence.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    level, message = _scope_line(
        doctor.plugin_provenance(
            answered, checkout, attested=elsewhere, attested_source="--plugin-root"
        )
    )
    assert level == "WARN", message
    assert "but doctor.py ran from" in message, message

    # And the agreeing control: the attested root that IS the tree that ran stays OK.
    level, message = _scope_line(
        doctor.plugin_provenance(
            answered, checkout, attested=answered, attested_source="CLAUDE_PLUGIN_ROOT"
        )
    )
    assert level == "OK", message


def test_two_spellings_of_the_attested_plugin_root_agree_once_it_exists(tmp_path):
    """The other half of the same call site, and the reason a string comparison was
    never enough here either: `--plugin-root` reaching this process through a symlink
    is one tree under two names, not two trees.
    """
    target, alias = _two_spellings(tmp_path)
    answered = _plugin_tree(target / "installed")
    checkout = tmp_path / "clone"
    checkout.mkdir()

    level, message = _scope_line(
        doctor.plugin_provenance(
            answered,
            checkout,
            attested=alias / "installed",
            attested_source="--plugin-root",
        )
    )
    assert level == "OK", message


def test_an_undecided_checkout_comparison_says_so_and_still_compares(
    tmp_path, monkeypatch
):
    """The third call site. Reached by injection on purpose, and the docstring in
    `plugin_provenance` says why: both trees have already had a manifest read out of
    them by the time this runs, so the filesystem has answered for both and the
    undecided arm is a race rather than an ordinary state. It still needs a branch --
    a silent fall-through would report one tree read twice as two identical trees.
    """
    answered = _plugin_tree(tmp_path / "installed")
    checkout = _plugin_tree(tmp_path / "clone")

    monkeypatch.setattr(
        doctor,
        "compare_directories",
        lambda left, right: (None, "injected: could not stat"),
    )
    lines = doctor.plugin_provenance(answered, checkout)
    copy = [m for _, m in lines if m.startswith(COPY)]
    assert any("could not be determined" in m for m in copy), lines
    assert any("injected: could not stat" in m for m in copy), lines

    # Must-fire control, same fixture and no injection: the real comparison of two
    # different trees produces no could-not-tell line at all.
    monkeypatch.undo()
    lines = doctor.plugin_provenance(answered, checkout)
    copy = [m for _, m in lines if m.startswith(COPY)]
    assert copy, lines
    assert not any("could not be determined" in m for m in copy), lines


# --------------------------------------------------------------------------
# Call site: `config_search_path` -- the one where a shared message is wrong
# because the right answer is no message at all.
# --------------------------------------------------------------------------


def test_config_search_path_does_not_widen_on_an_undecided_verdict(
    tmp_path, monkeypatch
):
    """`True` is the only verdict that may hand back the bare name.

    Widening is what searches the enclosing clone, and it is only correct when the
    project dir IS the current directory. `None` must take the same arm as `False`
    here -- not because could-not-tell is the same state, but because the conservative
    arm is the right one for it, and the second element of the return already tells
    the caller the clone was not searched.
    """
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    # Must-fire control first, so a broken fixture cannot make the assertion below
    # pass by accident: standing in the directory hands back the bare name.
    search, widened = doctor.config_search_path(str(project))
    assert widened is True
    assert search == doctor.oss_config.CONFIG_NAME

    monkeypatch.setattr(doctor, "same_directory", lambda left, right: None)
    search, widened = doctor.config_search_path(str(project))
    assert widened is False
    assert os.path.isabs(search), search


# --------------------------------------------------------------------------
# The contract the whole file sits under.
# --------------------------------------------------------------------------


def test_exit_0_and_one_verdict_line_survive_an_undecided_comparison(tmp_path):
    """A three-state comparison that raises kills doctor's contract from three frames
    away, which is how #124 happened. Run the script the way a user does.
    """
    target, alias = _two_spellings(tmp_path)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(target / "tree")
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "doctor.py"),
            "--root",
            str(alias / "tree"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        env=env,
        cwd=str(tmp_path),
    )
    assert done.returncode == 0, done.stdout
    verdicts = [
        line for line in done.stdout.splitlines() if line.startswith("VERDICT:")
    ]
    assert len(verdicts) == 1, done.stdout
    assert "disagree" not in done.stdout, done.stdout
