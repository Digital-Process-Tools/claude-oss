"""#368: `lane_setup.resolve_base` handed `default_branch` straight into git's argv
without consulting the problem sentence `oss_config` had already produced for it.

`oss_config.load()` deliberately returns the offending value *with* a sentence rather
than stripping it (the issue's own "Not claimed" says so), so the defect is the
consumer ignoring the sentence -- not a missing rule. #345's one-value-one-rule
constraint is why the fix calls `oss_config.default_branch_problem()` rather than
inventing a second validation here.

The assertion that matters is on the captured argv, not on the exit code: a version
that ran `git fetch --quiet origin --upload-pack=...` and *then* reported a failure
would satisfy an exit-code assertion while the command had already executed. Every
silence assertion below is paired with a positive control in the same fixture -- a
well-formed `default_branch` must still reach git -- because a stub that never fires,
or a harness that never called `compute` at all, would otherwise pass the silent half.

`branch_occupancy` is deliberately covered here too, as the *clean* half: it prefixes
`refs/heads/` and `refs/remotes/`, so a name can never occupy the flag position, and
the control below pins that this stays true rather than asserting it in a comment.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402
import oss_config  # noqa: E402

# Dash-prefixed: `git fetch --quiet origin --upload-pack=...` reads argv position 4 as
# an option. The payload is inert (`true`) on purpose -- nothing in this file should
# depend on the stub holding for its safety, but nothing should be executable either.
HOSTILE_DASH = "--upload-pack=true"

# Space-bearing: git's own `check-ref-format` refuses it, which is the sentence
# `default_branch_problem` transcribes.
HOSTILE_SPACE = "main branch"

WELL_FORMED = "main"

CONFIG = {
    "repo": "example/example",
    "default_branch": WELL_FORMED,
    "branch_pattern": "fix/{issue}",
    "test_command": "pytest",
    "version_sites": [],
    "changelog_dir": None,
    "docs_targets": [],
    "labels": {"priority": [], "lanes": []},
}


def _repo(tmp_path, default_branch):
    """A directory carrying only `.oss.json`. No git repo is built and none is needed:
    every git call is stubbed, which is the point -- the test must be able to observe
    the call that a real repository would have absorbed silently.
    """
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    config = dict(CONFIG)
    config["default_branch"] = default_branch
    (root / ".oss.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _capture(monkeypatch):
    """Replace `lane_setup._git` with a recorder. Returns the list it appends to.

    Patched on the module the code under test calls, not on `subprocess`: `compute`
    resolved `_git` by module attribute at call time, so this injection takes on every
    interpreter (CLAUDE.md, "Patching a module attribute injects nothing where the
    caller captured the function at import").
    """
    calls = []

    def _recorder(repo, *args):
        calls.append(list(args))
        return 1, "", "stubbed: nothing ran"

    monkeypatch.setattr(lane_setup.lane_setup_worktree, "_git", _recorder)
    monkeypatch.setattr(
        lane_setup,
        "read_board",
        lambda repo: {"state": "could-not-run", "lines": [], "detail": "stubbed"},
    )
    return calls


def _flat(calls):
    return [arg for call in calls for arg in call]


# ------------------------------------------------- the injection itself is measured


def test_the_recorder_actually_intercepts(tmp_path, monkeypatch):
    """The control for every silence assertion in this file.

    If `monkeypatch.setattr` did not take, or `compute` never ran, the recorder stays
    empty -- and an empty recorder is exactly what a passing "no git ran" assertion
    looks like. So the well-formed config must produce git calls, here, first.
    """
    calls = _capture(monkeypatch)
    lane_setup.compute(_repo(tmp_path, WELL_FORMED), 368)
    assert calls, "the stub never fired, so no silence assertion below means anything"
    assert ["fetch", "--quiet", "origin", WELL_FORMED] in calls


# ------------------------------------------------------- no argv is built at all


def test_a_dash_prefixed_default_branch_reaches_no_git_argv(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path, HOSTILE_DASH), 368)

    assert HOSTILE_DASH not in _flat(calls), (
        "the value oss_config had already refused reached git's argv: {!r}".format(
            calls
        )
    )
    assert not [c for c in calls if c[:1] == ["fetch"]], (
        "git fetch ran for a branch name git itself would refuse: {!r}".format(calls)
    )
    assert not [c for c in calls if c[:1] == ["rev-parse"]], calls
    assert payload["base"]["state"] == "could-not-resolve"


def test_a_space_bearing_default_branch_reaches_no_git_argv(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path, HOSTILE_SPACE), 368)

    assert HOSTILE_SPACE not in _flat(calls), calls
    assert not [c for c in calls if c[:1] in (["fetch"], ["rev-parse"])], calls
    assert payload["base"]["state"] == "could-not-resolve"


def test_a_well_formed_default_branch_still_resolves(tmp_path, monkeypatch):
    """Positive control: the guard must refuse the two above and nothing else.

    A guard that refused every value would pass both cases above, and this is the
    assertion that separates the two.
    """
    calls = _capture(monkeypatch)
    lane_setup.compute(_repo(tmp_path, WELL_FORMED), 368)
    assert ["fetch", "--quiet", "origin", WELL_FORMED] in calls
    assert ["rev-parse", "refs/remotes/origin/main"] in calls


# -------------------------------------------- the sentence, and where it comes from


def test_the_detail_is_oss_configs_own_sentence(tmp_path, monkeypatch):
    """#345: one value, one rule. The refusal must quote the rule that already exists,
    so a later change to `default_branch_problem` cannot leave two disagreeing texts.
    """
    _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path, HOSTILE_DASH), 368)
    sentence = oss_config.default_branch_problem(HOSTILE_DASH)
    assert sentence is not None, (
        "the premise of this test: oss_config refuses this value"
    )
    assert payload["base"]["detail"], (
        "could-not-resolve with an empty detail says nothing"
    )
    # The call site passes an explicit limit to `_one_line`, so the head is compared
    # rather than the whole sentence: comparing the whole one would assert that limit
    # by accident and fail the day it moves.
    assert payload["base"]["detail"][:60] == lane_setup._one_line(sentence)[:60]


def test_the_receipt_says_could_not_resolve(tmp_path, monkeypatch):
    """The third of the three renderings the issue found disagreeing. `blocked()` and
    the exit code are the other two, pinned below.
    """
    _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path, HOSTILE_DASH), 368)
    text = lane_setup.receipt(payload)
    assert "base      : COULD NOT RESOLVE" in text, text
    # Not just the heading: the stub makes every base fail, so a heading-only
    # assertion would pass against the unfixed script too. The reason has to be the
    # config sentence rather than a git error that arrived after the fetch ran.
    base_line = [ln for ln in text.splitlines() if ln.startswith("base      :")]
    assert len(base_line) == 1, text
    assert "it starts with '-'" in base_line[0], base_line
    # Scoped to the base line on purpose: the board stub carries the word "stubbed"
    # too, and a whole-receipt search would have been measuring the wrong line.
    assert "stubbed" not in base_line[0], (
        "the base line reported git's own failure, which means git was called: "
        + base_line[0]
    )


def test_blocked_is_true_and_the_control_is_false(tmp_path, monkeypatch):
    _capture(monkeypatch)
    hostile = lane_setup.compute(_repo(tmp_path, HOSTILE_DASH), 368)
    assert lane_setup.blocked(hostile) is True

    calls = _capture(monkeypatch)
    monkeypatch.setattr(
        lane_setup.lane_setup_worktree,
        "_git",
        lambda repo, *args: (calls.append(list(args)), (0, "a" * 40, ""))[1],
    )
    fine = lane_setup.compute(_repo(tmp_path, WELL_FORMED), 368)
    assert fine["base"]["state"] == "resolved"
    assert lane_setup.blocked(fine) is False


# --------------------------------------------------------- the clean half, measured


def test_branch_occupancy_never_puts_a_name_in_the_flag_position(monkeypatch):
    """The issue records `branch_occupancy` as unaffected because it prefixes its refs.
    That is a claim about this code, so it is measured here rather than asserted in
    prose: every argument it builds from `name` must start with `refs/`.
    """
    calls = []
    monkeypatch.setattr(
        lane_setup.lane_setup_worktree,
        "_git",
        lambda repo, *args: (calls.append(list(args)), (1, "", ""))[1],
    )
    lane_setup.branch_occupancy(".", "origin", "--upload-pack=true")
    assert calls, "branch_occupancy made no call at all, so nothing was measured"
    for call in calls:
        derived = [arg for arg in call if "upload-pack" in arg]
        assert derived, call
        for arg in derived:
            assert arg.startswith("refs/"), (
                "a contributor-chosen name reached git unprefixed: {!r}".format(call)
            )
