"""#381: `lane_setup.resolve_base` handed `--remote` straight into git's argv.

`git fetch --quiet <remote> <branch>` puts `remote` at argv position 6 unprefixed, two
positions from the `default_branch` that #368 taught this call site to refuse. So a
guard and a bypass sat in one argv.

The harm is measured rather than reasoned. Against git 2.46.2 on darwin,
`git fetch --quiet --upload-pack=<script> master` **ran** `<script>` -- it printed its
own argv on stderr before git reported "Could not read from remote repository". So this
is arbitrary command execution from that position, not a confusing flag. The same
fixture measured `git fetch --quiet -- <remote> <branch>` refusing the dash-prefixed
value with `fatal: strange pathname ... blocked` while a well-formed remote still
fetched, and `git -C <dash-value>` consuming its argument literally rather than
re-parsing it as an option.

Reachability, stated because the issue's "Not claimed" section binds: nothing in this
repository passes `--remote` -- `grep` over the whole tree finds the `add_argument` and
nothing else -- so the value arrives only on the maintainer's own command line today.
The guard is here anyway, because "nobody types that" is a fact about today and the
docstring beside it is what a future sweep reads.

Every silence assertion is paired with a positive control in the same fixture: a stub
that never fired, or a `compute` that never ran, produces an empty recorder, and an
empty recorder is exactly what a passing "no git ran" assertion looks like.

The last test is not about `remote` at all. It sweeps **every** argument this module
hands to `_git`, for a hostile value injected at each input site in turn, and fails on
any argument that could occupy an option position. #381 exists because the previous
guard was written for the site somebody enumerated; a sweep cannot be wrong about a
site nobody thought of.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402

# Inert on purpose (`true`): nothing in this file should depend on the stub holding for
# its safety, and nothing in it should be executable if the stub ever fails to take.
HOSTILE_DASH = "--upload-pack=true"

WELL_FORMED = "origin"
WELL_FORMED_OTHER = "upstream"

CONFIG = {
    "repo": "example/example",
    "default_branch": "main",
    "branch_pattern": "fix/{issue}",
    "test_command": "pytest",
    "version_sites": [],
    "changelog_dir": None,
    "docs_targets": [],
    "labels": {"priority": [], "lanes": []},
}

# The flags this module writes as literals. Anything else in argv starting with a dash
# came from an input, which is the whole finding.
LITERAL_FLAGS = {"--quiet", "--verify"}


def _repo(tmp_path, **overrides):
    """A directory carrying only `.oss.json`. No git repo is built and none is needed:
    every git call is stubbed, which is the point -- the test must be able to observe
    the call a real repository would have absorbed silently.
    """
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    config = dict(CONFIG)
    config.update(overrides)
    (root / ".oss.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _capture(monkeypatch):
    """Replace `lane_setup._git` with a recorder. Returns the list it appends to.

    Patched on the module the code under test calls, not on `subprocess`: `resolve_base`
    resolves `_git` by module attribute at call time, so this injection takes on every
    interpreter (CLAUDE.md, "Patching a module attribute injects nothing where the
    caller captured the function at import").
    """
    calls = []

    def _recorder(repo, *args):
        calls.append({"repo": str(repo), "args": list(args)})
        return 1, "", "stubbed: nothing ran"

    monkeypatch.setattr(lane_setup, "_git", _recorder)
    monkeypatch.setattr(
        lane_setup,
        "read_board",
        lambda repo: {"state": "could-not-run", "lines": [], "detail": "stubbed"},
    )
    return calls


def _args(calls):
    return [call["args"] for call in calls]


def _flat(calls):
    return [arg for call in calls for arg in call["args"]]


# ------------------------------------------------------------------ the control first


def test_the_recorder_actually_intercepts(tmp_path, monkeypatch):
    """The control for every silence assertion below. Without it, a `compute` that
    raised before reaching git would make each of them pass.
    """
    calls = _capture(monkeypatch)
    lane_setup.compute(_repo(tmp_path), 381, WELL_FORMED)
    assert calls, "the stub never fired, so no silence assertion below means anything"
    assert ["fetch", "--quiet", WELL_FORMED, "main"] in _args(calls)


# ---------------------------------------------------- no argv is built at all for it


def test_a_dash_prefixed_remote_reaches_no_git_argv(tmp_path, monkeypatch):
    """The assertion is on captured argv, not on the exit code. A version that ran the
    fetch and *then* reported a failure would satisfy an exit-code assertion while the
    injected `--upload-pack` had already executed.
    """
    calls = _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path), 381, HOSTILE_DASH)

    assert not [c for c in _args(calls) if c[:1] == ["fetch"]], (
        "git fetch ran with a remote git itself would refuse: {!r}".format(_args(calls))
    )
    assert not [c for c in _args(calls) if c[:1] == ["rev-parse"]], _args(calls)
    assert payload["base"]["state"] == "could-not-resolve"


def test_the_hostile_remote_reaches_no_unprefixed_argument_anywhere(tmp_path, monkeypatch):
    """`branch_occupancy` still runs with the same hostile remote, deliberately -- it
    interpolates it into `refs/remotes/<remote>/<name>`, so this pins that the value is
    absent from the flag position rather than absent from the process.
    """
    calls = _capture(monkeypatch)
    lane_setup.compute(_repo(tmp_path), 381, HOSTILE_DASH)

    assert HOSTILE_DASH not in _flat(calls), (
        "the refused remote occupied an argument of its own: {!r}".format(_args(calls))
    )
    for arg in _flat(calls):
        if HOSTILE_DASH in arg:
            assert arg.startswith("refs/"), (
                "the remote reached git unprefixed: {!r}".format(arg)
            )


# ------------------------------------------------------------- and the guard is narrow


def test_a_well_formed_non_default_remote_still_resolves(tmp_path, monkeypatch):
    """Positive control. A guard that refused every remote would pass both cases above,
    and a guard that only allowed the literal "origin" would pass the first control.
    """
    calls = _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path), 381, WELL_FORMED_OTHER)

    assert ["fetch", "--quiet", WELL_FORMED_OTHER, "main"] in _args(calls)
    assert ["rev-parse", "refs/remotes/upstream/main"] in _args(calls)
    # Not an assertion on `state`: the recorder fails every call, so the base is
    # `could-not-resolve` here for git's reason and would be whether or not the guard
    # fired. The two are told apart by whose sentence `detail` carries.
    assert "starts with" not in payload["base"]["detail"], payload["base"]


def test_remote_problem_refuses_the_dash_class_and_nothing_else():
    assert lane_setup.remote_problem(HOSTILE_DASH) is not None
    assert lane_setup.remote_problem("-") is not None
    for fine in (WELL_FORMED, WELL_FORMED_OTHER, "git@github.com:o/n.git", "a-b_c.d"):
        assert lane_setup.remote_problem(fine) is None, fine


# --------------------------------------------------------------- the sentence it gives


def test_the_detail_says_why_rather_than_reporting_a_git_error(tmp_path, monkeypatch):
    _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path), 381, HOSTILE_DASH)

    detail = payload["base"]["detail"]
    assert detail, "could-not-resolve with an empty detail says nothing"
    assert "stubbed" not in detail, (
        "the detail is git's own failure, which means git was called: " + detail
    )
    assert detail[:60] == lane_setup._one_line(lane_setup.remote_problem(HOSTILE_DASH))[:60]


def test_the_receipt_and_blocked_agree(tmp_path, monkeypatch):
    """The other two renderings of the same verdict. #368 found all three disagreeing."""
    _capture(monkeypatch)
    payload = lane_setup.compute(_repo(tmp_path), 381, HOSTILE_DASH)

    text = lane_setup.receipt(payload)
    base_line = [ln for ln in text.splitlines() if ln.startswith("base      :")]
    assert len(base_line) == 1, text
    assert "COULD NOT RESOLVE" in base_line[0], base_line
    assert "starts with" in base_line[0], base_line
    assert lane_setup.blocked(payload) is True


# ------------------------------------------- the sweep, which is the durable half


def test_no_input_can_occupy_an_option_position_at_any_argv_site(tmp_path, monkeypatch):
    """Every input site in turn, against every argument this module builds.

    #381 happened because the previous guard was written for the argv position somebody
    enumerated. This asserts the property instead: no argument `_git` receives may begin
    with a dash unless this module wrote it as a literal flag. A new `_git` call built
    from a new input is covered the day it is added, without anyone remembering to come
    back here.

    `repo` is asserted separately and for a different reason: it is `-C`'s argument, and
    git consumes that literally rather than re-parsing it as an option (measured, git
    2.46.2). So a dash-prefixed `--repo` is a bad directory, not an injection, and the
    assertion here is only that it does not leak into the option positions.
    """
    sites = {
        "remote": lambda: (_repo(tmp_path), 381, HOSTILE_DASH),
        "default_branch": lambda: (_repo(tmp_path, default_branch=HOSTILE_DASH), 381, WELL_FORMED),
        "branch_pattern": lambda: (
            _repo(tmp_path, branch_pattern=HOSTILE_DASH + "/{issue}"),
            381,
            WELL_FORMED,
        ),
        "repo": lambda: (tmp_path / "-repo", 381, WELL_FORMED),
    }

    control = _capture(monkeypatch)
    lane_setup.compute(_repo(tmp_path), 381, WELL_FORMED)
    assert control, "the harness produced no calls at all, so the sweep measured nothing"

    for name, build in sites.items():
        if name == "repo":
            hostile_root = _repo(tmp_path)
            (tmp_path / "-repo").mkdir(exist_ok=True)
            (tmp_path / "-repo" / ".oss.json").write_bytes(
                (hostile_root / ".oss.json").read_bytes()
            )
        calls = _capture(monkeypatch)
        lane_setup.compute(*build())
        # A site that produced no argv at all passes every assertion below without
        # measuring anything, which is this repository's own defect class pointed at
        # its own sweep. Measured at the time of writing: 2, 2, 4 and 4 calls.
        assert calls, "the {0} site produced no git argv, so nothing was swept".format(name)
        for call in calls:
            for arg in call["args"]:
                assert not arg.startswith("-") or arg in LITERAL_FLAGS, (
                    "{0} reached an option position: {1!r}".format(name, call["args"])
                )
